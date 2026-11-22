"""Comprehensive isolated database migration dry-run and safety tests (Stage 3A.1).

Validates:
1. Alembic upgrade and downgrade cycle.
2. Application startup after downgrade (init_db_schema does NOT re-add dropped columns).
3. Existing unstamped legacy database upgrade.
4. Fresh database initialization.
5. Partial schema upgrade.
6. Atomic reconciliation rollback on error (zero partial updates).
7. Duplicate identity & shop ID conflict rejection (security gate).
8. Unknown products remain in NEEDS_REVIEW.
9. Insufficient evidence items remain in NEEDS_REVIEW.
10. Full 65-product reconciliation idempotency (18 VERIFIED, 38 NEEDS_REVIEW, 8 INCOMPLETE, 1 WHOLESALE_ONLY).
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
import unittest.mock
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from alembic.config import Config
from alembic import command

from db.session import Base
from db.models.shop import Shop
from db.models.product import Product
from db.models.sale import Sale
from db.models.sale_item import SaleItem
from main import init_db_schema, INCREMENTAL_COLUMNS
from services.pricing_reconciliation import (
    AUDITED_65_PRODUCTS,
    reconcile_product_classification,
)
from services.db_backup import backup_sqlite_database, verify_sqlite_backup


@pytest.fixture
def temp_db():
    """Create a temporary standalone SQLite database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_path = tf.name
    yield temp_path
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def get_alembic_config(db_path: str) -> Config:
    """Create Alembic Config targeting the specified isolated SQLite database."""
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    clean_db_path = str(Path(db_path).resolve()).replace("\\", "/")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{clean_db_path}")
    return cfg


# -----------------------------------------------------------------------------
# 1. Upgrade and Downgrade Cycle (Alembic)
# -----------------------------------------------------------------------------
def test_1_upgrade_and_downgrade_cycle(temp_db):
    """Verify that Alembic upgrades to add the columns, and downgrades to drop them."""
    cfg = get_alembic_config(temp_db)

    # Start fresh with Base.metadata.create_all
    engine = create_engine(f"sqlite:///{temp_db}")
    Base.metadata.create_all(bind=engine)

    # Stamp as 2b3c4d5e6f70
    command.stamp(cfg, "2b3c4d5e6f70")

    # Upgrade to 3c4d5e6f7081
    command.upgrade(cfg, "3c4d5e6f7081")

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("products")}
    assert "price_basis_quantity" in cols
    assert "price_basis_unit" in cols
    assert "pricing_status" in cols

    # Downgrade back to 2b3c4d5e6f70
    command.downgrade(cfg, "2b3c4d5e6f70")

    inspector2 = inspect(engine)
    cols_after_down = {c["name"] for c in inspector2.get_columns("products")}
    assert "price_basis_quantity" not in cols_after_down
    assert "price_basis_unit" not in cols_after_down
    assert "pricing_status" not in cols_after_down


# -----------------------------------------------------------------------------
# 2. Application Startup After Downgrade (No Re-Add Contradiction)
# -----------------------------------------------------------------------------
def test_2_application_startup_after_downgrade_preserves_downgrade(temp_db):
    """CRITICAL TEST: init_db_schema() must NOT re-add columns after an Alembic downgrade."""
    cfg = get_alembic_config(temp_db)
    engine = create_engine(f"sqlite:///{temp_db}")
    Base.metadata.create_all(bind=engine)

    # Upgrade to 3c4d5e6f7081, then downgrade to 2b3c4d5e6f70
    command.stamp(cfg, "2b3c4d5e6f70")
    command.upgrade(cfg, "3c4d5e6f7081")
    command.downgrade(cfg, "2b3c4d5e6f70")

    # Simulate FastAPI startup by calling init_db_schema()
    init_db_schema(bind=engine)

    # Verify that the columns REMAIN DROPPED because alembic_version exists!
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("products")}
    assert "price_basis_quantity" not in cols, "init_db_schema subverted Alembic downgrade!"
    assert "price_basis_unit" not in cols, "init_db_schema subverted Alembic downgrade!"
    assert "pricing_status" not in cols, "init_db_schema subverted Alembic downgrade!"

    # Now upgrade again: columns must be added cleanly without collision
    command.upgrade(cfg, "3c4d5e6f7081")
    inspector3 = inspect(engine)
    cols_up = {c["name"] for c in inspector3.get_columns("products")}
    assert "price_basis_quantity" in cols_up
    assert "price_basis_unit" in cols_up
    assert "pricing_status" in cols_up


