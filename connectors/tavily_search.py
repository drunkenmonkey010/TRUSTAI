"""Tavily Search API connector (optional alternative/supplementary search).

Docs: https://help.tavily.com/articles/4840311948-what-is-the-tavily-search-api

  POST https://api.tavily.com/search
  json: {"api_key": <key>, "query": ..., "max_results": N}
Response: {"results": [{"title","url","content","published_date","score"}], ...}
"""
from __future__ import annotations

from typing import Any, List, Optional

from connectors._http import request_with_retries
from connectors.base import BaseConnector, ConnectorResult
from evidence.schemas import RetrievalStatus

ENDPOINT = "https://api.tavily.com/search"


class TavilySearchConnector(BaseConnector):
    name = "tavily_search"
    requires_key = True

    def is_available(self) -> bool:
        return bool(self.settings.tavily_api_key.strip())

    def _run(
        self,
        query: str,
        vendor_id: Optional[str] = None,
        run_id: Optional[str] = None,
        max_results: int = 8,
        **kwargs: Any,
    ) -> List[ConnectorResult]:
        body = {
            "api_key": self.settings.tavily_api_key.strip(),
            "query": query,
            "max_results": min(int(max_results), 20),
            "search_depth": "basic",
        }
        resp = request_with_retries(
            "POST",
            ENDPOINT,
            json_body=body,
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
        out: List[ConnectorResult] = []
        for item in payload.get("results", []):
            out.append(
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    url=item.get("url"),
                    title=item.get("title"),
                    snippet=item.get("content"),
                    published_at=item.get("published_date"),
                    source_type="web_search_result",
                    http_status=200,
                    retrieval_status=RetrievalStatus.OK,
                    metadata={"score": item.get("score")},
                )
            )
        return out
