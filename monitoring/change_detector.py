"""Vendor change detection and risk diff (V2.1 §6).

Turns each assessment into a versioned record. A baseline fingerprint of the
public evidence is stored; a later run is diffed against it. Cosmetic edits are
distinguished from material changes, events are de-duplicated, and a previous
assessment is NEVER silently overwritten. No background scheduler is claimed -
this is an explicit manual-refresh workflow (documented limitation).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from database.connection import Database, get_db, utcnow

# Fields whose change is treated as MATERIAL (vs cosmetic text edits).
_MATERIAL_FIELDS = {"ai_label", "providers", "retention_terms", "customer_data_involved"}


def _fingerprint(db: Database, run_id: str, vendor_id: str) -> Dict[str, Any]:
    sources = db.query("SELECT canonical_url, content_hash FROM sources WHERE run_id=?", (run_id,))
    ai = db.query_one("SELECT label FROM ai_usage_classifications WHERE run_id=? "
                      "ORDER BY classification_id DESC LIMIT 1", (run_id,)) or {}
    flow = db.query_one("SELECT customer_data_involved, retention_terms FROM data_flow_findings "
                        "WHERE run_id=? ORDER BY finding_id DESC LIMIT 1", (run_id,)) or {}
    providers = sorted({r["target_entity"] for r in db.query(
        "SELECT target_entity FROM vendor_relationships WHERE run_id=? AND relation_type='uses_ai_provider'",
        (run_id,))})
    return {
        "sources": {s.get("canonical_url"): s.get("content_hash") for s in sources if s.get("canonical_url")},
        "ai_label": ai.get("label"),
        "providers": providers,
        "customer_data_involved": flow.get("customer_data_involved"),
        "retention_terms": flow.get("retention_terms"),
    }


def capture_baseline(run_id: str, db: Optional[Database] = None) -> int:
    db = db or get_db()
    run = db.query_one("SELECT vendor_id FROM investigation_runs WHERE run_id=?", (run_id,))
    if not run:
        raise ValueError("run not found")
    vendor_id = run["vendor_id"]
    fp = _fingerprint(db, run_id, vendor_id)
    payload = json.dumps(fp, sort_keys=True, default=str)
    bid = db.insert("vendor_baselines", {
        "vendor_id": vendor_id, "run_id": run_id, "captured_at": utcnow(),
        "content": payload, "content_hash": hashlib.sha256(payload.encode()).hexdigest()})
    db.audit("monitoring", "baseline", subject=vendor_id, run_id=run_id, detail={"baseline_id": bid})
    return bid


def latest_baseline(vendor_id: str, db: Optional[Database] = None) -> Optional[Dict[str, Any]]:
    db = db or get_db()
    return db.query_one("SELECT * FROM vendor_baselines WHERE vendor_id=? ORDER BY captured_at DESC LIMIT 1",
                        (vendor_id,))


def detect_changes(vendor_id: str, new_run_id: str, db: Optional[Database] = None) -> List[Dict[str, Any]]:
    """Diff a new run against the vendor's latest baseline; record change events."""
    db = db or get_db()
    base = latest_baseline(vendor_id, db)
    new_fp = _fingerprint(db, new_run_id, vendor_id)
    events: List[Dict[str, Any]] = []
    if not base:
        return events
    old_fp = json.loads(base["content"])

    def add(change_type, field, prev, new, material, impact, action, reassess):
        diff_hash = hashlib.sha256(f"{vendor_id}{field}{prev}{new}".encode()).hexdigest()
        if db.query_one("SELECT 1 FROM change_events WHERE diff_hash=?", (diff_hash,)):
            return  # dedup
        db.insert("change_events", {
            "vendor_id": vendor_id, "baseline_id": base["baseline_id"], "detected_at": utcnow(),
            "change_type": change_type, "field": field, "previous_value": str(prev),
            "new_value": str(new), "materiality": material, "risk_impact": impact,
            "confidence": 0.7 if material == "material" else 0.3,
            "recommended_action": action, "reassessment_required": int(reassess),
            "source_url": None, "diff_hash": diff_hash})
        events.append({"field": field, "materiality": material, "change_type": change_type})

    # AI label change (material)
    if old_fp.get("ai_label") != new_fp.get("ai_label"):
        add("ai_usage_change", "ai_label", old_fp.get("ai_label"), new_fp.get("ai_label"),
            "material", "Reassess AI risk", "Re-run risk assessment", True)
    # Providers added/removed (material)
    old_p, new_p = set(old_fp.get("providers") or []), set(new_fp.get("providers") or [])
    for added in sorted(new_p - old_p):
        add("provider_added", "providers", "-", added, "material",
            "New AI provider disclosed", "Validate data flow to new provider", True)
    for removed in sorted(old_p - new_p):
        add("provider_removed", "providers", removed, "-", "material",
            "AI provider no longer listed", "Confirm dependency change", True)
    # Retention / customer-data flow change (material)
    for field in ("retention_terms", "customer_data_involved"):
        if old_fp.get(field) != new_fp.get(field):
            add("dataflow_change", field, old_fp.get(field), new_fp.get(field),
                "material", "Reassess data-flow risk", "Review updated terms", True)
    # Source content changes (cosmetic unless tied to material field)
    old_s, new_s = old_fp.get("sources", {}), new_fp.get("sources", {})
    changed_sources = [u for u in new_s if u in old_s and new_s[u] != old_s[u]]
    added_sources = [u for u in new_s if u not in old_s]
    if changed_sources:
        add("content_change", "source_content", f"{len(changed_sources)} changed", "updated",
            "cosmetic", "Monitor", "No action unless material field changed", False)
    if added_sources:
        add("source_added", "sources", "-", f"{len(added_sources)} new source(s)",
            "cosmetic", "Monitor", "Review new sources", False)

    db.audit("monitoring", "detect_changes", subject=vendor_id, run_id=new_run_id,
             detail={"events": len(events)})
    return events
