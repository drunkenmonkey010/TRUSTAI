"""Optional infrastructure-intelligence connectors: SecurityTrails, Censys, Shodan.

Docs:
  https://docs.securitytrails.com/docs/overview
  https://docs.censys.com/
  https://developer.shodan.io/api

These are provided as clearly-labeled INTEGRATION STUBS. Their live API shapes
are not validated in this build, so rather than fabricate infrastructure data
they report an explicit ``unavailable`` status with a note. A stub is never
presented as a working live connector.

Hard guardrails embedded in the design:
  * Infrastructure association is NOT ownership, deployment or data processing.
  * A domain resolving to a cloud/AI provider is NOT evidence the vendor uses AI
    or sends customer data there.
  * No intrusive scanning, exploitation or auth bypass is performed.
"""
from __future__ import annotations

from typing import Any, List, Optional

from connectors.base import BaseConnector, ConnectorResult
from evidence.schemas import RetrievalStatus


class _InfrastructureStub(BaseConnector):
    requires_key = True
    #: human label for the UI
    display_label = "infrastructure"

    def is_available(self) -> bool:
        # Key presence gates availability, but _run still returns an explicit
        # stub marker instead of fabricated infrastructure records.
        return self._has_key()

    def _has_key(self) -> bool:  # pragma: no cover - overridden
        return False

    def _run(
        self,
        query: str,
        vendor_id: Optional[str] = None,
        run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[ConnectorResult]:
        return [
            self._result(
                query=query,
                vendor_id=vendor_id,
                source_type=self.name,
                retrieval_status=RetrievalStatus.UNAVAILABLE,
                error_code="stub_not_implemented",
                error_message=(
                    f"{self.name} is an integration stub in this build; live API "
                    "calls are not implemented. Infrastructure association would not "
                    "by itself establish AI usage or customer-data flow."
                ),
                metadata={"stub": True, "guardrail": "association_is_not_ownership"},
            )
        ]


class SecurityTrailsConnector(_InfrastructureStub):
    name = "securitytrails"

    def _has_key(self) -> bool:
        return bool(self.settings.securitytrails_api_key.strip())


class CensysConnector(_InfrastructureStub):
    name = "censys"

    def _has_key(self) -> bool:
        return bool(self.settings.censys_api_id.strip() and self.settings.censys_api_secret.strip())


class ShodanConnector(_InfrastructureStub):
    name = "shodan"

    def _has_key(self) -> bool:
        return bool(self.settings.shodan_api_key.strip())
