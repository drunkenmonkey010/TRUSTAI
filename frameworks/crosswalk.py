"""Control-maturity matrix and regulatory/framework crosswalk (V2.1 §10, §13).

Control status is assessed conservatively from public evidence: a control is NEVER
marked absent merely because OSINT could not find documentation (default
'not_verified' / 'requires_review'), and documentation volume is never equated
with maturity. Framework identifiers are real objective references, not invented
compliance claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from database.connection import Database, get_db, utcnow

# Control domains with validated framework references (objective-level, not certs).
@dataclass
class _Domain:
    name: str
    objective: str
    frameworks: List[str]
    ai_relevant: bool


CONTROL_DOMAINS: List[_Domain] = [
    _Domain("AI governance", "Documented accountability for AI risk and use",
            ["NIST AI RMF GOVERN-1.1", "ISO/IEC 42001 Clause 5.2", "NIST CSF GV.RM-01"], True),
    _Domain("Data lineage & privacy", "Known data categories, flows and processing basis",
            ["NIST CSF ID.AM-07", "ISO/IEC 27001 A.5.34", "OWASP LLM02"], True),
    _Domain("Identity & access management", "Least-privilege access to systems and data",
            ["NIST CSF PR.AA-01", "ISO/IEC 27001 A.5.15"], False),
    _Domain("Model lifecycle management", "Controlled model/provider selection and change",
            ["NIST AI RMF MAP-2.3", "ISO/IEC 42001 Annex A.6.2.4", "OWASP LLM03"], True),
    _Domain("Logging & monitoring", "Audit logging covering AI-related actions",
            ["NIST CSF DE.CM-01", "ISO/IEC 27001 A.8.16"], True),
    _Domain("Incident response", "Incident handling incl. AI-provider incidents",
            ["NIST CSF RS.MA-01", "ISO/IEC 27001 A.5.24"], True),
    _Domain("Vulnerability management", "Identification and remediation of weaknesses",
            ["NIST CSF ID.RA-01", "ISO/IEC 27001 A.8.8"], False),
    _Domain("Subprocessor management", "Disclosure and change control for sub-processors",
            ["NIST CSF GV.SC-07", "ISO/IEC 27001 A.5.19"], True),
    _Domain("Data retention & deletion", "Defined retention, deletion and training use",
            ["ISO/IEC 27001 A.8.10", "NIST AI RMF MANAGE-2.2", "OWASP LLM04"], True),
    _Domain("Business continuity", "Resilience and recovery of critical services",
            ["NIST CSF RC.RP-01", "ISO/IEC 27001 A.5.30"], False),
    _Domain("Secure development", "Secure SDLC incl. AI integration secrets",
            ["NIST CSF PR.PS-06", "ISO/IEC 27001 A.8.25"], True),
    _Domain("Human oversight", "Human review of consequential AI output",
            ["NIST AI RMF MEASURE-2.6", "ISO/IEC 42001 Annex A.9.2", "OWASP LLM06"], True),
    _Domain("AI abuse prevention", "Protections against prompt injection / misuse",
            ["OWASP LLM01", "OWASP LLM05", "NIST AI RMF MANAGE-2.3"], True),
]


def _evidence_signals(db: Database, run_id: str, vendor_id: str) -> Dict[str, Any]:
    sources = db.query("SELECT url, source_type FROM sources WHERE run_id=?", (run_id,))
    urls = " ".join((s.get("url") or "").lower() for s in sources)
    ai = db.query_one("SELECT label FROM ai_usage_classifications WHERE run_id=? "
                      "ORDER BY classification_id DESC LIMIT 1", (run_id,)) or {}
    label = ai.get("label", "")
    retention_known = bool(db.query_one(
        "SELECT 1 FROM data_flow_findings WHERE run_id=? AND retention_terms='documented'", (run_id,)))
    return {
        "trust": any(k in urls for k in ("trust", "security", "soc2", "iso")),
        "privacy": "privacy" in urls,
        "subproc": any(k in urls for k in ("subprocessor", "sub-processor")),
        "retention_known": retention_known,
        "ai_present": label.startswith("Confirmed") or "indirect" in label.lower() or "Third-party" in label,
    }


def assess_controls(run_id: str, db: Optional[Database] = None) -> List[Dict[str, Any]]:
    db = db or get_db()
    run = db.query_one("SELECT vendor_id FROM investigation_runs WHERE run_id=?", (run_id,))
    if not run:
        return []
    vendor_id = run["vendor_id"]
    sig = _evidence_signals(db, run_id, vendor_id)
    out: List[Dict[str, Any]] = []
    for d in CONTROL_DOMAINS:
        applicability = "applicable"
        if d.ai_relevant and not sig["ai_present"]:
            applicability = "applicable (baseline)"
        # Conservative status from public evidence.
        if d.name == "Data retention & deletion" and sig["retention_known"]:
            status, quality, method = "partially_evidenced", "public_documentation", "osint_document"
        elif d.name == "Subprocessor management" and sig["subproc"]:
            status, quality, method = "partially_evidenced", "public_documentation", "osint_document"
        elif d.name in ("Data lineage & privacy",) and sig["privacy"]:
            status, quality, method = "partially_evidenced", "public_documentation", "osint_document"
        elif sig["trust"] and d.name in ("AI governance", "Logging & monitoring",
                                          "Incident response", "Secure development"):
            status, quality, method = "partially_evidenced", "trust_centre_reference", "osint_document"
        else:
            status, quality, method = "not_verified", "none_found", "osint_only"
        gap = None if status == "partially_evidenced" else "No public evidence located; not proof of absence."
        action = ("Request attestation / documentation for this control."
                  if status == "not_verified" else "Validate the documented control with the vendor.")
        cid = db.insert("control_assessments", {
            "run_id": run_id, "vendor_id": vendor_id, "domain": d.name, "objective": d.objective,
            "applicability": applicability, "status": status, "evidence_quality": quality,
            "validation_method": method, "confidence": 0.5 if status == "partially_evidenced" else 0.2,
            "uncertainty": "high" if status == "not_verified" else "medium",
            "gap": gap, "required_action": action, "framework_refs": "; ".join(d.frameworks),
            "created_at": utcnow()})
        out.append({"control_id": cid, "domain": d.name, "status": status,
                    "frameworks": d.frameworks})
    db.audit("controls", "assess", subject=vendor_id, run_id=run_id, detail={"count": len(out)})
    return out


def map_frameworks(run_id: str, db: Optional[Database] = None) -> List[Dict[str, Any]]:
    """Produce framework_mappings rows from the control assessment."""
    db = db or get_db()
    run = db.query_one("SELECT vendor_id FROM investigation_runs WHERE run_id=?", (run_id,))
    if not run:
        return []
    vendor_id = run["vendor_id"]
    controls = db.query("SELECT * FROM control_assessments WHERE run_id=? ORDER BY control_id", (run_id,))
    out: List[Dict[str, Any]] = []
    for c in controls:
        for ref in (c.get("framework_refs") or "").split(";"):
            ref = ref.strip()
            if not ref:
                continue
            parts = ref.rsplit(" ", 1)
            framework = parts[0] if len(parts) == 2 else ref
            identifier = parts[1] if len(parts) == 2 else ""
            status = "evidence_gap" if c["status"] == "not_verified" else "partially_addressed"
            mid = db.insert("framework_mappings", {
                "run_id": run_id, "vendor_id": vendor_id, "framework": framework, "version": None,
                "control_identifier": identifier, "control_objective": c["objective"],
                "finding": f"{c['domain']}: {c['status']}", "evidence": c.get("evidence_quality"),
                "status": status, "limitations": "OSINT-based; not a certification or compliance audit.",
                "recommended_action": c.get("required_action"), "created_at": utcnow()})
            out.append({"mapping_id": mid, "framework": framework, "identifier": identifier,
                        "status": status})
    db.audit("frameworks", "map", subject=vendor_id, run_id=run_id, detail={"count": len(out)})
    return out
