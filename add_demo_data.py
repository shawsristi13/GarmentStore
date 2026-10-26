from sqlalchemy import text
from database.db import engine

# Adds clearly labelled demo records to the LIVE database.
# Safe to rerun: demo products are identified by product_code/SKU,
# purchases and sales by invoice_number, and the demo expense by description.
# Existing records are not deleted or overwritten.

DEMO_PRODUCTS = [
    {
        "code": "DEMO-KURTI-001", "name": "Floral Cotton Kurti",
        "category": "Kurtis", "brand": "Demo Brand", "cost": 250,
        "price": 499, "color": "Pink", "size": "M", "stock": 10,
    },
    {
        "code": "DEMO-KURTI-002", "name": "Embroidered Kurti",
        "category": "Kurtis", "brand": "Demo Brand", "cost": 350,
        "price": 699, "color": "Blue", "size": "L", "stock": 8,
    },
    {
        "code": "DEMO-SAREE-001", "name": "Printed Cotton Saree",
        "category": "Sarees", "brand": "Demo Brand", "cost": 400,
        "price": 799, "color": "Green", "size": "Free Size", "stock": 6,
    },
    {
        "code": "DEMO-TOP-001", "name": "Casual Women Top",
        "category": "Tops", "brand": "Demo Brand", "cost": 180,
        "price": 399, "color": "White", "size": "M", "stock": 12,
    },
    {
        "code": "DEMO-DRESS-001", "name": "Floral Summer Dress",
        "category": "Dresses", "brand": "Demo Brand", "cost": 500,
        "price": 999, "color": "Yellow", "size": "L", "stock": 5,
    },
    {
        "code": "DEMO-JEANS-001", "name": "Women's Denim Jeans",
        "category": "Jeans", "brand": "Demo Brand", "cost": 600,
        "price": 1199, "color": "Black", "size": "30", "stock": 7,
    },
]


