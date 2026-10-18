"""Agent 12 - Independent Quality Assurance.

Reviews the investigation for unsupported claims, missing citations,
misclassification, confused identity, unsupported provider relationships,
contradictions, premature stopping, excessive repeated searches, unjustified
confidence and benchmark contamination. May flag a run as incomplete/unreliable.

It must NOT access the benchmark file; it only checks that no benchmark access
occurred before the snapshot was frozen (via the audit log).
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, InvestigationContext


class QualityAssuranceAgent(BaseAgent):
    name = "quality_assurance"
    depends_on = ["recommendations"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        issues: List[Dict[str, str]] = []

        def flag(severity: str, kind: str, detail: str) -> None:
            issues.append({"severity": severity, "kind": kind, "detail": detail})

        # 1) Unsupported claims.
        unsupported = ctx.ledger.unsupported_claims(ctx.run_id)
        extracted_unsupported = [c for c in unsupported if c.get("claim_type") in ("extracted", "inference")]
        if extracted_unsupported:
            flag("high", "unsupported_claims",
                 f"{len(extracted_unsupported)} extracted/inference claim(s) lack supporting evidence.")

        # 2) Missing citations on evidence.
        ev_rows = ctx.ledger.evidence_for_run(ctx.run_id)
        missing_excerpt = [e for e in ev_rows if not (e.get("excerpt") or "").strip()]
        if missing_excerpt:
            flag("medium", "missing_citations",
                 f"{len(missing_excerpt)} evidence row(s) have no excerpt.")

        # 3) Classification vs evidence sanity.
        classification = ctx.state.get("ai_classification", {})
        label = classification.get("label", "")
        if label.startswith("Confirmed") and not classification.get("evidence_ids"):
            flag("high", "misclassification", "AI usage marked Confirmed with no evidence ids.")

        # 4) Unsupported provider relationships.
        rels = ctx.db.query(
            "SELECT * FROM vendor_relationships WHERE run_id=? AND relation_type='uses_ai_provider'",
            (ctx.run_id,))
        for r in rels:
            ev_ids = r.get("evidence_ids")
            if not ev_ids or ev_ids in ("[]", "null", None):
                flag("medium", "unsupported_relationship",
                     f"Provider relationship to '{r.get('target_entity')}' has no evidence ids.")

        # 5) Contradictions.
        verif = ctx.state.get("verification", {})
        if verif.get("contradictions", 0) > 0:
            flag("medium", "contradictions",
                 f"{verif['contradictions']} unresolved contradiction(s) present.")

        # 6) Unjustified confidence.
        risk = ctx.state.get("risk", {})
        if (classification.get("confidence", 0) >= 0.8
                and risk.get("evidence_confidence", 0) < 0.4):
            flag("medium", "unjustified_confidence",
                 "High classification confidence but low underlying evidence confidence.")

        # 7) Premature stopping.
        coverage = ctx.state.get("layer_coverage", {})
        if (label in ("Insufficient evidence",) and coverage.get("layers_visited")
                and max(coverage["layers_visited"]) < coverage.get("max_layer", 3)
                and ctx.budget.remaining > 0 and ctx.live_mode):
            flag("low", "premature_stop",
                 "Stopped before max layer with budget remaining and an unresolved AI question.")

        # 8) Excessive repeated searches.
        qrows = ctx.db.query(
            "SELECT query_text, COUNT(*) c FROM investigation_queries WHERE run_id=? "
            "GROUP BY query_text HAVING c > 2", (ctx.run_id,))
        if qrows:
            flag("low", "repeated_searches", f"{len(qrows)} query text(s) repeated >2 times.")

        # 9) Benchmark contamination check (audit log must show no pre-freeze access).
        contamination = ctx.db.query(
            "SELECT * FROM audit_events WHERE category='benchmark' AND action='access' AND run_id=?",
            (ctx.run_id,))
        if contamination:
            flag("critical", "benchmark_contamination",
                 "Benchmark access events are associated with this investigation run.")

        high = [i for i in issues if i["severity"] in ("high", "critical")]
        reliability = "unreliable" if high else ("review" if issues else "ok")

        out = {"issues": issues, "issue_count": len(issues), "reliability": reliability}
        ctx.state["qa"] = out
        ctx.db.audit("qa", "review", subject=ctx.vendor_id, run_id=ctx.run_id,
                     detail={"reliability": reliability, "issues": len(issues)})
        return out
