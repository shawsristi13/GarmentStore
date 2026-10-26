
import pandas as pd
import streamlit as st
from datetime import date, timedelta
from decimal import Decimal

from services.reports import (
    get_sales_summary,
    get_daily_sales,
    get_purchase_summary,
    get_expense_summary,
    get_return_summary,
    get_exchange_summary,
    get_inventory_summary,
    get_low_stock_report,
    get_top_selling_products,
)

st.set_page_config(
    page_title="Reports | Garment Store",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Reports & Analytics")
st.caption("Review sales, purchases, expenses, inventory, returns, and exchanges.")


def money(value):
    """Format a number as Indian rupees."""
    if value is None or pd.isna(value):
        value = 0
    return f"₹{float(value):,.2f}"


def first_value(dataframe, column, default=0):
    """Safely retrieve the first value from a report."""
    if dataframe.empty or column not in dataframe.columns:
        return default

    value = dataframe.iloc[0][column]

    return default if pd.isna(value) else value


def show_csv_download(dataframe, filename, label="Download CSV"):
    """Display a CSV download button when data is available."""
    if dataframe.empty:
        st.info("No data available to export.")
        return

    st.download_button(
        label=label,
        data=dataframe.to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
    )


# ---------------- DATE FILTERS ----------------

st.subheader("Reporting Period")

date_col1, date_col2 = st.columns(2)

with date_col1:
    start_date = st.date_input(
        "Start date",
        value=date.today() - timedelta(days=30),
        key="report_start_date",
    )

with date_col2:
    end_date = st.date_input(
        "End date",
        value=date.today(),
        key="report_end_date",
    )

if start_date > end_date:
    st.error("The start date cannot be after the end date.")
    st.stop()

st.caption(
    f"Showing records from {start_date.strftime('%d %b %Y')} "
    f"to {end_date.strftime('%d %b %Y')}."
)

st.divider()


# ---------------- LOAD REPORT DATA ----------------

try:
    sales = get_sales_summary(start_date, end_date)
    daily_sales = get_daily_sales(start_date, end_date)
    purchases = get_purchase_summary(start_date, end_date)
    expenses = get_expense_summary(start_date, end_date)
    returns = get_return_summary(start_date, end_date)
    exchanges = get_exchange_summary(start_date, end_date)

    inventory = get_inventory_summary()
    low_stock = get_low_stock_report()

    top_products = get_top_selling_products(
        start_date,
        end_date,
        limit=10,
    )

except Exception as error:
    st.error("Unable to load reports from the database.")
    st.exception(error)
    st.stop()


# ---------------- SALES OVERVIEW ----------------

st.header("💰 Sales Overview")

total_sales = first_value(sales, "total_sales")
transaction_count = int(first_value(sales, "transaction_count"))
average_sale = first_value(sales, "average_sale")
total_discount = first_value(sales, "discount")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Sales", money(total_sales))
col2.metric("Transactions", f"{transaction_count:,}")
col3.metric("Average Sale", money(average_sale))
col4.metric("Discounts", money(total_discount))

st.subheader("Daily Sales")

if not daily_sales.empty:
    chart_data = daily_sales.copy()
    chart_data["sale_day"] = pd.to_datetime(chart_data["sale_day"])
    chart_data = chart_data.set_index("sale_day")

    st.line_chart(
        chart_data[["total_sales"]],
        x_label="Date",
        y_label="Sales (₹)",
    )

    display_daily = daily_sales.copy()
    display_daily["sale_day"] = pd.to_datetime(
        display_daily["sale_day"]
    ).dt.strftime("%d-%m-%Y")

    display_daily = display_daily.rename(
        columns={
            "sale_day": "Date",
            "transaction_count": "Transactions",
            "discount": "Discount (₹)",
            "total_sales": "Sales (₹)",
        }
    )

    st.dataframe(
        display_daily,
        use_container_width=True,
        hide_index=True,
    )

    show_csv_download(
        display_daily,
        "daily_sales_report.csv",
    )
else:
    st.info("No sales found for this reporting period.")


# ---------------- PURCHASES AND EXPENSES ----------------

st.divider()
st.header("🛒 Purchases & Expenses")

purchase_count = int(first_value(purchases, "purchase_count"))
purchase_total = first_value(purchases, "total_purchases")

expense_total = sum(
    (Decimal(str(value)) for value in expenses.get(
        "total_amount", pd.Series(dtype=object)
    )),
    Decimal("0.00"),
)

col1, col2, col3 = st.columns(3)

col1.metric("Purchase Transactions", f"{purchase_count:,}")
col2.metric("Total Purchases", money(purchase_total))
col3.metric("Total Expenses", money(expense_total))

left, right = st.columns(2)

with left:
    st.subheader("Purchase Summary")
    purchase_display = purchases.rename(
        columns={
            "purchase_count": "Purchase Transactions",
            "total_purchases": "Total Purchases (₹)",
        }
    )
    st.dataframe(
        purchase_display,
        use_container_width=True,
        hide_index=True,
    )
    show_csv_download(
        purchase_display,
        "purchase_summary.csv",
    )

with right:
    st.subheader("Expenses by Category")

    if not expenses.empty:
        expense_display = expenses.rename(
            columns={
                "category": "Category",
                "expense_count": "Number of Expenses",
                "total_amount": "Total Amount (₹)",
            }
        )

        st.dataframe(
            expense_display,
            use_container_width=True,
            hide_index=True,
        )

        st.bar_chart(
            expenses.set_index("category")[["total_amount"]],
            x_label="Category",
            y_label="Amount (₹)",
        )

        show_csv_download(
            expense_display,
            "expenses_by_category.csv",
        )
    else:
        st.info("No expenses found for this reporting period.")


# ---------------- INVENTORY ----------------

st.divider()
st.header("📦 Inventory Report")

stock_units = int(first_value(inventory, "total_stock_units"))
variant_count = int(first_value(inventory, "variant_count"))
stock_cost = first_value(inventory, "stock_cost_value")
retail_value = first_value(inventory, "potential_retail_value")
out_of_stock = int(first_value(inventory, "out_of_stock_variants"))
low_stock_count = int(first_value(inventory, "low_stock_variants"))

col1, col2, col3 = st.columns(3)

col1.metric("Active Variants", f"{variant_count:,}")
col2.metric("Units in Stock", f"{stock_units:,}")
col3.metric("Stock Cost Value", money(stock_cost))

col1, col2, col3 = st.columns(3)

col1.metric("Potential Retail Value", money(retail_value))
col2.metric("Low-Stock Variants", f"{low_stock_count:,}")
col3.metric("Out-of-Stock Variants", f"{out_of_stock:,}")

st.caption(
    "Stock cost value estimates inventory at current variant purchase prices. "
    "Potential retail value assumes every available unit sells at its current "
    "selling price; neither figure is realized profit."
)

st.subheader("Low-Stock Items")

if not low_stock.empty:
    low_stock_display = low_stock.rename(
        columns={
            "product_name": "Product",
            "category": "Category",
            "brand": "Brand",
            "sku": "SKU",
            "size": "Size",
            "color": "Colour",
            "stock_quantity": "Current Stock",
            "low_stock_threshold": "Low-Stock Threshold",
            "purchase_price": "Purchase Price (₹)",
            "selling_price": "Selling Price (₹)",
        }
    )

    st.dataframe(
        low_stock_display,
        use_container_width=True,
        hide_index=True,
    )

    show_csv_download(
        low_stock_display,
        "low_stock_report.csv",
    )
else:
    st.success("No active variants are currently at or below their stock threshold.")


# ---------------- TOP-SELLING PRODUCTS ----------------

st.divider()
st.header("🏆 Top-Selling Products")

if not top_products.empty:
    top_display = top_products.rename(
        columns={
            "product_name": "Product",
            "category": "Category",
            "sku": "SKU",
            "size": "Size",
            "color": "Colour",
            "units_sold": "Units Sold",
            "recorded_item_sales": "Recorded Item Sales (₹)",
        }
    )

    st.dataframe(
        top_display,
        use_container_width=True,
        hide_index=True,
    )

    st.bar_chart(
        top_products.set_index("product_name")[["units_sold"]],
        x_label="Product",
        y_label="Units Sold",
    )

    show_csv_download(
        top_display,
        "top_selling_products.csv",
    )
else:
    st.info("No product sales found for this reporting period.")


# ---------------- RETURNS AND EXCHANGES ----------------

st.divider()
st.header("🔄 Returns & Exchanges")

return_count = int(first_value(returns, "return_count"))
refund_total = first_value(returns, "recorded_refunds")

exchange_count = int(first_value(exchanges, "exchange_count"))
additional_payments = first_value(
    exchanges,
    "additional_payments",
)
exchange_refunds = first_value(
    exchanges,
    "recorded_refunds",
)

col1, col2, col3 = st.columns(3)

col1.metric("Return Transactions", f"{return_count:,}")
col2.metric("Recorded Return Refunds", money(refund_total))
col3.metric("Exchange Transactions", f"{exchange_count:,}")

col1, col2 = st.columns(2)

col1.metric(
    "Exchange Additional Payments",
    money(additional_payments),
)
col2.metric(
    "Exchange Recorded Refunds",
    money(exchange_refunds),
)

returns_display = returns.rename(
    columns={
        "return_count": "Return Transactions",
        "recorded_refunds": "Recorded Refunds (₹)",
    }
)

exchanges_display = exchanges.rename(
    columns={
        "exchange_count": "Exchange Transactions",
        "additional_payments": "Additional Payments (₹)",
        "recorded_refunds": "Recorded Refunds (₹)",
    }
)

left, right = st.columns(2)

with left:
    st.subheader("Return Summary")
    st.dataframe(
        returns_display,
        use_container_width=True,
        hide_index=True,
    )
    show_csv_download(
        returns_display,
        "returns_summary.csv",
    )

with right:
    st.subheader("Exchange Summary")
    st.dataframe(
        exchanges_display,
        use_container_width=True,
        hide_index=True,
    )
    show_csv_download(
        exchanges_display,
        "exchanges_summary.csv",
    )


# ---------------- END ----------------

st.divider()
st.caption(
    "Reports are based on the records currently stored in your database. "
    "Recorded refunds and exchange differences do not confirm that money "
    "was actually transferred. A complete net-profit report requires "
    "additional accounting treatment for discounts, returns, exchanges, "
    "and product costs."
)

