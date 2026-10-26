
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from database.models import Product, ProductVariant, Sale, SaleItem
from services.sales import create_sale


st.set_page_config(
    page_title="Sales and Billing",
    page_icon="🧾",
    layout="wide",
)

st.title("🧾 Sales and Billing")
st.caption("Create customer bills and automatically deduct inventory.")


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
                    f"{product.name} | Size: {variant.size or '-'} | "
                    f"Color: {variant.color or '-'} | SKU: {variant.sku}"
                ),
                "stock": int(variant.stock_quantity or 0),
                "price": float(variant.selling_price or 0),
            }
            for variant, product in rows
        ]


def load_sales_history():
    with SessionLocal() as session:
        sales = session.execute(
            select(Sale).order_by(
                Sale.sale_date.desc(),
                Sale.id.desc(),
            )
        ).scalars().all()

        return [
            {
                "Sale ID": sale.id,
                "Invoice Number": sale.invoice_number,
                "Date": (
                    sale.sale_date.strftime("%d-%m-%Y %H:%M")
                    if sale.sale_date
                    else ""
                ),
                "Customer": sale.customer_name or "Walk-in Customer",
                "Phone": sale.customer_phone or "-",
                "Subtotal (₹)": float(sale.subtotal or 0),
                "Discount (₹)": float(sale.discount or 0),
                "Total (₹)": float(sale.total_amount or 0),
                "Payment": sale.payment_method,
            }
            for sale in sales
        ]


def load_sale_details(sale_id):
    with SessionLocal() as session:
        sale = session.get(Sale, sale_id)

        if sale is None:
            return None, []

        rows = session.execute(
            select(SaleItem, ProductVariant, Product)
            .join(
                ProductVariant,
                ProductVariant.id == SaleItem.variant_id,
            )
            .join(
                Product,
                Product.id == ProductVariant.product_id,
            )
            .where(SaleItem.sale_id == sale_id)
            .order_by(SaleItem.id)
        ).all()

        details = [
            {
                "Product": product.name,
                "SKU": variant.sku,
                "Size": variant.size or "-",
                "Color": variant.color or "-",
                "Quantity": item.quantity,
                "Price (₹)": float(item.selling_price),
                "Amount (₹)": float(item.subtotal),
            }
            for item, variant, product in rows
        ]

        sale_data = {
            "id": sale.id,
            "invoice_number": sale.invoice_number,
            "sale_date": sale.sale_date,
            "customer_name": sale.customer_name or "Walk-in Customer",
            "customer_phone": sale.customer_phone or "-",
            "subtotal": float(sale.subtotal),
            "discount": float(sale.discount),
            "total_amount": float(sale.total_amount),
            "payment_method": sale.payment_method,
            "notes": sale.notes or "",
        }

        return sale_data, details


try:
    variants = load_variants()
except SQLAlchemyError:
    st.error("Could not load products. Check your database connection.")
    st.stop()


if not variants:
    st.warning("No active products found. Add products before making a sale.")
    st.stop()


variant_by_id = {item["id"]: item for item in variants}
variant_ids = list(variant_by_id.keys())

tab_new, tab_history = st.tabs(
    ["➕ New Sale", "📋 Sales History"]
)


