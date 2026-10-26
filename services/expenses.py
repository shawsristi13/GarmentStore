from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from database.db import engine


def get_expenses(
    search="",
    category="All",
    start_date=None,
    end_date=None,
):
    """Fetch expenses with optional filters."""

    query = """
        SELECT
            id,
            expense_date,
            category,
            description,
            amount,
            payment_method,
            notes
        FROM public.expenses
        WHERE 1 = 1
    """

    params = {}

    if search.strip():
        query += """
            AND (
                category ILIKE :search
                OR COALESCE(description, '') ILIKE :search
                OR COALESCE(notes, '') ILIKE :search
            )
        """
        params["search"] = f"%{search.strip()}%"

    if category and category != "All":
        query += " AND category = :category"
        params["category"] = category

    if start_date:
        query += " AND expense_date >= :start_date"
        params["start_date"] = start_date

    if end_date:
        query += " AND expense_date < :end_date"
        params["end_date"] = end_date

    query += " ORDER BY expense_date DESC, id DESC"

    with engine.connect() as connection:
        rows = connection.execute(
            text(query),
            params,
        ).mappings().all()

    return [dict(row) for row in rows]


def get_expense_categories():
    """Return the distinct expense categories."""

    query = """
        SELECT DISTINCT category
        FROM public.expenses
        ORDER BY category
    """

    with engine.connect() as connection:
        rows = connection.execute(text(query)).scalars().all()

    return list(rows)


def add_expense(
    category,
    amount,
    description="",
    expense_date=None,
    payment_method="Cash",
    notes="",
):
    """Add a new expense."""

    category = category.strip() if category else ""

    if not category:
        raise ValueError("Expense category is required.")

    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Enter a valid expense amount.")

    if not amount.is_finite() or amount <= 0:
        raise ValueError("Expense amount must be greater than zero.")

    allowed_methods = {
        "Cash",
        "UPI",
        "Card",
        "Bank Transfer",
        "Other",
    }

    if payment_method not in allowed_methods:
        raise ValueError("Select a valid payment method.")

    query = text("""
        INSERT INTO public.expenses (
            expense_date,
            category,
            description,
            amount,
            payment_method,
            notes
        )
        VALUES (
            COALESCE(CAST(:expense_date AS TIMESTAMPTZ), NOW()),
            :category,
            :description,
            :amount,
            :payment_method,
            :notes
        )
        RETURNING id
    """)

    params = {
        "expense_date": expense_date,
        "category": category,
        "description": description.strip() if description else None,
        "amount": amount,
        "payment_method": payment_method,
        "notes": notes.strip() if notes else None,
    }

    with engine.begin() as connection:
        expense_id = connection.execute(
            query,
            params,
        ).scalar_one()

    return expense_id


def update_expense(
    expense_id,
    category,
    amount,
    description="",
    expense_date=None,
    payment_method="Cash",
    notes="",
):
    """Update an existing expense."""

    category = category.strip() if category else ""

    if not category:
        raise ValueError("Expense category is required.")

    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Enter a valid expense amount.")

    if not amount.is_finite() or amount <= 0:
        raise ValueError("Expense amount must be greater than zero.")

    allowed_methods = {
        "Cash",
        "UPI",
        "Card",
        "Bank Transfer",
        "Other",
    }

    if payment_method not in allowed_methods:
        raise ValueError("Select a valid payment method.")

    query = text("""
        UPDATE public.expenses
        SET
            expense_date = COALESCE(
                CAST(:expense_date AS TIMESTAMPTZ),
                expense_date
            ),
            category = :category,
            description = :description,
            amount = :amount,
            payment_method = :payment_method,
            notes = :notes
        WHERE id = :expense_id
        RETURNING id
    """)

    params = {
        "expense_id": expense_id,
        "expense_date": expense_date,
        "category": category,
        "description": description.strip() if description else None,
        "amount": amount,
        "payment_method": payment_method,
        "notes": notes.strip() if notes else None,
    }

    with engine.begin() as connection:
        updated_id = connection.execute(
            query,
            params,
        ).scalar_one_or_none()

    if updated_id is None:
        raise ValueError("Expense not found.")

    return updated_id


def delete_expense(expense_id):
    """Delete an expense by its ID."""

    query = text("""
        DELETE FROM public.expenses
        WHERE id = :expense_id
        RETURNING id
    """)

    with engine.begin() as connection:
        deleted_id = connection.execute(
            query,
            {"expense_id": expense_id},
        ).scalar_one_or_none()

    if deleted_id is None:
        raise ValueError("Expense not found.")

    return deleted_id