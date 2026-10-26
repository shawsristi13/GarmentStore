
import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from database.models import Product, ProductVariant, Purchase, PurchaseItem, Supplier
from services.purchases import create_purchase


st.set_page_config(page_title="Purchases", page_icon="🛍️", layout="wide")

st.title("🛍️ Purchase Management")
st.caption("Record supplier purchases and automatically update inventory.")


def load_suppliers():
    with SessionLocal() as session:
        return session.execute(
            select(Supplier)
            .where(Supplier.is_active.is_(True))
            .order_by(Supplier.name)
        ).scalars().all()


def load_variants():
    with SessionLocal() as session:
        rows = session.execute(
            select(ProductVariant, Product)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                ProductVariant.is_active.is_(True),
                Product.is_active.is_(True),
            )
            .order_by(Product.name, ProductVariant.size, ProductVariant.color)
        ).all()

        return [
            {
                "id": variant.id,
                "label": (
                    f"{product.name} | {variant.size or '-'} | "
                    f"{variant.color or '-'} | SKU: {variant.sku}"
                ),
                "stock": int(variant.stock_quantity or 0),
                "purchase_price": float(variant.purchase_price or 0),
            }
            for variant, product in rows
        ]


def load_purchase_history():
    with SessionLocal() as session:
        rows = session.execute(
            select(Purchase, Supplier)
            .join(Supplier, Supplier.id == Purchase.supplier_id)
            .order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
        ).all()

        return [
            {
                "Purchase ID": purchase.id,
                "Date": purchase.purchase_date.strftime("%d-%m-%Y %H:%M")
                if purchase.purchase_date
                else "",
                "Supplier": supplier.name,
                "Invoice Number": purchase.invoice_number or "-",
                "Total Amount (₹)": float(purchase.total_amount or 0),
                "Notes": purchase.notes or "",
            }
            for purchase, supplier in rows
        ]


try:
    suppliers = load_suppliers()
    variants = load_variants()
except SQLAlchemyError as exc:
    st.error("Unable to load suppliers or products from the database.")
    st.exception(exc)
    st.stop()


if not suppliers:
    st.warning("No active suppliers found. Add a supplier on the Suppliers page first.")
    st.stop()

if not variants:
    st.warning("No active product variants found. Add products on the Products page first.")
    st.stop()


tab_new, tab_history = st.tabs(["➕ New Purchase", "📋 Purchase History"])

