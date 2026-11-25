"""
Stage 5.1: Database Initialization Safety Regression Tests.

Verifies:
1. Importing `main.py` does not create a database file.
2. Importing `main.py` does not alter an existing database's hash, size, or contents.
3. Importing routers, services, models, and db.session does not trigger schema creation.
4. The application can still start correctly when given an explicitly configured database.
5. Controlled startup (AUTO_INIT_DB=1) works on unmanaged databases while respecting Alembic-managed databases.
6. `init_db_schema()` safely bypasses Alembic-managed databases, preventing uncontrolled schema mutation.
7. Test databases remain isolated and guard_database_url fails closed against default/unsafe databases.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from core.db_safety import (
    BACKEND_DIR,
    DEFAULT_DB_PATH,
    UnsafeTestDatabaseError,
    assert_safe_test_database,
)
from main import app, init_db_schema


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# -----------------------------------------------------------------------------
# 1. Importing main.py does not create a database file
# -----------------------------------------------------------------------------
def test_01_import_main_does_not_create_database_file(tmp_path):
    """Importing main.py must NOT create a SQLite file when pointing to a non-existent path."""
    target_db = tmp_path / "should_not_exist.db"
    assert not target_db.exists()

    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SHOPPULSE_TEST_MODE")}
    env["DATABASE_URL"] = f"sqlite:///{target_db.as_posix()}"
    env["SHOPPULSE_TEST_MODE"] = "1"

    proc = subprocess.run(
        [sys.executable, "-c", "import main; print('MAIN_IMPORTED_SUCCESSFULLY')"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, f"Import failed: {proc.stderr}"
    assert "MAIN_IMPORTED_SUCCESSFULLY" in proc.stdout
    assert not target_db.exists(), f"Database file {target_db} was unexpectedly created upon import main!"


# -----------------------------------------------------------------------------
# 2. Importing main.py does not alter an existing database's hash or contents
# -----------------------------------------------------------------------------
def test_02_import_main_does_not_modify_existing_database(tmp_path):
    """Importing main.py must NOT alter the hash, size, or schema of an existing database."""
    temp_copy = tmp_path / "copy_shoppulse.db"
    shutil.copyfile(DEFAULT_DB_PATH, temp_copy)

    before_hash = _sha256(temp_copy)
    before_size = temp_copy.stat().st_size

    with sqlite3.connect(temp_copy) as conn:
        before_tables = sorted([r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])

    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SHOPPULSE_TEST_MODE")}
    env["DATABASE_URL"] = f"sqlite:///{temp_copy.as_posix()}"
    env["SHOPPULSE_TEST_MODE"] = "1"

    proc = subprocess.run(
        [sys.executable, "-c", "import main; print('MAIN_IMPORTED')"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, f"Import failed: {proc.stderr}"
    assert "MAIN_IMPORTED" in proc.stdout

    after_hash = _sha256(temp_copy)
    after_size = temp_copy.stat().st_size

    with sqlite3.connect(temp_copy) as conn:
        after_tables = sorted([r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])

    assert after_size == before_size, f"Size changed from {before_size} to {after_size}"
    assert after_hash == before_hash, f"Hash changed from {before_hash} to {after_hash}"
    assert after_tables == before_tables, f"Tables changed from {before_tables} to {after_tables}"


# -----------------------------------------------------------------------------
# 3. Importing routers, services, models, and db.session does not create schema
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("module_name", [
    "api.main",
    "api.deps",
    "api.routes.health",
    "api.routes.auth",
    "api.routes.shops",
    "api.routes.products",
    "api.routes.suppliers",
    "api.routes.purchases",
    "api.routes.sales",
    "api.routes.dashboard",
    "api.routes.voice",
    "api.routes.invoices",
    "api.routes.document_prep",
    "api.routes.search",
    "api.routes.insights",
    "api.routes.notifications",
    "api.routes.units",
    "db.session",
    "db.models",
    "services.product",
    "services.sale",
    "services.invoice",
    "services.purchase",
    "services.pricing_engine",
    "services.pricing_audit",
    "services.pricing_reconciliation",
    "services.shop_member",
])
def test_03_import_modules_does_not_trigger_schema_creation(tmp_path, module_name):
    """Importing any router, service, model, or session module must not create a DB file."""
    mod_db = tmp_path / f"test_{module_name.replace('.', '_')}.db"
    assert not mod_db.exists()

    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SHOPPULSE_TEST_MODE")}
    env["DATABASE_URL"] = f"sqlite:///{mod_db.as_posix()}"
    env["SHOPPULSE_TEST_MODE"] = "1"

    proc = subprocess.run(
        [sys.executable, "-c", f"import {module_name}; print('OK')"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, f"Importing {module_name} failed: {proc.stderr}"
    assert not mod_db.exists(), f"Importing {module_name} created database file {mod_db}!"


# -----------------------------------------------------------------------------
# 4. Application starts and operates correctly with an explicitly configured DB
# -----------------------------------------------------------------------------
def test_04_application_starts_and_operates_with_configured_database(tmp_path):
    """When configured with an isolated test DB and initialized, the app starts and responds."""
    test_db = tmp_path / "running_app.db"
    db_engine = create_engine(f"sqlite:///{test_db.as_posix()}", connect_args={"check_same_thread": False})
    init_db_schema(bind=db_engine)

    client = TestClient(app)
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "Shelfora API" in res_root.json()["message"]

    res_health = client.get("/api/v1/health")
    assert res_health.status_code == 200


# -----------------------------------------------------------------------------
# 5. Controlled startup (AUTO_INIT_DB=1) works on unmanaged databases
# -----------------------------------------------------------------------------
def test_05_controlled_startup_with_auto_init_db(tmp_path):
    """When AUTO_INIT_DB=1 is explicitly enabled, lifespan runs controlled dev initialization."""
    target_db = tmp_path / "auto_init.db"
    assert not target_db.exists()

    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SHOPPULSE_TEST_MODE", "AUTO_INIT_DB")}
    env["DATABASE_URL"] = f"sqlite:///{target_db.as_posix()}"
    env["SHOPPULSE_TEST_MODE"] = "1"
    env["AUTO_INIT_DB"] = "1"

    py_script = """
