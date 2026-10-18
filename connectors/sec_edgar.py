"""SEC EDGAR connector (optional, for publicly listed vendors / parents).

Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

SEC fair-access policy requires a descriptive User-Agent containing contact
information. No API key is used. The connector resolves a company name to a CIK
via the public company tickers file, then lists recent filings. It fails
gracefully (empty) when no plausible company is found - not every vendor is a
reporting company.
"""
from __future__ import annotations

import difflib
from typing import Any, List, Optional

from connectors._http import request_with_retries
from connectors.base import BaseConnector, ConnectorResult
from evidence.schemas import RetrievalStatus

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


class SecEdgarConnector(BaseConnector):
    name = "sec_edgar"
    requires_key = False

    _tickers_cache: Optional[list] = None

    def is_available(self) -> bool:
        # Fair-access requires a contact; treat a contact email as the gate.
        return bool(self.settings.sec_contact_email.strip())

    def _headers(self) -> dict:
        ua = self.settings.sec_user_agent
        contact = self.settings.sec_contact_email
        return {"User-Agent": f"{ua} ({contact})".strip(), "Accept": "application/json"}

    def _load_tickers(self) -> list:
        if self._tickers_cache is not None:
            return self._tickers_cache
        resp = request_with_retries(
            "GET",
            TICKERS_URL,
            headers=self._headers(),
            timeout=self.settings.http_timeout_seconds,
            max_retries=self.settings.http_max_retries,
        )
        data = resp.json()
        # data is a dict keyed by index -> {cik_str, ticker, title}
        self._tickers_cache = list(data.values()) if isinstance(data, dict) else []
        return self._tickers_cache

    def _resolve_cik(self, name: str) -> Optional[tuple[int, str, float]]:
        companies = self._load_tickers()
        names = [c.get("title", "") for c in companies]
        target = name.lower().strip()
        best = None
        best_score = 0.0
        for c, title in zip(companies, names):
            score = difflib.SequenceMatcher(None, target, title.lower()).ratio()
            # boost when target is a token subset of the title
            if target and target.split()[0] in title.lower():
                score += 0.1
            if score > best_score:
                best_score = score
                best = c
        if best and best_score >= 0.6:
            return int(best["cik_str"]), best.get("title", ""), round(best_score, 3)
        return None

    def _run(
        self,
        query: str,
        vendor_id: Optional[str] = None,
        run_id: Optional[str] = None,
        max_filings: int = 5,
        **kwargs: Any,
    ) -> List[ConnectorResult]:
        resolved = self._resolve_cik(query)
        if not resolved:
            return [
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    retrieval_status=RetrievalStatus.UNAVAILABLE,
                    source_type="sec_edgar",
                    error_code="no_match",
                    error_message=f"No SEC reporting company confidently matched '{query}'",
                )
            ]
        cik, title, score = resolved
        resp = request_with_retries(
            "GET",
            SUBMISSIONS_URL.format(cik=cik),
            headers=self._headers(),
            timeout=self.settings.http_timeout_seconds,
            max_retries=self.settings.http_max_retries,
        )
        data = resp.json()
        recent = (data.get("filings") or {}).get("recent") or {}
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accession = recent.get("accessionNumber", [])
        primary_doc = recent.get("primaryDocument", [])
        out: List[ConnectorResult] = []
        for i in range(min(max_filings, len(forms))):
            acc = accession[i].replace("-", "") if i < len(accession) else ""
            doc = primary_doc[i] if i < len(primary_doc) else ""
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}" if acc else None
            out.append(
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    url=url,
                    title=f"{title} - {forms[i]}",
                    published_at=dates[i] if i < len(dates) else None,
                    source_type="sec_filing",
                    source_owner=title,
                    http_status=200,
                    retrieval_status=RetrievalStatus.OK,
                    metadata={"cik": cik, "form": forms[i], "match_score": score},
                )
            )
        if not out:
            out.append(
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    title=title,
                    source_type="sec_edgar",
                    retrieval_status=RetrievalStatus.OK,
                    metadata={"cik": cik, "match_score": score, "note": "no recent filings"},
                )
            )
        return out
