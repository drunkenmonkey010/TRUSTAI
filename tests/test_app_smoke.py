"""Smoke tests: modules import and Streamlit pages are syntactically valid."""
from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

PROJECT = pathlib.Path(__file__).resolve().parent.parent

CORE_MODULES = [
    "config.settings", "config.logging_config",
    "database.connection", "database.schema",
    "connectors.base", "connectors.registry", "connectors.config",
    "connectors.brave_search", "connectors.public_web", "connectors.sec_edgar",
    "connectors.tavily_search", "connectors.opencorporates", "connectors.infrastructure",
    "evidence.schemas", "evidence.ledger", "evidence.verification", "evidence.provenance",
    "risk.scoring", "risk.weights", "risk.explanations",
    "imports.workbook", "imports.normalization",
    "agents.base", "agents.vendor_intake", "agents.criticality", "agents.osint_strategy",
    "agents.collection", "agents.evidence_extraction", "agents.evidence_verification",
    "agents.ai_classification", "agents.provider_dataflow", "agents.adaptive_depth",
    "agents.risk_assessment", "agents.recommendations", "agents.quality_assurance",
    "orchestration.workflow", "orchestration.run_manager", "orchestration.adaptive_controller",
    "orchestration.scheduler",
    "benchmark.access_control", "benchmark.pdf_parser", "benchmark.evaluator", "benchmark.schemas",
    "reports.vendor_report", "reports.portfolio_report", "reports.supply_chain",
    "exports.export_manager",
    # V2.1 feature modules
    "evidence.claim_classifier", "questionnaires.engine", "remediation.manager",
    "monitoring.change_detector", "frameworks.crosswalk", "threat_modeling.engine",
    "contracts.analyzer", "evaluation.lab",
]


@pytest.mark.parametrize("module", CORE_MODULES)
def test_core_modules_import(module):
    importlib.import_module(module)


def test_streamlit_pages_parse():
    files = [PROJECT / "app.py"] + list((PROJECT / "pages").glob("*.py"))
    assert files
    for f in files:
        ast.parse(f.read_text(encoding="utf-8"), filename=str(f))


def test_twelve_agents_present():
    from orchestration.workflow import ALL_AGENT_NAMES
    assert len(ALL_AGENT_NAMES) == 12


def test_streamlit_app_runs_without_exception(tmp_db):
    """Execute the entry page via Streamlit's AppTest (catches runtime errors)."""
    try:
        from streamlit.testing.v1 import AppTest
    except Exception:  # pragma: no cover
        pytest.skip("streamlit.testing not available")
    at = AppTest.from_file(str(PROJECT / "app.py"), default_timeout=60).run()
    assert not at.exception
