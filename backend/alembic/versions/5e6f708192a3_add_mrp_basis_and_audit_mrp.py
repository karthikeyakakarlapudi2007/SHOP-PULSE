"""Add mrp_basis_quantity and mrp_basis_unit to products, and mrp fields to pricing_audit_logs

Revision ID: 5e6f708192a3
Revises: 4d5e6f708192
Create Date: 2026-11-22 14:00:00.000000

All columns are additive and nullable or defaulted; existing rows preserve their data.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '5e6f708192a3'
down_revision: Union[str, None] = '4d5e6f708192'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRODUCT_COLUMNS = [
    ('mrp_basis_quantity', sa.Float(), sa.text('1.0'), True),
    ('mrp_basis_unit', sa.String(length=32), None, True),
]

AUDIT_LOG_COLUMNS = [
    ('previous_mrp', sa.Float(), None, True),
    ('new_mrp', sa.Float(), None, True),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'products' in tables:
        existing_prod_cols = {c['name'] for c in inspector.get_columns('products')}
        for name, col_type, s_default, nullable in PRODUCT_COLUMNS:
            if name not in existing_prod_cols:
                op.add_column(
                    'products',
                    sa.Column(name, col_type, nullable=nullable, server_default=s_default)
                )

    if 'pricing_audit_logs' in tables:
        existing_audit_cols = {c['name'] for c in inspector.get_columns('pricing_audit_logs')}
        for name, col_type, s_default, nullable in AUDIT_LOG_COLUMNS:
            if name not in existing_audit_cols:
                op.add_column(
                    'pricing_audit_logs',
                    sa.Column(name, col_type, nullable=nullable, server_default=s_default)
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'pricing_audit_logs' in tables:
        existing_audit_cols = {c['name'] for c in inspector.get_columns('pricing_audit_logs')}
        with op.batch_alter_table('pricing_audit_logs') as batch_op:
            for name, _, _, _ in reversed(AUDIT_LOG_COLUMNS):
                if name in existing_audit_cols:
                    batch_op.drop_column(name)

    if 'products' in tables:
        existing_prod_cols = {c['name'] for c in inspector.get_columns('products')}
        with op.batch_alter_table('products') as batch_op:
            for name, _, _, _ in reversed(PRODUCT_COLUMNS):
                if name in existing_prod_cols:
                    batch_op.drop_column(name)
