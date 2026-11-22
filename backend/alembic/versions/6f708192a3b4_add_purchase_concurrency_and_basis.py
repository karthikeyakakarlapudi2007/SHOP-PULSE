"""Add purchase unique constraint on (shop_id, supplier_id, invoice_number) and pricing basis to purchase_items

Revision ID: 6f708192a3b4
Revises: 5e6f708192a3
Create Date: 2026-11-22 15:00:00.000000

All columns and constraints are additive and safe for concurrent operations.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '6f708192a3b4'
down_revision: Union[str, None] = '5e6f708192a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURCHASE_ITEM_COLUMNS = [
    ('price_basis_quantity', sa.Float(), sa.text('1.0'), True),
    ('price_basis_unit', sa.String(length=32), None, True),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'purchase_items' in tables:
        existing_cols = {c['name'] for c in inspector.get_columns('purchase_items')}
        for name, col_type, s_default, nullable in PURCHASE_ITEM_COLUMNS:
            if name not in existing_cols:
                op.add_column(
                    'purchase_items',
                    sa.Column(name, col_type, nullable=nullable, server_default=s_default)
                )

    if 'purchases' in tables:
        existing_uqs = {uq['name'] for uq in inspector.get_unique_constraints('purchases')}
        if 'uq_purchases_shop_supplier_invoice' not in existing_uqs:
            with op.batch_alter_table('purchases') as batch_op:
                batch_op.create_unique_constraint(
                    'uq_purchases_shop_supplier_invoice',
                    ['shop_id', 'supplier_id', 'invoice_number']
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'purchases' in tables:
        with op.batch_alter_table('purchases') as batch_op:
            batch_op.drop_constraint('uq_purchases_shop_supplier_invoice', type_='unique')

    if 'purchase_items' in tables:
        existing_cols = {c['name'] for c in inspector.get_columns('purchase_items')}
        with op.batch_alter_table('purchase_items') as batch_op:
            for name, _, _, _ in reversed(PURCHASE_ITEM_COLUMNS):
                if name in existing_cols:
                    batch_op.drop_column(name)
