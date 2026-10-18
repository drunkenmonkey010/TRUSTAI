"""AI threat modeling and attack-path analysis (V2.1 §9, §12).

Scenarios are generated ONLY once AI use is established or sufficiently supported.
A generated scenario is NEVER presented as an observed vulnerability - each is
typed hypothetical / plausible / control_gap, with assumptions and evidence gaps
explicit. Scenarios map to OWASP LLM guidance. No exploitation is performed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from database.connection import Database, get_db, utcnow


@dataclass
class _Scenario:
    asset: str
    ai_component: str
    threat: str
    preconditions: str
    impact: str
    mitigations: str
    owasp_ref: str
    applies: Callable[[Dict[str, Any]], bool]


_CATALOGUE: List[_Scenario] = [
    _Scenario("Meridian customer data", "LLM prompt/response path",
              "Sensitive data exposure through prompts or outputs",
              "Customer data reaches the AI feature; retention/training undocumented",
              "Confidential borrower/payment data exposed to the model or provider",
              "Data minimisation; no-training contractual terms; output redaction",
              "OWASP LLM02", lambda c: c["ai_present"] and c["sensitive"]),
    _Scenario("Vendor AI interface", "LLM input handling",
              "Prompt injection manipulating AI behaviour",
              "AI consumes untrusted content; weak input isolation",
              "Unauthorised actions or data disclosure via crafted input",
              "Input/output isolation; guardrails; least privilege",
              "OWASP LLM01", lambda c: c["ai_present"]),
    _Scenario("External model provider", "Model / provider dependency",
              "Model or provider compromise (supply chain)",
              "Undisclosed or changeable AI sub-processors",
              "Downstream compromise affects Meridian data",
              "Sub-processor disclosure + change notification; provider assurance",
              "OWASP LLM03", lambda c: c["ai_present"] and (not c["provider_named"] or c["flow_unknown"])),
    _Scenario("AI agent", "Autonomous agent / tool use",
              "Excessive agency / unauthorised tool invocation",
              "Agentic AI with broad permissions (reported or possible)",
              "Unsafe autonomous actions on Meridian systems/data",
              "Scoped permissions; human approval gates; action logging",
              "OWASP LLM06", lambda c: c["ai_present"] and c["critical"]),
    _Scenario("AI output", "Output handling",
              "Improper output handling / model output manipulation",
              "AI output used without validation in downstream processes",
              "Incorrect borrower-facing content or decisions",
              "Human oversight; output validation; disclaimers",
              "OWASP LLM05", lambda c: c["ai_present"]),
    _Scenario("AI audit trail", "Logging & monitoring",
              "Inadequate logging of AI-related actions",
              "AI actions not covered by audit logs available to Meridian",
              "Incidents involving AI cannot be reconstructed",
              "AI-action audit logging with customer access",
              "OWASP LLM-Ops", lambda c: c["ai_present"]),
    _Scenario("Integration secrets", "AI integration",
              "Insecure integration secrets",
              "API keys / credentials for AI providers poorly managed",
              "Credential compromise enabling data access",
              "Secret management; rotation; scoped keys",
              "OWASP LLM03", lambda c: c["ai_present"] and c["provider_named"]),
]


def _context(db: Database, run_id: str) -> Dict[str, Any]:
    run = db.query_one("SELECT vendor_id FROM investigation_runs WHERE run_id=?", (run_id,)) or {}
    vendor = db.query_one("SELECT * FROM vendors WHERE vendor_id=?", (run.get("vendor_id"),)) or {}
    ai = db.query_one("SELECT label FROM ai_usage_classifications WHERE run_id=? "
                      "ORDER BY classification_id DESC LIMIT 1", (run_id,)) or {}
    flow = db.query_one("SELECT customer_data_involved FROM data_flow_findings WHERE run_id=? "
                        "ORDER BY finding_id DESC LIMIT 1", (run_id,)) or {}
    rels = db.query("SELECT 1 FROM vendor_relationships WHERE run_id=? AND relation_type='uses_ai_provider'", (run_id,))
    label = ai.get("label", "")
    data_cls = (vendor.get("data_classification") or "").lower()
    tier = (vendor.get("criticality_tier") or "").lower()
    return {
        "vendor_id": run.get("vendor_id"), "vendor_name": vendor.get("vendor_name"),
        "ai_present": label.startswith("Confirmed") or "indirect" in label.lower() or "Third-party" in label,
        "confirmed": label.startswith("Confirmed"),
        "sensitive": any(k in data_cls for k in ("health", "financial", "payment", "account", "card", "tax", "borrower")),
        "flow_unknown": flow.get("customer_data_involved", "unknown") == "unknown",
        "provider_named": bool(rels), "critical": tier in ("critical", "high"), "label": label,
        "providers": [r for r in db.query(
            "SELECT target_entity FROM vendor_relationships WHERE run_id=? AND relation_type='uses_ai_provider'",
            (run_id,))],
    }


def generate_scenarios(run_id: str, db: Optional[Database] = None) -> List[Dict[str, Any]]:
    db = db or get_db()
    ctx = _context(db, run_id)
    if not ctx["vendor_id"] or not ctx["ai_present"]:
        return []
    out: List[Dict[str, Any]] = []
    for s in _CATALOGUE:
        try:
            if not s.applies(ctx):
                continue
        except Exception:
            continue
        # Type: evidence-backed concern vs purely hypothetical. Never 'confirmed_vuln'.
        if ctx["confirmed"] and ctx["sensitive"] and ctx["flow_unknown"]:
            stype = "plausible"
        elif ctx["confirmed"]:
            stype = "plausible"
        else:
            stype = "hypothetical"
        human_review = stype == "plausible" and ctx["critical"]
        sid = db.insert("threat_scenarios", {
            "run_id": run_id, "vendor_id": ctx["vendor_id"], "asset": s.asset,
            "ai_component": s.ai_component, "threat": s.threat, "preconditions": s.preconditions,
            "impact": s.impact,
            "existing_evidence": f"AI usage: {ctx['label']}",
            "existing_controls": "None evidenced from public sources" ,
            "evidence_gaps": "Deployment specifics, data flow and controls require validation",
            "likelihood_rationale": "Based on vendor AI usage and data sensitivity; not tested",
            "impact_rationale": "Driven by criticality and data sensitivity",
            "mitigations": s.mitigations, "scenario_type": stype,
            "human_review": int(human_review), "owasp_ref": s.owasp_ref, "created_at": utcnow()})
        out.append({"scenario_id": sid, "threat": s.threat, "type": stype, "owasp": s.owasp_ref})
    db.audit("threat_modeling", "generate", subject=ctx["vendor_id"], run_id=run_id,
             detail={"count": len(out)})
    return out


def build_attack_paths(run_id: str, db: Optional[Database] = None) -> List[Dict[str, Any]]:
    """Construct evidence-aware risk paths from the supply-chain graph."""
    db = db or get_db()
    ctx = _context(db, run_id)
    if not ctx["vendor_id"] or not ctx["ai_present"]:
        return []
    vendor_name = ctx["vendor_name"] or ctx["vendor_id"]
    providers = [p["target_entity"] for p in ctx["providers"]] or ["(unnamed provider)"]
    out: List[Dict[str, Any]] = []
    rank = 1
    for provider in providers:
        nodes = ["Meridian", vendor_name, "AI feature", provider,
                 "Customer data" if ctx["sensitive"] else "Processed data"]
        edges = [
            {"from": "Meridian", "to": vendor_name, "rel": "uses_service", "established": True},
            {"from": vendor_name, "to": "AI feature", "rel": "offers", "established": ctx["confirmed"]},
            {"from": "AI feature", "to": provider, "rel": "uses_provider", "established": ctx["provider_named"]},
            {"from": "AI feature", "to": "Customer data", "rel": "may_process", "established": False},
        ]
        unknown = [e for e in edges if not e["established"]]
        path_type = "evidence_supported" if not unknown else "hypothetical"
        pid = db.insert("attack_paths", {
            "run_id": run_id, "vendor_id": ctx["vendor_id"],
            "nodes": nodes, "edges": edges, "evidence_ids": [],
            "assumptions": "Customer-data processing by the AI feature is assumed, not established.",
            "unknown_links": "; ".join(f"{e['from']}->{e['to']}" for e in unknown) or "none",
            "business_impact": "Critical" if ctx["critical"] else "Medium",
            "rationale": "Potential data pathway warranting validation; not an exploited chain.",
            "validation_steps": "Confirm data flow to provider; confirm retention/training; review controls.",
            "path_type": path_type, "rank": rank, "created_at": utcnow()})
        out.append({"path_id": pid, "provider": provider, "type": path_type, "rank": rank})
        rank += 1
    db.audit("attack_path", "build", subject=ctx["vendor_id"], run_id=run_id, detail={"count": len(out)})
    return out
