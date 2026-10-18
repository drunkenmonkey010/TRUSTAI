"""Vendor-level report generation (Markdown + structured dict)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from database.connection import Database, get_db
from orchestration.run_manager import RunManager


class VendorReport:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
        self.run_manager = RunManager(self.db)

    def build(self, run_id: str) -> Dict[str, Any]:
        rm = self.run_manager
        run = rm.get_run(run_id)
        if not run:
            raise ValueError(f"run {run_id} not found")
        vendor = self.db.query_one("SELECT * FROM vendors WHERE vendor_id=?", (run["vendor_id"],))
        findings = rm.collect_findings(run_id)
        qa = self.db.query_one(
            "SELECT output FROM agent_runs WHERE run_id=? AND agent_name='quality_assurance' "
            "ORDER BY agent_run_id DESC LIMIT 1", (run_id,))
        coverage = self.db.query_one(
            "SELECT output FROM agent_runs WHERE run_id=? AND agent_name='adaptive_depth' "
            "ORDER BY agent_run_id DESC LIMIT 1", (run_id,))
        return {
            "run": run, "vendor": vendor, "findings": findings,
            "qa": json.loads(qa["output"]) if qa and qa.get("output") else {},
            "coverage": json.loads(coverage["output"]) if coverage and coverage.get("output") else {},
        }

    # ------------------------------------------------------------------ #
    def to_markdown(self, run_id: str) -> str:
        data = self.build(run_id)
        v = data["vendor"] or {}
        run = data["run"]
        f = data["findings"]
        ai = f.get("ai_usage") or {}
        risk = f.get("risk") or {}
        flow = f.get("data_flow") or {}
        recs: List[Dict] = f.get("recommendations") or []
        evidence: List[Dict] = f.get("evidence") or []
        claims: List[Dict] = f.get("claims") or []
        rels: List[Dict] = f.get("relationships") or []
        decisions: List[Dict] = f.get("adaptive_decisions") or []
        qa = data["qa"]
        coverage = data["coverage"].get("coverage", {})

        L: List[str] = []
        L.append(f"# Vendor AI Intelligence Report - {v.get('vendor_name','?')} ({run['vendor_id']})")
        L.append("")
        L.append(f"*Run `{run_id}` | profile: {run['profile']} | mode: {'LIVE' if run['live_mode'] else 'OFFLINE'} | status: {run['status']}*")
        L.append("")
        L.append("## 1. Executive summary")
        L.append(f"- **AI usage classification:** {ai.get('label','?')} (confidence {ai.get('confidence','?')})")
        L.append(f"- **Overall risk priority:** {risk.get('overall_priority','?')} "
                 f"(inherent {risk.get('inherent_risk','?')}/100)")
        L.append(f"- **Evidence confidence:** {risk.get('evidence_confidence','?')} | "
                 f"**Investigation uncertainty:** {risk.get('investigation_uncertainty','?')}")
        L.append(f"- **QA reliability:** {qa.get('reliability','?')} ({qa.get('issue_count',0)} issue(s))")
        L.append("")
        L.append("## 2. Vendor identity and business context")
        for key in ("vendor_name", "category", "website", "service_provided",
                    "business_process", "operational_dependency", "data_classification",
                    "data_volume", "criticality_tier"):
            L.append(f"- **{key.replace('_',' ').title()}:** {v.get(key) or '-'}")
        L.append("")
        L.append("## 3. Investigation scope and profile")
        L.append(f"- Depth profile: **{run['profile']}**")
        L.append(f"- Layers visited: {coverage.get('layers_visited','?')} (max {coverage.get('max_layer','?')})")
        L.append(f"- Queries used: {run['queries_used']} / {run['query_budget']}")
        L.append("")
        L.append("## 4. AI-use classification")
        L.append(f"- Label: **{ai.get('label','?')}**")
        L.append(f"- Deployment context: {ai.get('deployment_context','-')}")
        L.append(f"- Rationale: {ai.get('rationale','-')}")
        L.append("")
        L.append("## 5-6. AI relationships and dependencies")
        if rels:
            for r in rels:
                L.append(f"- {r['source_entity']} --[{r['relation_type']}]--> {r['target_entity']} "
                         f"(status: {r['evidence_status']}, confidence {r['confidence']})")
        else:
            L.append("- No provider relationships established from public sources.")
        L.append("")
        L.append("## 7. Data-flow findings")
        L.append(f"- {flow.get('description','-')}")
        L.append(f"- Customer data involved: **{flow.get('customer_data_involved','unknown')}** | "
                 f"Transfer established: **{flow.get('transfer_established','unknown')}**")
        L.append(f"- Retention terms: {flow.get('retention_terms','-')} | Training terms: {flow.get('training_terms','-')}")
        if flow.get("open_questions"):
            L.append(f"- Open questions: {flow['open_questions']}")
        L.append("")
        L.append("## 8. Evidence table")
        if evidence:
            L.append("| ID | Relation | Directness | Authority | Source | Excerpt |")
            L.append("|----|----------|-----------|-----------|--------|---------|")
            for e in evidence[:40]:
                src = e.get("url") or e.get("source_owner") or "-"
                exc = (e.get("excerpt") or "").replace("|", "/")[:120]
                L.append(f"| {e['evidence_id']} | {e.get('relation')} | {e.get('directness')} | "
                         f"{e.get('authority')} | {src} | {exc} |")
        else:
            L.append("- No evidence collected.")
        L.append("")
        L.append("## 10-11. Risk assessment, confidence and uncertainty")
        L.append("```")
        L.append(risk.get("explanation", "(no risk explanation)"))
        L.append("```")
        L.append("")
        L.append("## 12. Investigation-depth trace")
        for d in decisions:
            L.append(f"- step {d['step']} (layer {d['layer']}): **{d['decision']}** - {d['rationale']}")
        L.append(f"- Stop rationale: {coverage.get('stop_rationale','-')}")
        L.append("")
        L.append("## 13. Recommendations")
        _prio = {"Immediate": 0, "High": 1, "Medium": 2, "Low": 3}
        for r in sorted(recs, key=lambda x: _prio.get(x.get("priority", ""), 9)):
            L.append(f"- **[{r.get('priority')}] {r.get('category')}** ({r.get('responsible_role')}, "
                     f"{r.get('time_horizon')}): {r.get('action')}")
        if not recs:
            L.append("- None.")
        L.append("")
        L.append("## 14-15. Unresolved questions and limitations")
        for cond in data["coverage"].get("coverage", {}).get("reopen_conditions", []):
            L.append(f"- Reopen if: {cond}")
        L.append(f"- QA issues: {qa.get('issues', [])}")
        if not run["live_mode"]:
            L.append("- **Limitation:** investigation ran OFFLINE (no live OSINT). "
                     "Absence of findings reflects absence of configured search, not absence of AI usage.")
        L.append("")
        L.append("## 16. Source inventory")
        sources = self.db.query("SELECT * FROM sources WHERE run_id=? ORDER BY source_id", (run_id,))
        for s in sources:
            L.append(f"- [{s.get('retrieval_status')}] {s.get('url') or s.get('title')} "
                     f"(retrieved {s.get('retrieved_at')}{', SAMPLE' if s.get('is_sample') else ''})")
        if not sources:
            L.append("- No sources retrieved.")
        return "\n".join(L)
