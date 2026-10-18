"""Investigation run lifecycle and frozen-snapshot creation.

A frozen snapshot is an immutable record of the system's findings (with a hash,
timestamp, run id and schema version). It is a record of what the system found -
NOT proof the findings are correct. The benchmark evaluation compares against it
without modifying it.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional

from database.connection import Database, get_db, utcnow
from database.schema import CURRENT_SCHEMA_VERSION


class RunManager:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    # ------------------------------------------------------------------ #
    def create_run(self, vendor_id: str, profile: str, live_mode: bool, query_budget: int) -> str:
        run_id = str(uuid.uuid4())
        self.db.insert("investigation_runs", {
            "run_id": run_id, "vendor_id": vendor_id, "profile": profile,
            "status": "pending", "live_mode": int(live_mode),
            "query_budget": query_budget, "queries_used": 0, "created_at": utcnow(),
        })
        self.db.audit("run", "create", subject=vendor_id, run_id=run_id,
                      detail={"profile": profile, "live": live_mode})
        return run_id

    def mark_running(self, run_id: str) -> None:
        self.db.execute("UPDATE investigation_runs SET status='running', started_at=? WHERE run_id=?",
                        (utcnow(), run_id))

    def complete_run(self, run_id: str, queries_used: int, summary: Dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE investigation_runs SET status='completed', completed_at=?, queries_used=?, summary=? "
            "WHERE run_id=?",
            (utcnow(), queries_used, json.dumps(summary, default=str), run_id))
        self.db.audit("run", "complete", run_id=run_id, detail=summary)

    def fail_run(self, run_id: str, error: str) -> None:
        self.db.execute("UPDATE investigation_runs SET status='failed', completed_at=? WHERE run_id=?",
                        (utcnow(), run_id))
        self.db.audit("run", "fail", run_id=run_id, detail={"error": error})

    # ------------------------------------------------------------------ #
    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.db.query_one("SELECT * FROM investigation_runs WHERE run_id=?", (run_id,))

    def latest_run_for_vendor(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        return self.db.query_one(
            "SELECT * FROM investigation_runs WHERE vendor_id=? ORDER BY created_at DESC LIMIT 1",
            (vendor_id,))

    def runs_for_vendor(self, vendor_id: str) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM investigation_runs WHERE vendor_id=? ORDER BY created_at DESC", (vendor_id,))

    # ------------------------------------------------------------------ #
    def collect_findings(self, run_id: str) -> Dict[str, Any]:
        """Assemble the full findings payload for a run (used for freezing/reports)."""
        q = self.db.query_one
        qa = self.db.query
        return {
            "run": q("SELECT * FROM investigation_runs WHERE run_id=?", (run_id,)),
            "ai_usage": q("SELECT * FROM ai_usage_classifications WHERE run_id=? ORDER BY classification_id DESC LIMIT 1", (run_id,)),
            "risk": q("SELECT * FROM risk_assessments WHERE run_id=? ORDER BY assessment_id DESC LIMIT 1", (run_id,)),
            "data_flow": q("SELECT * FROM data_flow_findings WHERE run_id=? ORDER BY finding_id DESC LIMIT 1", (run_id,)),
            "relationships": qa("SELECT * FROM vendor_relationships WHERE run_id=?", (run_id,)),
            "claims": qa("SELECT * FROM claims WHERE run_id=?", (run_id,)),
            "evidence": qa("SELECT * FROM evidence WHERE run_id=?", (run_id,)),
            "recommendations": qa("SELECT * FROM recommendations WHERE run_id=?", (run_id,)),
            "adaptive_decisions": qa("SELECT * FROM adaptive_decisions WHERE run_id=? ORDER BY step", (run_id,)),
        }

    # ------------------------------------------------------------------ #
    def freeze_snapshot(self, run_id: str) -> str:
        """Create an immutable frozen snapshot. Requires a completed run."""
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"run {run_id} not found")
        if run["status"] not in ("completed", "frozen"):
            raise ValueError("cannot freeze a run that has not completed successfully")

        payload = self.collect_findings(run_id)
        payload_json = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
        content_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        snapshot_id = str(uuid.uuid4())
        self.db.insert("frozen_snapshots", {
            "snapshot_id": snapshot_id, "run_id": run_id, "vendor_id": run["vendor_id"],
            "schema_version": CURRENT_SCHEMA_VERSION, "content_hash": content_hash,
            "payload": payload_json, "frozen_at": utcnow(), "is_locked": 1,
        })
        self.db.execute("UPDATE investigation_runs SET status='frozen' WHERE run_id=?", (run_id,))
        self.db.audit("snapshot", "freeze", subject=run["vendor_id"], run_id=run_id,
                      detail={"snapshot_id": snapshot_id, "content_hash": content_hash})
        return snapshot_id

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        return self.db.query_one("SELECT * FROM frozen_snapshots WHERE snapshot_id=?", (snapshot_id,))

    def latest_snapshot_for_vendor(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        return self.db.query_one(
            "SELECT * FROM frozen_snapshots WHERE vendor_id=? ORDER BY frozen_at DESC LIMIT 1",
            (vendor_id,))

    def verify_snapshot_hash(self, snapshot_id: str) -> bool:
        snap = self.get_snapshot(snapshot_id)
        if not snap:
            return False
        recomputed = hashlib.sha256(snap["payload"].encode("utf-8")).hexdigest()
        return recomputed == snap["content_hash"]
