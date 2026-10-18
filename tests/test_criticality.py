"""12-dimension criticality and auto-depth resolution tests."""
from __future__ import annotations

import json

from agents.criticality import _volume_scale
from agents.osint_strategy import PROFILE_BUDGET, resolve_profile
from orchestration.workflow import InvestigationWorkflow

TWELVE = {
    "business_function_centrality", "system_of_record_dependency", "failure_blast_radius",
    "time_criticality", "workaround_availability", "recoverability", "transaction_integrity",
    "data_consequence", "exit_substitutability", "regulatory_compliance",
    "financial_materiality", "concentration_dependency",
}


def test_resolve_profile_from_tier():
    assert resolve_profile("auto", "Critical") == "deep"
    assert resolve_profile("auto", "High") == "deep"
    assert resolve_profile("auto", "Medium") == "enhanced"
    assert resolve_profile("auto", "Low") == "baseline"
    # non-auto passes through unchanged (manual override)
    assert resolve_profile("baseline", "Critical") == "baseline"
    # unknown tier falls back to enhanced
    assert resolve_profile("auto", "") == "enhanced"


def test_volume_scale_handles_commas_and_words():
    assert _volume_scale("240,000 active accounts")[0] >= 2
    assert _volume_scale("19 million documents")[0] == 3
    assert _volume_scale("240 million transactions")[0] == 3
    assert _volume_scale("Not applicable") == (0, "unknown")
    # a stray comma must not crash
    assert _volume_scale("records, many")[1] in ("known", "partial", "unknown")


def test_twelve_dimensions_assessed(imported_db):
    wf = InvestigationWorkflow(db=imported_db)
    r = wf.investigate("V-002", profile="baseline")  # Fiserv
    out = imported_db.query_one(
        "SELECT output FROM agent_runs WHERE run_id=? AND agent_name='criticality' "
        "ORDER BY agent_run_id DESC LIMIT 1", (r["run_id"],))
    crit = json.loads(out["output"])
    assert set(crit["dimensions"].keys()) == TWELVE
    for d in crit["dimensions"].values():
        assert 0 <= d["score"] <= 3
        assert d["status"] in ("known", "partial", "unknown")
    # Fiserv (core banking, full customer master, 240M txns) -> Critical.
    assert crit["derived_tier"] == "Critical"


def test_auto_depth_sets_budget(imported_db):
    wf = InvestigationWorkflow(db=imported_db)
    r = wf.investigate("V-002", profile="auto")
    assert r["summary"]["resolved_profile"] == "deep"
    run = imported_db.query_one("SELECT query_budget, profile FROM investigation_runs WHERE run_id=?",
                                (r["run_id"],))
    assert run["profile"] == "deep"
    assert run["query_budget"] == PROFILE_BUDGET["deep"]
