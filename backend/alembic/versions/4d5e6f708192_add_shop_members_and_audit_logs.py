"""Add shop_members and pricing_audit_logs tables

Revision ID: 4d5e6f708192
Revises: 3c4d5e6f7081
Create Date: 2026-11-22 12:00:00.000000

All changes are additive. Existing shops and users are preserved,
and existing shop owners are automatically registered as OWNER in shop_members.
"""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '4d5e6f708192'
down_revision: Union[str, None] = '3c4d5e6f7081'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'shop_members' not in tables:
        op.create_table(
            'shop_members',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('shop_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('role', sa.String(length=20), nullable=False, server_default='CASHIER'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('shop_id', 'user_id', name='uq_shop_user_membership'),
        )
        op.create_index(op.f('ix_shop_members_id'), 'shop_members', ['id'], unique=False)
        op.create_index(op.f('ix_shop_members_shop_id'), 'shop_members', ['shop_id'], unique=False)
        op.create_index(op.f('ix_shop_members_user_id'), 'shop_members', ['user_id'], unique=False)

        # Seed existing shop owners into shop_members as OWNER
        if 'shops' in tables:
            try:
                res = bind.execute(sa.text("SELECT id, owner_id FROM shops")).fetchall()
                for row in res:
                    shop_id, owner_id = row[0], row[1]
                    if shop_id and owner_id:
                        bind.execute(
                            sa.text(
                                "INSERT INTO shop_members (id, shop_id, user_id, role, is_active) "
                                "VALUES (:id, :s_id, :u_id, 'OWNER', 1)"
                            ),
                            {"id": str(uuid.uuid4()), "s_id": str(shop_id), "u_id": str(owner_id)}
                        )
            except Exception:
                pass

    if 'pricing_audit_logs' not in tables:
        op.create_table(
            'pricing_audit_logs',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('shop_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('acting_user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('action_type', sa.String(length=50), nullable=False),
            sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('previous_status', sa.String(length=20), nullable=True),
            sa.Column('new_status', sa.String(length=20), nullable=True),
            sa.Column('previous_selling_price', sa.Float(), nullable=True),
            sa.Column('new_selling_price', sa.Float(), nullable=True),
            sa.Column('invoice_number', sa.String(length=100), nullable=True),
            sa.Column('reason', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['acting_user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_pricing_audit_logs_id'), 'pricing_audit_logs', ['id'], unique=False)
        op.create_index(op.f('ix_pricing_audit_logs_shop_id'), 'pricing_audit_logs', ['shop_id'], unique=False)
        op.create_index(op.f('ix_pricing_audit_logs_acting_user_id'), 'pricing_audit_logs', ['acting_user_id'], unique=False)
        op.create_index(op.f('ix_pricing_audit_logs_product_id'), 'pricing_audit_logs', ['product_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if 'pricing_audit_logs' in tables:
        op.drop_table('pricing_audit_logs')

    if 'shop_members' in tables:
        op.drop_table('shop_members')
