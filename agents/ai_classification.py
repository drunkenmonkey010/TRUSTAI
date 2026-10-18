"""Agent 7 - AI-Usage Classification (claim-level aggregation, V2.1).

Per-claim classifications (from the context-aware classifier) are independently
VERIFIED here - a confirmed claim whose excerpt does not actually support it is
downgraded, with the original preserved. The vendor-level label is the strongest
*verified* claim classification by precedence; keyword mentions aggregate to
"AI mention only", never to confirmed use. An LLM, if present, is advisory only.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, InvestigationContext
from database.connection import utcnow
from evidence.claim_classifier import verify_support
from evidence.schemas import AI_LABEL_PRECEDENCE, AIUsageLabel

_CONFIRMED = {
    AIUsageLabel.CONFIRMED_GENAI, AIUsageLabel.CONFIRMED_PRODUCT_FEATURE,
    AIUsageLabel.CONFIRMED_INTEGRATION, AIUsageLabel.CONFIRMED_AI,
}


class AiClassificationAgent(BaseAgent):
    name = "ai_classification"
    depends_on = ["evidence_verification"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        claims = ctx.db.query(
            "SELECT * FROM claims WHERE run_id=? AND classification IS NOT NULL ORDER BY claim_id",
            (ctx.run_id,))

        effective: List[Dict[str, Any]] = []   # {label, claim, evidence_ids}
        for c in claims:
            ev = ctx.db.query_one(
                "SELECT evidence_id, excerpt, source_type, verification_status "
                "FROM evidence WHERE claim_id=? ORDER BY evidence_id LIMIT 1", (c["claim_id"],))
            if not ev or ev.get("verification_status") == "circular":
                continue
            try:
                original = AIUsageLabel(c["classification"])
            except ValueError:
                continue
            verified, eff_label, why = verify_support(
                original, ev.get("excerpt") or "", ev.get("source_type"))
            ctx.db.execute(
                "UPDATE claims SET verification_status=?, classification_rationale="
                "COALESCE(classification_rationale,'') || ? WHERE claim_id=?",
                ("verified" if verified else "downgraded", f" | verify: {why}", c["claim_id"]))
            ev_ids = [e["evidence_id"] for e in ctx.db.query(
                "SELECT evidence_id FROM evidence WHERE claim_id=?", (c["claim_id"],))]
            effective.append({"label": eff_label, "claim": c, "evidence_ids": ev_ids})

        present = {e["label"] for e in effective}
        sources_examined = len(ctx.state.get("sources", []))

        # Conflicting = a confirmed claim co-exists with an explicit 'not established'.
        if (present & _CONFIRMED) and AIUsageLabel.NOT_ESTABLISHED in present:
            label = AIUsageLabel.CONFLICTING
        elif present:
            label = next((l for l in AI_LABEL_PRECEDENCE if l in present), AIUsageLabel.MENTION_ONLY)
        elif sources_examined > 0 and ctx.live_mode:
            label = AIUsageLabel.NOT_ESTABLISHED
        else:
            label = AIUsageLabel.INSUFFICIENT

        chosen = [e for e in effective if e["label"] == label]
        evidence_ids = [eid for e in chosen for eid in e["evidence_ids"]]
        verif = ctx.state.get("verification", {})
        confidence = self._confidence(label, chosen, verif)
        deployment_context = self._deployment_context(label, chosen)
        rationale = self._rationale(label, effective, sources_examined, ctx.live_mode)

        llm_suggestion = None
        if ctx.llm.available and chosen:
            excerpts = " | ".join(
                (ctx.db.query_one("SELECT excerpt FROM evidence WHERE evidence_id=?", (eid,)) or {})
                .get("excerpt", "")[:160] for eid in evidence_ids[:4])
            prompt = ("Classify the vendor's AI usage into exactly one of: "
                      + ", ".join(l.value for l in AIUsageLabel)
                      + f".\nEvidence excerpts: {excerpts}\nRespond with only the label.")
            llm_suggestion = ctx.llm.complete(prompt, system="You are a cautious third-party risk analyst.")

        ctx.db.insert("ai_usage_classifications", {
            "run_id": ctx.run_id, "vendor_id": ctx.vendor_id, "label": label.value,
            "deployment_context": deployment_context, "confidence": confidence,
            "evidence_ids": evidence_ids,
            "rationale": rationale + (f" [LLM advisory: {llm_suggestion.strip()}]" if llm_suggestion else ""),
            "created_at": utcnow(),
        })
        result = {
            "label": label.value, "deployment_context": deployment_context,
            "confidence": confidence, "evidence_ids": evidence_ids, "rationale": rationale,
            "claim_label_distribution": {l.value: sum(1 for e in effective if e["label"] == l)
                                         for l in present},
            "downgraded_claims": ctx.db.query_one(
                "SELECT COUNT(*) c FROM claims WHERE run_id=? AND verification_status='downgraded'",
                (ctx.run_id,))["c"],
        }
        ctx.state["ai_classification"] = result
        return result

    # ------------------------------------------------------------------ #
    def _confidence(self, label, chosen, verif) -> float:
        if label in (AIUsageLabel.INSUFFICIENT,):
            return 0.1
        if label == AIUsageLabel.NOT_ESTABLISHED:
            return 0.2
        base = max((e["claim"].get("confidence") or 0.0) for e in chosen) if chosen else 0.3
        base += min(0.15, 0.05 * verif.get("independent_corroboration", 0))
        if label == AIUsageLabel.CONFLICTING:
            base = min(base, 0.4)
        return round(min(0.95, base), 2)

    def _deployment_context(self, label, chosen) -> str:
        if not chosen:
            return "No AI usage established from public sources."
        c = chosen[0]["claim"]
        dfi = c.get("data_flow_implication")
        if dfi == "customer_controlled":
            return "Customer-controlled integration; vendor's own AI use not established."
        if dfi == "third_party":
            return "Third-party AI relationship; deployment in the consumed product unverified."
        if c.get("temporal_scope") == "planned":
            return "Announced as planned; not yet deployed."
        if label in _CONFIRMED:
            return "Vendor-stated AI capability in its service; human-oversight extent undetermined."
        return "AI referenced; deployment context undetermined from public sources."

    def _rationale(self, label, effective, sources_examined, live) -> str:
        if label == AIUsageLabel.INSUFFICIENT:
            return ("No live search and no analyst sources; insufficient public evidence."
                    if not live and sources_examined == 0 else
                    "Insufficient public evidence to establish AI usage.")
        if label == AIUsageLabel.NOT_ESTABLISHED:
            return f"Examined {sources_examined} source(s); no AI usage established (mentions/plans only)."
        if label == AIUsageLabel.MENTION_ONLY:
            return "AI is referenced but no deployed, functional capability is evidenced (mention only)."
        n = sum(1 for e in effective if e["label"] == label)
        return f"{n} verified claim(s) at this classification; strongest by precedence."
