"""Connector tests (external APIs are mocked - no paid calls)."""
from __future__ import annotations

import pytest

import connectors.brave_search as brave_mod
from connectors.base import ConnectorResult
from connectors.brave_search import BraveSearchConnector
from connectors.infrastructure import ShodanConnector
from connectors.public_web import PublicWebConnector
from connectors.registry import ConnectorRegistry
from evidence.schemas import RetrievalStatus


class _FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_brave_offline_without_key(tmp_db, monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    import config.settings as s
    s.reset_settings_cache()
    conn = BraveSearchConnector(s.get_settings(), tmp_db)
    assert conn.is_available() is False
    results = conn.run("test query", run_id=None)
    assert results == []  # never fabricates
    runs = tmp_db.query("SELECT * FROM connector_runs WHERE connector='brave_search'")
    assert runs and runs[0]["retrieval_status"] == "offline"  # recorded an honest run


def test_brave_normalizes_valid_response(tmp_db, monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "x" * 10)
    import config.settings as s
    s.reset_settings_cache()
    payload = {"web": {"results": [
        {"url": "https://example.com/ai", "title": "Example AI",
         "description": "We use generative AI", "profile": {"name": "Example"}}]}}
    monkeypatch.setattr(brave_mod, "request_with_retries",
                        lambda *a, **k: _FakeResp(200, payload))
    conn = BraveSearchConnector(s.get_settings(), tmp_db)
    assert conn.is_available()
    results = conn.run("example AI", vendor_id="V-1", run_id=None)
    assert len(results) == 1
    assert results[0].url == "https://example.com/ai"
    assert results[0].canonical_url  # computed
    assert results[0].retrieval_status == RetrievalStatus.OK


def test_brave_handles_http_error(tmp_db, monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "x" * 10)
    import config.settings as s
    s.reset_settings_cache()
    monkeypatch.setattr(brave_mod, "request_with_retries",
                        lambda *a, **k: _FakeResp(500, text="server error"))
    conn = BraveSearchConnector(s.get_settings(), tmp_db)
    results = conn.run("q", run_id=None)
    assert results[0].retrieval_status == RetrievalStatus.ERROR


def test_cache_prevents_duplicate_calls(tmp_db, monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "x" * 10)
    import config.settings as s
    s.reset_settings_cache()
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return _FakeResp(200, {"web": {"results": []}})

    monkeypatch.setattr(brave_mod, "request_with_retries", fake)
    conn = BraveSearchConnector(s.get_settings(), tmp_db)
    conn.run("same", run_id=None)
    conn.run("same", run_id=None)
    assert calls["n"] == 1  # second served from cache


def test_infrastructure_stub_never_fabricates(tmp_db, monkeypatch):
    monkeypatch.setenv("SHODAN_API_KEY", "x" * 10)
    import config.settings as s
    s.reset_settings_cache()
    conn = ShodanConnector(s.get_settings(), tmp_db)
    results = conn.run("example.com", run_id=None)
    assert results[0].retrieval_status == RetrievalStatus.UNAVAILABLE
    assert results[0].error_code == "stub_not_implemented"


def test_registry_offline_mode(tmp_db):
    reg = ConnectorRegistry(db=tmp_db)
    assert reg.execution_mode() == "offline"
    assert reg.get("public_web").is_available() is True
