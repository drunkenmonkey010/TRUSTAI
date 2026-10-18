"""SQLite connection management, migrations and small query helpers."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from config.logging_config import get_logger
from config.settings import get_settings
from database.schema import MIGRATIONS

log = get_logger("database")
_LOCK = threading.Lock()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thin wrapper around a SQLite file with migration support.

    A single instance is safe to share across Streamlit reruns; each operation
    opens a short-lived connection guarded by a process lock to avoid
    ``database is locked`` under light concurrency.
    """

    def __init__(self, path: Optional[Path | str] = None):
        if path is None:
            path = get_settings().absolute_db_path
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    # ----------------------------------------------------------------- #
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ----------------------------------------------------------------- #
    def _migrate(self) -> None:
        with _LOCK, self.connect() as conn:
            current = conn.execute("PRAGMA user_version;").fetchone()[0]
            for version, statements in MIGRATIONS:
                if version > current:
                    log.info("applying migration version=%s", version)
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(f"PRAGMA user_version = {version};")
                    current = version

    @property
    def schema_version(self) -> int:
        with self.connect() as conn:
            return conn.execute("PRAGMA user_version;").fetchone()[0]

    # ----------------------------------------------------------------- #
    # Generic helpers
    # ----------------------------------------------------------------- #
    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with _LOCK, self.connect() as conn:
            cur = conn.execute(sql, tuple(params))
            return cur.lastrowid

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> None:
        with _LOCK, self.connect() as conn:
            conn.executemany(sql, [tuple(s) for s in seq])

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        values = [self._encode(v) for v in data.values()]
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        return self.execute(sql, values)

    @staticmethod
    def _encode(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, bool):
            return int(value)
        return value

    # ----------------------------------------------------------------- #
    # Audit log (append-only)
    # ----------------------------------------------------------------- #
    def audit(
        self,
        category: str,
        action: str,
        subject: Optional[str] = None,
        detail: Optional[str | Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> int:
        if isinstance(detail, dict):
            detail = json.dumps(detail, ensure_ascii=False)
        return self.insert(
            "audit_events",
            {
                "occurred_at": utcnow(),
                "category": category,
                "action": action,
                "subject": subject,
                "detail": detail,
                "run_id": run_id,
            },
        )

    # ----------------------------------------------------------------- #
    # Application settings key/value
    # ----------------------------------------------------------------- #
    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO application_settings(key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), utcnow()),
        )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM application_settings WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return row["value"]


_DB_SINGLETON: Optional[Database] = None


def get_db() -> Database:
    global _DB_SINGLETON
    if _DB_SINGLETON is None:
        _DB_SINGLETON = Database()
    return _DB_SINGLETON


def reset_db_singleton() -> None:
    global _DB_SINGLETON
    _DB_SINGLETON = None
