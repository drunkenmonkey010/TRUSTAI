"""MANDATORY benchmark isolation tests.

These enforce, via architecture and behaviour, that the held-out benchmark is
inaccessible to automated investigation until results are frozen AND evaluation
is explicitly unlocked, and that evaluation never contaminates or mutates the
automated findings.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from benchmark.access_control import BenchmarkAccessController, BenchmarkLockedError
from orchestration.run_manager import RunManager
from orchestration.workflow import InvestigationWorkflow

PROJECT = pathlib.Path(__file__).resolve().parent.parent


def _run_and_freeze(db, vendor_id="V-000"):
    wf = InvestigationWorkflow(db=db)
    r = wf.investigate(vendor_id, profile="baseline")
    sid = RunManager(db).freeze_snapshot(r["run_id"])
    return r["run_id"], sid


# --------------------------------------------------------------------------- #
def test_benchmark_locked_before_freeze(tmp_db):
    ctrl = BenchmarkAccessController(tmp_db)
    assert ctrl.is_unlocked() is False
    with pytest.raises(BenchmarkLockedError):
        ctrl.benchmark_path()


def test_unlock_blocked_without_snapshot(tmp_db):
    ctrl = BenchmarkAccessController(tmp_db)
    with pytest.raises(BenchmarkLockedError):
        ctrl.unlock("premature")


def test_locked_after_freeze_until_explicit_unlock(imported_db):
    _run_and_freeze(imported_db)
    ctrl = BenchmarkAccessController(imported_db)
    # Frozen, but NOT yet unlocked -> still inaccessible.
    assert ctrl.is_unlocked() is False
    with pytest.raises(BenchmarkLockedError):
        ctrl.benchmark_path()


def test_loader_rejects_unauthorized_access(imported_db):
    from benchmark.pdf_parser import parse_benchmark
    with pytest.raises(BenchmarkLockedError):
        parse_benchmark(imported_db)  # locked


def test_unlock_requires_snapshot_then_allows(imported_db):
    _run_and_freeze(imported_db)
    ctrl = BenchmarkAccessController(imported_db)
    ctrl.unlock("evaluation")
    assert ctrl.is_unlocked() is True
    assert ctrl.benchmark_path().exists()


def test_every_unlock_and_eval_audited(imported_db):
    _run_and_freeze(imported_db)
    ctrl = BenchmarkAccessController(imported_db)
    ctrl.unlock("evaluation")
    from benchmark.evaluator import BenchmarkEvaluator
    BenchmarkEvaluator(imported_db).evaluate()
    events = imported_db.query("SELECT action FROM audit_events WHERE category='benchmark'")
    actions = {e["action"] for e in events}
    assert "unlock" in actions and "evaluate" in actions and "access" in actions


def test_evaluation_does_not_modify_snapshot(imported_db):
    _, sid = _run_and_freeze(imported_db)
    rm = RunManager(imported_db)
    before = rm.get_snapshot(sid)["content_hash"]
    ctrl = BenchmarkAccessController(imported_db)
    ctrl.unlock("evaluation")
    from benchmark.evaluator import BenchmarkEvaluator
    BenchmarkEvaluator(imported_db).evaluate()
    after = rm.get_snapshot(sid)["content_hash"]
    assert before == after
    assert rm.verify_snapshot_hash(sid) is True


def test_benchmark_does_not_alter_risk_or_queries(imported_db):
    run_id, sid = _run_and_freeze(imported_db, "V-002")
    risk_before = imported_db.query_one(
        "SELECT inherent_risk FROM risk_assessments WHERE run_id=?", (run_id,))["inherent_risk"]
    q_before = imported_db.query_one(
        "SELECT COUNT(*) c FROM investigation_queries WHERE run_id=?", (run_id,))["c"]
    ctrl = BenchmarkAccessController(imported_db)
    ctrl.unlock("evaluation")
    from benchmark.evaluator import BenchmarkEvaluator
    BenchmarkEvaluator(imported_db).evaluate()
    risk_after = imported_db.query_one(
        "SELECT inherent_risk FROM risk_assessments WHERE run_id=?", (run_id,))["inherent_risk"]
    q_after = imported_db.query_one(
        "SELECT COUNT(*) c FROM investigation_queries WHERE run_id=?", (run_id,))["c"]
    assert risk_before == risk_after
    assert q_before == q_after


def test_snapshot_hash_verifiable_and_tamper_evident(imported_db):
    _, sid = _run_and_freeze(imported_db)
    rm = RunManager(imported_db)
    assert rm.verify_snapshot_hash(sid) is True
    imported_db.execute("UPDATE frozen_snapshots SET payload=payload || ' tampered' WHERE snapshot_id=?", (sid,))
    assert rm.verify_snapshot_hash(sid) is False


def test_agents_and_connectors_do_not_import_benchmark():
    """Static guard: no agent or connector module imports the benchmark package."""
    offenders = []
    for folder in ("agents", "connectors", "orchestration", "risk", "evidence", "imports"):
        for py in (PROJECT / folder).glob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("benchmark"):
                    offenders.append(str(py))
                if isinstance(node, ast.Import):
                    for n in node.names:
                        if n.name.startswith("benchmark"):
                            offenders.append(str(py))
    assert not offenders, f"benchmark imported by: {offenders}"