with tab_new:
    st.subheader("Create Customer Bill")

    with st.form("sales_form"):
        customer_name = st.text_input(
            "Customer Name (optional)",
            max_chars=150,
        )

        customer_phone = st.text_input(
            "Customer Phone (optional)",
            max_chars=20,
        )

        st.markdown("### Products")

        line_count = st.number_input(
            "Number of product lines",
            min_value=1,
            max_value=30,
            value=1,
            step=1,
        )

        cart = []
        subtotal = Decimal("0.00")

        for index in range(int(line_count)):
            st.markdown(f"**Product {index + 1}**")

            col1, col2 = st.columns([3, 1])

            with col1:
                variant_id = st.selectbox(
                    "Product variant",
                    options=variant_ids,
                    format_func=lambda item_id: variant_by_id[item_id]["label"],
                    key=f"sale_variant_{index}",
                )

            with col2:
                quantity = st.number_input(
                    "Quantity",
                    min_value=1,
                    max_value=100000,
                    value=1,
                    step=1,
                    key=f"sale_quantity_{index}",
                )

            selected = variant_by_id[variant_id]

            price = Decimal(str(selected["price"]))
            line_total = price * int(quantity)
            subtotal += line_total

            cart.append(
                {
                    "variant_id": variant_id,
                    "quantity": int(quantity),
                }
            )

            st.caption(
                f"Available stock: {selected['stock']} units · "
                f"Selling price: ₹{price:,.2f} · "
                f"Line total: ₹{line_total:,.2f}"
            )

        st.divider()

        discount = st.number_input(
            "Discount (₹)",
            min_value=0.0,
            max_value=float(subtotal),
            value=0.0,
            step=1.0,
            format="%.2f",
        )

        total = max(Decimal("0.00"), subtotal - Decimal(str(discount)))

        col1, col2, col3 = st.columns(3)

        col1.metric("Subtotal", f"₹{subtotal:,.2f}")
        col2.metric("Discount", f"₹{discount:,.2f}")
        col3.metric("Final Total", f"₹{total:,.2f}")

        payment_method = st.selectbox(
            "Payment Method",
            ["Cash", "UPI", "Card", "Bank Transfer", "Other"],
        )

        notes = st.text_area("Notes (optional)")

        submitted = st.form_submit_button(
            "Complete Sale",
            type="primary",
            use_container_width=True,
        )

        if submitted:
            variant_counts = {}

            for item in cart:
                variant_counts[item["variant_id"]] = (
                    variant_counts.get(item["variant_id"], 0)
                    + item["quantity"]
                )

            duplicates = [
                variant_id
                for variant_id, count in variant_counts.items()
                if count > 1
                and sum(
                    1 for item in cart
                    if item["variant_id"] == variant_id
                ) > 1
            ]

            if duplicates:
                st.error(
                    "The same product variant appears more than once. "
                    "Combine its quantities into one product line."
                )

            else:
                result = create_sale(
                    items=cart,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    discount=discount,
                    payment_method=payment_method,
                    notes=notes,
                )

                if result["success"]:
                    st.session_state["last_sale_id"] = result["sale_id"]

                    st.success(
                        f"Sale completed successfully! "
                        f"Invoice: {result['invoice_number']} · "
                        f"Total: ₹{float(result['total_amount']):,.2f}"
                    )

                    st.rerun()

                else:
                    st.error(result["message"])


with tab_history:
    st.subheader("Previous Sales")

    try:
        history = load_sales_history()

        if not history:
            st.info("No sales have been recorded yet.")

        else:
            history_df = pd.DataFrame(history)

            st.dataframe(
                history_df,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download Sales History (CSV)",
                data=history_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="sales_history.csv",
                mime="text/csv",
            )

            sale_ids = [row["Sale ID"] for row in history]

            selected_sale_id = st.selectbox(
                "Select a sale to view or print its bill",
                options=sale_ids,
                format_func=lambda sale_id: next(
                    row["Invoice Number"]
                    for row in history
                    if row["Sale ID"] == sale_id
                ),
            )

            sale_data, details = load_sale_details(selected_sale_id)

            if sale_data and details:
                st.markdown("---")
                st.subheader("Customer Invoice")

                st.markdown(
                    f"""
                    **Invoice:** {sale_data['invoice_number']}  
                    **Date:** {sale_data['sale_date'].strftime('%d-%m-%Y %H:%M')}  
                    **Customer:** {sale_data['customer_name']}  
                    **Phone:** {sale_data['customer_phone']}  
                    **Payment:** {sale_data['payment_method']}
                    """
                )

                st.dataframe(
                    pd.DataFrame(details),
                    use_container_width=True,
                    hide_index=True,
                )

                st.markdown(
                    f"""
                    **Subtotal:** ₹{sale_data['subtotal']:,.2f}  
                    **Discount:** ₹{sale_data['discount']:,.2f}  
                    # Total: ₹{sale_data['total_amount']:,.2f}
                    """
                )

                if sale_data["notes"]:
                    st.caption(f"Notes: {sale_data['notes']}")

                invoice_rows = pd.DataFrame(details).to_csv(index=False)

                st.download_button(
                    "Download Invoice Items (CSV)",
                    data=invoice_rows.encode("utf-8-sig"),
                    file_name=f"{sale_data['invoice_number']}_items.csv",
                    mime="text/csv",
                )

                st.info(
                    "To print this invoice, use your browser's Print command "
                    "(Ctrl+P). A dedicated print-friendly invoice layout "
                    "can be added in the next refinement."
                )

    except SQLAlchemyError:
        st.error("Unable to load sales history. Check the application terminal.")

