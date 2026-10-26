from database.db import engine
from sqlalchemy import inspect

inspector = inspect(engine)

for table in ["products", "product_variants", "suppliers", "purchases", "purchase_items", "sales", "sale_items", "expenses"]:
    print(f"\n--- {table} ---")
    for column in inspector.get_columns(table, schema="public"):
        print(f"{column['name']} ({column['type']})")
