"""Investigation workflow orchestrator.

Runs the twelve agents in dependency order for one vendor. The adaptive-depth
agent internally drives the layered collection/extraction/verification loop, so
the top-level sequence is:

  intake -> criticality -> strategy -> adaptive_depth(loop) ->
  ai_classification -> provider_dataflow -> risk -> recommendations -> qa
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.adaptive_depth import AdaptiveDepthAgent
from agents.ai_classification import AiClassificationAgent
from agents.base import InvestigationContext, QueryBudget
from agents.criticality import CriticalityAgent
from agents.llm import LLMClient
from agents.osint_strategy import OsintStrategyAgent, PROFILE_BUDGET, resolve_profile
from agents.provider_dataflow import ProviderDataflowAgent
from agents.quality_assurance import QualityAssuranceAgent
from agents.recommendations import RecommendationsAgent
from agents.risk_assessment import RiskAssessmentAgent
from agents.vendor_intake import VendorIntakeAgent
from config.logging_config import get_logger
from config.settings import Settings, get_settings
from connectors.registry import ConnectorRegistry
from database.connection import Database, get_db
from evidence.ledger import EvidenceLedger
from orchestration.run_manager import RunManager

log = get_logger("workflow")

# Identity + criticality run first so an "auto" depth can be resolved from the
# derived tier BEFORE the strategy/budget are fixed.
PRE_AGENTS = [VendorIntakeAgent, CriticalityAgent]
# The remaining sequence (adaptive_depth contains the per-layer agents).
POST_AGENTS = [
    OsintStrategyAgent, AdaptiveDepthAgent, AiClassificationAgent, ProviderDataflowAgent,
    RiskAssessmentAgent, RecommendationsAgent, QualityAssuranceAgent,
]
TOP_LEVEL_AGENTS = PRE_AGENTS + POST_AGENTS

ALL_AGENT_NAMES = [
    "vendor_intake", "criticality", "osint_strategy", "collection",
    "evidence_extraction", "evidence_verification", "ai_classification",
    "provider_dataflow", "adaptive_depth", "risk_assessment",
    "recommendations", "quality_assurance",
]


class InvestigationWorkflow:
    def __init__(self, settings: Optional[Settings] = None, db: Optional[Database] = None):
        self.settings = settings or get_settings()
        self.db = db or get_db()
        self.registry = ConnectorRegistry(self.settings, self.db)
        self.run_manager = RunManager(self.db)

    def investigate(
        self,
        vendor_id: str,
        profile: str = "baseline",
        manual_sources: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        vendor = self.db.query_one("SELECT * FROM vendors WHERE vendor_id=?", (vendor_id,))
        if not vendor:
            raise ValueError(f"vendor {vendor_id} not found")

        live_mode = self.registry.live_search_available()
        requested_profile = profile
        # Provisional budget until an 'auto' profile is resolved from criticality.
        provisional = PROFILE_BUDGET.get(profile, self.settings.investigation_query_budget)
        run_id = self.run_manager.create_run(vendor_id, profile, live_mode, provisional)
        self.run_manager.mark_running(run_id)

        ctx = InvestigationContext(
            run_id=run_id, vendor=dict(vendor), profile=profile, live_mode=live_mode,
            registry=self.registry, ledger=EvidenceLedger(self.db), db=self.db,
            llm=LLMClient(self.settings), settings=self.settings,
            budget=QueryBudget(total=provisional),
            manual_sources=manual_sources or [],
        )

        statuses: Dict[str, str] = {}
        try:
            # Phase 1 - identity + criticality (no connector calls, no budget spend).
            for agent_cls in PRE_AGENTS:
                result = agent_cls().run(ctx)
                statuses[result.agent_name] = result.status

            # Resolve 'auto' depth from the derived criticality tier, then fix budget.
            tier = ctx.state.get("criticality", {}).get("criticality_tier", "")
            resolved = resolve_profile(requested_profile, tier)
            ctx.profile = resolved
            ctx.budget.total = PROFILE_BUDGET.get(resolved, provisional)
            self.db.execute(
                "UPDATE investigation_runs SET profile=?, query_budget=? WHERE run_id=?",
                (resolved, ctx.budget.total, run_id))
            if requested_profile.lower() == "auto":
                self.db.audit("run", "auto_depth", subject=vendor_id, run_id=run_id,
                              detail={"tier": tier, "resolved_profile": resolved})

            # Phase 2 - strategy, adaptive investigation loop, scoring, QA.
            for agent_cls in POST_AGENTS:
                result = agent_cls().run(ctx)
                statuses[result.agent_name] = result.status
                if result.status == "failed":
                    log.warning("agent %s failed: %s", result.agent_name, result.error)
            # Phase 3 - post-processing services (V2.1): derive remediation findings,
            # questionnaires, control/framework mappings, threat scenarios, attack
            # paths, evidence metrics, change detection + baseline. Each is guarded
            # so a service failure never fails the investigation.
            self._post_process(run_id, vendor_id)

            summary = self._summary(ctx, statuses)
            summary["requested_profile"] = requested_profile
            summary["resolved_profile"] = resolved
            self.run_manager.complete_run(run_id, ctx.budget.used, summary)
            return {"run_id": run_id, "status": "completed", "summary": summary,
                    "agent_statuses": statuses}
        except Exception as exc:  # pragma: no cover
            self.run_manager.fail_run(run_id, str(exc))
            raise

    # ------------------------------------------------------------------ #
    def _post_process(self, run_id: str, vendor_id: str) -> None:
        from frameworks.crosswalk import assess_controls, map_frameworks
        from monitoring.change_detector import capture_baseline, detect_changes
        from questionnaires.engine import generate_questions
        from remediation.manager import RemediationManager
        from threat_modeling.engine import build_attack_paths, generate_scenarios
        from evaluation.lab import run_evidence_metrics

        steps = [
            ("remediation", lambda: RemediationManager(self.db).create_findings_from_recommendations(run_id)),
            ("questionnaire", lambda: generate_questions(run_id, self.db)),
            ("controls", lambda: (assess_controls(run_id, self.db), map_frameworks(run_id, self.db))),
            ("threat_modeling", lambda: (generate_scenarios(run_id, self.db), build_attack_paths(run_id, self.db))),
            ("evidence_metrics", lambda: run_evidence_metrics(run_id, self.db)),
            ("change_detection", lambda: detect_changes(vendor_id, run_id, self.db)),
            ("baseline", lambda: capture_baseline(run_id, self.db)),
        ]
        for name, fn in steps:
            try:
                fn()
            except Exception as exc:
                log.warning("post-process step %s failed: %s", name, exc)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _summary(ctx: InvestigationContext, statuses: Dict[str, str]) -> Dict[str, Any]:
        risk = ctx.state.get("risk", {})
        classification = ctx.state.get("ai_classification", {})
        qa = ctx.state.get("qa", {})
        return {
            "vendor_id": ctx.vendor_id,
            "ai_usage_label": classification.get("label"),
            "ai_confidence": classification.get("confidence"),
            "overall_priority": risk.get("overall_priority"),
            "inherent_risk": risk.get("inherent_risk"),
            "evidence_confidence": risk.get("evidence_confidence"),
            "investigation_uncertainty": risk.get("investigation_uncertainty"),
            "qa_reliability": qa.get("reliability"),
            "sources": len(ctx.state.get("sources", [])),
            "queries_used": ctx.budget.used,
            "mode": "live" if ctx.live_mode else "offline",
            "agent_statuses": statuses,
        }
