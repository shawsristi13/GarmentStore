
import re

import pandas as pd
import streamlit as st
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database.db import SessionLocal


st.set_page_config(
    page_title="Suppliers | Garment Store",
    page_icon="🏭",
    layout="wide",
)

st.title("🏭 Supplier Management")
st.write(
    "Register garment suppliers, manage their contact details, "
    "and keep supplier records organised."
)

st.divider()


def load_suppliers():
    query = text(
        """
        SELECT
            id,
            name,
            business_name,
            phone,
            email,
            address,
            notes,
            is_active,
            created_at
        FROM public.suppliers
        ORDER BY id DESC
        """
    )

    with SessionLocal() as session:
        return pd.DataFrame(session.execute(query).mappings().all())


def validate_supplier(name, phone, email):
    if not name.strip():
        return "Supplier name is required."

    if len(name.strip()) > 150:
        return "Supplier name must be 150 characters or fewer."

    if not phone.strip():
        return "Phone number is required."

    if len(phone.strip()) > 20:
        return "Phone number must be 20 characters or fewer."

    if not re.fullmatch(r"[0-9+\-() ]{7,20}", phone.strip()):
        return "Enter a valid phone number using digits and optional +, -, or parentheses."

    if email.strip():
        if len(email.strip()) > 150 or not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email.strip(),
        ):
            return "Enter a valid email address."

    return None


def save_supplier(
    name,
    business_name,
    phone,
    email,
    address,
    notes,
    supplier_id=None,
):
    error = validate_supplier(name, phone, email)

    if error:
        raise ValueError(error)

    values = {
        "name": name.strip(),
        "business_name": business_name.strip() or None,
        "phone": phone.strip(),
        "email": email.strip() or None,
        "address": address.strip() or None,
        "notes": notes.strip() or None,
    }

    if supplier_id is None:
        statement = text(
            """
            INSERT INTO public.suppliers (
                name, business_name, phone, email, address, notes
            )
            VALUES (
                :name, :business_name, :phone, :email, :address, :notes
            )
            """
        )
    else:
        statement = text(
            """
            UPDATE public.suppliers
            SET
                name = :name,
                business_name = :business_name,
                phone = :phone,
                email = :email,
                address = :address,
                notes = :notes
            WHERE id = :supplier_id
            """
        )
        values["supplier_id"] = supplier_id

    with SessionLocal() as session:
        with session.begin():
            result = session.execute(statement, values)

            if supplier_id is not None and result.rowcount == 0:
                raise ValueError("Supplier not found.")

    return True


def set_supplier_status(supplier_id, active):
    statement = text(
        """
        UPDATE public.suppliers
        SET is_active = :active
        WHERE id = :supplier_id
        """
    )

    with SessionLocal() as session:
        with session.begin():
            result = session.execute(
                statement,
                {"supplier_id": supplier_id, "active": active},
            )

            if result.rowcount == 0:
                raise ValueError("Supplier not found.")


try:
    suppliers = load_suppliers()
except SQLAlchemyError as error:
    st.error("Could not load suppliers from the database.")
    st.code(str(error))
    st.stop()


total_suppliers = len(suppliers)
active_suppliers = (
    int(suppliers["is_active"].sum()) if total_suppliers else 0
)
inactive_suppliers = total_suppliers - active_suppliers

col1, col2, col3 = st.columns(3)
col1.metric("Total Suppliers", total_suppliers)
col2.metric("Active Suppliers", active_suppliers)
col3.metric("Inactive Suppliers", inactive_suppliers)

st.divider()

tab_add, tab_view, tab_edit = st.tabs(
    ["➕ Add Supplier", "📋 View Suppliers", "✏️ Edit / Status"]
)


with tab_add:
    st.subheader("Register a New Supplier")

    with st.form("add_supplier_form", clear_on_submit=True):
        name = st.text_input("Contact Person / Supplier Name *")
        business_name = st.text_input("Business Name")
        phone = st.text_input("Phone Number *")
        email = st.text_input("Email Address")
        address = st.text_area("Address")
        notes = st.text_area("Notes")

        submitted = st.form_submit_button(
            "Save Supplier",
            type="primary",
            width="stretch",
        )

        if submitted:
            try:
                save_supplier(
                    name,
                    business_name,
                    phone,
                    email,
                    address,
                    notes,
                )
                st.success("Supplier saved successfully.")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
            except SQLAlchemyError as error:
                st.error("Database error while saving supplier.")
                st.code(str(error))


