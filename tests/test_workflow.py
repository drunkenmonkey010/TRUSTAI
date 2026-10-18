"""End-to-end workflow tests (offline, deterministic)."""
from __future__ import annotations

from orchestration.run_manager import RunManager
from orchestration.workflow import InvestigationWorkflow


def test_offline_example_vendor_confirms_ai(imported_db):
    wf = InvestigationWorkflow(db=imported_db)
    result = wf.investigate("V-000", profile="enhanced")  # fictional example w/ sample sources
    assert result["summary"]["ai_usage_label"] == "Confirmed generative AI use"
    assert result["summary"]["mode"] == "offline"


def test_offline_real_vendor_is_insufficient(imported_db):
    wf = InvestigationWorkflow(db=imported_db)
    result = wf.investigate("V-002", profile="baseline")
    # No live OSINT and no sample sources for real vendors -> honest insufficiency.
    assert result["summary"]["ai_usage_label"] == "Insufficient evidence"


def test_all_agents_run(imported_db):
    wf = InvestigationWorkflow(db=imported_db)
    result = wf.investigate("V-000", profile="enhanced")
    statuses = result["agent_statuses"]
    for agent in ("vendor_intake", "criticality", "osint_strategy", "adaptive_depth",
                  "ai_classification", "provider_dataflow", "risk_assessment",
                  "recommendations", "quality_assurance"):
        assert statuses.get(agent) == "completed"


def test_history_preserved_on_rerun(imported_db):
    wf = InvestigationWorkflow(db=imported_db)
    r1 = wf.investigate("V-002", profile="baseline")
    r2 = wf.investigate("V-002", profile="enhanced")
    assert r1["run_id"] != r2["run_id"]
    runs = RunManager(imported_db).runs_for_vendor("V-002")
    assert len(runs) >= 2  # old run not overwritten


def test_snapshot_creation_and_hash(imported_db):
    wf = InvestigationWorkflow(db=imported_db)
    r = wf.investigate("V-000", profile="baseline")
    rm = RunManager(imported_db)
    sid = rm.freeze_snapshot(r["run_id"])
    assert rm.verify_snapshot_hash(sid) is True
    snap = rm.get_snapshot(sid)
    assert snap["content_hash"] and snap["schema_version"] >= 1


def test_reproducible_risk(imported_db):
    wf = InvestigationWorkflow(db=imported_db)
    r1 = wf.investigate("V-002", profile="baseline")
    r2 = wf.investigate("V-002", profile="baseline")
    assert r1["summary"]["inherent_risk"] == r2["summary"]["inherent_risk"]
