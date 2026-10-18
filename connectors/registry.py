"""Connector registry: instantiation, health checks and selection.

The registry exposes a clear live/offline execution indicator and lets the
investigation select connectors by the question being asked rather than firing
every connector at every vendor.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from config.settings import Settings, get_settings
from connectors.base import BaseConnector, HealthStatus
from connectors.config import CONNECTOR_SPECS, SPECS_BY_NAME
from database.connection import Database, get_db


class ConnectorRegistry:
    def __init__(self, settings: Optional[Settings] = None, db: Optional[Database] = None):
        self.settings = settings or get_settings()
        self.db = db or get_db()
        self._instances: Dict[str, BaseConnector] = {}

    # ------------------------------------------------------------------ #
    def _enabled(self, name: str) -> bool:
        return bool(self.db.get_setting(f"connector_enabled.{name}", True))

    def set_enabled(self, name: str, enabled: bool) -> None:
        self.db.set_setting(f"connector_enabled.{name}", bool(enabled))
        self.db.audit("connector", "set_enabled", subject=name, detail={"enabled": enabled})

    def get(self, name: str) -> Optional[BaseConnector]:
        if name not in SPECS_BY_NAME:
            return None
        if name not in self._instances:
            self._instances[name] = SPECS_BY_NAME[name].cls(self.settings, self.db)
        return self._instances[name]

    # ------------------------------------------------------------------ #
    def health(self) -> List[HealthStatus]:
        out: List[HealthStatus] = []
        for spec in CONNECTOR_SPECS:
            conn = self.get(spec.name)
            status = conn.health_check()
            if not self._enabled(spec.name):
                status.available = False
                status.detail = "disabled by configuration"
            out.append(status)
        return out

    def available_names(self, category: Optional[str] = None) -> List[str]:
        names = []
        for spec in CONNECTOR_SPECS:
            if category and spec.category != category:
                continue
            if not self._enabled(spec.name):
                continue
            conn = self.get(spec.name)
            if conn and conn.is_available():
                names.append(spec.name)
        return names

    def live_search_available(self) -> bool:
        return bool(self.available_names(category="search"))

    def execution_mode(self) -> str:
        """'live' when a live search provider is usable, else 'offline'."""
        return "live" if self.live_search_available() else "offline"

    def select_search_connector(self) -> Optional[BaseConnector]:
        """Pick the preferred live search connector (Brave before Tavily)."""
        for name in ("brave_search", "tavily_search"):
            if name in self.available_names(category="search"):
                return self.get(name)
        return None
