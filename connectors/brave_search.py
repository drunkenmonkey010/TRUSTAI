"""Brave Search API connector (primary public-web search).

Docs: https://api-dashboard.search.brave.com/documentation

Request shape per Brave Web Search API:
  GET https://api.search.brave.com/res/v1/web/search
  headers: Accept: application/json, X-Subscription-Token: <key>
  params:  q, count, country, search_lang, ...
Response: JSON with ``web.results`` list, each having title, url, description,
age/page_age, and profile metadata.
"""
from __future__ import annotations

from typing import Any, List, Optional

from connectors._http import request_with_retries
from connectors.base import BaseConnector, ConnectorResult
from evidence.schemas import RetrievalStatus

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchConnector(BaseConnector):
    name = "brave_search"
    requires_key = True

    def is_available(self) -> bool:
        return bool(self.settings.brave_search_api_key.strip())

    def _run(
        self,
        query: str,
        vendor_id: Optional[str] = None,
        run_id: Optional[str] = None,
        count: int = 8,
        **kwargs: Any,
    ) -> List[ConnectorResult]:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.settings.brave_search_api_key.strip(),
        }
        params = {"q": query, "count": min(int(count), 20)}
        resp = request_with_retries(
            "GET",
            ENDPOINT,
            headers=headers,
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
        payload = resp.json()
        web = (payload.get("web") or {}).get("results") or []
        out: List[ConnectorResult] = []
        for item in web:
            out.append(
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    url=item.get("url"),
                    title=item.get("title"),
                    snippet=item.get("description"),
                    published_at=item.get("page_age") or item.get("age"),
                    source_type="web_search_result",
                    source_owner=(item.get("profile") or {}).get("name"),
                    http_status=200,
                    retrieval_status=RetrievalStatus.OK,
                    metadata={"family": item.get("family_friendly"), "language": item.get("language")},
                )
            )
        if not out:
            out.append(
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    http_status=200,
                    retrieval_status=RetrievalStatus.OK,
                    snippet=None,
                    metadata={"note": "no results"},
                )
            )
        return out
