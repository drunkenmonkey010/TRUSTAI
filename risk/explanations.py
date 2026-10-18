"""Human-readable explanations of a risk result."""
from __future__ import annotations

from typing import List

from risk.scoring import RiskResult

_LABELS = {
    "vendor_criticality": "Vendor criticality (business impact)",
    "data_sensitivity": "Data sensitivity",
    "ai_usage_exposure": "AI usage exposure",
    "provider_transparency_gap": "External provider transparency gap",
    "data_flow_uncertainty": "Data-flow uncertainty",
    "retention_training_uncertainty": "Retention / training uncertainty",
    "unresolved_contradictions": "Unresolved contradictions",
    "security_governance_gap": "Security / governance evidence gap",
}


def explain(result: RiskResult) -> str:
    lines: List[str] = []
    lines.append(f"Risk model {result.model_version}")
    lines.append(
        f"Inherent risk: {result.inherent_risk}/100  |  "
        f"Residual risk: {result.residual_risk if result.residual_risk is not None else 'not reducible (no control evidence)'}"
    )
    lines.append(
        f"Evidence confidence: {result.evidence_confidence:.2f}  |  "
        f"Investigation uncertainty: {result.investigation_uncertainty:.2f}  |  "
        f"Overall priority: {result.overall_priority}"
    )
    lines.append("")
    lines.append("Contributing factors (score x weight):")
    contributions = sorted(
        (
            (k, result.dimension_scores[k], result.weights[k],
             result.dimension_scores[k] * result.weights[k] * 100)
            for k in result.weights
        ),
        key=lambda t: t[3],
        reverse=True,
    )
    for key, score, weight, contrib in contributions:
        lines.append(f"  - {_LABELS.get(key, key)}: {score:.2f} x {weight:.2f} = {contrib:.1f} pts")
    if result.missing_information:
        lines.append("")
        lines.append(
            "Missing information (scored via documented unknown policy, NOT as zero risk): "
            + ", ".join(_LABELS.get(m, m) for m in result.missing_information)
        )
    return "\n".join(lines)
