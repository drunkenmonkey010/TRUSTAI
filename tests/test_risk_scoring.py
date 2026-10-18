"""Deterministic risk scoring tests."""
from __future__ import annotations

import pytest

from evidence.schemas import AIUsageLabel, TriState
from risk.scoring import RiskInputs, compute_risk
from risk.weights import DEFAULT_WEIGHTS, validate_weights


def _base(**kw):
    defaults = dict(vendor_id="V-1", run_id="r-1", criticality_tier="Critical",
                    data_classification="customer payment account numbers",
                    ai_usage_label=AIUsageLabel.CONFIRMED_GENAI, provider_named=True,
                    data_flow_established=TriState.YES, retention_training_known=True,
                    security_controls_evidence=True, evidence_reliability=0.8,
                    independent_corroboration=2, contradictions_count=0, open_questions_count=0)
    defaults.update(kw)
    return RiskInputs(**defaults)


def test_deterministic_same_input_same_output():
    a = compute_risk(_base())
    b = compute_risk(_base())
    assert a.inherent_risk == b.inherent_risk
    assert a.dimension_scores == b.dimension_scores


def test_weight_validation_normalizes():
    w = validate_weights({k: 1.0 for k in DEFAULT_WEIGHTS})
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_weight_validation_rejects_unknown():
    with pytest.raises(ValueError):
        validate_weights({"not_a_dimension": 1.0})


def test_unknown_not_treated_as_zero():
    # Everything unknown -> uncertainty high and inherent risk clearly > 0.
    r = compute_risk(RiskInputs(vendor_id="V-1", run_id="r-1"))
    assert r.inherent_risk > 0
    assert r.investigation_uncertainty > 0
    assert r.missing_information  # unknowns explicitly tracked


def test_confidence_not_confused_with_risk():
    # Low evidence reliability lowers confidence but criticality still drives risk.
    r = compute_risk(_base(evidence_reliability=0.0, independent_corroboration=0))
    assert r.evidence_confidence < 0.5
    assert r.inherent_risk > 40  # risk independent of confidence


def test_residual_only_with_controls():
    with_controls = compute_risk(_base(security_controls_evidence=True))
    without = compute_risk(_base(security_controls_evidence=None))
    assert with_controls.residual_risk is not None
    assert without.residual_risk is None  # cannot reduce without control evidence


def test_model_version_preserved():
    r = compute_risk(_base())
    assert r.model_version.startswith("risk-model-")
    assert set(r.weights.keys()) == set(DEFAULT_WEIGHTS.keys())
