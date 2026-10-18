"""Export tests."""
from __future__ import annotations

import io
import json

from exports.export_manager import ExportManager
from orchestration.workflow import InvestigationWorkflow


def _run(db, vid="V-000"):
    return InvestigationWorkflow(db=db).investigate(vid, profile="baseline")["run_id"]


def test_csv_export(imported_db):
    em = ExportManager(imported_db)
    name, data = em.vendor_inventory("csv")
    assert name.endswith(".csv")
    text = data.decode("utf-8")
    assert "vendor_id" in text and "V-001" in text


def test_json_export_has_meta(imported_db):
    em = ExportManager(imported_db)
    name, data = em.risk_register("json")
    payload = json.loads(data)
    assert "meta" in payload and "limitations" in payload["meta"]
    assert payload["meta"]["risk_model_version"]


def test_evidence_ledger_xlsx(imported_db):
    run_id = _run(imported_db)
    em = ExportManager(imported_db)
    name, data = em.evidence_ledger(run_id, "xlsx")
    assert name.endswith(".xlsx")
    assert data[:2] == b"PK"  # xlsx is a zip


def test_investigation_report_markdown(imported_db):
    run_id = _run(imported_db)
    em = ExportManager(imported_db)
    name, data = em.investigation_report(run_id, "markdown")
    assert name.endswith(".md")
    assert b"Vendor AI Intelligence Report" in data


def test_v21_exports(ai_run):
    db, run_id = ai_run
    em = ExportManager(db)
    for name, data in [em.remediation_register("csv"), em.control_matrix(run_id, "csv"),
                       em.framework_crosswalk(run_id, "json"), em.questionnaire(run_id, "csv"),
                       em.threat_scenarios(run_id, "xlsx")]:
        assert data and len(data) > 0


def test_snapshot_manifest_export(imported_db):
    run_id = _run(imported_db)
    from orchestration.run_manager import RunManager
    RunManager(imported_db).freeze_snapshot(run_id)
    name, data = ExportManager(imported_db).snapshot_manifest("csv")
    assert b"content_hash" in data
