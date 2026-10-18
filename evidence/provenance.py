"""Provenance helpers: URL canonicalization and content hashing.

Deterministic so that the same source retrieved twice produces the same
canonical URL and hash, enabling deduplication across connectors.
"""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Tracking parameters stripped during canonicalization.
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "ref_src")


def canonicalize_url(url: str | None) -> str | None:
    """Return a stable canonical form of a URL (lowercased host, no tracking)."""
    if not url:
        return None
    url = url.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/") or "/"
    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(kept))
    return urlunparse((scheme, netloc, path, "", query, ""))


def content_hash(text: str | None) -> str | None:
    """SHA-256 of normalized text content, or None when there is nothing."""
    if text is None:
        return None
    normalized = " ".join(text.split())
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def file_hash(path) -> str:
    """SHA-256 of a file's bytes (used for benchmark integrity)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
