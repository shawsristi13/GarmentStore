
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal
from database.models import (
    Sale,
    SaleItem,
    Product,
    ProductVariant,
    SalesReturn,
    SalesReturnItem,
    Exchange,
    ExchangeItem,
)
from services.exchanges import process_exchange


st.set_page_config(
    page_title="Exchanges",
    page_icon="🔄",
    layout="wide",
)

st.title("🔄 Exchanges")
st.caption(
    "Exchange garments, calculate price differences, and record payment details."
)

PAYMENT_METHODS = [
    "Cash",
    "UPI",
    "Card",
    "Bank Transfer",
    "Other",
]


def load_sales():
    with SessionLocal() as session:
        sales = session.execute(
            select(Sale).order_by(
                Sale.sale_date.desc(),
                Sale.id.desc(),
            )
        ).scalars().all()

        return [
            {
                "id": sale.id,
                "invoice": sale.invoice_number,
                "date": sale.sale_date,
                "customer": sale.customer_name or "Walk-in Customer",
                "phone": sale.customer_phone or "-",
            }
            for sale in sales
        ]


def load_original_items(sale_id):
    with SessionLocal() as session:
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

        result = []

        for item, variant, product in rows:
            returned = session.execute(
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
                    SalesReturnItem.sale_item_id == item.id,
                )
            ).scalar_one()

            exchanged = session.execute(
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
                    ExchangeItem.original_sale_item_id == item.id,
                )
            ).scalar_one()

            returned = int(returned or 0)
            exchanged = int(exchanged or 0)

            remaining = max(
                0,
                item.quantity - returned - exchanged,
            )

            result.append(
                {
                    "sale_item_id": item.id,
                    "variant_id": item.variant_id,
                    "product": product.name,
                    "sku": variant.sku,
                    "size": variant.size or "-",
                    "color": variant.color or "-",
                    "sold": item.quantity,
                    "returned": returned,
                    "exchanged": exchanged,
                    "remaining": remaining,
                    "price": Decimal(
                        str(item.selling_price or 0)
                    ),
                }
            )

        return result


def load_replacement_variants():
    with SessionLocal() as session:
        rows = session.execute(
            select(ProductVariant, Product)
            .join(
                Product,
                Product.id == ProductVariant.product_id,
            )
            .where(
                ProductVariant.is_active.is_(True),
                Product.is_active.is_(True),
                ProductVariant.stock_quantity > 0,
            )
            .order_by(
                Product.name,
                ProductVariant.size,
                ProductVariant.color,
            )
        ).all()

        result = []

        for variant, product in rows:
            stock = (
                variant.stock_quantity
                if variant.stock_quantity is not None
                else variant.quantity
            )

            result.append(
                {
                    "id": variant.id,
                    "label": (
                        f"{product.name} | "
                        f"Size: {variant.size or '-'} | "
                        f"Color: {variant.color or '-'} | "
                        f"SKU: {variant.sku}"
                    ),
                    "stock": int(stock or 0),
                    "price": Decimal(
                        str(variant.selling_price or 0)
                    ),
                }
            )

        return result


def load_exchange_history():
    with SessionLocal() as session:
        rows = session.execute(
            select(Exchange, Sale)
            .join(
                Sale,
                Sale.id == Exchange.sale_id,
            )
            .order_by(
                Exchange.exchange_date.desc(),
                Exchange.id.desc(),
            )
        ).all()

        history = []

        for exchange, sale in rows:
            items = session.execute(
                select(
                    ExchangeItem,
                    ProductVariant,
                    Product,
                )
                .join(
                    ProductVariant,
                    ProductVariant.id
                    == ExchangeItem.replacement_variant_id,
                )
                .join(
                    Product,
                    Product.id == ProductVariant.product_id,
                )
                .where(
                    ExchangeItem.exchange_id == exchange.id
                )
            ).all()

            replacement_names = ", ".join(
                (
                    f"{product.name} "
                    f"(Size: {variant.size or '-'}, "
                    f"Color: {variant.color or '-'}) "
                    f"× {item.quantity}"
                )
                for item, variant, product in items
            )

            history.append(
                {
                    "Exchange Number": exchange.exchange_number,
                    "Original Invoice": sale.invoice_number,
                    "Date": (
                        exchange.exchange_date.strftime(
                            "%d-%m-%Y %H:%M"
                        )
                        if exchange.exchange_date
                        else ""
                    ),
                    "Customer": (
                        exchange.customer_name or "Walk-in Customer"
                    ),
                    "Replacement Items": replacement_names,
                    "Additional Payment (₹)": float(
                        exchange.additional_payment or 0
                    ),
                    "Payment Method": (
                        exchange.payment_method or "Cash"
                    ),
                    "Refund (₹)": float(
                        exchange.refund_amount or 0
                    ),
                    "Reason": exchange.reason or "-",
                    "Notes": exchange.notes or "",
                }
            )

        return history


