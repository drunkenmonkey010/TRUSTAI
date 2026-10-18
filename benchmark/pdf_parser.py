"""Benchmark PDF parser.

Generic, structure-tolerant extraction of per-vendor benchmark findings from the
held-out PDF. It reads the file ONLY through the access controller (so it cannot
run while locked) and does not hardcode any benchmark conclusions - it segments
by vendor anchors (IDs and names) and extracts verdict/provider/risk signals.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from agents.signals import PROVIDER_NAMES
from benchmark.access_control import BenchmarkAccessController
from benchmark.schemas import BenchmarkRecord
from database.connection import Database, get_db, utcnow
from evidence.provenance import file_hash

_RISK_WORDS = ["critical", "high", "medium", "moderate", "low", "none identified", "none"]


@dataclass
class _Anchor:
    pos: int
    vendor_id: str


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_full_text(path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return _normalize("\n".join((p.extract_text() or "") for p in reader.pages))


def _verdict(segment: str) -> Optional[str]:
    """Map the segment's AI-usage language to yes | no | inconclusive.

    Targets the benchmark's explicit verdict phrasing (e.g. "AI usage detected:
    YES", "AI Usage Detected = Inconclusive") rather than stray words like
    "Confirmed" that appear in unrelated criticality matrices.
    """
    low = segment.lower()
    # 1) Explicit verdict statement (strongest signal).
    m = re.search(
        r"ai usage(?:\s+detected|\s+assessment)?\s*[:=]?\s*[-–—]?\s*(yes|no|inconclusive)", low
    )
    if m:
        return m.group(1)
    # 2) Explicit negative/positive phrasing.
    if "no evidence of ai" in low or re.search(r"\bno ai use\b", low):
        return "no"
    if re.search(r"ai (?:is )?(?:confirmed|deployed|in use)", low) or "confirmed ai use" in low:
        return "yes"
    # 3) Conservative fallback.
    if "inconclusive" in low:
        return "inconclusive"
    return None


def _risk(segment: str) -> Optional[str]:
    low = segment.lower()
    m = re.search(r"(ai security risk|risk classification|risk rating)[^a-z]{0,10}([a-z ]+)", low)
    if m:
        for w in _RISK_WORDS:
            if m.group(2).strip().startswith(w):
                return w.title()
    return None


def _providers(segment: str) -> List[str]:
    low = segment.lower()
    found = []
    for p in PROVIDER_NAMES:
        if re.search(r"\b" + re.escape(p) + r"\b", low):
            found.append(p)
    return sorted(set(found))


def parse_benchmark(
    db: Optional[Database] = None,
    vendor_directory: Optional[List[Dict[str, str]]] = None,
) -> List[BenchmarkRecord]:
    """Parse the benchmark into per-vendor records. Requires unlocked access."""
    db = db or get_db()
    controller = BenchmarkAccessController(db)
    path = controller.benchmark_path()  # raises BenchmarkLockedError if locked
    fhash = file_hash(path)
    text = _extract_full_text(path)

    directory = vendor_directory or db.query("SELECT vendor_id, vendor_name FROM vendors WHERE is_example=0")

    # Build ALL anchors (every id/name occurrence) so verdicts can be assigned to
    # the nearest preceding vendor anchor - robust to an interleaved document.
    all_anchors: List[_Anchor] = []
    first: Dict[str, int] = {}
    for v in directory:
        vid = v["vendor_id"]
        for m in re.finditer(re.escape(vid), text):
            all_anchors.append(_Anchor(m.start(), vid))
            first.setdefault(vid, m.start())
        name = v.get("vendor_name", "")
        token = re.sub(r"[^A-Za-z ].*$", "", name).strip()
        # Accept tokens >=4 chars, or short all-caps acronyms (e.g. "BNY").
        if token and (len(token) >= 4 or (len(token) >= 3 and token.isupper())):
            flags = 0 if token.isupper() else re.IGNORECASE
            for m in re.finditer(r"\b" + re.escape(token) + r"\b", text, flags=flags):
                all_anchors.append(_Anchor(m.start(), vid))
                first.setdefault(vid, m.start())
    all_anchors.sort(key=lambda a: a.pos)

    def owner_at(pos: int) -> Optional[str]:
        owner = None
        for a in all_anchors:
            if a.pos <= pos:
                owner = a.vendor_id
            else:
                break
        return owner

    # Assign explicit "AI usage detected: X" verdicts to the nearest owner.
    verdict_by_vendor: Dict[str, str] = {}
    for m in re.finditer(
        r"ai usage(?:\s+detected|\s+assessment)?\s*[:=]?\s*[-–—]?\s*(yes|no|inconclusive)",
        text, flags=re.IGNORECASE,
    ):
        owner = owner_at(m.start())
        if owner and owner not in verdict_by_vendor:
            verdict_by_vendor[owner] = m.group(1).lower()

    # Contiguous segments (earliest anchor per vendor) for providers/risk/excerpt.
    ordered = sorted(first.items(), key=lambda kv: kv[1])
    records: List[BenchmarkRecord] = []
    for i, (vid, start) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(text)
        segment = text[start:end]
        rec = BenchmarkRecord(
            vendor_id=vid,
            source_file=path.name,
            ai_usage_label=verdict_by_vendor.get(vid) or _verdict(segment),
            named_providers=_providers(segment),
            risk_classification=_risk(segment),
            raw_excerpt=segment[:1500],
        )
        records.append(rec)
        db.insert("benchmark_records", {
            "vendor_id": vid, "source_file": path.name, "file_hash": fhash,
            "loaded_at": utcnow(), "ai_usage_label": rec.ai_usage_label,
            "named_providers": ", ".join(rec.named_providers), "risk_classification": rec.risk_classification,
            "raw_excerpt": rec.raw_excerpt,
            "structured": rec.model_dump(),
        })
    db.audit("benchmark", "parse", detail={"records": len(records), "file_hash": fhash})
    return records
