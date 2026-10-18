"""Common connector interface and normalized result schema.

Every connector normalizes its output into :class:`ConnectorResult`. Connectors
never fabricate results: when a provider is unavailable or fails they return an
empty list and record an honest ``retrieval_status`` on a connector run.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from config.logging_config import get_logger
from config.settings import Settings, get_settings
from database.connection import Database, get_db, utcnow
from evidence.provenance import canonicalize_url, content_hash
from evidence.schemas import RetrievalStatus

log = get_logger("connector")


class ConnectorResult(BaseModel):
    """Normalized search or retrieval result shared by all connectors."""

    connector_name: str
    query: Optional[str] = None
    vendor_id: Optional[str] = None
    retrieved_at: str
    url: Optional[str] = None
    canonical_url: Optional[str] = None
    title: Optional[str] = None
    published_at: Optional[str] = None
    source_type: Optional[str] = None
    source_owner: Optional[str] = None
    snippet: Optional[str] = None
    extracted_text: Optional[str] = None
    http_status: Optional[int] = None
    retrieval_status: RetrievalStatus = RetrievalStatus.OK
    content_hash: Optional[str] = None
    is_sample: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = {}


@dataclass
class HealthStatus:
    name: str
    available: bool
    configured: bool
    detail: str
    requires_key: bool = True


@dataclass
class _RateLimiter:
    per_second: float
    _last: float = field(default=0.0)

    def wait(self) -> None:
        if self.per_second <= 0:
            return
        min_interval = 1.0 / self.per_second
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last = time.monotonic()


class BaseConnector(ABC):
    """Abstract connector. Subclasses implement :meth:`_run`."""

    #: short machine name, e.g. "brave_search"
    name: str = "base"
    #: whether an API key is required to be considered available
    requires_key: bool = True

    def __init__(self, settings: Optional[Settings] = None, db: Optional[Database] = None):
        self.settings = settings or get_settings()
        self.db = db or get_db()
        self._limiter = _RateLimiter(self.settings.connector_rate_limit_per_sec)
        self._cache: Dict[str, List[ConnectorResult]] = {}

    # ------------------------------------------------------------------ #
    # Capability surface
    # ------------------------------------------------------------------ #
    @abstractmethod
    def is_available(self) -> bool:
        """True when the connector can make live calls (keys present, etc.)."""

    def health_check(self) -> HealthStatus:
        avail = self.is_available()
        return HealthStatus(
            name=self.name,
            available=avail,
            configured=avail,
            detail="ready" if avail else "not configured / offline",
            requires_key=self.requires_key,
        )

    # ------------------------------------------------------------------ #
    # Public entry point with caching, rate limiting and run recording.
    # ------------------------------------------------------------------ #
    def run(
        self,
        query: str,
        vendor_id: Optional[str] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[ConnectorResult]:
        cache_key = f"{query}|{kwargs}"
        if cache_key in self._cache:
            log.info("connector=%s cache_hit query_len=%s", self.name, len(query))
            return self._cache[cache_key]

        requested_at = utcnow()
        start = time.monotonic()
        http_status: Optional[int] = None
        status = RetrievalStatus.OK
        err_code = err_msg = None
        results: List[ConnectorResult] = []

        if not self.is_available():
            status = RetrievalStatus.OFFLINE
            err_msg = "connector unavailable (no credentials or disabled)"
        else:
            try:
                self._limiter.wait()
                results = self._run(query, vendor_id=vendor_id, run_id=run_id, **kwargs)
                for r in results:
                    if r.http_status and http_status is None:
                        http_status = r.http_status
            except Exception as exc:  # pragma: no cover - network paths
                status = RetrievalStatus.ERROR
                err_code = type(exc).__name__
                err_msg = str(exc)[:500]
                log.warning("connector=%s error=%s", self.name, err_code)

        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            self.db.insert(
                "connector_runs",
                {
                    "run_id": run_id,
                    "connector": self.name,
                    "query": query,
                    "requested_at": requested_at,
                    "http_status": http_status,
                    "retrieval_status": status.value if results or status != RetrievalStatus.OK else RetrievalStatus.OK.value,
                    "result_count": len(results),
                    "error_code": err_code,
                    "error_message": err_msg,
                    "latency_ms": latency_ms,
                },
            )
        except Exception:  # pragma: no cover - DB best effort
            pass

        self._cache[cache_key] = results
        return results

    # ------------------------------------------------------------------ #
    @abstractmethod
    def _run(
        self,
        query: str,
        vendor_id: Optional[str] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[ConnectorResult]:
        """Perform the actual provider call. Only invoked when available."""

    # ------------------------------------------------------------------ #
    # Helpers for subclasses
    # ------------------------------------------------------------------ #
    def _result(self, **kwargs: Any) -> ConnectorResult:
        kwargs.setdefault("connector_name", self.name)
        kwargs.setdefault("retrieved_at", utcnow())
        url = kwargs.get("url")
        if url and not kwargs.get("canonical_url"):
            kwargs["canonical_url"] = canonicalize_url(url)
        text = kwargs.get("extracted_text") or kwargs.get("snippet")
        if text and not kwargs.get("content_hash"):
            kwargs["content_hash"] = content_hash(text)
        return ConnectorResult(**kwargs)