import asyncio
from main import app, lifespan

async def run_startup():
    async with lifespan(app):
        print("LIFESPAN_COMPLETED")

asyncio.run(run_startup())
"""
    proc = subprocess.run(
        [sys.executable, "-c", py_script],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, f"Startup failed: {proc.stderr}"
    assert "LIFESPAN_COMPLETED" in proc.stdout
    assert target_db.exists(), "Controlled startup should initialize the database when AUTO_INIT_DB=1"

    with sqlite3.connect(target_db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"products", "purchases", "sales"} <= tables


# -----------------------------------------------------------------------------
# 6. init_db_schema safely bypasses Alembic-managed databases
# -----------------------------------------------------------------------------
def test_06_init_db_schema_bypasses_alembic_managed_database(tmp_path):
    """Calling init_db_schema() on an Alembic-managed database must NOT run create_all or alter tables."""
    temp_copy = tmp_path / "alembic_db.db"
    shutil.copyfile(DEFAULT_DB_PATH, temp_copy)

    before_hash = _sha256(temp_copy)
    copy_engine = create_engine(f"sqlite:///{temp_copy.as_posix()}", connect_args={"check_same_thread": False})

    with sqlite3.connect(temp_copy) as conn:
        before_tables = set(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())

    # Call init_db_schema explicitly
    init_db_schema(bind=copy_engine)

    after_hash = _sha256(temp_copy)
    assert after_hash == before_hash, "init_db_schema mutated an Alembic-managed database!"

    with sqlite3.connect(temp_copy) as conn:
        after_tables = set(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())

    # Ensure tables were completely untouched by init_db_schema on an Alembic-managed database
    assert after_tables == before_tables, "init_db_schema added or removed tables on an Alembic-managed database!"


# -----------------------------------------------------------------------------
# 7. Test database isolation guard fails closed against default/unsafe DB
# -----------------------------------------------------------------------------
def test_07_test_database_isolation_guard_remains_active():
    """Verify that assert_safe_test_database rejects production/default DB in test mode."""
    with pytest.raises(UnsafeTestDatabaseError):
        assert_safe_test_database(f"sqlite:///{DEFAULT_DB_PATH.as_posix()}", explicit=True)

    with pytest.raises(UnsafeTestDatabaseError):
        assert_safe_test_database(None, explicit=True)
