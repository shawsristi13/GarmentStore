
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from database.models import ProductVariant


class InventoryError(Exception):
    """Raised when an inventory operation cannot be completed."""


def get_inventory():
    """Return all active product variants with their current stock."""

    with SessionLocal() as session:
        statement = (
            select(ProductVariant)
            .where(ProductVariant.is_active.is_(True))
            .order_by(ProductVariant.id.desc())
        )

        variants = session.scalars(statement).all()

        return [
            {
                "id": variant.id,
                "product_id": variant.product_id,
                "sku": variant.sku,
                "size": variant.size,
                "color": variant.color,
                "quantity": variant.quantity,
                "stock_quantity": variant.stock_quantity,
                "purchase_price": variant.purchase_price,
                "selling_price": variant.selling_price,
                "low_stock_threshold": variant.low_stock_threshold,
            }
            for variant in variants
        ]


def adjust_stock(variant_id, adjustment_type, amount, reason):
    """
    Adjust stock and save its movement record in the same transaction.

    adjustment_type: ADD, REMOVE, or SET.
    """

    if adjustment_type not in {"ADD", "REMOVE", "SET"}:
        raise InventoryError("Invalid stock adjustment type.")

    if not isinstance(amount, int) or isinstance(amount, bool):
        raise InventoryError("Stock quantity must be a whole number.")

    if amount < 0:
        raise InventoryError("Stock quantity cannot be negative.")

    if not isinstance(reason, str) or not reason.strip():
        raise InventoryError("Please provide a reason for the adjustment.")

    reason = reason.strip()

    if len(reason) > 255:
        raise InventoryError("Reason must be 255 characters or fewer.")

    try:
        with SessionLocal() as session:
            with session.begin():
                statement = (
                    select(ProductVariant)
                    .where(
                        ProductVariant.id == variant_id,
                        ProductVariant.is_active.is_(True),
                    )
                    .with_for_update()
                )

                variant = session.scalars(statement).first()

                if variant is None:
                    raise InventoryError(
                        "The selected product variant was not found "
                        "or is inactive."
                    )

                previous_stock = variant.stock_quantity

                if adjustment_type == "ADD":
                    new_stock = previous_stock + amount
                elif adjustment_type == "REMOVE":
                    new_stock = previous_stock - amount
                else:
                    new_stock = amount

                if new_stock < 0:
                    raise InventoryError(
                        f"Insufficient stock. Current stock is {previous_stock}."
                    )

                change_quantity = new_stock - previous_stock

                variant.quantity = new_stock
                variant.stock_quantity = new_stock

                # Save a history record only when stock actually changes.
                if change_quantity != 0:
                    from sqlalchemy import text

                    session.execute(
                        text(
                            """
                            INSERT INTO public.inventory_movements (
                                variant_id,
                                movement_type,
                                previous_stock,
                                change_quantity,
                                new_stock,
                                reason
                            )
                            VALUES (
                                :variant_id,
                                :movement_type,
                                :previous_stock,
                                :change_quantity,
                                :new_stock,
                                :reason
                            )
                            """
                        ),
                        {
                            "variant_id": variant.id,
                            "movement_type": adjustment_type,
                            "previous_stock": previous_stock,
                            "change_quantity": change_quantity,
                            "new_stock": new_stock,
                            "reason": reason,
                        },
                    )

                result = {
                    "variant_id": variant.id,
                    "sku": variant.sku,
                    "movement_type": adjustment_type,
                    "previous_stock": previous_stock,
                    "change_quantity": change_quantity,
                    "new_stock": new_stock,
                    "reason": reason,
                }

            return result

    except InventoryError:
        raise
    except SQLAlchemyError as error:
        raise InventoryError(
            f"Could not update inventory or save its history: {error}"
        ) from error

