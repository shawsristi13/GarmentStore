from database.db import engine
from sqlalchemy import text

query = text("""
    SELECT
        p.id,
        p.name,
        p.is_active AS product_active,
        pv.sku,
        pv.is_active AS variant_active
    FROM public.products p
    JOIN public.product_variants pv
        ON pv.product_id = p.id
    ORDER BY p.id
""")

with engine.connect() as connection:
    rows = connection.execute(query).mappings().all()

    for row in rows:
        print(dict(row))

    print(f"\nTotal active products/variants: {sum(1 for r in rows if r['product_active'] and r['variant_active'])}")