tab_new, tab_history = st.tabs(
    [
        "➕ New Exchange",
        "📋 Exchange History",
    ]
)


# ---------------------------------------------------------
# NEW EXCHANGE
# ---------------------------------------------------------

with tab_new:
    st.subheader("Process Garment Exchange")

    try:
        sales = load_sales()
        variants = load_replacement_variants()

        if not sales:
            st.info(
                "No sales found. Complete a sale before processing "
                "an exchange."
            )

        elif not variants:
            st.warning(
                "No active replacement products have available stock."
            )

        else:
            sale_by_id = {
                sale["id"]: sale
                for sale in sales
            }

            selected_sale_id = st.selectbox(
                "Original Sales Invoice",
                options=list(sale_by_id),
                format_func=lambda sale_id: (
                    f"{sale_by_id[sale_id]['invoice']} | "
                    f"{sale_by_id[sale_id]['customer']} | "
                    f"{sale_by_id[sale_id]['date'].strftime('%d-%m-%Y %H:%M')}"
                ),
            )

            selected_sale = sale_by_id[selected_sale_id]

            st.write(
                f"**Customer:** {selected_sale['customer']}"
            )
            st.write(
                f"**Phone:** {selected_sale['phone']}"
            )

            original_items = load_original_items(
                selected_sale_id
            )

            if not original_items:
                st.warning(
                    "No products were found in this sale."
                )

            else:
                original_df = pd.DataFrame(
                    [
                        {
                            "Sale Item ID": item["sale_item_id"],
                            "Product": item["product"],
                            "SKU": item["sku"],
                            "Size": item["size"],
                            "Color": item["color"],
                            "Sold": item["sold"],
                            "Returned": item["returned"],
                            "Previously Exchanged": item["exchanged"],
                            "Eligible Quantity": item["remaining"],
                            "Original Unit Price (₹)": float(
                                item["price"]
                            ),
                        }
                        for item in original_items
                    ]
                )

                st.dataframe(
                    original_df,
                    use_container_width=True,
                    hide_index=True,
                )

                eligible_items = [
                    item
                    for item in original_items
                    if item["remaining"] > 0
                ]

                if not eligible_items:
                    st.warning(
                        "All units in this sale have already been "
                        "returned or exchanged."
                    )

                else:
                    st.markdown("### Exchange Details")

                    original_by_id = {
                        item["sale_item_id"]: item
                        for item in eligible_items
                    }

                    variant_by_id = {
                        item["id"]: item
                        for item in variants
                    }

                    with st.form("exchange_form"):
                        original_item_id = st.selectbox(
                            "Garment being returned",
                            options=list(original_by_id),
                            format_func=lambda item_id: (
                                f"{original_by_id[item_id]['product']} | "
                                f"Size: "
                                f"{original_by_id[item_id]['size']} | "
                                f"Color: "
                                f"{original_by_id[item_id]['color']} | "
                                f"Eligible: "
                                f"{original_by_id[item_id]['remaining']}"
                            ),
                        )

                        original_item = original_by_id[
                            original_item_id
                        ]

                        replacement_variant_id = st.selectbox(
                            "Replacement garment",
                            options=list(variant_by_id),
                            format_func=lambda variant_id: (
                                f"{variant_by_id[variant_id]['label']} | "
                                f"Stock: "
                                f"{variant_by_id[variant_id]['stock']} | "
                                f"Price: ₹"
                                f"{variant_by_id[variant_id]['price']:,.2f}"
                            ),
                        )

                        replacement = variant_by_id[
                            replacement_variant_id
                        ]

                        max_quantity = min(
                            int(original_item["remaining"]),
                            int(replacement["stock"]),
                        )

                        if max_quantity < 1:
                            st.warning(
                                "The selected replacement has no "
                                "available stock, or no original "
                                "units remain eligible."
                            )
                            quantity = 1

                        else:
                            quantity = st.number_input(
                                "Quantity to exchange",
                                min_value=1,
                                max_value=max_quantity,
                                value=1,
                                step=1,
                            )

                        original_value = (
                            original_item["price"] * int(quantity)
                        )

                        replacement_value = (
                            replacement["price"] * int(quantity)
                        )

                        difference = (
                            replacement_value - original_value
                        )

                        additional_payment = max(
                            difference,
                            Decimal("0.00"),
                        )

                        refund_amount = max(
                            -difference,
                            Decimal("0.00"),
                        )

                        st.divider()

                        col1, col2 = st.columns(2)

                        col1.metric(
                            "Value of Returned Garments",
                            f"₹{original_value:,.2f}",
                        )

                        col2.metric(
                            "Value of Replacement Garments",
                            f"₹{replacement_value:,.2f}",
                        )

                        if additional_payment > 0:
                            st.success(
                                "Customer must pay an additional "
                                f"₹{additional_payment:,.2f}."
                            )

                        elif refund_amount > 0:
                            st.info(
                                "Customer is due a refund of "
                                f"₹{refund_amount:,.2f}."
                            )

                        else:
                            st.info(
                                "There is no price difference."
                            )

                        payment_method = st.selectbox(
                            "Payment Method for Additional Payment",
                            options=PAYMENT_METHODS,
                            disabled=additional_payment == 0,
                        )

                        reason = st.selectbox(
                            "Reason for Exchange",
                            options=[
                                "Size issue",
                                "Color issue",
                                "Defective product",
                                "Wrong item",
                                "Customer preference",
                                "Other",
                            ],
                        )

                        notes = st.text_area(
                            "Additional Notes (optional)"
                        )

                        st.caption(
                            "The payment method is stored for reference. "
                            "The application does not itself collect "
                            "payments or issue actual refunds."
                        )

                        submitted = st.form_submit_button(
                            "Complete Exchange",
                            type="primary",
                            use_container_width=True,
                        )

                        if submitted:
                            if (
                                max_quantity < 1
                                or int(quantity) > max_quantity
                            ):
                                st.error(
                                    "The selected quantity exceeds "
                                    "the available stock or eligible "
                                    "original quantity."
                                )

                            elif (
                                original_item["variant_id"]
                                == replacement_variant_id
                            ):
                                st.error(
                                    "Choose a different product variant "
                                    "for the replacement."
                                )

                            else:
                                result = process_exchange(
                                    sale_id=selected_sale_id,
                                    original_sale_item_id=(
                                        original_item_id
                                    ),
                                    replacement_variant_id=(
                                        replacement_variant_id
                                    ),
                                    quantity=int(quantity),
                                    reason=reason,
                                    notes=notes,
                                    payment_method=payment_method,
                                )

                                if result.get("success"):
                                    st.success(
                                        "Exchange completed successfully! "
                                        f"Exchange Number: "
                                        f"{result['exchange_number']}"
                                    )

                                    st.write(
                                        "**Payment Method:** "
                                        f"{result['payment_method']}"
                                    )

                                    st.metric(
                                        "Additional Payment (₹)",
                                        (
                                            "₹"
                                            f"{float(result['additional_payment']):,.2f}"
                                        ),
                                    )

                                    st.metric(
                                        "Refund Amount (₹)",
                                        (
                                            "₹"
                                            f"{float(result['refund_amount']):,.2f}"
                                        ),
                                    )

                                    st.rerun()

                                else:
                                    st.error(
                                        result.get(
                                            "error",
                                            "Could not process "
                                            "the exchange.",
                                        )
                                    )

    except SQLAlchemyError:
        st.error(
            "Could not load exchange data. "
            "Check the application terminal for details."
        )


# ---------------------------------------------------------
# EXCHANGE HISTORY
# ---------------------------------------------------------

with tab_history:
    st.subheader("Exchange History")

    try:
        history = load_exchange_history()

        if not history:
            st.info(
                "No exchanges have been recorded yet."
            )

        else:
            history_df = pd.DataFrame(history)

            st.dataframe(
                history_df,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download Exchange History (CSV)",
                data=history_df.to_csv(
                    index=False
                ).encode("utf-8-sig"),
                file_name="exchange_history.csv",
                mime="text/csv",
            )

    except SQLAlchemyError:
        st.error(
            "Unable to load exchange history. "
            "Check the application terminal for details."
        )

