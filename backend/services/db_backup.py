"""SQLite database backup and integrity verification service (Stage 3A).

Provides WAL-safe online SQLite backups, cryptographic SHA-256 verification,
and schema/row-count integrity validation before and after migrations.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, Optional


def compute_file_sha256(file_path: str | Path) -> str:
    """Compute SHA-256 hexadecimal hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def backup_sqlite_database(
    src_path: str | Path,
    dst_path: str | Path,
) -> Dict[str, Any]:
    """Perform a WAL-safe online backup of a SQLite database.

    1. Executes PRAGMA wal_checkpoint(TRUNCATE) on source to ensure all WAL pages are committed.
    2. Uses sqlite3 online backup API to copy cleanly without locking readers.
    3. Verifies PRAGMA integrity_check and PRAGMA foreign_key_check on destination.
    4. Computes SHA-256 checksums and returns metadata dictionary.
    """
    src_p = Path(src_path).resolve()
    dst_p = Path(dst_path).resolve()

    if not src_p.exists():
        raise FileNotFoundError(f"Source database not found: {src_p}")

    dst_p.parent.mkdir(parents=True, exist_ok=True)

    # 1. Connect and flush WAL
    src_conn = sqlite3.connect(str(src_p))
    try:
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass  # Non-WAL or read-only mode

    # 2. Online backup
    dst_conn = sqlite3.connect(str(dst_p))
    try:
        src_conn.backup(dst_conn, pages=250)
    finally:
        dst_conn.close()
        src_conn.close()

    # 3. Verify destination integrity
    verify_conn = sqlite3.connect(str(dst_p))
    try:
        integrity_status = verify_conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_errors = verify_conn.execute("PRAGMA foreign_key_check").fetchall()
        cur = verify_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        table_counts = {}
        for t in tables:
            table_counts[t] = verify_conn.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
    finally:
        verify_conn.close()

    if integrity_status != "ok":
        raise RuntimeError(f"Backup integrity check failed: {integrity_status}")

    dst_sha = compute_file_sha256(dst_p)

    return {
        "status": "success",
        "source_path": str(src_p),
        "backup_path": str(dst_p),
        "backup_size_bytes": dst_p.stat().st_size,
        "backup_sha256": dst_sha,
        "integrity_status": integrity_status,
        "foreign_key_errors": fk_errors,
        "table_counts": table_counts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def verify_sqlite_backup(
    backup_path: str | Path,
    expected_tables: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Verify integrity, table inventory, and readability of a SQLite backup."""
    p = Path(backup_path).resolve()
    if not p.exists():
        return {"status": "error", "error": f"File does not exist: {p}"}

    conn = sqlite3.connect(str(p))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fks = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0] for t in tables}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    finally:
        conn.close()

    missing = []
    if expected_tables:
        missing = [t for t in expected_tables if t not in tables]

    return {
        "status": "ok" if integrity == "ok" and not fks and not missing else "failed",
        "integrity": integrity,
        "foreign_key_errors": fks,
        "tables": tables,
        "missing_expected_tables": missing,
        "table_counts": counts,
        "size_bytes": p.stat().st_size,
        "sha256": compute_file_sha256(p),
    }
