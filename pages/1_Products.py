
import streamlit as st
import pandas as pd

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database.db import SessionLocal
from database.models import Product, ProductVariant


st.set_page_config(
    page_title="Products | Garment Store",
    page_icon="👗",
    layout="wide",
)

st.title("👗 Product Management")
st.write("Add garments, manage variants, and view saved products.")

st.divider()

# --------------------------------------------------
# Add a new product
# --------------------------------------------------

st.subheader("Add New Product")

with st.form("add_product_form", clear_on_submit=True):

    name = st.text_input(
        "Product Name *",
        placeholder="Example: Cotton Kurti",
    )

    col1, col2 = st.columns(2)

    with col1:
        category = st.selectbox(
            "Category *",
            [
                "Kurtis",
                "Sarees",
                "Tops",
                "Shirts",
                "Jeans",
                "Trousers",
                "Dresses",
                "Ethnic Wear",
                "Other",
            ],
        )

        brand = st.text_input(
            "Brand",
            placeholder="Example: Local Brand",
        )

        size = st.selectbox(
            "Size *",
            [
                "One Size",
                "XS",
                "S",
                "M",
                "L",
                "XL",
                "XXL",
                "3XL",
                "Free Size",
            ],
        )

    with col2:
        color = st.text_input(
            "Colour *",
            placeholder="Example: Black",
        )

        sku = st.text_input(
            "SKU *",
            placeholder="Example: KUR-BLK-M-001",
        )

        purchase_price = st.number_input(
            "Purchase Price (₹) *",
            min_value=0.0,
            value=100.0,
            step=10.0,
        )

        selling_price = st.number_input(
            "Selling Price (₹) *",
            min_value=0.0,
            value=150.0,
            step=10.0,
        )

    col3, col4 = st.columns(2)

    with col3:
        stock_quantity = st.number_input(
            "Opening Stock Quantity *",
            min_value=0,
            value=0,
            step=1,
        )

    with col4:
        low_stock_threshold = st.number_input(
            "Low Stock Alert Threshold",
            min_value=0,
            value=5,
            step=1,
        )

    description = st.text_area("Description")

    submitted = st.form_submit_button(
        "Save Product",
        type="primary",
        use_container_width=True,
    )

    if submitted:

        if not name.strip():
            st.error("Please enter a product name.")

        elif not color.strip():
            st.error("Please enter a colour.")

        elif not sku.strip():
            st.error("Please enter a unique SKU.")

        elif selling_price < purchase_price:
            st.warning(
                "The selling price is below the purchase price. "
                "Check the prices before saving."
            )

        else:
            session = SessionLocal()

            try:
                product = Product(
                    name=name.strip(),
                    category=category,
                    brand=brand.strip() or None,
                    description=description.strip() or None,
                )

                session.add(product)
                session.flush()

                # Both database stock columns must receive
                # the same opening quantity.
                variant = ProductVariant(
                    product_id=product.id,
                    sku=sku.strip(),
                    size=size,
                    color=color.strip(),
                    purchase_price=purchase_price,
                    selling_price=selling_price,
                    quantity=int(stock_quantity),
                    stock_quantity=int(stock_quantity),
                    low_stock_threshold=int(low_stock_threshold),
                )

                session.add(variant)
                session.commit()

                st.success(
                    f"Product '{name.strip()}' saved successfully!"
                )

            except IntegrityError as error:
                session.rollback()

                error_message = str(error.orig)

                if "uq_variant_product_size_color" in error_message:
                    st.error(
                        "This product already has a variant "
                        "with the same size and colour."
                    )
                elif "sku" in error_message.lower():
                    st.error(
                        "This SKU already exists. "
                        "Please enter a unique SKU."
                    )
                else:
                    st.error(f"Database error: {error.orig}")

            except SQLAlchemyError as error:
                session.rollback()
                st.error(f"Database error: {error}")

            finally:
                session.close()


# --------------------------------------------------
# Display saved products
# --------------------------------------------------

st.divider()
st.subheader("Saved Products")

session = SessionLocal()

try:
    statement = (
        select(Product, ProductVariant)
        .join(
            ProductVariant,
            Product.id == ProductVariant.product_id,
        )
        .where(
            Product.is_active.is_(True),
            ProductVariant.is_active.is_(True),
        )
        .order_by(Product.id.desc())
    )

    results = session.execute(statement).all()

    if results:
        rows = []

        for product, variant in results:
            rows.append(
                {
                    "Product ID": product.id,
                    "Product Name": product.name,
                    "Category": product.category,
                    "Brand": product.brand or "-",
                    "SKU": variant.sku,
                    "Size": variant.size,
                    "Colour": variant.color,
                    "Purchase Price (₹)": float(
                        variant.purchase_price
                    ),
                    "Selling Price (₹)": float(
                        variant.selling_price
                    ),
                    "Stock": variant.stock_quantity,
                    "Low Stock Threshold": variant.low_stock_threshold,
                }
            )

        dataframe = pd.DataFrame(rows)

        search = st.text_input(
            "Search by product name, category, SKU, or colour",
            placeholder="Type to search...",
        )

        if search.strip():
            search_lower = search.strip().lower()

            mask = dataframe.apply(
                lambda row: row.astype(str)
                .str.lower()
                .str.contains(search_lower, regex=False)
                .any(),
                axis=1,
            )

            dataframe = dataframe[mask]

        st.dataframe(
            dataframe,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            f"Showing {len(dataframe)} product variant(s)."
        )

        low_stock_items = dataframe[
            dataframe["Stock"]
            <= dataframe["Low Stock Threshold"]
        ]

        if not low_stock_items.empty:
            st.warning(
                f"{len(low_stock_items)} displayed variant(s) "
                "are at or below their low-stock threshold."
            )

    else:
        st.info(
            "No products have been added yet. "
            "Use the form above to add your first garment."
        )

except SQLAlchemyError as error:
    st.error(f"Could not load products: {error}")

finally:
    session.close()