with tab_new:
    st.subheader("Record a New Purchase")

    supplier_options = {
        f"{supplier.name} — {supplier.phone}": supplier.id
        for supplier in suppliers
    }

    with st.form("purchase_form", clear_on_submit=False):
        selected_supplier_label = st.selectbox(
            "Supplier",
            options=list(supplier_options.keys()),
        )

        invoice_number = st.text_input(
            "Supplier Invoice Number (optional)",
            max_chars=100,
        )

        notes = st.text_area("Notes (optional)")

        st.markdown("### Products")

        if "purchase_cart" not in st.session_state:
            st.session_state["purchase_cart"] = [
                {
                    "variant_id": variants[0]["id"],
                    "quantity": 1,
                    "purchase_price": variants[0]["purchase_price"],
                }
            ]

        cart = st.session_state["purchase_cart"]

        number_of_items = st.number_input(
            "Number of product lines",
            min_value=1,
            max_value=30,
            value=max(1, min(len(cart), 30)),
            step=1,
        )

        # Resize the cart to match the selected number of lines.
        while len(cart) < number_of_items:
            cart.append(
                {
                    "variant_id": variants[0]["id"],
                    "quantity": 1,
                    "purchase_price": variants[0]["purchase_price"],
                }
            )

        while len(cart) > number_of_items:
            cart.pop()

        variant_by_id = {variant["id"]: variant for variant in variants}
        variant_ids = list(variant_by_id.keys())

        total_amount = 0.0

        for index in range(int(number_of_items)):
            item = cart[index]
            selected_variant_id = (
                item["variant_id"]
                if item["variant_id"] in variant_by_id
                else variant_ids[0]
            )

            st.markdown(f"**Product line {index + 1}**")

            col1, col2, col3 = st.columns([3, 1, 2])

            with col1:
                chosen_variant_id = st.selectbox(
                    "Product variant",
                    options=variant_ids,
                    index=variant_ids.index(selected_variant_id),
                    format_func=lambda variant_id: variant_by_id[variant_id]["label"],
                    key=f"purchase_variant_{index}",
                )

            with col2:
                quantity = st.number_input(
                    "Quantity",
                    min_value=1,
                    max_value=100000,
                    value=max(1, int(item["quantity"])),
                    step=1,
                    key=f"purchase_quantity_{index}",
                )

            with col3:
                purchase_price = st.number_input(
                    "Purchase price per item (₹)",
                    min_value=0.0,
                    max_value=10000000.0,
                    value=max(
                        0.0,
                        float(
                            item["purchase_price"]
                            if item["variant_id"] == chosen_variant_id
                            else variant_by_id[chosen_variant_id]["purchase_price"]
                        ),
                    ),
                    step=1.0,
                    format="%.2f",
                    key=f"purchase_price_{index}",
                )

            subtotal = float(quantity) * float(purchase_price)
            total_amount += subtotal

            st.caption(
                f"Current stock: {variant_by_id[chosen_variant_id]['stock']} "
                f"units · Line subtotal: ₹{subtotal:,.2f}"
            )

            cart[index] = {
                "variant_id": chosen_variant_id,
                "quantity": int(quantity),
                "purchase_price": float(purchase_price),
            }

        st.divider()
        st.subheader(f"Total Purchase Amount: ₹{total_amount:,.2f}")

        submitted = st.form_submit_button(
            "Save Purchase and Update Inventory",
            type="primary",
            use_container_width=True,
        )

        if submitted:
            duplicate_ids = [
                item["variant_id"]
                for item in cart
                if sum(
                    1 for other in cart
                    if other["variant_id"] == item["variant_id"]
                ) > 1
            ]

            if duplicate_ids:
                st.error(
                    "The same product variant is selected more than once. "
                    "Combine its quantity into a single product line."
                )
            else:
                result = create_purchase(
                    supplier_id=supplier_options[selected_supplier_label],
                    items=cart,
                    invoice_number=invoice_number,
                    notes=notes,
                )

                if result["success"]:
                    st.session_state["purchase_cart"] = [
                        {
                            "variant_id": variants[0]["id"],
                            "quantity": 1,
                            "purchase_price": variants[0]["purchase_price"],
                        }
                    ]
                    st.success(
                        f"{result['message']} Purchase ID: "
                        f"{result['purchase_id']} | "
                        f"Total: ₹{float(result['total_amount']):,.2f}"
                    )
                    st.rerun()
                else:
                    st.error(result["message"])


with tab_history:
    st.subheader("Previous Purchases")

    try:
        history = load_purchase_history()

        if history:
            history_df = pd.DataFrame(history)
            st.dataframe(
                history_df,
                use_container_width=True,
                hide_index=True,
            )

            csv_data = history_df.to_csv(index=False).encode("utf-8-sig")

            st.download_button(
                "Download Purchase History (CSV)",
                data=csv_data,
                file_name="purchase_history.csv",
                mime="text/csv",
            )

            purchase_ids = [row["Purchase ID"] for row in history]

            selected_purchase_id = st.selectbox(
                "View purchase details",
                options=purchase_ids,
                format_func=lambda purchase_id: (
                    f"Purchase #{purchase_id}"
                ),
            )

            with SessionLocal() as session:
                details = session.execute(
                    select(PurchaseItem, ProductVariant, Product)
                    .join(
                        ProductVariant,
                        ProductVariant.id == PurchaseItem.variant_id,
                    )
                    .join(
                        Product,
                        Product.id == ProductVariant.product_id,
                    )
                    .where(
                        PurchaseItem.purchase_id == selected_purchase_id
                    )
                    .order_by(PurchaseItem.id)
                ).all()

            if details:
                detail_df = pd.DataFrame(
                    [
                        {
                            "Product": product.name,
                            "SKU": variant.sku,
                            "Size": variant.size or "-",
                            "Color": variant.color or "-",
                            "Quantity": item.quantity,
                            "Purchase Price (₹)": float(item.purchase_price),
                            "Subtotal (₹)": float(item.subtotal),
                        }
                        for item, variant, product in details
                    ]
                )

                st.dataframe(
                    detail_df,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No line items found for this purchase.")

        else:
            st.info("No purchases recorded yet.")

    except SQLAlchemyError as exc:
        st.error("Unable to load purchase history.")
        st.exception(exc)

