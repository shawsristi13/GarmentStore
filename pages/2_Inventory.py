import pandas as pd
import streamlit as st

from database.db import SessionLocal
from database.models import Product, ProductVariant
from services.inventory import adjust_stock, InventoryError


st.set_page_config(
    page_title="Inventory | Garment Store",
    page_icon="📦",
    layout="wide",
)

st.title("📦 Inventory Management")
st.write(
    "View available stock, identify low-stock garments, "
    "and make controlled stock adjustments."
)

st.divider()


# --------------------------------------------------
# Load inventory
# --------------------------------------------------

session = SessionLocal()

try:
    results = (
        session.query(Product, ProductVariant)
        .join(
            ProductVariant,
            Product.id == ProductVariant.product_id,
        )
        .filter(
            Product.is_active.is_(True),
            ProductVariant.is_active.is_(True),
        )
        .order_by(Product.name.asc(), ProductVariant.size.asc())
        .all()
    )

    rows = []

    for product, variant in results:
        rows.append(
            {
                "Variant ID": variant.id,
                "Product": product.name,
                "Category": product.category,
                "SKU": variant.sku,
                "Size": variant.size,
                "Colour": variant.color,
                "Stock": variant.stock_quantity,
                "Low Stock Limit": variant.low_stock_threshold,
                "Purchase Price (₹)": float(variant.purchase_price),
                "Selling Price (₹)": float(variant.selling_price),
            }
        )

finally:
    session.close()


# --------------------------------------------------
# Inventory overview
# --------------------------------------------------

if not rows:
    st.info(
        "No active product variants found. "
        "Add a product on the Products page first."
    )

else:
    dataframe = pd.DataFrame(rows)

    total_variants = len(dataframe)
    total_units = int(dataframe["Stock"].sum())

    low_stock = dataframe[
        (dataframe["Stock"] > 0)
        & (dataframe["Stock"] <= dataframe["Low Stock Limit"])
    ]

    out_of_stock = dataframe[dataframe["Stock"] == 0]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Product Variants", total_variants)
    col2.metric("Total Units", total_units)
    col3.metric("Low Stock Variants", len(low_stock))
    col4.metric("Out of Stock", len(out_of_stock))

    st.divider()

    # --------------------------------------------------
    # Search and filters
    # --------------------------------------------------

    st.subheader("Current Inventory")

    search = st.text_input(
        "Search inventory",
        placeholder="Product name, SKU, size, or colour",
    )

    filter_type = st.selectbox(
        "Filter inventory",
        [
            "All Items",
            "Low Stock",
            "Out of Stock",
            "In Stock",
        ],
    )

    filtered = dataframe.copy()

    if search.strip():
        search_term = search.strip().lower()

        searchable_columns = [
            "Product",
            "Category",
            "SKU",
            "Size",
            "Colour",
        ]

        mask = filtered[searchable_columns].apply(
            lambda column: column.astype(str)
            .str.lower()
            .str.contains(search_term, regex=False)
        ).any(axis=1)

        filtered = filtered[mask]

    if filter_type == "Low Stock":
        filtered = filtered[
            (filtered["Stock"] > 0)
            & (filtered["Stock"] <= filtered["Low Stock Limit"])
        ]

    elif filter_type == "Out of Stock":
        filtered = filtered[filtered["Stock"] == 0]

    elif filter_type == "In Stock":
        filtered = filtered[filtered["Stock"] > 0]

    st.dataframe(
        filtered.drop(columns=["Variant ID"]),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(f"Showing {len(filtered)} variant(s).")

    if not low_stock.empty:
        st.warning(
            f"{len(low_stock)} variant(s) have reached "
            "their low-stock threshold."
        )

    if not out_of_stock.empty:
        st.error(
            f"{len(out_of_stock)} variant(s) are out of stock."
        )

    # --------------------------------------------------
    # Stock adjustment
    # --------------------------------------------------

    st.divider()
    st.subheader("Adjust Stock")

    st.write(
        "Use this form for physical stock corrections, "
        "damaged items, or other manual inventory adjustments."
    )

    variant_options = {
        (
            f"{row['Product']} | "
            f"{row['SKU']} | "
            f"{row['Size']} | "
            f"{row['Colour']} | "
            f"Stock: {row['Stock']}"
        ): int(row["Variant ID"])
        for _, row in dataframe.iterrows()
    }

    with st.form("inventory_adjustment_form"):

        selected_label = st.selectbox(
            "Select Product Variant",
            list(variant_options.keys()),
        )

        adjustment_type = st.selectbox(
            "Adjustment Type",
            [
                "Add Stock",
                "Remove Stock",
                "Set Exact Stock",
            ],
        )

        amount = st.number_input(
            "Quantity",
            min_value=0,
            value=1,
            step=1,
        )

        reason = st.text_input(
            "Reason *",
            placeholder=(
                "Example: Physical stock count or damaged garment"
            ),
        )

        submitted = st.form_submit_button(
            "Update Inventory",
            type="primary",
            use_container_width=True,
        )

        if submitted:

            if not reason.strip():
                st.error("Please provide a reason for the adjustment.")

            else:
                operation_map = {
                    "Add Stock": "ADD",
                    "Remove Stock": "REMOVE",
                    "Set Exact Stock": "SET",
                }

                try:
                    result = adjust_stock(
                        variant_id=variant_options[selected_label],
                        adjustment_type=operation_map[adjustment_type],
                        amount=int(amount),
                        reason=reason,
                    )

                    st.success(
                        f"Stock updated for SKU {result['sku']}: "
                        f"{result['previous_stock']} → "
                        f"{result['new_stock']} units."
                    )

                    st.info(
                        "Refresh the inventory display to see the "
                        "updated quantities."
                    )

                    st.rerun()

                except InventoryError as error:
                    st.error(str(error))