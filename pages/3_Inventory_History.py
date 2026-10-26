
import pandas as pd
import streamlit as st
from sqlalchemy import text

from database.db import SessionLocal


st.set_page_config(
    page_title="Inventory History | Garment Store",
    page_icon="📜",
    layout="wide",
)

st.title("📜 Inventory Movement History")
st.write(
    "View previous stock adjustments, including quantities, "
    "reasons, and timestamps."
)

st.divider()


def load_movement_history():
    """Retrieve stock movement records with their product details."""

    query = text(
        """
        SELECT
            im.id AS "Movement ID",
            im.created_at AS "Date & Time",
            p.name AS "Product",
            p.category AS "Category",
            pv.sku AS "SKU",
            pv.size AS "Size",
            pv.color AS "Colour",
            im.movement_type AS "Movement Type",
            im.previous_stock AS "Previous Stock",
            im.change_quantity AS "Change",
            im.new_stock AS "New Stock",
            im.reason AS "Reason"
        FROM public.inventory_movements im
        JOIN public.product_variants pv
            ON pv.id = im.variant_id
        JOIN public.products p
            ON p.id = pv.product_id
        ORDER BY im.created_at DESC, im.id DESC
        """
    )

    with SessionLocal() as session:
        result = session.execute(query)
        return pd.DataFrame(result.mappings().all())


try:
    history = load_movement_history()

except Exception as error:
    st.error("Unable to load inventory history.")
    st.code(str(error))
    st.stop()


if history.empty:
    st.info(
        "No inventory movements have been recorded yet. "
        "Go to Inventory Management and make a stock adjustment "
        "to create your first history record."
    )

else:
    total_movements = len(history)

    total_added = int(
        history.loc[history["Change"] > 0, "Change"].sum()
    )

    total_removed = abs(
        int(history.loc[history["Change"] < 0, "Change"].sum())
    )

    col1, col2, col3 = st.columns(3)

    col1.metric("Total Movements", total_movements)
    col2.metric("Units Added", total_added)
    col3.metric("Units Removed", total_removed)

    st.divider()
    st.subheader("Search and Filter")

    col1, col2 = st.columns(2)

    with col1:
        search = st.text_input(
            "Search history",
            placeholder="Product name, SKU, or reason",
        )

    with col2:
        movement_types = ["All"] + sorted(
            history["Movement Type"].dropna().unique().tolist()
        )

        selected_type = st.selectbox(
            "Movement Type",
            movement_types,
        )

    filtered = history.copy()

    if search.strip():
        term = search.strip().lower()

        search_columns = ["Product", "SKU", "Reason", "Category"]

        mask = filtered[search_columns].apply(
            lambda column: column.astype(str)
            .str.lower()
            .str.contains(term, regex=False)
        ).any(axis=1)

        filtered = filtered[mask]

    if selected_type != "All":
        filtered = filtered[
            filtered["Movement Type"] == selected_type
        ]

    display_history = filtered.copy()

    if not display_history.empty:
        display_history["Date & Time"] = pd.to_datetime(
            display_history["Date & Time"],
            errors="coerce",
        ).dt.strftime("%d %b %Y, %I:%M:%S %p")

        display_history["Change"] = display_history["Change"].apply(
            lambda value: f"+{value}" if value > 0 else str(value)
        )

    st.subheader("Movement Records")

    st.dataframe(
        display_history,
        width="stretch",
        hide_index=True,
    )

    st.caption(f"Showing {len(filtered)} of {total_movements} records.")

    if not filtered.empty:
        csv_data = filtered.to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            label="Download History as CSV",
            data=csv_data,
            file_name="inventory_movement_history.csv",
            mime="text/csv",
        )

