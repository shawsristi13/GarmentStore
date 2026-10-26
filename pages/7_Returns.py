
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from database.models import (
    Sale,
    SaleItem,
    Product,
    ProductVariant,
    SalesReturn,
    SalesReturnItem,
)
from services.returns import process_return


st.set_page_config(
    page_title="Returns",
    page_icon="↩️",
    layout="wide",
)

st.title("↩️ Returns")
st.caption("Process customer returns, record refunds, and update inventory.")


def load_sales():
    with SessionLocal() as session:
        sales = session.execute(
            select(Sale).order_by(Sale.sale_date.desc(), Sale.id.desc())
        ).scalars().all()

        return [
            {
                "id": sale.id,
                "invoice_number": sale.invoice_number,
                "date": sale.sale_date,
                "customer_name": sale.customer_name or "Walk-in Customer",
                "customer_phone": sale.customer_phone or "-",
            }
            for sale in sales
        ]


def load_returnable_items(sale_id):
    with SessionLocal() as session:
        rows = session.execute(
            select(SaleItem, ProductVariant, Product)
            .join(ProductVariant, ProductVariant.id == SaleItem.variant_id)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(SaleItem.sale_id == sale_id)
            .order_by(SaleItem.id)
        ).all()

        result = []

        for item, variant, product in rows:
            returned_rows = session.execute(
                select(SalesReturnItem.quantity)
                .join(
                    SalesReturn,
                    SalesReturn.id == SalesReturnItem.return_id,
                )
                .where(
                    SalesReturn.sale_id == sale_id,
                    SalesReturnItem.sale_item_id == item.id,
                )
            ).scalars().all()

            returned_quantity = sum(returned_rows)
            remaining = max(0, item.quantity - returned_quantity)

            result.append(
                {
                    "sale_item_id": item.id,
                    "variant_id": variant.id,
                    "product": product.name,
                    "sku": variant.sku,
                    "size": variant.size or "-",
                    "color": variant.color or "-",
                    "sold_quantity": item.quantity,
                    "returned_quantity": returned_quantity,
                    "remaining": remaining,
                    "price": Decimal(str(item.selling_price)),
                }
            )

        return result


def load_return_history():
    with SessionLocal() as session:
        rows = session.execute(
            select(SalesReturn, Sale)
            .join(Sale, Sale.id == SalesReturn.sale_id)
            .order_by(SalesReturn.return_date.desc(), SalesReturn.id.desc())
        ).all()

        return [
            {
                "Return Number": record.return_number,
                "Original Invoice": sale.invoice_number,
                "Date": (
                    record.return_date.strftime("%d-%m-%Y %H:%M")
                    if record.return_date
                    else ""
                ),
                "Customer": record.customer_name or "Walk-in Customer",
                "Refund (₹)": float(record.refund_amount or 0),
                "Reason": record.reason or "-",
                "Notes": record.notes or "",
            }
            for record, sale in rows
        ]


tab_new, tab_history = st.tabs(["➕ Process Return", "📋 Return History"])


