"""Agent 5 - Evidence Extraction (claim-level, V2.1).

Extracts claims from retrieved sources and classifies each AI signal IN CONTEXT
via ``evidence.claim_classifier``. A keyword match is a discovery signal only; the
context (product claim vs policy/discussion/marketing/plan/history/partnership/job
advert/customer-controlled) decides the per-claim classification. Every claim is
linked to an exact supporting excerpt, with structured fields persisted.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, InvestigationContext
from agents.signals import analyze_text
from database.connection import utcnow
from evidence.claim_classifier import classify_claim
from evidence.schemas import (
    Authority,
    Claim,
    ClaimType,
    Directness,
    EvidenceRecord,
    EvidenceRelation,
)


class EvidenceExtractionAgent(BaseAgent):
    name = "evidence_extraction"
    depends_on = ["collection"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        processed: set = set(ctx.state.get("extracted_sources", []))
        all_sids: List[int] = ctx.state.get("sources", [])
        to_process = [sid for sid in all_sids if sid not in processed]

        claims_made = 0
        evidence_made = 0
        for sid in to_process:
            row = ctx.db.query_one("SELECT * FROM sources WHERE source_id=?", (sid,))
            if not row:
                continue
            text = row.get("extracted_text") or row.get("snippet")
            report = analyze_text(text)
            if not report.hits:
                processed.add(sid)
                continue

            is_sample = bool(row.get("is_sample"))

            # One AI claim per salient category present (generative/integration/ai).
            for category in ("generative", "integration", "ai"):
                hits = [h for h in report.hits if h.category == category]
                if not hits:
                    continue
                hit = hits[0]
                analysis = classify_claim(vendor_name=ctx.vendor["vendor_name"], source=dict(row), hit=hit)
                if not analysis:
                    continue
                claim_id = self._record_claim(ctx, hit, analysis)
                claims_made += 1
                self._record_evidence(ctx, sid, row, hit, analysis, claim_id, is_sample)
                evidence_made += 1

            # Non-AI context claims (data-flow / retention) feed the provider agent.
            for category in ("data_flow", "retention"):
                hits = [h for h in report.hits if h.category == category]
                if not hits:
                    continue
                hit = hits[0]
                claim_id = ctx.ledger.record_claim(Claim(
                    run_id=ctx.run_id, vendor_id=ctx.vendor_id,
                    claim_text=f"{ctx.vendor['vendor_name']} documentation references {category} ('{hit.phrase}').",
                    claim_type=ClaimType.OBSERVATION, subject=ctx.vendor["vendor_name"],
                    action=category, qualifiers=f"phrase='{hit.phrase}'", created_by_agent=self.name))
                ctx.ledger.record_evidence(EvidenceRecord(
                    run_id=ctx.run_id, vendor_id=ctx.vendor_id, claim_id=claim_id, source_id=sid,
                    url=row.get("url"), canonical_url=row.get("canonical_url"), title=row.get("title"),
                    source_owner=row.get("source_owner"), source_type=row.get("source_type"),
                    published_at=row.get("published_at"), retrieved_at=row.get("retrieved_at"),
                    excerpt=hit.excerpt, content_hash=row.get("content_hash"),
                    relation=EvidenceRelation.SUPPORTS, directness=Directness.INDIRECT,
                    authority=Authority.FIRST_PARTY if row.get("source_type") in
                    ("web_page", "social_post", "sec_filing") else Authority.UNKNOWN,
                    is_sample=is_sample, extraction_method="deterministic_signal_scan",
                    created_by_agent=self.name))

            if report.providers:
                ctx.state.setdefault("provider_candidates", {}).setdefault(str(sid), report.providers)
            if report.deployment_status:
                ctx.state.setdefault("deployment_status", []).extend(report.deployment_status)
            processed.add(sid)

        ctx.state["extracted_sources"] = list(processed)
        return {"claims_made": claims_made, "evidence_made": evidence_made,
                "sources_processed": len(to_process)}

    # ------------------------------------------------------------------ #
    def _record_claim(self, ctx: InvestigationContext, hit, analysis) -> int:
        claim_text = f"{ctx.vendor['vendor_name']}: {analysis.context_label} context for AI signal '{hit.phrase}'."
        return ctx.db.insert("claims", {
            "run_id": ctx.run_id, "vendor_id": ctx.vendor_id, "claim_text": claim_text,
            "claim_type": analysis.claim_type.value, "subject": analysis.subject,
            "action": analysis.action, "qualifiers": f"phrase='{hit.phrase}'",
            "supported": 0, "created_by_agent": self.name, "created_at": utcnow(),
            "classification": analysis.classification.value if analysis.classification else None,
            "context_label": analysis.context_label,
            "deployment_status": analysis.deployment_status,
            "temporal_scope": analysis.temporal_scope,
            "data_flow_implication": analysis.data_flow_implication,
            "confidence": analysis.confidence,
            "classification_rationale": analysis.rationale,
            "verification_status": "unverified", "review_status": "pending",
        })

    def _record_evidence(self, ctx, sid, row, hit, analysis, claim_id, is_sample) -> None:
        ctx.ledger.record_evidence(EvidenceRecord(
            run_id=ctx.run_id, vendor_id=ctx.vendor_id, claim_id=claim_id, source_id=sid,
            url=row.get("url"), canonical_url=row.get("canonical_url"), title=row.get("title"),
            source_owner=row.get("source_owner"), source_type=row.get("source_type"),
            published_at=row.get("published_at"), retrieved_at=row.get("retrieved_at"),
            excerpt=hit.excerpt, content_hash=row.get("content_hash"),
            relation=EvidenceRelation.SUPPORTS, directness=analysis.directness,
            authority=analysis.authority, is_sample=is_sample,
            extraction_method="context_aware_claim_classifier",
            confidence_rationale=analysis.rationale, created_by_agent=self.name))
