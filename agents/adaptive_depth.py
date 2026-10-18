"""Agent 9 - Adaptive Depth Controller.

Drives the seven-layer investigation loop. For each layer it runs collection,
extraction and verification, then asks the :class:`AdaptiveController` whether to
continue, stop or escalate - recording a structured decision each step. It
tracks layer coverage and remaining uncertainty separately (completing layers is
not treated as the same thing as investigation quality).
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, InvestigationContext
from agents.collection import CollectionAgent
from agents.criticality import CriticalityAgent  # noqa: F401 (documents dependency)
from agents.evidence_extraction import EvidenceExtractionAgent
from agents.evidence_verification import EvidenceVerificationAgent
from database.connection import utcnow
from orchestration.adaptive_controller import AdaptiveController, ControllerMetrics

_MAX_STEPS = 10


class AdaptiveDepthAgent(BaseAgent):
    name = "adaptive_depth"
    depends_on = ["osint_strategy"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        max_layer = int(ctx.state.get("max_layer", 3))
        controller = AdaptiveController(max_layer, lambda: ctx.budget.remaining)
        collection = CollectionAgent()
        extraction = EvidenceExtractionAgent()
        verification = EvidenceVerificationAgent()

        crit = ctx.state.get("criticality", {})
        layers_visited: List[int] = []
        decisions: List[Dict[str, Any]] = []
        layer = 1
        step = 0

        while step < _MAX_STEPS:
            step += 1
            ctx.state["current_layer"] = layer
            layers_visited.append(layer)

            collection.run(ctx)
            extraction.run(ctx)
            verification.run(ctx)

            verif = ctx.state.get("verification", {})
            new_sources = len(ctx.state.get("collected_by_layer", {}).get(str(layer), []))
            metrics = ControllerMetrics(
                layer=layer,
                new_sources_last_layer=new_sources,
                total_sources=len(ctx.state.get("sources", [])),
                mean_quality=verif.get("mean_quality", 0.0),
                contradictions=verif.get("contradictions", 0),
                independent_corroboration=verif.get("independent_corroboration", 0),
                ai_label=self._interim_label(ctx),
                criticality_tier=crit.get("criticality_tier", ""),
                data_sensitivity_rank=crit.get("data_sensitivity_rank", 0),
                data_flow_unknown=True,  # data-flow agent runs after the loop
            )
            decision = controller.decide(metrics)
            self._record_decision(ctx, step, layer, decision)
            decisions.append({
                "step": step, "layer": layer, "decision": decision.decision,
                "proposed_action": decision.proposed_action, "rationale": decision.rationale,
                "gaps": decision.gaps_considered,
            })

            if decision.decision == "stop" or decision.next_layer is None:
                ctx.state["stop_rationale"] = decision.rationale
                ctx.state["human_review_trigger"] = decision.human_review_trigger
                break
            layer = decision.next_layer

        coverage = {
            "layers_visited": sorted(set(layers_visited)),
            "max_layer": max_layer,
            "steps": step,
            "stop_rationale": ctx.state.get("stop_rationale", "loop step cap reached"),
            "reopen_conditions": self._reopen_conditions(ctx),
        }
        ctx.state["layer_coverage"] = coverage
        return {"decisions": decisions, "coverage": coverage}

    # ------------------------------------------------------------------ #
    def _interim_label(self, ctx: InvestigationContext) -> str:
        rows = ctx.ledger.evidence_for_run(ctx.run_id)
        direct_gen = False
        any_ai = False
        for e in rows:
            if e.get("verification_status") == "circular":
                continue
            claim = ctx.db.query_one("SELECT action FROM claims WHERE claim_id=?", (e.get("claim_id"),))
            action = (claim or {}).get("action")
            if action in ("ai", "generative", "integration"):
                any_ai = True
                if action == "generative" and e.get("directness") == "direct":
                    direct_gen = True
        if direct_gen:
            return "Confirmed generative AI use"
        if any_ai:
            return "AI use indicated by indirect evidence"
        return "Insufficient evidence"

    def _record_decision(self, ctx, step, layer, decision) -> None:
        ctx.db.insert("adaptive_decisions", {
            "run_id": ctx.run_id, "step": step, "layer": layer,
            "state_summary": decision.state_summary,
            "gaps_considered": decision.gaps_considered,
            "proposed_action": decision.proposed_action,
            "action_value": decision.action_value,
            "expected_uncertainty_reduction": decision.expected_uncertainty_reduction,
            "budget_cost": decision.budget_cost,
            "decision": decision.decision,
            "human_review_trigger": int(decision.human_review_trigger),
            "rationale": decision.rationale, "created_at": utcnow(),
        })

    @staticmethod
    def _reopen_conditions(ctx: InvestigationContext) -> List[str]:
        return [
            "New public disclosure of AI usage or a named model provider.",
            "Vendor publishes (or updates) a subprocessor list / trust centre.",
            "Independent reporting contradicts the current conclusion.",
            "Analyst supplies additional first-party sources.",
        ]
