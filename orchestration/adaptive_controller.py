"""Adaptive investigation controller (seven-layer methodology).

Decides the next investigative action and the stop/continue/escalate decision
from the current investigation state. It does NOT use a naive "always do N
searches" rule: the decision weighs criticality, data sensitivity, evidence
quality, uncertainty, contradictions, expected information gain, diminishing
returns and remaining budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ControllerMetrics:
    layer: int
    new_sources_last_layer: int
    total_sources: int
    mean_quality: float
    contradictions: int
    independent_corroboration: int
    ai_label: str
    criticality_tier: str
    data_sensitivity_rank: int
    data_flow_unknown: bool


@dataclass
class Decision:
    decision: str  # continue | stop | escalate
    next_layer: Optional[int]
    proposed_action: str
    action_value: str
    expected_uncertainty_reduction: float
    budget_cost: int
    human_review_trigger: bool
    rationale: str
    state_summary: Dict[str, Any] = field(default_factory=dict)
    gaps_considered: List[str] = field(default_factory=list)


_CONFIRMED = ("Confirmed",)


class AdaptiveController:
    def __init__(self, max_layer: int, budget_remaining_fn):
        self.max_layer = max_layer
        self._budget_remaining = budget_remaining_fn

    # ------------------------------------------------------------------ #
    def decide(self, m: ControllerMetrics) -> Decision:
        remaining = self._budget_remaining()
        critical = m.criticality_tier.lower() in ("critical", "high")
        sensitive = m.data_sensitivity_rank >= 2
        confirmed = m.ai_label.startswith(_CONFIRMED)
        gaps = self._gaps(m, confirmed)

        state_summary = {
            "layer": m.layer, "total_sources": m.total_sources,
            "mean_quality": m.mean_quality, "ai_label": m.ai_label,
            "contradictions": m.contradictions,
            "independent_corroboration": m.independent_corroboration,
            "budget_remaining": remaining,
        }

        # 1) Budget exhausted -> stop.
        if remaining <= 0:
            return Decision("stop", None, "halt", "budget exhausted", 0.0, 0, critical,
                            "Query budget exhausted; stopping and flagging remaining gaps.",
                            state_summary, gaps)

        # 2) Contradictions -> escalate to corroboration layer (6) if not past it.
        if m.contradictions > 0 and m.layer < 6:
            return Decision("escalate", 6, "corroborate",
                            "resolve contradictory evidence", 0.4, 2, True,
                            "Contradictory evidence present; escalating to independent corroboration.",
                            state_summary, gaps)

        # 3) Reached max layer -> stop.
        if m.layer >= self.max_layer:
            return Decision("stop", None, "halt", "reached profile depth", 0.0, 0,
                            critical and m.data_flow_unknown,
                            f"Reached configured max layer ({self.max_layer}).",
                            state_summary, gaps)

        # 4) Strong confirmation + no contradictions: consider early stop unless a
        #    critical/sensitive vendor still has an unresolved data-flow question.
        if confirmed and m.contradictions == 0 and m.layer >= 3:
            if critical and sensitive and m.data_flow_unknown and m.layer < 5:
                return Decision("continue", m.layer + 1, "map_data_flow",
                                "pursue data-flow/provider evidence", 0.35, 2, False,
                                "AI use confirmed; critical+sensitive vendor with unknown data flow "
                                "warrants deeper provider/data-flow investigation.",
                                state_summary, gaps)
            return Decision("stop", None, "halt", "confident conclusion reached", 0.0, 0, False,
                            "AI use confirmed with no contradictions; diminishing returns - stopping.",
                            state_summary, gaps)

        # 5) Diminishing returns: last layer produced nothing and vendor not critical.
        if m.new_sources_last_layer == 0 and m.layer >= 2 and not critical:
            return Decision("stop", None, "halt", "diminishing returns", 0.0, 0, False,
                            "Last layer produced no new sources and vendor is not critical; stopping.",
                            state_summary, gaps)

        # 6) Default: continue one layer deeper.
        return Decision("continue", m.layer + 1, "deepen",
                        f"advance to layer {m.layer + 1}",
                        0.3 if gaps else 0.15, 2, False,
                        "Open gaps remain and budget allows; continuing to next layer.",
                        state_summary, gaps)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _gaps(m: ControllerMetrics, confirmed: bool) -> List[str]:
        gaps: List[str] = []
        if m.ai_label in ("Insufficient evidence", ""):
            gaps.append("AI usage not yet determined")
        if m.data_flow_unknown:
            gaps.append("customer-data flow unknown")
        if confirmed and m.independent_corroboration == 0:
            gaps.append("no independent corroboration of confirmed AI use")
        if m.mean_quality and m.mean_quality < 0.5:
            gaps.append("mean evidence quality is low")
        return gaps
