"""Remediation case management and risk-decision workflow (V2.1 §11, §20).

Findings follow an explicit, audited state machine. An automatically generated
recommendation is NOT counted as completed remediation until a human confirms the
action and closure evidence. Risk acceptance and manual overrides always preserve
the original automated conclusion.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from database.connection import Database, get_db, utcnow

STATUSES = ["open", "under_review", "remediation_planned", "in_progress",
            "awaiting_vendor_response", "accepted_risk", "closed", "reopened"]

# Allowed transitions (state machine). Closing requires evidence (checked below).
_TRANSITIONS = {
    "open": {"under_review", "remediation_planned", "in_progress", "awaiting_vendor_response", "accepted_risk"},
    "under_review": {"remediation_planned", "in_progress", "accepted_risk", "awaiting_vendor_response"},
    "remediation_planned": {"in_progress", "awaiting_vendor_response", "accepted_risk"},
    "in_progress": {"awaiting_vendor_response", "closed", "accepted_risk"},
    "awaiting_vendor_response": {"in_progress", "under_review", "closed", "accepted_risk"},
    "accepted_risk": {"reopened"},
    "closed": {"reopened"},
    "reopened": {"under_review", "remediation_planned", "in_progress"},
}

_PRIORITY_TO_SEVERITY = {"Immediate": "Critical", "High": "High", "Medium": "Medium", "Low": "Low"}


class InvalidTransition(ValueError):
    pass


class RemediationManager:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    # ------------------------------------------------------------------ #
    def create_findings_from_recommendations(self, run_id: str) -> List[int]:
        run = self.db.query_one("SELECT vendor_id FROM investigation_runs WHERE run_id=?", (run_id,))
        if not run:
            return []
        vendor_id = run["vendor_id"]
        created: List[int] = []
        for rec in self.db.query("SELECT * FROM recommendations WHERE run_id=? ORDER BY rec_id", (run_id,)):
            fid = self.db.insert("remediation_findings", {
                "run_id": run_id, "vendor_id": vendor_id, "source_rec_id": rec["rec_id"],
                "risk_category": rec.get("category"),
                "severity": _PRIORITY_TO_SEVERITY.get(rec.get("priority"), "Medium"),
                "confidence": None, "business_impact": rec.get("rationale"),
                "description": rec.get("finding"), "recommendation": rec.get("action"),
                "responsible_role": rec.get("responsible_role"), "due_date": None,
                "status": "open", "closure_criteria": rec.get("closure_conditions"),
                "closure_evidence": None, "notes": None, "created_at": utcnow(),
            })
            self.db.insert("finding_history", {
                "finding_id": fid, "actor": "system", "action": "create",
                "from_status": None, "to_status": "open",
                "rationale": "derived from automated recommendation", "occurred_at": utcnow()})
            created.append(fid)
        self.db.audit("remediation", "create_findings", subject=vendor_id, run_id=run_id,
                      detail={"count": len(created)})
        return created

    # ------------------------------------------------------------------ #
    def transition(self, finding_id: int, to_status: str, actor: str,
                   rationale: str = "", closure_evidence: Optional[str] = None,
                   due_date: Optional[str] = None) -> Dict[str, Any]:
        f = self.db.query_one("SELECT * FROM remediation_findings WHERE finding_id=?", (finding_id,))
        if not f:
            raise ValueError("finding not found")
        frm = f["status"]
        if to_status not in STATUSES:
            raise InvalidTransition(f"unknown status '{to_status}'")
        if to_status not in _TRANSITIONS.get(frm, set()):
            raise InvalidTransition(f"cannot move from '{frm}' to '{to_status}'")
        if to_status == "closed" and not (closure_evidence or f.get("closure_evidence")):
            raise InvalidTransition("closing requires closure evidence (human-confirmed)")
        fields = {"status": to_status}
        if closure_evidence:
            fields["closure_evidence"] = closure_evidence
        if due_date:
            fields["due_date"] = due_date
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE remediation_findings SET {sets} WHERE finding_id=?",
                        (*fields.values(), finding_id))
        self.db.insert("finding_history", {
            "finding_id": finding_id, "actor": actor, "action": "transition",
            "from_status": frm, "to_status": to_status, "rationale": rationale,
            "occurred_at": utcnow()})
        self.db.audit("remediation", "transition", subject=f["vendor_id"],
                      detail={"finding_id": finding_id, "from": frm, "to": to_status, "actor": actor})
        return {"finding_id": finding_id, "from": frm, "to": to_status}

    # ------------------------------------------------------------------ #
    def accept_risk(self, finding_id: int, decision_maker: str, justification: str,
                    accepted_risk: str, scope: str, conditions: str = "",
                    compensating_controls: str = "", expiry_date: Optional[str] = None,
                    approvals: str = "") -> int:
        f = self.db.query_one("SELECT * FROM remediation_findings WHERE finding_id=?", (finding_id,))
        if not f:
            raise ValueError("finding not found")
        decision_id = self.db.insert("risk_decisions", {
            "vendor_id": f["vendor_id"], "finding_id": finding_id, "decision_type": "risk_acceptance",
            "decision_maker": decision_maker, "justification": justification,
            "accepted_risk": accepted_risk, "scope": scope, "conditions": conditions,
            "compensating_controls": compensating_controls, "expiry_date": expiry_date,
            "approvals": approvals,
            "original_conclusion": f.get("description"),  # preserve automated conclusion
            "created_at": utcnow()})
        # move finding to accepted_risk (if transition allowed)
        if "accepted_risk" in _TRANSITIONS.get(f["status"], set()):
            self.transition(finding_id, "accepted_risk", decision_maker,
                            rationale=f"risk accepted: {justification}")
        self.db.audit("risk_decision", "accept", subject=f["vendor_id"],
                      detail={"finding_id": finding_id, "decision_maker": decision_maker})
        return decision_id

    def reopen(self, finding_id: int, actor: str, rationale: str) -> Dict[str, Any]:
        return self.transition(finding_id, "reopened", actor, rationale=rationale)

    def history(self, finding_id: int) -> List[Dict[str, Any]]:
        return self.db.query("SELECT * FROM finding_history WHERE finding_id=? ORDER BY history_id",
                             (finding_id,))
