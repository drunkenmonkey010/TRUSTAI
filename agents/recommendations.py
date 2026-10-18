"""Agent 11 - Recommendations.

Produces prioritised, actionable recommendations tied to findings and evidence
gaps, scaled by vendor criticality and data sensitivity. It distinguishes
immediate control actions, contractual/governance questions, technical
validation, additional evidence collection and routine monitoring. Every
recommendation maps to a real finding or gap - no padding.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, InvestigationContext
from database.connection import utcnow
from evidence.schemas import Recommendation

# Explicit priority ordering (string priorities don't sort correctly on their own).
PRIORITY_ORDER = {"Immediate": 0, "High": 1, "Medium": 2, "Low": 3}


class RecommendationsAgent(BaseAgent):
    name = "recommendations"
    depends_on = ["risk_assessment"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        risk = ctx.state.get("risk", {})
        classification = ctx.state.get("ai_classification", {})
        data_flow = ctx.state.get("data_flow", {})
        crit = ctx.state.get("criticality", {})

        label = classification.get("label", "")
        tier = (crit.get("criticality_tier") or "").lower()
        critical = tier in ("critical", "high")
        sensitive = crit.get("data_sensitivity_rank", 0) >= 2
        confirmed = label.startswith("Confirmed")
        indirect = ("indirect" in label.lower()) or ("advertised" in label.lower())
        unknown_flow = data_flow.get("customer_data_involved", "unknown") == "unknown"
        provider_named = bool(ctx.state.get("provider_named"))
        retention_known = bool(ctx.state.get("retention_training_known"))
        no_control_evidence = risk.get("residual_risk") is None  # residual only set when controls exist
        evidence_ref = f"AI classification evidence ids: {classification.get('evidence_ids')}"

        recs: List[Recommendation] = []

        def add(category, finding, rationale, action, priority, role, horizon, evidence, closure):
            recs.append(Recommendation(
                vendor_id=ctx.vendor_id, run_id=ctx.run_id, category=category, finding=finding,
                rationale=rationale, action=action, priority=priority, responsible_role=role,
                time_horizon=horizon, supporting_evidence=evidence, closure_conditions=closure))

        hi = "Immediate" if critical else "High"
        reassess_cadence = "Quarterly" if critical else "Semi-annually"

        # --- Confirmed AI use branch ---
        if confirmed:
            if unknown_flow:
                sens_bits = (" call-audio/sensitive-data handling," if sensitive else "")
                add("evidence_collection",
                    f"AI usage '{label}' but customer-data flow to the AI feature is unknown.",
                    "Confirmed AI use with undetermined data flow is a material gap, more so for a "
                    f"{tier or 'significant'} vendor.",
                    f"Issue a targeted vendor questionnaire: model provider identity, hosting region, "
                    f"retention, training use of data,{sens_bits} and human oversight over AI output.",
                    hi, "Third-Party Risk / Vendor Manager", "15 business days",
                    evidence_ref, "Vendor provides written answers on provider, data flow, retention.")

            if critical and (unknown_flow or sensitive):
                add("governance",
                    f"Critical/{tier} vendor with confirmed AI use and unresolved data-flow/sensitivity.",
                    "The combination of criticality, sensitive data and an unverified AI data path "
                    "warrants governance oversight beyond the assessment team.",
                    "Escalate to the Third-Party Risk Committee for a risk-acceptance or remediation decision.",
                    "Immediate", "Third-Party Risk Committee", "10 business days",
                    f"Risk priority {risk.get('overall_priority')}, inherent {risk.get('inherent_risk')}",
                    "Committee decision recorded (accept / remediate / exit).")

            add("governance",
                "No AI clauses confirmed in the current contract.",
                "AI processing of Meridian data should be governed contractually.",
                "Add AI clauses at the next contract review: training restrictions, subprocessor "
                "change notification, human-oversight thresholds, and audit rights.",
                hi if sensitive else "Medium", "Procurement / Legal", "Next contract review",
                "Risk assessment + classification", "AI addendum executed.")

            flag = "" if provider_named else " with an unresolved-provider flag"
            add("evidence_collection",
                "Vendor uses AI; subprocessor/model-provider governance needs a register entry.",
                "Confirmed AI vendors should be tracked on the AI subprocessor inventory regardless of "
                "whether a provider is publicly named.",
                f"Register the vendor on the AI subprocessor inventory{flag}.",
                "High" if critical else "Medium", "Third-Party Risk", "15 business days",
                evidence_ref, "Inventory entry created and reviewed.")

            if not retention_known:
                add("evidence_collection",
                    "Retention and model-training terms not found in public sources.",
                    "Without documented retention/training terms, onward data use cannot be bounded.",
                    "Obtain documented retention, deletion and model-training terms for any data processed.",
                    "High" if sensitive else "Medium", "Third-Party Risk / Legal", "30 days",
                    "Data-flow finding", "Retention & training terms documented.")

            if provider_named:
                add("technical_validation",
                    "AI provider(s) named publicly but the integration/data path is unverified.",
                    "A named provider is an association, not proof of a live customer-data path.",
                    "Validate whether the named provider actually processes Meridian data and under what terms.",
                    "Medium", "Security Architecture", "30 days",
                    "Provider relationships", "Data path confirmed or ruled out.")
            else:
                add("technical_validation",
                    "No AI model/provider named in public sources.",
                    "Provider identity is required to trace onward data flows and retention.",
                    "Determine the model/AI provider via vendor engagement or technical validation.",
                    "Medium", "Security Architecture", "30 days",
                    "Negative finding in evidence ledger", "Provider identified or confirmed absent.")

            if no_control_evidence:
                add("technical_validation",
                    "No public security/trust documentation (trust centre, SOC2/ISO, DPA) was found.",
                    "Absence of control evidence is not proof of weak controls, but prevents residual-risk reduction.",
                    "Request the vendor's security attestations and AI governance documentation.",
                    "Medium", "Security Assurance", "30 days",
                    "Source inventory", "Control evidence obtained and reviewed.")

        # --- Indirect / advertised branch ---
        elif indirect:
            add("technical_validation",
                f"AI usage only indirectly indicated ('{label}').",
                "Indirect signals (e.g. careers pages, marketing) do not establish deployment.",
                "Confirm whether AI is actually deployed in the service Meridian consumes.",
                "High" if critical else "Medium", "Third-Party Risk", "30 days",
                evidence_ref, "Deployment confirmed or ruled out.")
            if critical:
                add("evidence_collection",
                    "Critical/High vendor with unconfirmed AI signals.",
                    "Criticality warrants resolving the AI question despite weak public evidence.",
                    "Send a direct AI-usage questionnaire to the vendor.",
                    "High", "Third-Party Risk / Vendor Manager", "15 business days",
                    evidence_ref, "Vendor confirms or denies AI usage in writing.")

        # --- Insufficient / not established branch ---
        else:
            if critical:
                add("evidence_collection",
                    f"AI usage '{label}' for a {tier} vendor.",
                    "Public evidence is insufficient, but the vendor's criticality warrants confirmation.",
                    "Perform analyst-led OSINT and/or issue a direct AI-usage questionnaire.",
                    "High", "Third-Party Risk / Vendor Manager", "20 business days",
                    "Investigation trace", "AI-usage question resolved for this vendor.")
            add("monitoring",
                f"AI usage '{label}'.",
                "No control action is justified by current public evidence; keep the vendor under watch.",
                "Place vendor on periodic re-scan; reopen on new disclosures.",
                "Low", "Third-Party Risk", reassess_cadence,
                "Investigation trace", "Scheduled re-scan completed.")

        # --- Periodic reassessment when AI activity exists (insufficient branch
        #     already adds its own monitoring rec, so avoid a duplicate there). ---
        if confirmed or indirect:
            add("monitoring",
                "Assessment reflects public evidence at a point in time.",
                "AI posture and data flows change; a critical vendor warrants a tighter cadence.",
                "Schedule a periodic re-assessment of this vendor's AI usage and data flows.",
                "Low", "Third-Party Risk", reassess_cadence,
                "This investigation run", "Next scheduled assessment completed.")

        # --- Human-review trigger ---
        if ctx.state.get("human_review_trigger"):
            add("governance",
                "Investigation flagged for analyst review.",
                "Contradictions or a critical vendor with unresolved data-flow require human judgement.",
                "Analyst to review evidence and decide on escalation.",
                "High", "Lead Analyst", "10 business days",
                "Adaptive decision trace", "Analyst sign-off recorded.")

        # De-duplicate on (category, action) and sort by priority.
        seen = set()
        unique: List[Recommendation] = []
        for r in recs:
            key = (r.category, r.action)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        unique.sort(key=lambda r: PRIORITY_ORDER.get(r.priority, 9))

        for r in unique:
            ctx.db.insert("recommendations", {
                "run_id": ctx.run_id, "vendor_id": ctx.vendor_id, "category": r.category,
                "finding": r.finding, "rationale": r.rationale, "action": r.action,
                "priority": r.priority, "responsible_role": r.responsible_role,
                "time_horizon": r.time_horizon, "supporting_evidence": r.supporting_evidence,
                "closure_conditions": r.closure_conditions, "created_at": utcnow(),
            })
        ctx.state["recommendations"] = [r.model_dump() for r in unique]
        return {"recommendation_count": len(unique),
                "priorities": sorted({r.priority for r in unique}, key=lambda p: PRIORITY_ORDER.get(p, 9))}
