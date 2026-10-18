"""Vendor questionnaire and evidence-validation engine (V2.1 §5).

Generates TARGETED questions from the actual evidence gaps of a run - not a giant
one-size questionnaire. Each question records its evidence gap, business
rationale, priority, required supporting evidence, reviewer role and closure
criteria. Responses are validated deterministically and compared with existing
public evidence (self-attestation is kept distinct from verified evidence).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from database.connection import Database, get_db, utcnow


@dataclass
class _Candidate:
    domain: str
    gap: str
    question: str
    rationale: str
    response_type: str
    required_evidence: str
    reviewer_role: str
    closure_criteria: str
    base_priority: str
    applies: Callable[[Dict[str, Any]], bool]


# Catalogue of gap-driven questions. Each only fires when its gap is present.
_CATALOGUE: List[_Candidate] = [
    _Candidate("Data flow", "customer-data flow to AI unknown",
               "Is Meridian customer data processed by the AI feature, and is it transmitted to any external model provider?",
               "Confirmed/likely AI use with an undocumented customer-data path is a material gap.",
               "yes/no + description", "Data-flow diagram or DPA excerpt", "Third-Party Risk",
               "Vendor confirms whether customer data reaches the AI feature/provider.",
               "High", lambda c: c["ai_present"] and c["flow_unknown"]),
    _Candidate("Model provider", "AI provider not named",
               "Which model/AI provider(s) power the AI capability, and in which region are they hosted?",
               "Provider identity is required to trace onward data flows and retention.",
               "named list", "Sub-processor list / trust-centre reference", "Third-Party Risk",
               "Vendor names the provider(s) and hosting region.",
               "High", lambda c: c["ai_present"] and not c["provider_named"]),
    _Candidate("Retention & training", "retention/training terms unknown",
               "Are customer prompts/outputs retained, and is customer data used to train or fine-tune models?",
               "Retention and training use determine onward exposure of Meridian data.",
               "yes/no + terms", "Retention policy / contractual clause", "Legal / Third-Party Risk",
               "Vendor states retention period and training usage in writing.",
               "High", lambda c: c["ai_present"] and not c["retention_known"]),
    _Candidate("Sub-processors", "subprocessor change notification unknown",
               "Can AI sub-processors change without prior notification to Meridian?",
               "Undisclosed sub-processor changes break data-flow assumptions.",
               "yes/no", "Sub-processor change policy", "Procurement / Legal",
               "Vendor confirms notification obligations.",
               "Medium", lambda c: c["ai_present"]),
    _Candidate("Controls", "human oversight unknown",
               "Can customers disable the AI functionality, and is it enabled by default? What human-oversight controls apply to AI output?",
               "Default-on AI and no human oversight raise exposure, especially for sensitive data.",
               "description", "Product configuration documentation", "Security Architecture",
               "Vendor documents enable/disable and oversight controls.",
               "Medium", lambda c: c["ai_present"] and c["sensitive"]),
    _Candidate("AI agents", "agent tool/permission scope unknown",
               "Can AI agents invoke tools or access privileged systems, and what are their permission boundaries?",
               "Over-permissioned AI agents can broaden blast radius.",
               "description", "Architecture / permission model", "Security Architecture",
               "Vendor documents agent permissions and tool access.",
               "Medium", lambda c: c["ai_present"] and c["critical"]),
    _Candidate("Logging", "AI audit logging unknown",
               "Do audit logs cover AI-related actions, and are they available to Meridian?",
               "Without AI audit logging, incidents cannot be reconstructed.",
               "yes/no", "Logging/monitoring documentation", "Security Assurance",
               "Vendor confirms AI audit-log coverage and access.",
               "Low", lambda c: c["ai_present"]),
    _Candidate("Incident", "AI incident notification unknown",
               "Do incidents involving AI providers trigger contractual notification obligations to Meridian?",
               "AI-provider incidents may affect Meridian data without notification.",
               "yes/no", "Incident-notification clause", "Legal",
               "Vendor confirms notification obligations for AI-provider incidents.",
               "Low", lambda c: c["ai_present"]),
]

_PRIORITY_BUMP = {"Low": "Medium", "Medium": "High", "High": "Immediate"}


def _context(db: Database, run_id: str) -> Dict[str, Any]:
    ai = db.query_one("SELECT label FROM ai_usage_classifications WHERE run_id=? "
                      "ORDER BY classification_id DESC LIMIT 1", (run_id,)) or {}
    flow = db.query_one("SELECT customer_data_involved FROM data_flow_findings WHERE run_id=? "
                        "ORDER BY finding_id DESC LIMIT 1", (run_id,)) or {}
    run = db.query_one("SELECT vendor_id FROM investigation_runs WHERE run_id=?", (run_id,)) or {}
    vendor = db.query_one("SELECT * FROM vendors WHERE vendor_id=?", (run.get("vendor_id"),)) or {}
    rels = db.query("SELECT 1 FROM vendor_relationships WHERE run_id=? AND relation_type='uses_ai_provider'", (run_id,))
    label = ai.get("label", "")
    ai_present = label.startswith("Confirmed") or "indirect" in label.lower() or "Third-party" in label
    tier = (vendor.get("criticality_tier") or "").lower()
    data_cls = (vendor.get("data_classification") or "").lower()
    sensitive = any(k in data_cls for k in ("health", "financial", "payment", "account", "card", "tax", "borrower", "ssn"))
    retention_known = bool(db.query_one(
        "SELECT 1 FROM data_flow_findings WHERE run_id=? AND retention_terms='documented'", (run_id,)))
    return {
        "vendor_id": run.get("vendor_id"), "ai_present": ai_present,
        "flow_unknown": (flow.get("customer_data_involved", "unknown") == "unknown"),
        "provider_named": bool(rels), "retention_known": retention_known,
        "sensitive": sensitive, "critical": tier in ("critical", "high"), "label": label,
    }


def generate_questions(run_id: str, db: Optional[Database] = None) -> List[Dict[str, Any]]:
    db = db or get_db()
    ctx = _context(db, run_id)
    vendor_id = ctx["vendor_id"]
    if not vendor_id:
        return []
    out: List[Dict[str, Any]] = []
    for cand in _CATALOGUE:
        try:
            if not cand.applies(ctx):
                continue
        except Exception:
            continue
        priority = cand.base_priority
        if ctx["critical"] and priority in ("Low", "Medium"):
            priority = _PRIORITY_BUMP[priority]
        qid = db.insert("questionnaires", {
            "run_id": run_id, "vendor_id": vendor_id, "product": None,
            "risk_domain": cand.domain, "evidence_gap": cand.gap, "question_text": cand.question,
            "business_rationale": cand.rationale, "priority": priority,
            "response_type": cand.response_type, "required_evidence": cand.required_evidence,
            "validation_rules": "non-empty; matches response_type; evidence attached for closure",
            "reviewer_role": cand.reviewer_role, "closure_criteria": cand.closure_criteria,
            "status": "draft", "created_at": utcnow(),
        })
        out.append({"question_id": qid, "domain": cand.domain, "priority": priority,
                    "question": cand.question})
    db.audit("questionnaire", "generate", subject=vendor_id, run_id=run_id,
             detail={"count": len(out)})
    return out


# --------------------------------------------------------------------------- #
def validate_response(question_id: int, answer_text: str, response_type: Optional[str] = None,
                      evidence_ref: Optional[str] = None, submitted_by: str = "analyst",
                      db: Optional[Database] = None) -> Dict[str, Any]:
    """Validate a vendor answer and compare it with existing public evidence.

    Self-attestation is NOT independently verified merely because it is detailed.
    """
    db = db or get_db()
    q = db.query_one("SELECT * FROM questionnaires WHERE question_id=?", (question_id,))
    if not q:
        raise ValueError("question not found")
    issues: List[str] = []
    answer = (answer_text or "").strip()
    if not answer:
        issues.append("empty answer")
    if len(answer) < 10:
        issues.append("answer too short to assess")
    rtype = (q.get("response_type") or "")
    if "yes/no" in rtype and not any(w in answer.lower() for w in ("yes", "no")):
        issues.append("expected a yes/no determination")

    # Compare with public evidence: supported if any evidence excerpt corroborates.
    corroborated = False
    for ev in db.query("SELECT excerpt FROM evidence WHERE vendor_id=?", (q["vendor_id"],)):
        exc = (ev.get("excerpt") or "").lower()
        if exc and any(tok in exc for tok in answer.lower().split()[:8] if len(tok) > 5):
            corroborated = True
            break

    if issues:
        verification = "needs_revision"
    elif evidence_ref:
        verification = "self_attested_with_evidence"
    elif corroborated:
        verification = "consistent_with_public_evidence"
    else:
        verification = "self_attested_unverified"

    db.insert("vendor_responses", {
        "question_id": question_id, "vendor_id": q["vendor_id"], "answer_text": answer,
        "response_type": response_type or rtype, "evidence_ref": evidence_ref,
        "submitted_by": submitted_by, "submitted_at": utcnow(),
        "validation_result": "; ".join(issues) or "passed structural validation",
        "verification_status": verification, "notes": None,
    })
    status = "answered" if not issues else "needs_revision"
    db.execute("UPDATE questionnaires SET status=? WHERE question_id=?", (status, question_id))
    db.audit("questionnaire", "respond", subject=q["vendor_id"],
             detail={"question_id": question_id, "verification": verification})
    return {"verification_status": verification, "issues": issues, "status": status}
