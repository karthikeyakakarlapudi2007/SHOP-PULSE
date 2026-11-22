"""Add price_basis_quantity, price_basis_unit, and pricing_status to products

Revision ID: 3c4d5e6f7081
Revises: 2b3c4d5e6f70
Create Date: 2026-11-21 12:00:00.000000

All columns are additive and nullable or defaulted; existing rows keep their data.
The same columns are applied at startup by main.init_db_schema() for databases
that are not managed with Alembic.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '3c4d5e6f7081'
down_revision: Union[str, None] = '2b3c4d5e6f70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_PRODUCT_COLUMNS = [
    ('price_basis_quantity', sa.Float(), sa.text('1.0'), True),
    ('price_basis_unit', sa.String(length=32), None, True),
    ('pricing_status', sa.String(length=20), sa.text("'NEEDS_REVIEW'"), False),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if 'products' not in tables:
        return

    existing = {c['name'] for c in inspector.get_columns('products')}
    for name, col_type, s_default, nullable in NEW_PRODUCT_COLUMNS:
        if name not in existing:
            op.add_column(
                'products',
                sa.Column(name, col_type, nullable=nullable, server_default=s_default)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if 'products' not in tables:
        return

    existing = {c['name'] for c in inspector.get_columns('products')}
    # SQLite batch alteration
    with op.batch_alter_table('products') as batch_op:
        for name, _, _, _ in reversed(NEW_PRODUCT_COLUMNS):
            if name in existing:
                batch_op.drop_column(name)
