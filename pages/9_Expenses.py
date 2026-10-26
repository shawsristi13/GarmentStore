
import pandas as pd
import streamlit as st
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from services.expenses import (
    add_expense,
    get_expenses,
    get_expense_categories,
    update_expense,
    delete_expense,
)

st.set_page_config(
    page_title="Expenses | Garment Store",
    page_icon="💰",
    layout="wide",
)

st.title("💰 Expense Management")
st.caption("Record, track, edit, and review your store expenses.")

PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer", "Other"]

DEFAULT_CATEGORIES = [
    "Rent",
    "Electricity",
    "Salary",
    "Transport",
    "Packaging",
    "Maintenance",
    "Internet",
    "Marketing",
    "Other",
]


def money(value):
    return f"₹{float(value or 0):,.2f}"


# -------------------- SUMMARY --------------------

try:
    all_expenses = get_expenses()
except Exception as error:
    st.error(f"Unable to load expenses: {error}")
    st.stop()

total_expenses = sum(
    (Decimal(str(row["amount"])) for row in all_expenses),
    Decimal("0.00"),
)

col1, col2 = st.columns(2)

with col1:
    st.metric("Total Recorded Expenses", money(total_expenses))

with col2:
    st.metric("Number of Expenses", len(all_expenses))

st.divider()


# -------------------- TABS --------------------

add_tab, history_tab, manage_tab = st.tabs(
    ["➕ Add Expense", "📋 Expense History", "✏️ Edit / Delete"]
)


# -------------------- ADD EXPENSE --------------------

with add_tab:
    st.subheader("Record a New Expense")

    with st.form("add_expense_form", clear_on_submit=True):
        expense_date = st.date_input(
            "Expense Date",
            value=date.today(),
        )

        category_choice = st.selectbox(
            "Expense Category",
            DEFAULT_CATEGORIES,
        )

        custom_category = ""
        if category_choice == "Other":
            custom_category = st.text_input(
                "Enter Category",
                placeholder="e.g. Insurance",
            )

        description = st.text_input(
            "Description",
            placeholder="e.g. September shop electricity bill",
        )

        amount = st.number_input(
            "Amount (₹)",
            min_value=0.01,
            value=100.00,
            step=50.00,
            format="%.2f",
        )

        payment_method = st.selectbox(
            "Payment Method",
            PAYMENT_METHODS,
        )

        notes = st.text_area("Additional Notes")

        submitted = st.form_submit_button(
            "Save Expense",
            type="primary",
            use_container_width=True,
        )

        if submitted:
            final_category = (
                custom_category.strip()
                if category_choice == "Other"
                else category_choice
            )

            if not final_category:
                st.error("Please enter an expense category.")
            else:
                try:
                    expense_id = add_expense(
                        category=final_category,
                        amount=amount,
                        description=description,
                        expense_date=datetime.combine(
                            expense_date,
                            time.min,
                        ),
                        payment_method=payment_method,
                        notes=notes,
                    )

                    st.success(
                        f"Expense saved successfully! Record ID: {expense_id}"
                    )
                    st.rerun()

                except Exception as error:
                    st.error(f"Unable to save expense: {error}")


# -------------------- EXPENSE HISTORY --------------------

