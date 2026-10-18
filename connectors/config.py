"""Connector catalogue and per-connector enable/disable configuration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Type

from connectors.base import BaseConnector
from connectors.brave_search import BraveSearchConnector
from connectors.infrastructure import (
    CensysConnector,
    SecurityTrailsConnector,
    ShodanConnector,
)
from connectors.opencorporates import OpenCorporatesConnector
from connectors.public_web import PublicWebConnector
from connectors.sec_edgar import SecEdgarConnector
from connectors.tavily_search import TavilySearchConnector


@dataclass(frozen=True)
class ConnectorSpec:
    name: str
    cls: Type[BaseConnector]
    category: str  # search | retrieval | identity | filing | infrastructure
    required_for_core: bool
    description: str


# Priority order matters: search first, then retrieval, identity, filing, infra.
CONNECTOR_SPECS: List[ConnectorSpec] = [
    ConnectorSpec("brave_search", BraveSearchConnector, "search", False,
                  "Primary public-web search (Brave Search API)."),
    ConnectorSpec("tavily_search", TavilySearchConnector, "search", False,
                  "Optional alternative/supplementary search (Tavily)."),
    ConnectorSpec("public_web", PublicWebConnector, "retrieval", True,
                  "Direct retrieval of explicitly supplied public URLs."),
    ConnectorSpec("sec_edgar", SecEdgarConnector, "filing", False,
                  "SEC EDGAR filings for listed vendors/parents (contact email required)."),
    ConnectorSpec("opencorporates", OpenCorporatesConnector, "identity", False,
                  "Optional legal-entity corroboration (OpenCorporates)."),
    ConnectorSpec("securitytrails", SecurityTrailsConnector, "infrastructure", False,
                  "Optional DNS/domain intelligence (integration stub)."),
    ConnectorSpec("censys", CensysConnector, "infrastructure", False,
                  "Optional internet-facing infrastructure (integration stub)."),
    ConnectorSpec("shodan", ShodanConnector, "infrastructure", False,
                  "Optional exposed-service intelligence (integration stub)."),
]

SPECS_BY_NAME: Dict[str, ConnectorSpec] = {s.name: s for s in CONNECTOR_SPECS}

#: default enablement if no DB override is present
DEFAULT_ENABLED = {s.name: True for s in CONNECTOR_SPECS}
