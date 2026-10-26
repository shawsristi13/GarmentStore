
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.db import SessionLocal
from database.models import (
    Purchase,
    PurchaseItem,
    ProductVariant,
    Supplier,
)


def create_purchase(
    supplier_id: int,
    items: list[dict],
    invoice_number: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Create a purchase, increase inventory, and record stock movements
    in a single database transaction.

    Each item must contain:
        variant_id: int
        quantity: int
        purchase_price: Decimal, float, or string
    """

    if not items:
        return {"success": False, "message": "Add at least one product."}

    try:
        supplier_id = int(supplier_id)
    except (TypeError, ValueError):
        return {"success": False, "message": "Invalid supplier."}

    prepared_items = []
    seen_variants = set()

    for item in items:
        try:
            variant_id = int(item["variant_id"])
            quantity = int(item["quantity"])
            price = Decimal(str(item["purchase_price"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return {
                "success": False,
                "message": "Each item needs a valid product, quantity, and price.",
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

        if not price.is_finite() or price < 0:
            return {
                "success": False,
                "message": "Purchase prices must be valid, non-negative numbers.",
            }

        price = price.quantize(Decimal("0.01"))

        prepared_items.append(
            {
                "variant_id": variant_id,
                "quantity": quantity,
                "purchase_price": price,
                "subtotal": (price * quantity).quantize(Decimal("0.01")),
            }
        )
        seen_variants.add(variant_id)

    session: Session = SessionLocal()

    try:
        with session.begin():
            supplier = session.get(Supplier, supplier_id)

            if supplier is None or not supplier.is_active:
                raise ValueError("Select an existing active supplier.")

            # Lock product rows in a consistent order to reduce deadlocks.
            variants = {}

            for item in sorted(prepared_items, key=lambda x: x["variant_id"]):
                variant = session.execute(
                    select(ProductVariant)
                    .where(ProductVariant.id == item["variant_id"])
                    .with_for_update()
                ).scalar_one_or_none()

                if variant is None or not variant.is_active:
                    raise ValueError(
                        f"Product variant {item['variant_id']} does not exist or is inactive."
                    )

                variants[item["variant_id"]] = variant

            total_amount = sum(
                (item["subtotal"] for item in prepared_items),
                Decimal("0.00"),
            ).quantize(Decimal("0.01"))

            purchase = Purchase(
                supplier_id=supplier_id,
                invoice_number=(invoice_number or "").strip() or None,
                total_amount=total_amount,
                notes=(notes or "").strip() or None,
            )

            session.add(purchase)
            session.flush()

            for item in prepared_items:
                variant = variants[item["variant_id"]]
                previous_stock = int(variant.stock_quantity or 0)
                new_stock = previous_stock + item["quantity"]

                # Keep both stock columns synchronized.
                variant.quantity = new_stock
                variant.stock_quantity = new_stock

                session.add(
                    PurchaseItem(
                        purchase_id=purchase.id,
                        variant_id=item["variant_id"],
                        quantity=item["quantity"],
                        purchase_price=item["purchase_price"],
                        subtotal=item["subtotal"],
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
                                'PURCHASE',
                                :previous_stock,
                                :change_quantity,
                                :new_stock,
                                :reason
                            )
                        """
                    ),
                    {
                        "variant_id": item["variant_id"],
                        "previous_stock": previous_stock,
                        "change_quantity": item["quantity"],
                        "new_stock": new_stock,
                        "reason": f"Purchase #{purchase.id}",
                    },
                )

            session.flush()

            purchase_id = purchase.id

        return {
            "success": True,
            "message": "Purchase saved and inventory updated successfully.",
            "purchase_id": purchase_id,
            "total_amount": str(total_amount),
        }

    except ValueError as exc:
        session.rollback()
        return {"success": False, "message": str(exc)}

    except SQLAlchemyError:
        session.rollback()
        return {
            "success": False,
            "message": (
                "The purchase could not be saved. "
                "No purchase or inventory changes were committed. "
                "Check your database permissions and application logs."
            ),
        }

    finally:
        session.close()