with tab_view:
    st.subheader("Supplier Directory")

    search = st.text_input(
        "Search suppliers",
        placeholder="Name, business, phone, or email",
        key="supplier_search",
    )

    status_filter = st.selectbox(
        "Status",
        ["All", "Active", "Inactive"],
        key="supplier_status_filter",
    )

    filtered = suppliers.copy()

    if search.strip():
        term = search.strip().lower()
        searchable_columns = [
            "name",
            "business_name",
            "phone",
            "email",
        ]

        mask = filtered[searchable_columns].apply(
            lambda column: column.fillna("").astype(str)
            .str.lower()
            .str.contains(term, regex=False)
        ).any(axis=1)

        filtered = filtered[mask]

    if status_filter == "Active":
        filtered = filtered[filtered["is_active"]]
    elif status_filter == "Inactive":
        filtered = filtered[~filtered["is_active"]]

    if not filtered.empty:
        display = filtered[
            [
                "id",
                "name",
                "business_name",
                "phone",
                "email",
                "address",
                "is_active",
            ]
        ].copy()

        display = display.rename(
            columns={
                "id": "Supplier ID",
                "name": "Contact Name",
                "business_name": "Business",
                "phone": "Phone",
                "email": "Email",
                "address": "Address",
                "is_active": "Active",
            }
        )

        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No suppliers match your search.")


with tab_edit:
    st.subheader("Edit Supplier or Change Status")

    if suppliers.empty:
        st.info("Add a supplier before using this section.")
    else:
        supplier_options = {
            (
                f"{row['name']} | "
                f"{row['business_name'] or 'No business name'} | "
                f"{row['phone']} | "
                f"ID {row['id']}"
            ): int(row["id"])
            for _, row in suppliers.iterrows()
        }

        selected_label = st.selectbox(
            "Select Supplier",
            list(supplier_options.keys()),
        )

        selected_id = supplier_options[selected_label]
        selected = suppliers[suppliers["id"] == selected_id].iloc[0]

        with st.form("edit_supplier_form"):
            edit_name = st.text_input(
                "Contact Person / Supplier Name *",
                value=selected["name"] or "",
            )
            edit_business = st.text_input(
                "Business Name",
                value=selected["business_name"] or "",
            )
            edit_phone = st.text_input(
                "Phone Number *",
                value=selected["phone"] or "",
            )
            edit_email = st.text_input(
                "Email Address",
                value=selected["email"] or "",
            )
            edit_address = st.text_area(
                "Address",
                value=selected["address"] or "",
            )
            edit_notes = st.text_area(
                "Notes",
                value=selected["notes"] or "",
            )

            save_changes = st.form_submit_button(
                "Save Changes",
                type="primary",
                width="stretch",
            )

            if save_changes:
                try:
                    save_supplier(
                        edit_name,
                        edit_business,
                        edit_phone,
                        edit_email,
                        edit_address,
                        edit_notes,
                        supplier_id=selected_id,
                    )
                    st.success("Supplier updated successfully.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
                except SQLAlchemyError as error:
                    st.error("Database error while updating supplier.")
                    st.code(str(error))

        current_active = bool(selected["is_active"])

        st.write(
            f"Current status: **{'Active' if current_active else 'Inactive'}**"
        )

        if current_active:
            if st.button(
                "Deactivate Supplier",
                key=f"deactivate_{selected_id}",
            ):
                try:
                    set_supplier_status(selected_id, False)
                    st.success("Supplier deactivated.")
                    st.rerun()
                except SQLAlchemyError as error:
                    st.error("Could not deactivate supplier.")
                    st.code(str(error))
        else:
            if st.button(
                "Activate Supplier",
                key=f"activate_{selected_id}",
            ):
                try:
                    set_supplier_status(selected_id, True)
                    st.success("Supplier activated.")
                    st.rerun()
                except SQLAlchemyError as error:
                    st.error("Could not activate supplier.")
                    st.code(str(error))

