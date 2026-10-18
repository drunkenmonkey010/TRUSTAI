"""Shared HTTP request helper with timeouts, bounded retries and backoff."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx

from config.logging_config import get_logger

log = get_logger("http")


class RateLimitedError(Exception):
    pass


def request_with_retries(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float = 20.0,
    max_retries: int = 3,
    backoff_base: float = 0.75,
) -> httpx.Response:
    """Perform an HTTP request, retrying transient errors with exponential backoff.

    Raises on exhaustion; the caller is expected to catch and record the error.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.request(
                    method, url, headers=headers, params=params, json=json_body
                )
            if resp.status_code == 429:
                raise RateLimitedError(f"rate limited: {url}")
            if 500 <= resp.status_code < 600:
                raise httpx.HTTPStatusError(
                    f"server error {resp.status_code}", request=resp.request, response=resp
                )
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError, RateLimitedError) as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            sleep_for = backoff_base * (2 ** attempt)
            log.info("http retry attempt=%s sleep=%.2fs", attempt + 1, sleep_for)
            time.sleep(sleep_for)
    assert last_exc is not None
    raise last_exc
