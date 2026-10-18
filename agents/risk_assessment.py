"""Agent 10 - Risk Assessment.

Assembles validated structured inputs and calls the deterministic risk model.
Inherent risk, residual risk, evidence confidence, investigation uncertainty and
business impact are kept separate. Missing evidence is handled by the documented
unknown policy - never silently treated as zero risk.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from agents.base import BaseAgent, InvestigationContext
from database.connection import utcnow
from evidence.schemas import AIUsageLabel, TriState
from risk.explanations import explain
from risk.scoring import RiskInputs, compute_risk
from risk.weights import DEFAULT_WEIGHTS


class RiskAssessmentAgent(BaseAgent):
    name = "risk_assessment"
    depends_on = ["provider_dataflow"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        crit = ctx.state.get("criticality", {})
        classification = ctx.state.get("ai_classification", {})
        verif = ctx.state.get("verification", {})
        data_flow = ctx.state.get("data_flow", {})

        label = self._to_label(classification.get("label"))
        weights = ctx.db.get_setting("risk_weights", None) or DEFAULT_WEIGHTS

        inputs = RiskInputs(
            vendor_id=ctx.vendor_id, run_id=ctx.run_id,
            criticality_tier=crit.get("criticality_tier"),
            data_classification=ctx.vendor.get("data_classification"),
            ai_usage_label=label,
            provider_named=ctx.state.get("provider_named"),
            data_flow_established=TriState(data_flow.get("transfer_established", "unknown")),
            retention_training_known=ctx.state.get("retention_training_known"),
            security_controls_evidence=self._has_control_evidence(ctx),
            evidence_reliability=verif.get("mean_quality", 0.0),
            independent_corroboration=verif.get("independent_corroboration", 0),
            contradictions_count=verif.get("contradictions", 0),
            open_questions_count=len((data_flow.get("open_questions") or "").split(";")) if data_flow.get("open_questions") else 0,
        )
        result = compute_risk(inputs, weights)
        explanation = explain(result)

        ctx.db.insert("risk_assessments", {
            "run_id": ctx.run_id, "vendor_id": ctx.vendor_id,
            "model_version": result.model_version, "weights": result.weights,
            "dimension_scores": result.dimension_scores,
            "inherent_risk": result.inherent_risk, "residual_risk": result.residual_risk,
            "evidence_confidence": result.evidence_confidence,
            "investigation_uncertainty": result.investigation_uncertainty,
            "overall_priority": result.overall_priority, "explanation": explanation,
            "missing_information": "; ".join(result.missing_information),
            "created_at": utcnow(),
        })
        out = {
            "inherent_risk": result.inherent_risk, "residual_risk": result.residual_risk,
            "evidence_confidence": result.evidence_confidence,
            "investigation_uncertainty": result.investigation_uncertainty,
            "overall_priority": result.overall_priority,
            "dimension_scores": result.dimension_scores,
            "missing_information": result.missing_information,
            "explanation": explanation,
        }
        ctx.state["risk"] = out
        return out

    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_label(value: Optional[str]) -> Optional[AIUsageLabel]:
        if not value:
            return None
        for lab in AIUsageLabel:
            if lab.value == value:
                return lab
        return None

    @staticmethod
    def _has_control_evidence(ctx: InvestigationContext) -> Optional[bool]:
        # Control evidence = a trust centre / security doc was retrieved.
        rows = ctx.ledger.sources_for_run(ctx.run_id)
        for s in rows:
            url = (s.get("url") or "").lower()
            if any(k in url for k in ("trust", "security", "/dpa", "soc2", "iso27001")):
                return True
        return None  # unknown (not False) - absence is not proof of no controls
