"""Vendor identifier and name normalization + duplicate detection."""
from __future__ import annotations

import difflib
import re
from typing import Dict, List, Tuple

# Common legal/organizational suffixes stripped for MATCHING only (never from
# the stored display name, which is preserved verbatim).
_LEGAL_SUFFIXES = [
    "incorporated", "inc", "corporation", "corp", "company", "co", "limited",
    "ltd", "llc", "l.l.c", "llp", "lp", "plc", "gmbh", "ag", "sa", "s.a",
    "pty", "pte", "bv", "nv", "group", "holdings", "holding",
]
_SUFFIX_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r")\b\.?", re.IGNORECASE
)


def normalize_name(name: str | None) -> str:
    """Lowercase, strip punctuation and legal suffixes for comparison."""
    if not name:
        return ""
    n = name.lower()
    n = n.replace("&", " and ")
    n = _SUFFIX_RE.sub(" ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def normalize_vendor_id(vid: str | None) -> str:
    if not vid:
        return ""
    return str(vid).strip().upper()


def name_similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def detect_duplicates(
    records: List[Dict], threshold: float = 0.88
) -> List[Tuple[str, str, float, str]]:
    """Return (vendor_id_a, vendor_id_b, score, kind) for likely duplicates.

    ``kind`` is 'exact' (identical normalized name or id) or 'probable'.
    """
    dupes: List[Tuple[str, str, float, str]] = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            a, b = records[i], records[j]
            if a.get("vendor_id") and a.get("vendor_id") == b.get("vendor_id"):
                dupes.append((a["vendor_id"], b["vendor_id"], 1.0, "exact_id"))
                continue
            score = name_similarity(a.get("vendor_name", ""), b.get("vendor_name", ""))
            if score >= 0.999:
                dupes.append((a["vendor_id"], b["vendor_id"], score, "exact"))
            elif score >= threshold:
                dupes.append((a["vendor_id"], b["vendor_id"], round(score, 3), "probable"))
    return dupes
