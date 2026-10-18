"""OpenCorporates connector (optional corporate identity enrichment).

Docs: https://api.opencorporates.com/

Resolves candidate legal entities for a vendor name. Distinguishes an exact
name match from a probable match; ambiguous matches are flagged for analyst
review. Corporate registration is NEVER treated as evidence of AI usage.
"""
from __future__ import annotations

import difflib
from typing import Any, List, Optional

from connectors._http import request_with_retries
from connectors.base import BaseConnector, ConnectorResult
from evidence.schemas import RetrievalStatus

ENDPOINT = "https://api.opencorporates.com/v0.4/companies/search"


class OpenCorporatesConnector(BaseConnector):
    name = "opencorporates"
    requires_key = True

    def is_available(self) -> bool:
        return bool(self.settings.opencorporates_api_key.strip())

    def _run(
        self,
        query: str,
        vendor_id: Optional[str] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[ConnectorResult]:
        params = {"q": query, "api_token": self.settings.opencorporates_api_key.strip(), "per_page": 10}
        resp = request_with_retries(
            "GET",
            ENDPOINT,
            params=params,
            timeout=self.settings.http_timeout_seconds,
            max_retries=self.settings.http_max_retries,
        )
        if resp.status_code != 200:
            return [
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    http_status=resp.status_code,
                    retrieval_status=RetrievalStatus.ERROR,
                    error_code=str(resp.status_code),
                    error_message=resp.text[:300],
                )
            ]
        companies = (resp.json().get("results") or {}).get("companies") or []
        out: List[ConnectorResult] = []
        for entry in companies:
            c = entry.get("company", {})
            name = c.get("name", "")
            score = difflib.SequenceMatcher(None, query.lower(), name.lower()).ratio()
            match_kind = "exact" if score >= 0.97 else ("probable" if score >= 0.75 else "ambiguous")
            out.append(
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    url=c.get("opencorporates_url"),
                    title=name,
                    source_type="corporate_registry",
                    source_owner=c.get("jurisdiction_code"),
                    published_at=c.get("incorporation_date"),
                    retrieval_status=RetrievalStatus.OK,
                    http_status=200,
                    metadata={
                        "jurisdiction": c.get("jurisdiction_code"),
                        "company_number": c.get("company_number"),
                        "match_kind": match_kind,
                        "match_score": round(score, 3),
                        "current_status": c.get("current_status"),
                    },
                )
            )
        return out
