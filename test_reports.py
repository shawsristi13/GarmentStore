
import pandas as pd
import pytest

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


REPORT_FUNCTIONS = [
    ("Sales Summary", get_sales_summary),
    ("Daily Sales", get_daily_sales),
    ("Purchase Summary", get_purchase_summary),
    ("Expense Summary", get_expense_summary),
    ("Return Summary", get_return_summary),
    ("Exchange Summary", get_exchange_summary),
    ("Inventory Summary", get_inventory_summary),
    ("Low Stock Report", get_low_stock_report),
    ("Top Selling Products", get_top_selling_products),
]


@pytest.mark.parametrize(
    "report_name, report_function",
    REPORT_FUNCTIONS,
)
def test_report_returns_dataframe(report_name, report_function):
    """Each report should execute and return a pandas DataFrame."""

    result = report_function()

    assert isinstance(result, pd.DataFrame), (
        f"{report_name} did not return a pandas DataFrame."
    )

