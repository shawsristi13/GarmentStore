
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from database.models import (
    Sale,
    SaleItem,
    SalesReturn,
    SalesReturnItem,
    ProductVariant,
    InventoryMovement,
)


def process_return(
    sale_id,
    items,
    reason=None,
    notes=None,
    restock=True,
):
    """
    Process a return against an original sale.

    items must be a list of dictionaries:
    [{"sale_item_id": 1, "quantity": 1, "refund_amount": 100}]
    """

    if not items:
        return {"success": False, "error": "Add at least one return item."}

    session = SessionLocal()

    try:
        with session.begin():
            sale = session.execute(
                select(Sale)
                .where(Sale.id == sale_id)
                .with_for_update()
            ).scalar_one_or_none()

            if sale is None:
                raise ValueError("The original sale was not found.")

            # Validate the requested items and combine their quantities.
            requested = {}

            for item in items:
                sale_item_id = int(item["sale_item_id"])
                quantity = int(item["quantity"])

                if quantity <= 0:
                    raise ValueError("Return quantity must be greater than zero.")

                if sale_item_id in requested:
                    raise ValueError(
                        "The same sale item cannot appear more than once."
                    )

                requested[sale_item_id] = {
                    "quantity": quantity,
                    "refund_amount": Decimal(
                        str(item.get("refund_amount", "0"))
                    ),
                }

            # Lock original sale items and validate quantities already returned.
            sale_items = session.execute(
                select(SaleItem)
                .where(
                    SaleItem.id.in_(list(requested)),
                    SaleItem.sale_id == sale_id,
                )
                .with_for_update()
            ).scalars().all()

            sale_items_by_id = {item.id: item for item in sale_items}

            if len(sale_items_by_id) != len(requested):
                raise ValueError(
                    "One or more items do not belong to this sale."
                )

            return_items = []
            total_refund = Decimal("0.00")

            for sale_item_id, request in requested.items():
                original_item = sale_items_by_id[sale_item_id]
                quantity = request["quantity"]
                refund_amount = request["refund_amount"]

                if not refund_amount.is_finite() or refund_amount < 0:
                    raise ValueError("Refund amounts must be non-negative.")

                already_returned = session.execute(
                    select(SalesReturnItem.quantity)
                    .join(
                        SalesReturn,
                        SalesReturn.id == SalesReturnItem.return_id,
                    )
                    .where(
                        SalesReturn.sale_id == sale_id,
                        SalesReturnItem.sale_item_id == sale_item_id,
                    )
                ).scalars().all()

                returned_quantity = sum(already_returned)
                remaining_quantity = original_item.quantity - returned_quantity

                if quantity > remaining_quantity:
                    raise ValueError(
                        f"Only {remaining_quantity} unit(s) remain eligible "
                        f"for return for sale item {sale_item_id}."
                    )

                original_value = (
                    Decimal(str(original_item.selling_price)) * quantity
                )

                if refund_amount > original_value:
                    raise ValueError(
                        "The refund cannot exceed the original value "
                        "of the returned units."
                    )

                variant = session.execute(
                    select(ProductVariant)
                    .where(ProductVariant.id == original_item.variant_id)
                    .with_for_update()
                ).scalar_one()

                return_items.append(
                    {
                        "sale_item": original_item,
                        "variant": variant,
                        "quantity": quantity,
                        "refund_amount": refund_amount,
                    }
                )

                total_refund += refund_amount

            # Create the return record first to obtain its ID.
            return_record = SalesReturn(
                return_number="PENDING",
                sale_id=sale_id,
                customer_name=sale.customer_name,
                refund_amount=total_refund,
                reason=reason,
                notes=notes,
            )
            session.add(return_record)
            session.flush()

            return_record.return_number = f"RET-{return_record.id:08d}"

            for entry in return_items:
                original_item = entry["sale_item"]
                variant = entry["variant"]
                quantity = entry["quantity"]
                refund_amount = entry["refund_amount"]

                session.add(
                    SalesReturnItem(
                        return_id=return_record.id,
                        sale_item_id=original_item.id,
                        quantity=quantity,
                        refund_amount=refund_amount,
                        restock=restock,
                    )
                )

                if restock:
                    previous_stock = (
                        variant.stock_quantity
                        if variant.stock_quantity is not None
                        else variant.quantity
                    )
                    previous_stock = int(previous_stock or 0)
                    new_stock = previous_stock + quantity

                    variant.quantity = new_stock
                    variant.stock_quantity = new_stock

                    session.add(
                        InventoryMovement(
                            variant_id=variant.id,
                            movement_type="RETURN",
                            previous_stock=previous_stock,
                            change_quantity=quantity,
                            new_stock=new_stock,
                            reason=f"Customer return {return_record.return_number}",
                        )
                    )

            session.flush()

            result = {
                "success": True,
                "return_id": return_record.id,
                "return_number": return_record.return_number,
                "sale_id": sale_id,
                "refund_amount": str(total_refund),
                "restocked": restock,
            }

        return result

    except ValueError as exc:
        session.rollback()
        return {"success": False, "error": str(exc)}

    except (InvalidOperation, KeyError, TypeError) as exc:
        session.rollback()
        return {
            "success": False,
            "error": f"Invalid return information: {exc}",
        }

    except SQLAlchemyError as exc:
        session.rollback()
        return {
            "success": False,
            "error": f"Database error while processing return: {exc}",
        }

    finally:
        session.close()

