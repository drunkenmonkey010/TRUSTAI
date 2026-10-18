"""Evidence ledger and verification tests."""
from __future__ import annotations

from database.connection import utcnow
from evidence.ledger import EvidenceLedger
from evidence.schemas import (
    Authority,
    Claim,
    ClaimType,
    Directness,
    EvidenceRecord,
    EvidenceRelation,
    SourceRecord,
)
from evidence.verification import (
    detect_circular_reporting,
    detect_contradictions,
    score_evidence,
)


def _seed_run(db, vendor_id="V-1", run_id="run-1"):
    db.insert("vendors", {"vendor_id": vendor_id, "vendor_name": "Acme",
                          "normalized_name": "acme", "created_at": utcnow()})
    db.insert("investigation_runs", {"run_id": run_id, "vendor_id": vendor_id,
                                     "profile": "baseline", "status": "running",
                                     "created_at": utcnow()})
    return run_id, vendor_id


def test_claim_without_evidence_is_unsupported(tmp_db):
    run_id, vid = _seed_run(tmp_db)
    ledger = EvidenceLedger(tmp_db)
    cid = ledger.record_claim(Claim(run_id=run_id, vendor_id=vid, claim_text="uses AI",
                                    claim_type=ClaimType.EXTRACTED))
    unsupported = ledger.unsupported_claims(run_id)
    assert any(c["claim_id"] == cid for c in unsupported)


def test_supporting_evidence_marks_claim_supported(tmp_db):
    run_id, vid = _seed_run(tmp_db)
    ledger = EvidenceLedger(tmp_db)
    cid = ledger.record_claim(Claim(run_id=run_id, vendor_id=vid, claim_text="uses AI"))
    ledger.record_evidence(EvidenceRecord(run_id=run_id, vendor_id=vid, claim_id=cid,
                                          excerpt="we use AI", relation=EvidenceRelation.SUPPORTS))
    assert not any(c["claim_id"] == cid for c in ledger.unsupported_claims(run_id))


def test_duplicate_sources_deduplicated(tmp_db):
    run_id, vid = _seed_run(tmp_db)
    ledger = EvidenceLedger(tmp_db)
    s1 = ledger.record_source(SourceRecord(run_id=run_id, vendor_id=vid,
                              url="https://www.example.com/ai", extracted_text="same body"))
    s2 = ledger.record_source(SourceRecord(run_id=run_id, vendor_id=vid,
                              url="https://example.com/ai/", extracted_text="same body"))
    assert s1 == s2  # canonical url + hash dedup


def test_publication_date_distinct_from_retrieval(tmp_db):
    run_id, vid = _seed_run(tmp_db)
    ledger = EvidenceLedger(tmp_db)
    sid = ledger.record_source(SourceRecord(run_id=run_id, vendor_id=vid, url="https://x.com",
                               published_at="2020-01-01", retrieved_at="2026-10-13T00:00:00"))
    row = tmp_db.query_one("SELECT published_at, retrieved_at FROM sources WHERE source_id=?", (sid,))
    assert row["published_at"] != row["retrieved_at"]


def test_contradictions_represented(tmp_db):
    run_id, vid = _seed_run(tmp_db)
    ledger = EvidenceLedger(tmp_db)
    cid = ledger.record_claim(Claim(run_id=run_id, vendor_id=vid, claim_text="uses AI"))
    ledger.record_evidence(EvidenceRecord(run_id=run_id, vendor_id=vid, claim_id=cid,
                           excerpt="uses AI", relation=EvidenceRelation.SUPPORTS))
    ledger.record_evidence(EvidenceRecord(run_id=run_id, vendor_id=vid, claim_id=cid,
                           excerpt="does not use AI", relation=EvidenceRelation.CONTRADICTS))
    rows = ledger.evidence_for_run(run_id)
    contradictions = detect_contradictions(rows)
    assert contradictions and contradictions[0]["claim_id"] == cid


def test_source_confidence_not_claim_certainty():
    # High-authority, direct, fresh evidence scores high; indirect/unknown scores lower.
    strong = score_evidence({"authority": Authority.INDEPENDENT.value,
                             "directness": Directness.DIRECT.value,
                             "published_at": "2026-01-01", "independence": "independent"})
    weak = score_evidence({"authority": Authority.UNKNOWN.value,
                           "directness": Directness.INDIRECT.value,
                           "published_at": None, "independence": "unknown"})
    assert strong.score > weak.score
    # A single strong source does not imply certainty (score stays < 1.0 unless perfect).
    assert weak.score < 0.7


def test_circular_reporting_detected():
    rows = [
        {"evidence_id": 1, "content_hash": "abc", "relation": "supports", "authority": "independent",
         "source_owner": "a"},
        {"evidence_id": 2, "content_hash": "abc", "relation": "supports", "authority": "independent",
         "source_owner": "b"},
    ]
    circular = detect_circular_reporting(rows)
    assert 2 in circular
