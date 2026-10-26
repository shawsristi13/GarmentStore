import pandas as pd
import streamlit as st
from sqlalchemy import text

from database.db import Base, engine
from database import models

Base.metadata.create_all(bind=engine)

st.set_page_config(
    page_title="Garment Store Management",
    page_icon="👗",
    layout="wide",
    initial_sidebar_state="expanded",
)


def fetch_data(query, params=None):
    """Execute a read-only query and return its results as a DataFrame."""
    with engine.connect() as connection:
        result = connection.execute(
            text(query),
            params or {},
        )
        return pd.DataFrame(result.mappings().all())


def format_currency(value):
    """Format an amount in Indian rupees."""
    return f"₹{float(value or 0):,.2f}"


def format_integer(value):
    """Format a count as an integer."""
    return f"{int(value or 0):,}"


st.title("👗 Garment Store Management System")

st.write(
    "Manage your garments, inventory, suppliers, purchases, "
    "sales, returns, exchanges, and expenses in one place."
)

st.divider()

st.header("Dashboard")

# Refresh dashboard data when the user requests it.
if st.button("🔄 Refresh Dashboard"):
    st.rerun()


try:
    # --------------------------------------------------
    # 1. Dashboard summary
    # --------------------------------------------------

    summary = fetch_data(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM products
                WHERE is_active = TRUE
            ) AS total_products,

            (
                SELECT COALESCE(SUM(stock_quantity), 0)
                FROM product_variants
                WHERE is_active = TRUE
            ) AS total_stock_units,

            (
                SELECT COALESCE(SUM(total_amount), 0)
                FROM sales
                WHERE sale_date >= CURRENT_DATE
                  AND sale_date < CURRENT_DATE + INTERVAL '1 day'
            ) AS today_sales,

            (
                SELECT COUNT(*)
                FROM product_variants
                WHERE is_active = TRUE
                  AND stock_quantity <= low_stock_threshold
            ) AS low_stock_items,

            (
                SELECT COUNT(*)
                FROM sales
                WHERE sale_date >= CURRENT_DATE
                  AND sale_date < CURRENT_DATE + INTERVAL '1 day'
            ) AS today_transactions
        """
    )

    if summary.empty:
        st.warning("Dashboard summary data is unavailable.")
        st.stop()

    metrics = summary.iloc[0]

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Active Products",
            format_integer(metrics["total_products"]),
        )

    with col2:
        st.metric(
            "Total Stock Units",
            format_integer(metrics["total_stock_units"]),
        )

    with col3:
        st.metric(
            "Today's Sales",
            format_currency(metrics["today_sales"]),
        )

    with col4:
        st.metric(
            "Low-Stock Variants",
            format_integer(metrics["low_stock_items"]),
        )

    st.metric(
        "Today's Sales Transactions",
        format_integer(metrics["today_transactions"]),
    )

    st.caption(
        "Low-stock variants include items whose stock is equal to "
        "or below their configured threshold."
    )

    st.divider()

    # --------------------------------------------------
    # 2. Low-stock alerts
    # --------------------------------------------------

    st.subheader("⚠️ Low-Stock Alerts")

    low_stock = fetch_data(
        """
        SELECT
            p.name AS product,
            p.category,
            pv.sku,
            pv.size,
            pv.color,
            pv.stock_quantity AS stock,
            pv.low_stock_threshold AS threshold
        FROM product_variants pv
        JOIN products p ON p.id = pv.product_id
        WHERE p.is_active = TRUE
          AND pv.is_active = TRUE
          AND pv.stock_quantity <= pv.low_stock_threshold
        ORDER BY pv.stock_quantity ASC, p.name ASC
        LIMIT 20
        """
    )

    if low_stock.empty:
        st.success("No low-stock items. Your stock levels look good!")
    else:
        st.dataframe(
            low_stock,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Showing up to 20 low-stock variants. "
            "Open Inventory for complete stock management."
        )

    st.divider()

    # --------------------------------------------------
    # 3. Recent sales
    # --------------------------------------------------

    st.subheader("🛍️ Recent Sales")

    recent_sales = fetch_data(
        """
        SELECT
            invoice_number AS invoice,
            sale_date AS date,
            COALESCE(customer_name, 'Walk-in Customer') AS customer,
            total_amount AS total,
            payment_method AS payment
        FROM sales
        ORDER BY sale_date DESC, id DESC
        LIMIT 10
        """
    )

    if recent_sales.empty:
        st.info("No sales have been recorded yet.")
    else:
        recent_sales["total"] = recent_sales["total"].apply(
            format_currency
        )

        st.dataframe(
            recent_sales,
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # --------------------------------------------------
    # 4. Recent inventory activity
    # --------------------------------------------------

    st.subheader("📦 Recent Inventory Activity")

    inventory_activity = fetch_data(
        """
        SELECT
            p.name AS product,
            pv.sku,
            pv.size,
            pv.color,
            im.movement_type AS activity,
            im.previous_stock AS previous_stock,
            im.change_quantity AS stock_change,
            im.new_stock AS current_stock,
            im.reason,
            im.created_at AS date
        FROM inventory_movements im
        JOIN product_variants pv ON pv.id = im.variant_id
        JOIN products p ON p.id = pv.product_id
        ORDER BY im.created_at DESC, im.id DESC
        LIMIT 10
        """
    )

    if inventory_activity.empty:
        st.info("No inventory movements have been recorded yet.")
    else:
        st.dataframe(
            inventory_activity,
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # --------------------------------------------------
    # 5. Quick navigation
    # --------------------------------------------------

    st.subheader("🚀 Quick Start")

    st.write(
        "Use the pages in the sidebar to manage your store."
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            """
            **Products & Inventory**

            - Add products and variants
            - Check stock availability
            - Review inventory history
            """
        )

    with col2:
        st.markdown(
            """
            **Purchases & Sales**

            - Record supplier purchases
            - Create sales transactions
            - Manage returns and exchanges
            """
        )

    with col3:
        st.markdown(
            """
            **Business Management**

            - Maintain supplier records
            - Track operating expenses
            - Review reports and analytics
            """
        )

except Exception as error:
    st.error(
        "The dashboard could not load data from the database."
    )

    st.info(
        "Please check your database connection and table permissions."
    )

    with st.expander("Technical error details"):
        st.code(str(error))