# -----------------------------------------------------------------------------
# 3. Existing Unstamped Database Baseline & Upgrade
# -----------------------------------------------------------------------------
def test_3_existing_unstamped_database_handling(temp_db):
    """An existing database with legacy columns but no alembic_version can be baselined and upgraded."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    # Create legacy tables without alembic_version
    cur.execute("""
    CREATE TABLE products (
        id VARCHAR PRIMARY KEY,
        shop_id VARCHAR NOT NULL,
        name VARCHAR NOT NULL,
        selling_price FLOAT NOT NULL,
        unit VARCHAR DEFAULT 'pcs',
        mrp FLOAT,
        is_active BOOLEAN DEFAULT 1
    )
    """)
    cur.execute("INSERT INTO products (id, shop_id, name, selling_price, unit) VALUES ('p1', 's1', 'Tata Salt', 25.0, 'pcs')")
    conn.commit()
    conn.close()

    cfg = get_alembic_config(temp_db)
    # Baseline the legacy DB
    command.stamp(cfg, "2b3c4d5e6f70")
    # Upgrade to head
    command.upgrade(cfg, "3c4d5e6f7081")

    engine = create_engine(f"sqlite:///{temp_db}")
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("products")}
    assert "price_basis_quantity" in cols
    assert "price_basis_unit" in cols
    assert "pricing_status" in cols

    # Verify legacy row preserved
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    row = cur.execute("SELECT id, name, selling_price, price_basis_quantity, pricing_status FROM products WHERE id='p1'").fetchone()
    conn.close()
    assert row[0] == "p1"
    assert row[1] == "Tata Salt"
    assert row[2] == 25.0
    assert row[3] == 1.0
    assert row[4] == "NEEDS_REVIEW"


# -----------------------------------------------------------------------------
# 4. Fresh Database Initialization
# -----------------------------------------------------------------------------
def test_4_fresh_database_initialization(temp_db):
    """Fresh database initialization via Alembic creates all tables, columns, and alembic_version."""
    cfg = get_alembic_config(temp_db)
    command.upgrade(cfg, "3c4d5e6f7081")

    engine = create_engine(f"sqlite:///{temp_db}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "products" in tables
    assert "alembic_version" in tables

    cols = {c["name"] for c in inspector.get_columns("products")}
    assert "price_basis_quantity" in cols
    assert "price_basis_unit" in cols
    assert "pricing_status" in cols


# -----------------------------------------------------------------------------
# 5. Partial Schema Upgrade
# -----------------------------------------------------------------------------
def test_5_partial_schema_upgrade(temp_db):
    """Database that already has one pricing column adds missing columns defensively."""
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE products (
        id VARCHAR PRIMARY KEY,
        shop_id VARCHAR NOT NULL,
        name VARCHAR NOT NULL,
        selling_price FLOAT NOT NULL,
        price_basis_quantity FLOAT DEFAULT 1.0
    )
    """)
    conn.commit()
    conn.close()

    cfg = get_alembic_config(temp_db)
    command.stamp(cfg, "2b3c4d5e6f70")
    # Upgrade must not crash on existing price_basis_quantity
    command.upgrade(cfg, "3c4d5e6f7081")

    engine = create_engine(f"sqlite:///{temp_db}")
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("products")}
    assert "price_basis_quantity" in cols
    assert "price_basis_unit" in cols
    assert "pricing_status" in cols


