"""Database, migration and audit tests."""
from __future__ import annotations

from database.connection import Database
from database.schema import CURRENT_SCHEMA_VERSION


def test_migrations_applied(tmp_db):
    assert tmp_db.schema_version == CURRENT_SCHEMA_VERSION
    tables = {r["name"] for r in tmp_db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("vendors", "evidence", "claims", "frozen_snapshots",
              "benchmark_records", "benchmark_evaluations", "audit_events"):
        assert t in tables


def test_migration_idempotent(tmp_path):
    db_file = tmp_path / "x.db"
    Database(db_file)
    db2 = Database(db_file)  # re-open, migrations should not re-run destructively
    assert db2.schema_version == CURRENT_SCHEMA_VERSION


def test_audit_append_only(tmp_db):
    tmp_db.audit("test", "did_thing", subject="s", detail={"k": "v"})
    rows = tmp_db.query("SELECT * FROM audit_events")
    assert rows and rows[0]["category"] == "test"


def test_settings_roundtrip(tmp_db):
    tmp_db.set_setting("foo", {"a": 1})
    assert tmp_db.get_setting("foo") == {"a": 1}
    assert tmp_db.get_setting("missing", "default") == "default"


def test_benchmark_tables_separate_from_operational(tmp_db):
    # Operational evidence and benchmark records live in distinct tables.
    cols_ev = {r["name"] for r in tmp_db.query("PRAGMA table_info(evidence)")}
    cols_bench = {r["name"] for r in tmp_db.query("PRAGMA table_info(benchmark_records)")}
    assert "run_id" in cols_ev
    assert "run_id" not in cols_bench  # benchmark records are not tied to operational runs
