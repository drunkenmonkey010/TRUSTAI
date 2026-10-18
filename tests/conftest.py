"""Shared pytest fixtures: isolated temp database and offline settings."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import config.settings as settings_mod
import database.connection as conn_mod
from database.connection import Database


@pytest.fixture
def tmp_db(tmp_path, monkeypatch) -> Database:
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("MERIDIAN_DB_PATH", str(db_file))
    # Ensure no live providers leak in from the developer environment.
    for var in ("BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY", "OPENAI_API_KEY",
                "OPENCORPORATES_API_KEY", "SECURITYTRAILS_API_KEY", "SHODAN_API_KEY",
                "SEC_CONTACT_EMAIL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "none")
    settings_mod.reset_settings_cache()
    conn_mod.reset_db_singleton()
    db = Database(db_file)
    # Point the singleton at this db too, so modules using get_db() share it.
    conn_mod._DB_SINGLETON = db
    yield db
    conn_mod.reset_db_singleton()
    settings_mod.reset_settings_cache()


@pytest.fixture
def sample_workbook() -> str:
    path = Path(settings_mod.PROJECT_ROOT) / "samples" / "Meridian_Vendor_Input.xlsx"
    return str(path)


@pytest.fixture
def imported_db(tmp_db, sample_workbook):
    from imports.workbook import import_file
    import_file(sample_workbook, db=tmp_db)
    return tmp_db


@pytest.fixture
def ai_run(imported_db):
    """An offline investigation of the example vendor (Confirmed generative AI),
    which triggers all V2.1 post-processing services. Returns (db, run_id)."""
    from orchestration.workflow import InvestigationWorkflow
    wf = InvestigationWorkflow(db=imported_db)
    r = wf.investigate("V-000", profile="enhanced")
    return imported_db, r["run_id"]
