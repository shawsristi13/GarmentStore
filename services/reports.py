
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import text

from database.db import engine


def _date_range(start_date=None, end_date=None):
    """Build an inclusive date range using an exclusive end timestamp."""

    start = datetime.combine(start_date, time.min) if start_date else None

    end = (
        datetime.combine(end_date + timedelta(days=1), time.min)
        if end_date
        else None
    )

    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    return start, end


def _range_conditions(column_name):
    """Return SQL date conditions for a trusted column name."""

    return f"""
        (:start_date IS NULL OR {column_name} >= :start_date)
        AND (:end_date IS NULL OR {column_name} < :end_date)
    """


def _range_params(start_date=None, end_date=None):
    start, end = _date_range(start_date, end_date)

    return {
        "start_date": start,
        "end_date": end,
    }


def _fetch_dataframe(query, params=None):
    """Execute a read-only report query and return a DataFrame."""

    with engine.connect() as connection:
        result = connection.execute(
            text(query),
            params or {},
        )

        return pd.DataFrame(
            result.fetchall(),
            columns=result.keys(),
        )


def get_sales_summary(start_date=None, end_date=None):
    """Return sales totals and transaction counts."""

    query = f"""
        SELECT
            COUNT(*) AS transaction_count,
            COALESCE(SUM(subtotal), 0) AS subtotal,
            COALESCE(SUM(discount), 0) AS discount,
            COALESCE(SUM(total_amount), 0) AS total_sales,
            COALESCE(AVG(total_amount), 0) AS average_sale
        FROM public.sales
        WHERE {_range_conditions("sale_date")}
    """

    return _fetch_dataframe(
        query,
        _range_params(start_date, end_date),
    )


def get_daily_sales(start_date=None, end_date=None):
    """Group sales by calendar date."""

    query = f"""
        SELECT
            sale_date::date AS sale_day,
            COUNT(*) AS transaction_count,
            COALESCE(SUM(discount), 0) AS discount,
            COALESCE(SUM(total_amount), 0) AS total_sales
        FROM public.sales
        WHERE {_range_conditions("sale_date")}
        GROUP BY sale_date::date
        ORDER BY sale_day
    """

    return _fetch_dataframe(
        query,
        _range_params(start_date, end_date),
    )


def get_purchase_summary(start_date=None, end_date=None):
    """Summarize supplier purchases."""

    query = f"""
        SELECT
            COUNT(*) AS purchase_count,
            COALESCE(SUM(total_amount), 0) AS total_purchases
        FROM public.purchases
        WHERE {_range_conditions("purchase_date")}
    """

    return _fetch_dataframe(
        query,
        _range_params(start_date, end_date),
    )


def get_expense_summary(start_date=None, end_date=None):
    """Summarize expenses by category."""

    query = f"""
        SELECT
            category,
            COUNT(*) AS expense_count,
            COALESCE(SUM(amount), 0) AS total_amount
        FROM public.expenses
        WHERE {_range_conditions("expense_date")}
        GROUP BY category
        ORDER BY total_amount DESC, category
    """

    return _fetch_dataframe(
        query,
        _range_params(start_date, end_date),
    )


def get_return_summary(start_date=None, end_date=None):
    """Summarize recorded sales returns and refund amounts."""

    query = f"""
        SELECT
            COUNT(*) AS return_count,
            COALESCE(SUM(refund_amount), 0) AS recorded_refunds
        FROM public.sales_returns
        WHERE {_range_conditions("return_date")}
    """

    return _fetch_dataframe(
        query,
        _range_params(start_date, end_date),
    )


def get_exchange_summary(start_date=None, end_date=None):
    """Summarize exchanges and recorded payment differences."""

    query = f"""
        SELECT
            COUNT(*) AS exchange_count,
            COALESCE(SUM(additional_payment), 0) AS additional_payments,
            COALESCE(SUM(refund_amount), 0) AS recorded_refunds
        FROM public.exchanges
        WHERE {_range_conditions("exchange_date")}
    """

    return _fetch_dataframe(
        query,
        _range_params(start_date, end_date),
    )


def get_inventory_summary():
    """Summarize active product variants and their stock valuation."""

    query = """
        SELECT
            COUNT(*) AS variant_count,
            COALESCE(SUM(GREATEST(stock_quantity, 0)), 0)
                AS total_stock_units,
            COALESCE(
                SUM(GREATEST(stock_quantity, 0) * purchase_price),
                0
            ) AS stock_cost_value,
            COALESCE(
                SUM(GREATEST(stock_quantity, 0) * selling_price),
                0
            ) AS potential_retail_value,
            COUNT(*) FILTER (
                WHERE stock_quantity <= 0
            ) AS out_of_stock_variants,
            COUNT(*) FILTER (
                WHERE stock_quantity > 0
                  AND stock_quantity <= low_stock_threshold
            ) AS low_stock_variants
        FROM public.product_variants
        WHERE is_active = TRUE
    """

    return _fetch_dataframe(query)


def get_low_stock_report():
    """List active variants at or below their low-stock threshold."""

    query = """
        SELECT
            p.id AS product_id,
            p.name AS product_name,
            p.category,
            p.brand,
            pv.id AS variant_id,
            pv.sku,
            pv.size,
            pv.color,
            pv.stock_quantity,
            pv.low_stock_threshold,
            pv.purchase_price,
            pv.selling_price
        FROM public.product_variants pv
        JOIN public.products p ON p.id = pv.product_id
        WHERE pv.is_active = TRUE
          AND p.is_active = TRUE
          AND pv.stock_quantity <= pv.low_stock_threshold
        ORDER BY pv.stock_quantity ASC, p.name, pv.size, pv.color
    """

    return _fetch_dataframe(query)


def get_top_selling_products(start_date=None, end_date=None, limit=10):
    """List variants with the greatest recorded sales quantities."""

    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100.")

    query = f"""
        SELECT
            p.name AS product_name,
            p.category,
            pv.sku,
            pv.size,
            pv.color,
            SUM(si.quantity) AS units_sold,
            SUM(si.subtotal) AS recorded_item_sales
        FROM public.sale_items si
        JOIN public.sales s ON s.id = si.sale_id
        JOIN public.product_variants pv ON pv.id = si.variant_id
        JOIN public.products p ON p.id = pv.product_id
        WHERE {_range_conditions("s.sale_date")}
        GROUP BY p.name, p.category, pv.sku, pv.size, pv.color
        ORDER BY units_sold DESC, recorded_item_sales DESC
        LIMIT :limit
    """

    params = _range_params(start_date, end_date)
    params["limit"] = limit

    return _fetch_dataframe(query, params)

