"""Persistent, queryable evidence ledger.

Writes sources, claims and evidence with provenance, deduplicates sources by
canonical URL + content hash, and enforces the rule that a claim without any
evidence reference is marked unsupported.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from database.connection import Database, get_db, utcnow
from evidence.provenance import canonicalize_url, content_hash
from evidence.schemas import Claim, EvidenceRecord, SourceRecord


class EvidenceLedger:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    # ------------------------------------------------------------------ #
    # Sources
    # ------------------------------------------------------------------ #
    def record_source(self, src: SourceRecord) -> int:
        canonical = src.canonical_url or canonicalize_url(src.url)
        chash = src.content_hash or content_hash(src.extracted_text or src.snippet)
        # Deduplicate within the same run on canonical url + hash.
        if canonical:
            existing = self.db.query_one(
                "SELECT source_id FROM sources WHERE run_id IS ? AND canonical_url = ? "
                "AND (content_hash IS ? OR ? IS NULL)",
                (src.run_id, canonical, chash, chash),
            )
            if existing:
                return existing["source_id"]
        return self.db.insert(
            "sources",
            {
                "run_id": src.run_id,
                "vendor_id": src.vendor_id,
                "connector_name": src.connector_name,
                "url": src.url,
                "canonical_url": canonical,
                "title": src.title,
                "source_type": src.source_type,
                "source_owner": src.source_owner,
                "published_at": src.published_at,
                "retrieved_at": src.retrieved_at or utcnow(),
                "snippet": src.snippet,
                "extracted_text": src.extracted_text,
                "http_status": src.http_status,
                "retrieval_status": src.retrieval_status.value,
                "content_hash": chash,
                "is_sample": int(src.is_sample),
                "error_code": src.error_code,
                "error_message": src.error_message,
                "metadata": json.dumps(src.metadata) if src.metadata else None,
            },
        )

    # ------------------------------------------------------------------ #
    # Claims + evidence
    # ------------------------------------------------------------------ #
    def record_claim(self, claim: Claim) -> int:
        return self.db.insert(
            "claims",
            {
                "run_id": claim.run_id,
                "vendor_id": claim.vendor_id,
                "claim_text": claim.claim_text,
                "claim_type": claim.claim_type.value,
                "subject": claim.subject,
                "action": claim.action,
                "product": claim.product,
                "qualifiers": claim.qualifiers,
                "supported": int(claim.supported),
                "created_by_agent": claim.created_by_agent,
                "created_at": utcnow(),
            },
        )

    def record_evidence(self, ev: EvidenceRecord) -> int:
        eid = self.db.insert(
            "evidence",
            {
                "run_id": ev.run_id,
                "vendor_id": ev.vendor_id,
                "claim_id": ev.claim_id,
                "source_id": ev.source_id,
                "url": ev.url,
                "canonical_url": ev.canonical_url or canonicalize_url(ev.url),
                "title": ev.title,
                "source_owner": ev.source_owner,
                "source_type": ev.source_type,
                "published_at": ev.published_at,
                "retrieved_at": ev.retrieved_at,
                "excerpt": ev.excerpt,
                "content_hash": ev.content_hash,
                "relation": ev.relation.value,
                "directness": ev.directness.value,
                "authority": ev.authority.value,
                "freshness": ev.freshness,
                "independence": ev.independence,
                "confidence_rationale": ev.confidence_rationale,
                "extraction_method": ev.extraction_method,
                "verification_status": ev.verification_status.value,
                "is_sample": int(ev.is_sample),
                "error_note": ev.error_note,
                "created_by_agent": ev.created_by_agent,
                "created_at": utcnow(),
            },
        )
        # A claim with at least one supporting evidence record is 'supported'.
        if ev.claim_id and ev.relation.value == "supports":
            self.db.execute("UPDATE claims SET supported=1 WHERE claim_id=?", (ev.claim_id,))
        return eid

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def claims_for_run(self, run_id: str) -> List[Dict]:
        return self.db.query("SELECT * FROM claims WHERE run_id=? ORDER BY claim_id", (run_id,))

    def evidence_for_claim(self, claim_id: int) -> List[Dict]:
        return self.db.query("SELECT * FROM evidence WHERE claim_id=? ORDER BY evidence_id", (claim_id,))

    def evidence_for_run(self, run_id: str) -> List[Dict]:
        return self.db.query("SELECT * FROM evidence WHERE run_id=? ORDER BY evidence_id", (run_id,))

    def sources_for_run(self, run_id: str) -> List[Dict]:
        return self.db.query("SELECT * FROM sources WHERE run_id=? ORDER BY source_id", (run_id,))

    def unsupported_claims(self, run_id: str) -> List[Dict]:
        return self.db.query(
            "SELECT * FROM claims WHERE run_id=? AND supported=0 ORDER BY claim_id", (run_id,)
        )
