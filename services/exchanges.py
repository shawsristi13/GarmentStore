
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from database.models import (
    Sale,
    SaleItem,
    SalesReturn,
    SalesReturnItem,
    Exchange,
    ExchangeItem,
    Product,
    ProductVariant,
    InventoryMovement,
)


ALLOWED_PAYMENT_METHODS = {
    "Cash",
    "UPI",
    "Card",
    "Bank Transfer",
    "Other",
}


def process_exchange(
    sale_id,
    original_sale_item_id,
    replacement_variant_id,
    quantity=1,
    reason=None,
    notes=None,
    payment_method="Cash",
):
    """
    Exchange an item from an original sale for another product variant.

    Price difference:
        Positive -> customer pays extra.
        Negative -> customer receives a refund.
        Zero     -> no price difference.

    The returned item is restocked and the replacement item is deducted
    from inventory within the same database transaction.

    The selected payment method is stored in the exchanges table.
    This function records the payment details but does not actually
    collect additional payments or issue refunds.
    """

    if payment_method not in ALLOWED_PAYMENT_METHODS:
        return {
            "success": False,
            "error": (
                "Invalid payment method. Choose Cash, UPI, Card, "
                "Bank Transfer, or Other."
            ),
        }

    session = SessionLocal()

    try:
        sale_id = int(sale_id)
        original_sale_item_id = int(original_sale_item_id)
        replacement_variant_id = int(replacement_variant_id)
        quantity = int(quantity)

        if quantity <= 0:
            raise ValueError(
                "Exchange quantity must be greater than zero."
            )

        with session.begin():

            # Lock the original sale.
            sale = session.execute(
                select(Sale)
                .where(Sale.id == sale_id)
                .with_for_update()
            ).scalar_one_or_none()

            if sale is None:
                raise ValueError(
                    "The original sale was not found."
                )

            # Lock the original sale item.
            original_item = session.execute(
                select(SaleItem)
                .where(
                    SaleItem.id == original_sale_item_id,
                    SaleItem.sale_id == sale_id,
                )
                .with_for_update()
            ).scalar_one_or_none()

            if original_item is None:
                raise ValueError(
                    "The selected original item does not belong "
                    "to this sale."
                )

            # Calculate how many units have already been returned.
            returned_quantity = session.execute(
                select(
                    func.coalesce(
                        func.sum(SalesReturnItem.quantity),
                        0,
                    )
                )
                .join(
                    SalesReturn,
                    SalesReturn.id == SalesReturnItem.return_id,
                )
                .where(
                    SalesReturn.sale_id == sale_id,
                    SalesReturnItem.sale_item_id
                    == original_sale_item_id,
                )
            ).scalar_one()

            # Calculate how many units have already been exchanged.
            exchanged_quantity = session.execute(
                select(
                    func.coalesce(
                        func.sum(ExchangeItem.quantity),
                        0,
                    )
                )
                .join(
                    Exchange,
                    Exchange.id == ExchangeItem.exchange_id,
                )
                .where(
                    Exchange.sale_id == sale_id,
                    ExchangeItem.original_sale_item_id
                    == original_sale_item_id,
                )
            ).scalar_one()

            remaining_quantity = (
                original_item.quantity
                - int(returned_quantity or 0)
                - int(exchanged_quantity or 0)
            )

            if remaining_quantity <= 0:
                raise ValueError(
                    "No units remain eligible for exchange."
                )

            if quantity > remaining_quantity:
                raise ValueError(
                    f"Only {remaining_quantity} unit(s) remain "
                    "eligible for exchange."
                )

            # Lock the replacement variant and its product.
            replacement_row = session.execute(
                select(ProductVariant, Product)
                .join(
                    Product,
                    Product.id == ProductVariant.product_id,
                )
                .where(
                    ProductVariant.id == replacement_variant_id
                )
                .with_for_update(of=ProductVariant)
            ).first()

            if replacement_row is None:
                raise ValueError(
                    "The replacement product was not found."
                )

            replacement_variant, replacement_product = replacement_row

            if (
                not replacement_variant.is_active
                or not replacement_product.is_active
            ):
                raise ValueError(
                    "The replacement product is inactive."
                )

            # Check replacement stock.
            replacement_stock = (
                replacement_variant.stock_quantity
                if replacement_variant.stock_quantity is not None
                else replacement_variant.quantity
            )

            replacement_stock = int(replacement_stock or 0)

            if replacement_stock < quantity:
                raise ValueError(
                    "Insufficient stock for the replacement item. "
                    f"Available: {replacement_stock}; "
                    f"requested: {quantity}."
                )

            # Calculate the price difference using Decimal.
            original_price = Decimal(
                str(original_item.selling_price or 0)
            )

            replacement_price = Decimal(
                str(replacement_variant.selling_price or 0)
            )

            original_value = original_price * quantity
            replacement_value = replacement_price * quantity

            difference = replacement_value - original_value

            additional_payment = max(
                difference,
                Decimal("0.00"),
            )

            refund_amount = max(
                -difference,
                Decimal("0.00"),
            )

            # Lock the original variant.
            # Reuse the replacement variant if both IDs are identical.
            if original_item.variant_id == replacement_variant.id:
                original_variant = replacement_variant
            else:
                original_variant = session.execute(
                    select(ProductVariant)
                    .where(
                        ProductVariant.id == original_item.variant_id
                    )
                    .with_for_update()
                ).scalar_one()

            original_stock = (
                original_variant.stock_quantity
                if original_variant.stock_quantity is not None
                else original_variant.quantity
            )

            original_stock = int(original_stock or 0)

            # Same-variant exchanges do not change inventory.
            if original_variant.id == replacement_variant.id:
                additional_payment = Decimal("0.00")
                refund_amount = Decimal("0.00")

            # Create the exchange record.
            exchange = Exchange(
                exchange_number="PENDING",
                sale_id=sale_id,
                customer_name=sale.customer_name,
                additional_payment=additional_payment,
                refund_amount=refund_amount,
                payment_method=payment_method,
                reason=reason,
                notes=notes,
            )

            session.add(exchange)
            session.flush()

            exchange.exchange_number = (
                f"EXC-{exchange.id:08d}"
            )

            # Record the original and replacement items.
            session.add(
                ExchangeItem(
                    exchange_id=exchange.id,
                    original_sale_item_id=original_sale_item_id,
                    replacement_variant_id=replacement_variant_id,
                    quantity=quantity,
                    original_unit_price=original_price,
                    replacement_unit_price=replacement_price,
                )
            )

            # Update stock and record inventory movements.
            if original_variant.id != replacement_variant.id:

                original_new_stock = original_stock + quantity

                replacement_new_stock = (
                    replacement_stock - quantity
                )

                # Keep both stock columns synchronized.
                original_variant.quantity = original_new_stock
                original_variant.stock_quantity = original_new_stock

                replacement_variant.quantity = replacement_new_stock
                replacement_variant.stock_quantity = (
                    replacement_new_stock
                )

                # Record returned stock.
                session.add(
                    InventoryMovement(
                        variant_id=original_variant.id,
                        movement_type="EXCHANGE_IN",
                        previous_stock=original_stock,
                        change_quantity=quantity,
                        new_stock=original_new_stock,
                        reason=(
                            f"Exchange {exchange.exchange_number}: "
                            "returned item"
                        ),
                    )
                )

                # Record replacement stock deduction.
                session.add(
                    InventoryMovement(
                        variant_id=replacement_variant.id,
                        movement_type="EXCHANGE_OUT",
                        previous_stock=replacement_stock,
                        change_quantity=-quantity,
                        new_stock=replacement_new_stock,
                        reason=(
                            f"Exchange {exchange.exchange_number}: "
                            "replacement item"
                        ),
                    )
                )

            session.flush()

            result = {
                "success": True,
                "exchange_id": exchange.id,
                "exchange_number": exchange.exchange_number,
                "sale_id": sale_id,
                "quantity": quantity,
                "original_price": str(original_price),
                "replacement_price": str(replacement_price),
                "additional_payment": str(additional_payment),
                "refund_amount": str(refund_amount),
                "payment_method": payment_method,
            }

        return result

    except ValueError as exc:
        session.rollback()

        return {
            "success": False,
            "error": str(exc),
        }

    except (
        InvalidOperation,
        TypeError,
        OverflowError,
    ) as exc:
        session.rollback()

        return {
            "success": False,
            "error": f"Invalid exchange information: {exc}",
        }

    except SQLAlchemyError as exc:
        session.rollback()

        return {
            "success": False,
            "error": (
                "Database error while processing exchange: "
                f"{exc}"
            ),
        }

    finally:
        session.close()

