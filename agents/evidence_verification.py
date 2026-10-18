"""Agent 6 - Evidence Verification.

Scores evidence quality, detects circular/duplicate reporting and
contradictions, and separates first-party statements from independent
corroboration. Multiple sites repeating one press release do NOT inflate
confidence.
"""
from __future__ import annotations

from typing import Any, Dict

from agents.base import BaseAgent, InvestigationContext
from evidence.schemas import VerificationStatus
from evidence.verification import (
    detect_circular_reporting,
    detect_contradictions,
    independent_corroboration_count,
    score_evidence,
)


class EvidenceVerificationAgent(BaseAgent):
    name = "evidence_verification"
    depends_on = ["evidence_extraction"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        rows = ctx.ledger.evidence_for_run(ctx.run_id)
        if not rows:
            summary = {"evidence_count": 0, "mean_quality": 0.0, "contradictions": 0,
                       "circular": 0, "independent_corroboration": 0}
            ctx.state["verification"] = summary
            return summary

        circular = set(detect_circular_reporting(rows))
        contradictions = detect_contradictions(rows)
        qualities = []

        for ev in rows:
            q = score_evidence(ev)
            qualities.append(q.score)
            status = VerificationStatus.VERIFIED
            independence = "independent" if ev.get("authority") == "independent" else "first_party_or_unknown"
            if ev["evidence_id"] in circular:
                status = VerificationStatus.CIRCULAR
                independence = "circular/duplicate"
            ctx.db.execute(
                "UPDATE evidence SET verification_status=?, independence=?, freshness=?, "
                "confidence_rationale=COALESCE(confidence_rationale,'') || ? WHERE evidence_id=?",
                (status.value, independence, f"quality={q.score}",
                 f" | {q.rationale}", ev["evidence_id"]),
            )

        mean_quality = round(sum(qualities) / len(qualities), 3)
        indep = independent_corroboration_count(rows)
        summary = {
            "evidence_count": len(rows),
            "mean_quality": mean_quality,
            "contradictions": len(contradictions),
            "contradiction_claims": contradictions,
            "circular": len(circular),
            "independent_corroboration": indep,
        }
        ctx.state["verification"] = summary
        return summary
