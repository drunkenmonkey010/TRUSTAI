"""Benchmark access control - the single gateway to the held-out benchmark.

ALL benchmark-file access flows through this module. Agents and connectors never
import it, and the benchmark path lives here, not in agent configuration. Access
states are explicit and every access/unlock event is written to the append-only
audit log.

Rules enforced here:
  * The benchmark cannot be read while LOCKED (the default).
  * Unlock requires a valid FROZEN snapshot to already exist - otherwise the
    operation is blocked with an explanation.
  * Benchmark evaluation never modifies the frozen snapshot.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from config.settings import PROJECT_ROOT
from database.connection import Database, get_db, utcnow

# The benchmark file location is defined ONLY here.
BENCHMARK_PATH = PROJECT_ROOT / "data" / "benchmark_protected" / "OPTIV.pdf"

_STATE_KEY = "benchmark_state"
_UNLOCK_META_KEY = "benchmark_unlock_meta"


class BenchmarkState(str, Enum):
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class BenchmarkLockedError(RuntimeError):
    """Raised when benchmark access is attempted while locked / not permitted."""


class BenchmarkAccessController:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    # ------------------------------------------------------------------ #
    def state(self) -> BenchmarkState:
        return BenchmarkState(self.db.get_setting(_STATE_KEY, BenchmarkState.LOCKED.value))

    def is_unlocked(self) -> bool:
        return self.state() == BenchmarkState.UNLOCKED

    def has_frozen_snapshot(self, vendor_id: Optional[str] = None) -> bool:
        if vendor_id:
            row = self.db.query_one(
                "SELECT 1 FROM frozen_snapshots WHERE vendor_id=? LIMIT 1", (vendor_id,))
        else:
            row = self.db.query_one("SELECT 1 FROM frozen_snapshots LIMIT 1")
        return bool(row)

    # ------------------------------------------------------------------ #
    def unlock(self, reason: str, vendor_id: Optional[str] = None) -> None:
        """Explicitly unlock benchmark evaluation. Requires a frozen snapshot."""
        if not self.has_frozen_snapshot(vendor_id):
            self.db.audit("benchmark", "unlock_blocked",
                          subject=vendor_id, detail={"reason": "no frozen snapshot"})
            raise BenchmarkLockedError(
                "Cannot unlock benchmark evaluation: no valid frozen snapshot exists. "
                "Freeze the automated results first."
            )
        self.db.set_setting(_STATE_KEY, BenchmarkState.UNLOCKED.value)
        self.db.set_setting(_UNLOCK_META_KEY, {"reason": reason, "unlocked_at": utcnow(),
                                               "vendor_id": vendor_id})
        self.db.audit("benchmark", "unlock", subject=vendor_id, detail={"reason": reason})

    def relock(self) -> None:
        self.db.set_setting(_STATE_KEY, BenchmarkState.LOCKED.value)
        self.db.audit("benchmark", "relock")

    # ------------------------------------------------------------------ #
    def benchmark_path(self) -> Path:
        """Return the benchmark file path, ONLY when unlocked. Audited."""
        if not self.is_unlocked():
            self.db.audit("benchmark", "access_denied", detail={"state": self.state().value})
            raise BenchmarkLockedError(
                "Benchmark is LOCKED. It is inaccessible until automated results are "
                "frozen and evaluation is explicitly unlocked."
            )
        if not BENCHMARK_PATH.exists():
            raise FileNotFoundError(f"Benchmark file not found at {BENCHMARK_PATH}")
        self.db.audit("benchmark", "access", detail={"path": str(BENCHMARK_PATH.name)})
        return BENCHMARK_PATH

    def read_bytes(self) -> bytes:
        return self.benchmark_path().read_bytes()