def table_columns(conn, table):
    result = conn.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table
    """), {"table": table})
    return {row[0] for row in result}


def main():
    with engine.begin() as conn:
        # Confirm expected tables exist before writing anything.
        required = [
            "products", "product_variants", "suppliers", "purchases",
            "purchase_items", "sales", "sale_items", "expenses",
        ]
        for table in required:
            exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = :table
                )
            """), {"table": table}).scalar()
            if not exists:
                raise RuntimeError(
                    f"Required table public.{table} is missing. No demo data was committed."
                )

        # 1. Products and variants.
        variants = []
        for item in DEMO_PRODUCTS:
            product_id = conn.execute(text("""
                SELECT id FROM public.products WHERE product_code = :code
            """), {"code": item["code"]}).scalar()

            if product_id is None:
                product_id = conn.execute(text("""
                    INSERT INTO public.products
                        (product_code, name, category, brand, purchase_price,
                         selling_price, description, is_active, created_at, updated_at)
                    VALUES
                        (:code, :name, :category, :brand, :cost,
                         :price, 'Demo data - safe to remove manually', TRUE, NOW(), NOW())
                    RETURNING id
                """), {
                    "code": item["code"], "name": item["name"],
                    "category": item["category"], "brand": item["brand"],
                    "cost": item["cost"], "price": item["price"],
                }).scalar()

            sku = f'{item["code"]}-{item["color"].upper().replace(" ", "")}-{item["size"].upper().replace(" ", "")}'
            variant_id = conn.execute(text("""
                SELECT id FROM public.product_variants WHERE sku = :sku
            """), {"sku": sku}).scalar()

            if variant_id is None:
                variant_id = conn.execute(text("""
                    INSERT INTO public.product_variants
                        (product_id, sku, color, size, purchase_price, selling_price,
                         stock_quantity, quantity, low_stock_threshold, is_active,
                         created_at, updated_at)
                    VALUES
                        (:product_id, :sku, :color, :size, :cost, :price,
                         :stock, :stock, 3, TRUE, NOW(), NOW())
                    RETURNING id
                """), {
                    "product_id": product_id, "sku": sku,
                    "color": item["color"], "size": item["size"],
                    "cost": item["cost"], "price": item["price"],
                    "stock": item["stock"],
                }).scalar()

            variants.append({
                "id": variant_id, "cost": item["cost"],
                "price": item["price"], "stock": item["stock"],
            })

        # 2. Supplier.
        supplier_id = conn.execute(text("""
            SELECT id FROM public.suppliers
            WHERE name = 'Demo Clothing Supplier'
            LIMIT 1
        """)).scalar()

        if supplier_id is None:
            supplier_id = conn.execute(text("""
                INSERT INTO public.suppliers
                    (name, business_name, phone, address, notes, is_active, created_at)
                VALUES
                    ('Demo Clothing Supplier', 'Demo Garments Wholesale',
                     '0000000000', 'Demo address', 'Sample/demo record', TRUE, NOW())
                RETURNING id
            """)).scalar()

        # 3. Purchase and items. This records the purchase but does not add
        # its quantities to stock again because opening stock was set above.
        purchase_id = conn.execute(text("""
            SELECT id FROM public.purchases
            WHERE invoice_number = 'DEMO-PUR-001'
        """)).scalar()

        if purchase_id is None:
            purchase_total = sum(v["cost"] * v["stock"] for v in variants)
            purchase_id = conn.execute(text("""
                INSERT INTO public.purchases
                    (supplier_id, invoice_number, purchase_date, total_amount, notes, created_at)
                VALUES
                    (:supplier_id, 'DEMO-PUR-001', NOW(), :total,
                     'Demo purchase; quantities are represented as demo opening stock', NOW())
                RETURNING id
            """), {"supplier_id": supplier_id, "total": purchase_total}).scalar()

            for v in variants:
                conn.execute(text("""
                    INSERT INTO public.purchase_items
                        (purchase_id, variant_id, quantity, purchase_price, subtotal)
                    VALUES (:purchase_id, :variant_id, :quantity, :cost, :subtotal)
                """), {
                    "purchase_id": purchase_id, "variant_id": v["id"],
                    "quantity": v["stock"], "cost": v["cost"],
                    "subtotal": v["cost"] * v["stock"],
                })

        # 4. One demo sale and sale item. Adjust stock only when creating it.
        sale_id = conn.execute(text("""
            SELECT id FROM public.sales
            WHERE invoice_number = 'DEMO-SALE-001'
        """)).scalar()

        if sale_id is None:
            v = variants[0]
            sale_id = conn.execute(text("""
                INSERT INTO public.sales
                    (invoice_number, sale_date, customer_name, subtotal, discount,
                     total_amount, payment_method, notes, created_at)
                VALUES
                    ('DEMO-SALE-001', NOW(), 'Demo Customer', :price, 0,
                     :price, 'Cash', 'Demo sale', NOW())
                RETURNING id
            """), {"price": v["price"]}).scalar()

            conn.execute(text("""
                INSERT INTO public.sale_items
                    (sale_id, variant_id, quantity, selling_price, subtotal)
                VALUES (:sale_id, :variant_id, 1, :price, :price)
            """), {
                "sale_id": sale_id, "variant_id": v["id"], "price": v["price"],
            })

            conn.execute(text("""
                UPDATE public.product_variants
                SET stock_quantity = stock_quantity - 1,
                    quantity = GREATEST(COALESCE(quantity, stock_quantity) - 1, 0),
                    updated_at = NOW()
                WHERE id = :variant_id AND stock_quantity > 0
            """), {"variant_id": v["id"]})

        # 5. One demo expense.
        expense_id = conn.execute(text("""
            SELECT id FROM public.expenses
            WHERE description = 'Demo shop electricity bill'
            LIMIT 1
        """)).scalar()

        if expense_id is None:
            conn.execute(text("""
                INSERT INTO public.expenses
                    (expense_date, category, description, amount, payment_method, notes, created_at)
                VALUES
                    (NOW(), 'Utilities', 'Demo shop electricity bill',
                     1200, 'Cash', 'Sample/demo expense', NOW())
            """))

    print("Demo data added successfully.")
    print("Processed: 6 demo products/variants, 1 supplier, 1 purchase, 1 sale, 1 expense.")
    print("Existing records were not deleted. Returns and exchanges were not created by this script.")


if __name__ == "__main__":
    main()
