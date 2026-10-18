"""Risk model weights and the documented unknown-handling policy.

Weights are visible to the user and stored with each scoring run. The model is
versioned so historical assessments remain interpretable.
"""
from __future__ import annotations

from typing import Dict

MODEL_VERSION = "risk-model-1.0.0"

# Each dimension contributes to INHERENT risk. Weights sum to 1.0.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "vendor_criticality": 0.20,
    "data_sensitivity": 0.18,
    "ai_usage_exposure": 0.16,
    "provider_transparency_gap": 0.12,
    "data_flow_uncertainty": 0.12,
    "retention_training_uncertainty": 0.10,
    "unresolved_contradictions": 0.06,
    "security_governance_gap": 0.06,
}

# Documented policy for unknown/missing structured inputs. Unknown is NEVER
# silently treated as zero risk, and NEVER treated as proof of a failure.
# Instead unknowns map to an explicit elevated-uncertainty value in [0,1].
UNKNOWN_POLICY: Dict[str, float] = {
    "data_sensitivity": 0.6,            # unknown sensitivity -> assume moderately high
    "ai_usage_exposure": 0.4,           # unknown AI exposure -> mid
    "provider_transparency_gap": 0.7,   # no named provider -> high transparency gap
    "data_flow_uncertainty": 0.7,       # undocumented flow -> high uncertainty
    "retention_training_uncertainty": 0.7,
    "security_governance_gap": 0.6,     # no control evidence -> elevated gap (not proof)
}


def validate_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Validate and normalize weights to sum to 1.0. Raises on bad input."""
    if not weights:
        raise ValueError("weights cannot be empty")
    for k, v in weights.items():
        if k not in DEFAULT_WEIGHTS:
            raise ValueError(f"unknown risk dimension: {k}")
        if v < 0:
            raise ValueError(f"weight for {k} must be non-negative")
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weights must sum to a positive value")
    return {k: round(v / total, 6) for k, v in weights.items()}
