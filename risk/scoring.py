"""Deterministic risk scoring.

Keeps five concepts strictly separate:
  * inherent_risk          - risk before considering controls
  * residual_risk          - inherent adjusted down ONLY where control evidence exists
  * evidence_confidence    - how reliable the underlying evidence is
  * investigation_uncertainty - how much remains unknown
  * business_impact        - vendor criticality (an input, surfaced separately)

If an LLM proposes a classification, the final numeric score is ALWAYS computed
here from validated structured inputs - the LLM never sets the number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from evidence.schemas import AIUsageLabel, TriState
from risk.weights import DEFAULT_WEIGHTS, MODEL_VERSION, UNKNOWN_POLICY, validate_weights

# ---- categorical -> [0,1] mappings (documented, deterministic) ----
_CRITICALITY = {"critical": 1.0, "high": 0.75, "medium": 0.5, "moderate": 0.5, "low": 0.25}

_SENSITIVITY_KEYWORDS = {
    1.0: ["health", "vulnerab", "biometric", "ssn", "social security", "government id",
          "financial", "account number", "card", "payment", "credentials", "password",
          "call audio", "income"],
    0.7: ["personal", "name", "address", "date of birth", "customer", "borrower", "pii"],
    0.4: ["configuration", "schedule", "metadata", "aggregate"],
    0.1: ["no direct customer data", "not applicable", "in transit only", "public"],
}

_AI_EXPOSURE = {
    AIUsageLabel.CONFIRMED_GENAI: 1.0,
    AIUsageLabel.CONFIRMED_PRODUCT_FEATURE: 0.9,
    AIUsageLabel.CONFIRMED_INTEGRATION: 0.9,
    AIUsageLabel.CONFIRMED_AI: 0.85,
    AIUsageLabel.THIRD_PARTY_RELATIONSHIP: 0.6,
    AIUsageLabel.INDIRECT: 0.55,
    AIUsageLabel.ADVERTISED_UNVERIFIED: 0.45,
    AIUsageLabel.CONFLICTING: 0.5,
    AIUsageLabel.MENTION_ONLY: 0.25,
    AIUsageLabel.INSUFFICIENT: None,       # -> unknown policy
    AIUsageLabel.NOT_ESTABLISHED: 0.1,
}

_PRIORITY_BANDS = [(80, "Critical"), (60, "High"), (40, "Medium"), (0, "Low")]


@dataclass
class RiskInputs:
    vendor_id: str
    run_id: str
    criticality_tier: Optional[str] = None
    data_classification: Optional[str] = None
    ai_usage_label: Optional[AIUsageLabel] = None
    provider_named: Optional[bool] = None            # are AI providers publicly named?
    data_flow_established: TriState = TriState.UNKNOWN
    retention_training_known: Optional[bool] = None
    security_controls_evidence: Optional[bool] = None
    evidence_reliability: float = 0.0                # mean evidence quality 0..1
    independent_corroboration: int = 0
    contradictions_count: int = 0
    open_questions_count: int = 0


@dataclass
class RiskResult:
    vendor_id: str
    run_id: str
    model_version: str
    weights: Dict[str, float]
    dimension_scores: Dict[str, float]
    inherent_risk: float
    residual_risk: Optional[float]
    evidence_confidence: float
    investigation_uncertainty: float
    overall_priority: str
    missing_information: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
def _sensitivity_score(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    low = text.lower()
    if any(k in low for k in _SENSITIVITY_KEYWORDS[0.1]):
        base = 0.1
    else:
        base = None
    for value in (1.0, 0.7, 0.4):
        if any(k in low for k in _SENSITIVITY_KEYWORDS[value]):
            return value
    return base


def _unknown(dimension: str, missing: list) -> float:
    missing.append(dimension)
    return UNKNOWN_POLICY.get(dimension, 0.5)


def compute_risk(inputs: RiskInputs, weights: Optional[Dict[str, float]] = None) -> RiskResult:
    weights = validate_weights(weights or DEFAULT_WEIGHTS)
    missing: list = []
    dim: Dict[str, float] = {}

    # vendor_criticality (business impact)
    dim["vendor_criticality"] = _CRITICALITY.get((inputs.criticality_tier or "").lower(), None) \
        if inputs.criticality_tier else None
    if dim["vendor_criticality"] is None:
        dim["vendor_criticality"] = _unknown("vendor_criticality", missing) if True else 0.5

    # data_sensitivity
    s = _sensitivity_score(inputs.data_classification)
    dim["data_sensitivity"] = s if s is not None else _unknown("data_sensitivity", missing)

    # ai_usage_exposure
    if inputs.ai_usage_label is None:
        dim["ai_usage_exposure"] = _unknown("ai_usage_exposure", missing)
    else:
        v = _AI_EXPOSURE.get(inputs.ai_usage_label)
        dim["ai_usage_exposure"] = v if v is not None else _unknown("ai_usage_exposure", missing)

    # provider_transparency_gap (higher = worse). Named provider -> low gap.
    if inputs.provider_named is None:
        dim["provider_transparency_gap"] = _unknown("provider_transparency_gap", missing)
    else:
        dim["provider_transparency_gap"] = 0.1 if inputs.provider_named else 0.7

    # data_flow_uncertainty
    if inputs.data_flow_established == TriState.YES:
        dim["data_flow_uncertainty"] = 0.2
    elif inputs.data_flow_established == TriState.NO:
        dim["data_flow_uncertainty"] = 0.15
    else:
        dim["data_flow_uncertainty"] = _unknown("data_flow_uncertainty", missing)

    # retention_training_uncertainty
    if inputs.retention_training_known is None:
        dim["retention_training_uncertainty"] = _unknown("retention_training_uncertainty", missing)
    else:
        dim["retention_training_uncertainty"] = 0.15 if inputs.retention_training_known else 0.7

    # unresolved_contradictions (0,1,2+ -> escalating)
    dim["unresolved_contradictions"] = min(1.0, 0.0 + 0.4 * inputs.contradictions_count)

    # security_governance_gap (higher = worse). Control evidence lowers it.
    if inputs.security_controls_evidence is None:
        dim["security_governance_gap"] = _unknown("security_governance_gap", missing)
    else:
        dim["security_governance_gap"] = 0.1 if inputs.security_controls_evidence else 0.6

    # ---- inherent risk (weighted sum, 0..100) ----
    inherent = sum(dim[k] * weights[k] for k in weights) * 100.0

    # ---- evidence confidence (0..1) ----
    corrob = min(1.0, inputs.independent_corroboration / 3.0)
    evidence_confidence = round(0.6 * inputs.evidence_reliability + 0.4 * corrob, 3)

    # ---- investigation uncertainty (0..1) ----
    # driven by unknown dimensions, open questions and low corroboration
    unknown_fraction = len(missing) / max(1, len(weights))
    oq = min(1.0, inputs.open_questions_count / 5.0)
    investigation_uncertainty = round(
        min(1.0, 0.5 * unknown_fraction + 0.3 * oq + 0.2 * (1 - evidence_confidence)), 3
    )

    # ---- residual risk: only when control evidence exists ----
    residual: Optional[float]
    if inputs.security_controls_evidence:
        residual = round(inherent * 0.8, 2)  # modest, evidence-based reduction
    else:
        residual = None  # cannot justify a reduction without control evidence

    # ---- overall priority ----
    # Uncertainty on a critical/sensitive vendor legitimately raises priority.
    priority_base = inherent
    if investigation_uncertainty >= 0.6 and dim["vendor_criticality"] >= 0.75:
        priority_base = min(100.0, priority_base + 10.0)
    priority = next(label for threshold, label in _PRIORITY_BANDS if priority_base >= threshold)

    return RiskResult(
        vendor_id=inputs.vendor_id,
        run_id=inputs.run_id,
        model_version=MODEL_VERSION,
        weights=weights,
        dimension_scores={k: round(v, 3) for k, v in dim.items()},
        inherent_risk=round(inherent, 2),
        residual_risk=residual,
        evidence_confidence=evidence_confidence,
        investigation_uncertainty=investigation_uncertainty,
        overall_priority=priority,
        missing_information=sorted(set(missing)),
    )
