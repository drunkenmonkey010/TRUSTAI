"""Agent 3 - OSINT Strategy.

Sets investigation questions and hypotheses, then builds a bounded, layered
query plan prioritising high-information-value sources. Each planned query
carries a rationale. The plan respects the run's query budget.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, InvestigationContext

# How many investigation layers each profile targets initially (controller may
# stop earlier or escalate within budget).
PROFILE_MAX_LAYER = {"baseline": 3, "enhanced": 6, "deep": 7}

# Initial query budget per profile (each live search/retrieval costs 1). Sized so
# a profile can actually reach its target layers in live mode.
PROFILE_BUDGET = {"baseline": 18, "enhanced": 35, "deep": 65}

# "Auto" depth: derive the profile from the computed criticality tier so the
# analyst does not have to choose. Manual profiles remain available as overrides.
PROFILE_BY_TIER = {"critical": "deep", "high": "deep", "medium": "enhanced", "low": "baseline"}


def resolve_profile(profile: str, criticality_tier: str) -> str:
    """Resolve 'auto' to a concrete profile from the criticality tier."""
    if (profile or "").lower() != "auto":
        return profile
    return PROFILE_BY_TIER.get((criticality_tier or "").lower(), "enhanced")


class OsintStrategyAgent(BaseAgent):
    name = "osint_strategy"
    depends_on = ["vendor_intake", "criticality"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        v = ctx.vendor
        name = v.get("vendor_name", "")
        website = v.get("website") or ""
        domain = website.replace("www.", "").strip()

        questions = [
            "Is the vendor identity unambiguous and what is its official domain?",
            "Does the vendor publicly advertise or document AI capabilities?",
            "Are AI features released and relevant to the service Meridian consumes?",
            "Which external AI providers or subprocessors are publicly documented?",
            "What data is documented as processed, and is customer data involved?",
            "Is any AI finding independently corroborated or contradicted?",
            "What is the highest-impact unresolved question for the risk assessment?",
        ]
        hypotheses = [
            f"{name} may use AI within '{v.get('service_provided') or 'its service'}'.",
            "If AI is used, customer-data involvement is unknown until documented.",
        ]

        # Layered query plan. Live search queries vs direct retrieval targets.
        plan: Dict[int, List[Dict[str, str]]] = {}

        def add(layer: int, connector: str, query: str, rationale: str) -> None:
            plan.setdefault(layer, []).append(
                {"connector": connector, "query": query, "rationale": rationale}
            )

        # Layer 1 - identity & baseline
        if domain:
            add(1, "public_web", f"https://{domain}", "Retrieve official homepage for baseline/identity.")
            add(1, "public_web", f"https://{domain}/about", "Confirm corporate identity and scope.")
        add(1, "brave_search", f'"{name}" official site', "Confirm official domain and identity.")
        add(1, "sec_edgar", name, "Check for SEC filings if a listed company/parent.")

        # Layer 2 - AI signal discovery
        add(2, "brave_search", f'"{name}" artificial intelligence', "Surface public AI mentions.")
        add(2, "brave_search", f'"{name}" "generative AI" OR copilot OR assistant', "Detect generative AI signals.")
        if domain:
            add(2, "public_web", f"https://{domain}/ai", "Vendor AI product/landing page if present.")

        # Layer 3 - product & technical validation
        if domain:
            add(3, "public_web", f"https://{domain}/product", "Validate feature availability / status.")
            add(3, "public_web", f"https://{domain}/release-notes", "Check release status of AI features.")
        add(3, "brave_search", f'"{name}" AI documentation OR release notes', "Validate deployment status.")

        # Layer 4 - provider & dependency mapping
        if domain:
            add(4, "public_web", f"https://{domain}/subprocessors", "Named subprocessors / model providers.")
            add(4, "public_web", f"https://{domain}/trust", "Trust centre / security documentation.")
        add(4, "brave_search", f'"{name}" subprocessors OR "model provider" OR OpenAI OR Anthropic', "Provider relationships.")

        # Layer 5 - data-flow & processing
        if domain:
            add(5, "public_web", f"https://{domain}/privacy", "Privacy policy / data-processing terms.")
        add(5, "brave_search", f'"{name}" privacy policy data processing retention training', "Data-flow / retention terms.")

        # Layer 6 - corroboration & contradiction
        add(6, "brave_search", f'"{name}" AI announcement news', "Independent corroboration.")
        add(6, "brave_search", f'"{name}" AI incident OR breach OR concern', "Contradiction / negative evidence.")

        # Layer 7 - risk-oriented gap closure (controller fills specifics)
        add(7, "brave_search", f'"{name}" AI governance OR "responsible AI" OR DPA', "Close highest-impact gap.")

        max_layer = PROFILE_MAX_LAYER.get(ctx.profile, 3)
        plan = {k: val for k, val in plan.items() if k <= max_layer}

        # Persist planned queries (status=planned).
        for layer, queries in plan.items():
            for q in queries:
                ctx.db.insert(
                    "investigation_queries",
                    {
                        "run_id": ctx.run_id,
                        "layer": layer,
                        "connector": q["connector"],
                        "query_text": q["query"],
                        "rationale": q["rationale"],
                        "status": "planned",
                    },
                )

        ctx.state["layer_plan"] = {str(k): val for k, val in plan.items()}
        ctx.state["max_layer"] = max_layer
        ctx.state["questions"] = questions
        ctx.state["hypotheses"] = hypotheses
        return {
            "questions": questions,
            "hypotheses": hypotheses,
            "max_layer": max_layer,
            "planned_query_count": sum(len(x) for x in plan.values()),
            "layers": sorted(plan.keys()),
        }
