"""Add normalized invoice identity unique expression indexes and supplier name index

Revision ID: 708192a3b4c5
Revises: 6f708192a3b4
Create Date: 2026-11-23 20:30:00.000000

Adds partial unique expression indexes to purchases and suppliers:
1. uq_purchases_shop_supplier_lower_inv: (shop_id, supplier_id, lower(trim(invoice_number)))
   WHERE supplier_id IS NOT NULL AND invoice_number IS NOT NULL
2. uq_purchases_shop_null_supplier_lower_inv: (shop_id, lower(trim(invoice_number)))
   WHERE supplier_id IS NULL AND invoice_number IS NOT NULL
3. uq_suppliers_shop_lower_name: (shop_id, lower(trim(supplier_name)))

These indexes guarantee strict concurrency protection and identity normalization
for both NULL and non-NULL suppliers under case and whitespace variations.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '708192a3b4c5'
down_revision: Union[str, None] = '6f708192a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'purchases' in tables:
        cols = {c['name'] for c in inspector.get_columns('purchases')}
        if 'shop_id' in cols and 'invoice_number' in cols:
            if 'supplier_id' in cols:
                # Pre-check for duplicate normalized records with supplier_id
                dup_with_sup = bind.execute(sa.text("""
                    SELECT shop_id, supplier_id, lower(trim(invoice_number)), count(*)
                    FROM purchases
                    WHERE supplier_id IS NOT NULL AND invoice_number IS NOT NULL AND trim(invoice_number) != ''
                    GROUP BY shop_id, supplier_id, lower(trim(invoice_number))
                    HAVING count(*) > 1
                """)).fetchall()
                if dup_with_sup:
                    raise ValueError(
                        f"Cannot create unique index uq_purchases_shop_supplier_lower_inv: "
                        f"found {len(dup_with_sup)} duplicate normalized purchase group(s): {dup_with_sup}"
                    )

                op.execute(sa.text("""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_purchases_shop_supplier_lower_inv
                    ON purchases (shop_id, supplier_id, lower(trim(invoice_number)))
                    WHERE supplier_id IS NOT NULL AND invoice_number IS NOT NULL
                """))

            # Pre-check for duplicate normalized records with NULL supplier
            dup_null_sup = bind.execute(sa.text("""
                SELECT shop_id, lower(trim(invoice_number)), count(*)
                FROM purchases
                WHERE supplier_id IS NULL AND invoice_number IS NOT NULL AND trim(invoice_number) != ''
                GROUP BY shop_id, lower(trim(invoice_number))
                HAVING count(*) > 1
            """)).fetchall()
            if dup_null_sup:
                raise ValueError(
                    f"Cannot create unique index uq_purchases_shop_null_supplier_lower_inv: "
                    f"found {len(dup_null_sup)} duplicate normalized NULL-supplier purchase group(s): {dup_null_sup}"
                )

            op.execute(sa.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_purchases_shop_null_supplier_lower_inv
                ON purchases (shop_id, lower(trim(invoice_number)))
                WHERE supplier_id IS NULL AND invoice_number IS NOT NULL
            """))

    if 'suppliers' in tables:
        cols = {c['name'] for c in inspector.get_columns('suppliers')}
        name_col = 'supplier_name' if 'supplier_name' in cols else ('name' if 'name' in cols else None)
        if name_col and 'shop_id' in cols:
            # Pre-check for duplicate normalized supplier names
            dup_sups = bind.execute(sa.text(f"""
                SELECT shop_id, lower(trim({name_col})), count(*)
                FROM suppliers
                GROUP BY shop_id, lower(trim({name_col}))
                HAVING count(*) > 1
            """)).fetchall()
            if dup_sups:
                raise ValueError(
                    f"Cannot create unique index uq_suppliers_shop_lower_name: "
                    f"found {len(dup_sups)} duplicate normalized supplier name group(s): {dup_sups}"
                )

            op.execute(sa.text(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_shop_lower_name
                ON suppliers (shop_id, lower(trim({name_col})))
            """))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'suppliers' in tables:
        op.execute(sa.text("DROP INDEX IF EXISTS uq_suppliers_shop_lower_name"))

    if 'purchases' in tables:
        op.execute(sa.text("DROP INDEX IF EXISTS uq_purchases_shop_null_supplier_lower_inv"))
        op.execute(sa.text("DROP INDEX IF EXISTS uq_purchases_shop_supplier_lower_inv"))