with history_tab:
    st.subheader("Expense History")

    filter1, filter2 = st.columns(2)

    with filter1:
        search_text = st.text_input(
            "Search",
            placeholder="Search category, description, or notes",
            key="history_search",
        )

    with filter2:
        categories = get_expense_categories()
        category_options = ["All"] + categories

        selected_category = st.selectbox(
            "Filter by Category",
            category_options,
            key="history_category",
        )

    date_col1, date_col2 = st.columns(2)

    with date_col1:
        start_date = st.date_input(
            "From Date",
            value=None,
            key="history_start_date",
        )

    with date_col2:
        end_date = st.date_input(
            "To Date",
            value=None,
            key="history_end_date",
        )

    if start_date and end_date and start_date > end_date:
        st.error("The start date cannot be after the end date.")
        filtered_expenses = []
    else:
        filtered_expenses = get_expenses(
            search=search_text,
            category=selected_category,
            start_date=(
                datetime.combine(start_date, time.min)
                if start_date
                else None
            ),
            end_date=(
                datetime.combine(
                    end_date + timedelta(days=1),
                    time.min,
                )
                if end_date
                else None
            ),
        )

    st.write(f"Matching records: **{len(filtered_expenses)}**")

    if filtered_expenses:
        display_rows = []

        for row in filtered_expenses:
            display_rows.append(
                {
                    "ID": row["id"],
                    "Date": row["expense_date"].strftime("%d-%m-%Y"),
                    "Category": row["category"],
                    "Description": row["description"] or "",
                    "Amount (₹)": float(row["amount"]),
                    "Payment Method": row["payment_method"],
                    "Notes": row["notes"] or "",
                }
            )

        df = pd.DataFrame(display_rows)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "⬇️ Download CSV",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"expenses_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.info(
            "Filtered total: "
            + money(
                sum(
                    (Decimal(str(row["amount"])) for row in filtered_expenses),
                    Decimal("0.00"),
                )
            )
        )

    else:
        st.info("No expenses match the selected filters.")


# -------------------- EDIT / DELETE --------------------

with manage_tab:
    st.subheader("Manage Existing Expenses")

    if not all_expenses:
        st.info("No expenses have been recorded yet.")
    else:
        expense_options = {
            (
                f"#{row['id']} | {row['category']} | "
                f"{money(row['amount'])} | "
                f"{row['expense_date'].strftime('%d-%m-%Y')}"
            ): row
            for row in all_expenses
        }

        selected_label = st.selectbox(
            "Select an Expense",
            list(expense_options.keys()),
        )

        selected_expense = expense_options[selected_label]

        st.write("### Edit Expense")

        with st.form("edit_expense_form"):
            edit_date = st.date_input(
                "Expense Date",
                value=selected_expense["expense_date"].date(),
                key="edit_date",
            )

            edit_category = st.text_input(
                "Category",
                value=selected_expense["category"],
                key="edit_category",
            )

            edit_description = st.text_input(
                "Description",
                value=selected_expense["description"] or "",
                key="edit_description",
            )

            edit_amount = st.number_input(
                "Amount (₹)",
                min_value=0.01,
                value=float(selected_expense["amount"]),
                step=50.00,
                format="%.2f",
                key="edit_amount",
            )

            current_method = selected_expense["payment_method"]

            edit_payment_method = st.selectbox(
                "Payment Method",
                PAYMENT_METHODS,
                index=(
                    PAYMENT_METHODS.index(current_method)
                    if current_method in PAYMENT_METHODS
                    else 0
                ),
                key="edit_payment_method",
            )

            edit_notes = st.text_area(
                "Notes",
                value=selected_expense["notes"] or "",
                key="edit_notes",
            )

            update_clicked = st.form_submit_button(
                "Update Expense",
                type="primary",
                use_container_width=True,
            )

            if update_clicked:
                if not edit_category.strip():
                    st.error("Category is required.")
                else:
                    try:
                        update_expense(
                            expense_id=selected_expense["id"],
                            category=edit_category,
                            amount=edit_amount,
                            description=edit_description,
                            expense_date=datetime.combine(
                                edit_date,
                                time.min,
                            ),
                            payment_method=edit_payment_method,
                            notes=edit_notes,
                        )

                        st.success("Expense updated successfully.")
                        st.rerun()

                    except Exception as error:
                        st.error(f"Unable to update expense: {error}")

        st.divider()
        st.write("### Delete Expense")

        st.warning(
            "Deleting an expense permanently removes its record. "
            "Make sure you have selected the correct expense."
        )

        confirm_delete = st.checkbox(
            f"I confirm that I want to delete expense #{selected_expense['id']}.",
            key=f"confirm_delete_{selected_expense['id']}",
        )

        if st.button(
            "🗑️ Delete Selected Expense",
            disabled=not confirm_delete,
            type="secondary",
            use_container_width=True,
        ):
            try:
                delete_expense(selected_expense["id"])
                st.success("Expense deleted successfully.")
                st.rerun()

            except Exception as error:
                st.error(f"Unable to delete expense: {error}")