# -----------------------------------------------------------------------------
# 6. Atomic Reconciliation Rollback on Error
# -----------------------------------------------------------------------------
def test_6_atomic_reconciliation_rollback_on_error(temp_db):
    """If a database error occurs mid-reconciliation, all updates must be rolled back completely."""
    engine = create_engine(f"sqlite:///{temp_db}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    pid1 = uuid.UUID("98cecae7af374265ba7413e2e6da6902")
    sid1 = uuid.UUID("ec51853a955b4fe3b277afcad5ae59a9")
    p1 = Product(id=pid1, shop_id=sid1, name="Fortune Sunflower Oil (1L)", selling_price=165.0, unit="pouch", pricing_status="NEEDS_REVIEW")
    db.add(p1)
    db.commit()

    # Verify that if an exception occurs prior to or during commit, rollback triggers
    with unittest.mock.patch.object(db, "commit", side_effect=RuntimeError("Simulated Database Commit Error")):
        with pytest.raises(RuntimeError):
            reconcile_product_classification(db)

    # Re-query p1 in a fresh session to confirm zero changes were committed
    db.close()
    db2 = Session()
    refreshed_p1 = db2.query(Product).filter_by(id=pid1).first()
    assert refreshed_p1.pricing_status == "NEEDS_REVIEW"
    assert refreshed_p1.price_basis_unit is None
    db2.close()


# -----------------------------------------------------------------------------
# 7. Duplicate Identity & Shop ID Conflict Rejection
# -----------------------------------------------------------------------------
def test_7_shop_id_conflict_fails_closed(temp_db):
    """Product ID matching with wrong Shop ID fails closed and records conflict."""
    engine = create_engine(f"sqlite:///{temp_db}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    pid = uuid.UUID("98cecae7af374265ba7413e2e6da6902")
    tampered_shop_id = uuid.uuid4()
    p = Product(id=pid, shop_id=tampered_shop_id, name="Fortune Sunflower Oil (1L)", selling_price=165.0, unit="pouch", pricing_status="NEEDS_REVIEW")
    db.add(p)
    db.commit()

    report = reconcile_product_classification(db)
    assert report.conflict_count == 1
    assert report.conflicts[0]["product_id"] == "98cecae7af374265ba7413e2e6da6902"

    db.refresh(p)
    assert p.pricing_status == "NEEDS_REVIEW"
    db.close()


# -----------------------------------------------------------------------------
# 8. Unknown Products Fail Closed
# -----------------------------------------------------------------------------
def test_8_unknown_products_fail_closed(temp_db):
    """Unmatched products not in audit catalog remain in NEEDS_REVIEW."""
    engine = create_engine(f"sqlite:///{temp_db}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    unknown = Product(id=uuid.uuid4(), shop_id=uuid.uuid4(), name="Unknown Tea", selling_price=99.0, unit="pkt", pricing_status="NEEDS_REVIEW")
    db.add(unknown)
    db.commit()

    reconcile_product_classification(db)
    db.refresh(unknown)
    assert unknown.pricing_status == "NEEDS_REVIEW"
    db.close()


# -----------------------------------------------------------------------------
# 9. Insufficient Classification Evidence (Moved to NEEDS_REVIEW)
# -----------------------------------------------------------------------------
def test_9_insufficient_evidence_products_remain_needs_review(temp_db):
    """Verify that catalog items lacking empirical invoice/sales/MRP evidence remain in NEEDS_REVIEW."""
    engine = create_engine(f"sqlite:///{temp_db}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Tata Salt in Sharma Kirana Store (0 purchases, 0 sales, no MRP)
    pid = uuid.UUID("89b6e6d8882b4852978fb33d5d862f1d")
    sid = uuid.UUID("62142ac63acb4816a0d531759d641d4c")
    prod = Product(id=pid, shop_id=sid, name="Tata Salt 1kg", selling_price=28.0, unit="pkt", pricing_status="NEEDS_REVIEW")
    db.add(prod)
    db.commit()

    report = reconcile_product_classification(db)
    db.refresh(prod)
    assert prod.pricing_status == "NEEDS_REVIEW"
    db.close()


# -----------------------------------------------------------------------------
# 10. Full 65-Product Reconciliation Idempotency
# -----------------------------------------------------------------------------
def test_10_full_65_reconciliation_exact_counts(temp_db):
    """Dry run of all 65 ground-truth audited products produces exact target counts: 18/38/8/1."""
    engine = create_engine(f"sqlite:///{temp_db}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    for pid_str, item in AUDITED_65_PRODUCTS.items():
        p = Product(
            id=uuid.UUID(pid_str),
            shop_id=uuid.UUID(item["shop_id"]),
            name=item["name"],
            unit=item["unit"],
            selling_price=50.0 if item["status"] != "INCOMPLETE" else 0.0,
            pricing_status="NEEDS_REVIEW"
        )
        db.add(p)
    db.commit()

    report = reconcile_product_classification(db, dry_run=False)

    assert report.total_audited == 65
    assert report.matched_count == 65
    assert report.unmatched_count == 0
    assert report.conflict_count == 0
    assert report.status_counts["VERIFIED"] == 18
    assert report.status_counts["NEEDS_REVIEW"] == 38
    assert report.status_counts["INCOMPLETE"] == 8
    assert report.status_counts["WHOLESALE_ONLY"] == 1

    # Idempotency: second run produces exact same counts
    report2 = reconcile_product_classification(db, dry_run=False)
    assert report2.matched_count == 65
    assert report2.status_counts["VERIFIED"] == 18
    assert report2.status_counts["NEEDS_REVIEW"] == 38
    assert report2.status_counts["INCOMPLETE"] == 8
    assert report2.status_counts["WHOLESALE_ONLY"] == 1
    db.close()


# -----------------------------------------------------------------------------
# 11. Shop Members and Audit Logs Migration Upgrade & Downgrade Cycle
# -----------------------------------------------------------------------------
def test_11_shop_members_and_audit_logs_migration_cycle(temp_db):
    """Alembic revision 4d5e6f708192 upgrades cleanly, seeds shop owners, and downgrades without data corruption."""
    cfg = get_alembic_config(temp_db)

    # 1. Upgrade to previous head (3c4d5e6f7081)
    command.upgrade(cfg, "3c4d5e6f7081")

    # Insert a dummy user and shop
    engine = create_engine(f"sqlite:///{temp_db}")
    with engine.begin() as conn:
        u_id = str(uuid.uuid4())
        s_id = str(uuid.uuid4())
        conn.execute(
            text("INSERT INTO users (id, email, hashed_password, is_active, created_at) VALUES (:id, 'owner@mig.com', 'hash', 1, CURRENT_TIMESTAMP)"),
            {"id": u_id}
        )
        conn.execute(
            text("INSERT INTO shops (id, name, owner_id, created_at) VALUES (:id, 'Mig Shop', :owner_id, CURRENT_TIMESTAMP)"),
            {"id": s_id, "owner_id": u_id}
        )

    # 2. Upgrade to new revision (4d5e6f708192)
    command.upgrade(cfg, "4d5e6f708192")

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "shop_members" in tables
    assert "pricing_audit_logs" in tables

    # Verify seed created an OWNER membership
    with engine.connect() as conn:
        member = conn.execute(
            text("SELECT role, is_active FROM shop_members WHERE shop_id = :s_id AND user_id = :u_id"),
            {"s_id": s_id, "u_id": u_id}
        ).fetchone()
        assert member is not None
        assert member[0] == "OWNER"
        assert member[1] in [1, True]

    # 3. Downgrade back to 3c4d5e6f7081
    command.downgrade(cfg, "3c4d5e6f7081")

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "shop_members" not in tables
    assert "pricing_audit_logs" not in tables

    # 4. Re-upgrade to head
    command.upgrade(cfg, "head")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert "shop_members" in tables
    assert "pricing_audit_logs" in tables


# -----------------------------------------------------------------------------
# 12. MRP Basis & Audit Log Columns Migration Cycle (5e6f708192a3)
# -----------------------------------------------------------------------------
def test_12_mrp_basis_and_audit_mrp_migration_cycle(temp_db):
    """Verify that Alembic upgrades to add mrp_basis columns and audit mrp columns, and downgrades cleanly."""
    cfg = get_alembic_config(temp_db)

    # 1. Upgrade to 4d5e6f708192
    command.upgrade(cfg, "4d5e6f708192")

    engine = create_engine(f"sqlite:///{temp_db}")
    insp = inspect(engine)
    prod_cols = {c["name"] for c in insp.get_columns("products")}
    audit_cols = {c["name"] for c in insp.get_columns("pricing_audit_logs")}
    assert "mrp_basis_quantity" not in prod_cols
    assert "previous_mrp" not in audit_cols

    # 2. Upgrade to 5e6f708192a3
    command.upgrade(cfg, "5e6f708192a3")

    insp2 = inspect(engine)
    prod_cols2 = {c["name"] for c in insp2.get_columns("products")}
    audit_cols2 = {c["name"] for c in insp2.get_columns("pricing_audit_logs")}
    assert "mrp_basis_quantity" in prod_cols2
    assert "mrp_basis_unit" in prod_cols2
    assert "previous_mrp" in audit_cols2
    assert "new_mrp" in audit_cols2

    # 3. Downgrade back to 4d5e6f708192
    command.downgrade(cfg, "4d5e6f708192")

    insp3 = inspect(engine)
    prod_cols3 = {c["name"] for c in insp3.get_columns("products")}
    audit_cols3 = {c["name"] for c in insp3.get_columns("pricing_audit_logs")}
    assert "mrp_basis_quantity" not in prod_cols3
    assert "mrp_basis_unit" not in prod_cols3
    assert "previous_mrp" not in audit_cols3
    assert "new_mrp" not in audit_cols3

    # 4. Re-upgrade to head
    command.upgrade(cfg, "head")
    insp4 = inspect(engine)
    prod_cols4 = {c["name"] for c in insp4.get_columns("products")}
    assert "mrp_basis_quantity" in prod_cols4


# -----------------------------------------------------------------------------
# 13. Purchase Concurrency & Basis Migration Cycle (6f708192a3b4)
# -----------------------------------------------------------------------------
def test_13_purchase_concurrency_and_basis_migration_cycle(temp_db):
    """Verify that Alembic upgrades to add unique constraint on purchases and basis columns on purchase_items."""
    cfg = get_alembic_config(temp_db)

    # 1. Upgrade to 5e6f708192a3
    command.upgrade(cfg, "5e6f708192a3")

    engine = create_engine(f"sqlite:///{temp_db}")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE purchases (
                id VARCHAR PRIMARY KEY,
                shop_id VARCHAR NOT NULL,
                supplier_id VARCHAR,
                invoice_number VARCHAR,
                total_amount FLOAT DEFAULT 0.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE purchase_items (
                id VARCHAR PRIMARY KEY,
                purchase_id VARCHAR NOT NULL,
                product_id VARCHAR NOT NULL,
                quantity FLOAT NOT NULL,
                purchase_price FLOAT NOT NULL,
                line_amount FLOAT,
                mrp FLOAT,
                mrp_source VARCHAR,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

    insp = inspect(engine)
    item_cols = {c["name"] for c in insp.get_columns("purchase_items")}
    assert "price_basis_quantity" not in item_cols

    # 2. Upgrade to 6f708192a3b4
    command.upgrade(cfg, "6f708192a3b4")

    insp2 = inspect(engine)
    item_cols2 = {c["name"] for c in insp2.get_columns("purchase_items")}
    uqs = {uq["name"] for uq in insp2.get_unique_constraints("purchases")}
    assert "price_basis_quantity" in item_cols2
    assert "price_basis_unit" in item_cols2
    assert "uq_purchases_shop_supplier_invoice" in uqs

    # 3. Downgrade back to 5e6f708192a3
    command.downgrade(cfg, "5e6f708192a3")

    insp3 = inspect(engine)
    item_cols3 = {c["name"] for c in insp3.get_columns("purchase_items")}
    uqs3 = {uq["name"] for uq in insp3.get_unique_constraints("purchases")}
    assert "price_basis_quantity" not in item_cols3
    assert "uq_purchases_shop_supplier_invoice" not in uqs3

    # 4. Re-upgrade to head
    command.upgrade(cfg, "head")
    insp4 = inspect(engine)
    item_cols4 = {c["name"] for c in insp4.get_columns("purchase_items")}
    assert "price_basis_quantity" in item_cols4