with tab_new:
    st.subheader("Process Customer Return")

    try:
        sales = load_sales()

        if not sales:
            st.info("No sales found. Complete a sale before recording a return.")

        else:
            sale_by_id = {sale["id"]: sale for sale in sales}
            sale_ids = list(sale_by_id)

            selected_sale_id = st.selectbox(
                "Select the original sales invoice",
                options=sale_ids,
                format_func=lambda sale_id: (
                    f"{sale_by_id[sale_id]['invoice_number']} | "
                    f"{sale_by_id[sale_id]['customer_name']} | "
                    f"{sale_by_id[sale_id]['date'].strftime('%d-%m-%Y %H:%M')}"
                ),
            )

            selected_sale = sale_by_id[selected_sale_id]

            st.write(f"**Customer:** {selected_sale['customer_name']}")
            st.write(f"**Phone:** {selected_sale['customer_phone']}")

            items = load_returnable_items(selected_sale_id)

            if not items:
                st.warning("No items were found for this sale.")

            else:
                display_items = [
                    {
                        "Sale Item ID": item["sale_item_id"],
                        "Product": item["product"],
                        "SKU": item["sku"],
                        "Size": item["size"],
                        "Color": item["color"],
                        "Sold": item["sold_quantity"],
                        "Previously Returned": item["returned_quantity"],
                        "Eligible to Return": item["remaining"],
                        "Original Unit Price (₹)": float(item["price"]),
                    }
                    for item in items
                ]

                st.dataframe(
                    pd.DataFrame(display_items),
                    use_container_width=True,
                    hide_index=True,
                )

                eligible_items = [
                    item for item in items if item["remaining"] > 0
                ]

                if not eligible_items:
                    st.warning(
                        "All items in this sale have already been returned."
                    )

                else:
                    st.markdown("### Return Details")

                    with st.form("return_form"):
                        eligible_ids = [
                            item["sale_item_id"] for item in eligible_items
                        ]
                        item_by_id = {
                            item["sale_item_id"]: item
                            for item in eligible_items
                        }

                        selected_item_id = st.selectbox(
                            "Product being returned",
                            options=eligible_ids,
                            format_func=lambda item_id: (
                                f"{item_by_id[item_id]['product']} | "
                                f"Size: {item_by_id[item_id]['size']} | "
                                f"Color: {item_by_id[item_id]['color']} | "
                                f"SKU: {item_by_id[item_id]['sku']}"
                            ),
                        )

                        chosen_item = item_by_id[selected_item_id]

                        return_quantity = st.number_input(
                            "Quantity being returned",
                            min_value=1,
                            max_value=int(chosen_item["remaining"]),
                            value=1,
                            step=1,
                        )

                        maximum_refund = (
                            chosen_item["price"] * int(return_quantity)
                        )

                        refund_amount = st.number_input(
                            "Refund Amount (₹)",
                            min_value=0.0,
                            max_value=float(maximum_refund),
                            value=float(maximum_refund),
                            step=1.0,
                            format="%.2f",
                        )

                        reason = st.selectbox(
                            "Reason for return",
                            [
                                "Size issue",
                                "Color issue",
                                "Defective product",
                                "Customer changed mind",
                                "Wrong item",
                                "Other",
                            ],
                        )

                        notes = st.text_area("Additional Notes (optional)")

                        restock = st.checkbox(
                            "Add returned item(s) back to inventory",
                            value=True,
                        )

                        st.caption(
                            "The refund amount is recorded for bookkeeping. "
                            "This page does not initiate an actual payment refund."
                        )

                        submitted = st.form_submit_button(
                            "Process Return",
                            type="primary",
                            use_container_width=True,
                        )

                        if submitted:
                            try:
                                parsed_refund = Decimal(str(refund_amount))

                                if not parsed_refund.is_finite():
                                    st.error("Enter a valid refund amount.")

                                else:
                                    result = process_return(
                                        sale_id=selected_sale_id,
                                        items=[
                                            {
                                                "sale_item_id": selected_item_id,
                                                "quantity": int(return_quantity),
                                                "refund_amount": str(parsed_refund),
                                            }
                                        ],
                                        reason=reason,
                                        notes=notes,
                                        restock=restock,
                                    )

                                    if result.get("success"):
                                        st.session_state["last_return_number"] = (
                                            result["return_number"]
                                        )
                                        st.success(
                                            "Return processed successfully! "
                                            f"Return number: "
                                            f"{result['return_number']}"
                                        )
                                        st.rerun()
                                    else:
                                        st.error(
                                            result.get(
                                                "error",
                                                "Could not process the return.",
                                            )
                                        )

                            except (InvalidOperation, ValueError, TypeError):
                                st.error("Enter valid return information.")

    except SQLAlchemyError:
        st.error(
            "Could not load sales or return information. "
            "Check the application terminal."
        )


with tab_history:
    st.subheader("Return History")

    try:
        history = load_return_history()

        if not history:
            st.info("No returns have been recorded yet.")

        else:
            history_df = pd.DataFrame(history)

            st.dataframe(
                history_df,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download Return History (CSV)",
                data=history_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="returns_history.csv",
                mime="text/csv",
            )

    except SQLAlchemyError:
        st.error(
            "Could not load return history. "
            "Check the application terminal."
        )

