"""Direct public-source retrieval via HTTPX + BeautifulSoup.

Respects robots.txt (when enabled), uses a descriptive User-Agent, applies
timeouts, and treats retrieved page content as untrusted DATA - never as
instructions for the agents. It does not bypass authentication, paywalls or
CAPTCHAs; such pages are recorded as inaccessible.
"""
from __future__ import annotations

import urllib.robotparser
from typing import Any, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from connectors._http import request_with_retries
from connectors.base import BaseConnector, ConnectorResult
from evidence.schemas import RetrievalStatus

# Markers that strongly suggest an access wall rather than real content.
_BLOCK_MARKERS = ("captcha", "are you a robot", "access denied", "enable javascript to")


class PublicWebConnector(BaseConnector):
    """Fetch and extract readable text from a specific public URL.

    ``query`` is interpreted as the URL to fetch.
    """

    name = "public_web"
    requires_key = False

    def is_available(self) -> bool:
        # Always available - it only fetches explicitly supplied public URLs.
        return True

    # ------------------------------------------------------------------ #
    def _robots_allows(self, url: str) -> bool:
        if not self.settings.respect_robots_txt:
            return True
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = urllib.robotparser.RobotFileParser()
            resp = request_with_retries(
                "GET", robots_url, timeout=self.settings.http_timeout_seconds, max_retries=1
            )
            if resp.status_code >= 400:
                return True  # no robots => allowed
            rp.parse(resp.text.splitlines())
            return rp.can_fetch(self.settings.public_web_user_agent, url)
        except Exception:
            return True  # fail open on robots retrieval, but still polite

    def _run(
        self,
        query: str,
        vendor_id: Optional[str] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[ConnectorResult]:
        url = query.strip()
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url

        if not self._robots_allows(url):
            return [
                self._result(
                    query=query,
                    vendor_id=vendor_id,
                    url=url,
                    retrieval_status=RetrievalStatus.INACCESSIBLE,
                    error_code="robots_disallow",
                    error_message="robots.txt disallows retrieval",
                )
            ]

        headers = {"User-Agent": self.settings.public_web_user_agent}
        resp = request_with_retries(
            "GET",
            url,
            headers=headers,
            timeout=self.settings.http_timeout_seconds,
            max_retries=self.settings.http_max_retries,
        )

        status = RetrievalStatus.OK
        if resp.status_code in (401, 402, 403):
            status = RetrievalStatus.INACCESSIBLE
        elif resp.status_code >= 400:
            status = RetrievalStatus.ERROR

        title, text, published = self._extract(resp.text if resp.status_code < 400 else "")
        if status == RetrievalStatus.OK and text:
            low = text.lower()
            if any(m in low for m in _BLOCK_MARKERS) and len(text) < 600:
                status = RetrievalStatus.INACCESSIBLE

        owner = urlparse(url).netloc.lower().lstrip("www.")
        return [
            self._result(
                query=query,
                vendor_id=vendor_id,
                url=url,
                title=title,
                extracted_text=text or None,
                published_at=published,
                source_type="web_page",
                source_owner=owner,
                http_status=resp.status_code,
                retrieval_status=status,
                error_code=None if status == RetrievalStatus.OK else str(resp.status_code),
            )
        ]

    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract(html: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not html:
            return None, None, None
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else None
        published = None
        meta = soup.find("meta", attrs={"property": "article:published_time"}) or soup.find(
            "meta", attrs={"name": "date"}
        )
        if meta and meta.get("content"):
            published = meta["content"]
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = " ".join(main.get_text(" ").split())
        return title, text[:20000], published
