
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.db import SessionLocal
from database.models import Sale, SaleItem, ProductVariant, Product


def create_sale(
    items: list[dict],
    customer_name: str | None = None,
    customer_phone: str | None = None,
    discount: Decimal | float | str = Decimal("0.00"),
    payment_method: str = "Cash",
    notes: str | None = None,
) -> dict:
    """
    Save a sale, deduct inventory, and record stock movements
    in one database transaction.

    Each item must contain:
        variant_id: int
        quantity: int
    """

    if not items:
        return {"success": False, "message": "Add at least one product."}

    try:
        discount = Decimal(str(discount))
    except (ValueError, TypeError, InvalidOperation):
        return {"success": False, "message": "Invalid discount amount."}

    if not discount.is_finite() or discount < 0:
        return {
            "success": False,
            "message": "Discount must be a valid, non-negative amount.",
        }

    payment_method = (payment_method or "").strip()

    allowed_payment_methods = {
        "Cash",
        "UPI",
        "Card",
        "Bank Transfer",
        "Other",
    }

    if payment_method not in allowed_payment_methods:
        return {"success": False, "message": "Select a valid payment method."}

    prepared_items = []
    seen_variants = set()

    for item in items:
        try:
            variant_id = int(item["variant_id"])
            quantity = int(item["quantity"])
        except (KeyError, TypeError, ValueError):
            return {
                "success": False,
                "message": "Every item must have a valid product and quantity.",
            }

        if variant_id <= 0 or quantity <= 0:
            return {
                "success": False,
                "message": "Product IDs and quantities must be positive.",
            }

        if variant_id in seen_variants:
            return {
                "success": False,
                "message": "A product variant appears more than once. Combine its quantities.",
            }

        prepared_items.append(
            {"variant_id": variant_id, "quantity": quantity}
        )
        seen_variants.add(variant_id)

    session: Session = SessionLocal()

    try:
        with session.begin():
            # Lock variants in a consistent order to reduce deadlocks.
            variants = {}

            for item in sorted(prepared_items, key=lambda x: x["variant_id"]):
                row = session.execute(
                    select(ProductVariant, Product)
                    .join(Product, Product.id == ProductVariant.product_id)
                    .where(ProductVariant.id == item["variant_id"])
                    .with_for_update(of=ProductVariant)
                ).one_or_none()

                if row is None:
                    raise ValueError(
                        f"Product variant {item['variant_id']} was not found."
                    )

                variant, product = row

                if not variant.is_active or not product.is_active:
                    raise ValueError(
                        f"{product.name} is inactive and cannot be sold."
                    )

                available_stock = int(variant.stock_quantity or 0)

                if available_stock < item["quantity"]:
                    raise ValueError(
                        f"Insufficient stock for {product.name} "
                        f"(SKU: {variant.sku}). Available: {available_stock}, "
                        f"requested: {item['quantity']}."
                    )

                selling_price = Decimal(str(variant.selling_price or 0))

                if not selling_price.is_finite() or selling_price < 0:
                    raise ValueError(
                        f"Invalid selling price for SKU {variant.sku}."
                    )

                selling_price = selling_price.quantize(Decimal("0.01"))

                variants[item["variant_id"]] = {
                    "variant": variant,
                    "product": product,
                    "available_stock": available_stock,
                    "selling_price": selling_price,
                    "quantity": item["quantity"],
                }

            subtotal = sum(
                (
                    data["selling_price"] * data["quantity"]
                    for data in variants.values()
                ),
                Decimal("0.00"),
            ).quantize(Decimal("0.01"))

            discount = discount.quantize(Decimal("0.01"))

            if discount > subtotal:
                raise ValueError(
                    "Discount cannot exceed the sale subtotal."
                )

            total_amount = (subtotal - discount).quantize(Decimal("0.01"))

            sale = Sale(
                invoice_number="PENDING",
                customer_name=(customer_name or "").strip() or None,
                customer_phone=(customer_phone or "").strip() or None,
                subtotal=subtotal,
                discount=discount,
                total_amount=total_amount,
                payment_method=payment_method,
                notes=(notes or "").strip() or None,
            )

            session.add(sale)
            session.flush()

            # Use the database-generated sale ID for a unique invoice number.
            sale.invoice_number = f"INV-{sale.id:08d}"

            for variant_id, data in variants.items():
                variant = data["variant"]
                quantity = data["quantity"]
                previous_stock = data["available_stock"]
                new_stock = previous_stock - quantity

                # Keep the two existing stock columns synchronized.
                variant.quantity = new_stock
                variant.stock_quantity = new_stock

                session.add(
                    SaleItem(
                        sale_id=sale.id,
                        variant_id=variant_id,
                        quantity=quantity,
                        selling_price=data["selling_price"],
                        subtotal=(
                            data["selling_price"] * quantity
                        ).quantize(Decimal("0.01")),
                    )
                )

                session.execute(
                    text(
                        """
                        INSERT INTO public.inventory_movements
                        (
                            variant_id,
                            movement_type,
                            previous_stock,
                            change_quantity,
                            new_stock,
                            reason
                        )
                        VALUES
                        (
                            :variant_id,
                            'SALE',
                            :previous_stock,
                            :change_quantity,
                            :new_stock,
                            :reason
                        )
                        """
                    ),
                    {
                        "variant_id": variant_id,
                        "previous_stock": previous_stock,
                        "change_quantity": -quantity,
                        "new_stock": new_stock,
                        "reason": f"Sale {sale.invoice_number}",
                    },
                )

            session.flush()

            result = {
                "success": True,
                "message": "Sale completed and inventory updated successfully.",
                "sale_id": sale.id,
                "invoice_number": sale.invoice_number,
                "subtotal": str(subtotal),
                "discount": str(discount),
                "total_amount": str(total_amount),
                "payment_method": payment_method,
            }

        return result

    except ValueError as exc:
        session.rollback()
        return {"success": False, "message": str(exc)}

    except SQLAlchemyError:
        session.rollback()
        return {
            "success": False,
            "message": (
                "The sale could not be saved. No sale or inventory changes "
                "were committed. Check the application terminal for details."
            ),
        }

    finally:
        session.close()

