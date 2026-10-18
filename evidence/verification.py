"""Evidence quality scoring, contradiction and circular-citation detection.

Scoring is deterministic and explainable. High confidence is NOT awarded merely
because several pages repeat the same original press release - circular /
duplicate reporting is detected and down-weighted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from evidence.schemas import Authority, Directness

# Weights for the four evidence-quality facets (sum to 1.0).
_FACET_WEIGHTS = {"authority": 0.3, "directness": 0.3, "freshness": 0.2, "independence": 0.2}

_AUTHORITY_SCORE = {
    Authority.FIRST_PARTY.value: 0.9,
    Authority.INDEPENDENT.value: 1.0,
    Authority.AGGREGATOR.value: 0.4,
    Authority.UNKNOWN.value: 0.3,
}
_DIRECTNESS_SCORE = {Directness.DIRECT.value: 1.0, Directness.INDIRECT.value: 0.5}


@dataclass
class QualityScore:
    score: float
    rationale: str


def _freshness_score(published_at: Optional[str]) -> float:
    if not published_at:
        return 0.4  # unknown publication date
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%d-%m-%Y", "%Y"):
        try:
            dt = datetime.strptime(published_at[: len(fmt) + 6], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - dt).days
            if age_days < 0:
                return 0.6
            if age_days <= 365:
                return 1.0
            if age_days <= 365 * 2:
                return 0.8
            if age_days <= 365 * 4:
                return 0.6
            return 0.4
        except (ValueError, TypeError):
            continue
    return 0.4


def score_evidence(ev: Dict) -> QualityScore:
    """Return a 0..1 quality score for one evidence row (dict from DB)."""
    authority = _AUTHORITY_SCORE.get(ev.get("authority", "unknown"), 0.3)
    directness = _DIRECTNESS_SCORE.get(ev.get("directness", "indirect"), 0.5)
    freshness = _freshness_score(ev.get("published_at"))
    independence = 1.0 if (ev.get("independence") or "").lower().startswith("independent") else 0.5
    total = (
        authority * _FACET_WEIGHTS["authority"]
        + directness * _FACET_WEIGHTS["directness"]
        + freshness * _FACET_WEIGHTS["freshness"]
        + independence * _FACET_WEIGHTS["independence"]
    )
    rationale = (
        f"authority={ev.get('authority')} ({authority:.2f}), "
        f"directness={ev.get('directness')} ({directness:.2f}), "
        f"freshness={freshness:.2f}, independence={independence:.2f}"
    )
    return QualityScore(round(total, 3), rationale)


def detect_circular_reporting(evidence_rows: List[Dict]) -> List[int]:
    """Flag evidence IDs that share a content hash with earlier rows.

    Repeated identical content (same original source re-published) should not be
    counted as independent corroboration.
    """
    seen: Dict[str, int] = {}
    circular: List[int] = []
    for ev in evidence_rows:
        h = ev.get("content_hash")
        if not h:
            continue
        if h in seen:
            circular.append(ev["evidence_id"])
        else:
            seen[h] = ev["evidence_id"]
    return circular


def detect_contradictions(evidence_rows: List[Dict]) -> List[Dict]:
    """Return claim_ids that have both supporting and contradicting evidence."""
    by_claim: Dict[int, set] = {}
    for ev in evidence_rows:
        cid = ev.get("claim_id")
        if cid is None:
            continue
        by_claim.setdefault(cid, set()).add(ev.get("relation"))
    out = []
    for cid, relations in by_claim.items():
        if "supports" in relations and "contradicts" in relations:
            out.append({"claim_id": cid, "relations": sorted(relations)})
    return out


def independent_corroboration_count(evidence_rows: List[Dict]) -> int:
    """Count distinct independent (non-circular) supporting sources."""
    circular = set(detect_circular_reporting(evidence_rows))
    owners = set()
    for ev in evidence_rows:
        if ev.get("relation") != "supports":
            continue
        if ev["evidence_id"] in circular:
            continue
        if (ev.get("authority") == Authority.INDEPENDENT.value):
            owners.add(ev.get("source_owner") or ev.get("canonical_url"))
    return len(owners)
