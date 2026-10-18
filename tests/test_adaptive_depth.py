"""Adaptive controller tests."""
from __future__ import annotations

from orchestration.adaptive_controller import AdaptiveController, ControllerMetrics


def _metrics(**kw):
    defaults = dict(layer=1, new_sources_last_layer=2, total_sources=2, mean_quality=0.6,
                    contradictions=0, independent_corroboration=0, ai_label="Insufficient evidence",
                    criticality_tier="Low", data_sensitivity_rank=0, data_flow_unknown=True)
    defaults.update(kw)
    return ControllerMetrics(**defaults)


def _ctrl(max_layer=7, budget=10):
    return AdaptiveController(max_layer, lambda: budget)


def test_budget_exhausted_stops():
    d = AdaptiveController(7, lambda: 0).decide(_metrics())
    assert d.decision == "stop"
    assert "budget" in d.rationale.lower()


def test_contradiction_triggers_escalation():
    d = _ctrl().decide(_metrics(contradictions=1, layer=2))
    assert d.decision == "escalate"
    assert d.next_layer == 6
    assert d.human_review_trigger is True


def test_strong_evidence_justifies_stop():
    d = _ctrl().decide(_metrics(ai_label="Confirmed generative AI use", layer=3,
                                criticality_tier="Low", data_sensitivity_rank=0,
                                data_flow_unknown=False))
    assert d.decision == "stop"
    assert "confirmed" in d.rationale.lower()


def test_critical_sensitive_continues_despite_confirmation():
    d = _ctrl().decide(_metrics(ai_label="Confirmed generative AI use", layer=3,
                                criticality_tier="Critical", data_sensitivity_rank=2,
                                data_flow_unknown=True))
    assert d.decision == "continue"
    assert d.next_layer == 4


def test_diminishing_returns_stops_for_noncritical():
    d = _ctrl().decide(_metrics(new_sources_last_layer=0, layer=3, criticality_tier="Low"))
    assert d.decision == "stop"
    assert "diminishing" in d.action_value.lower() or "no new sources" in d.rationale.lower()


def test_max_layer_respected():
    d = _ctrl(max_layer=3).decide(_metrics(layer=3))
    assert d.decision == "stop"


def test_every_decision_has_rationale():
    for m in (_metrics(), _metrics(contradictions=1),
              _metrics(ai_label="Confirmed AI use", layer=4)):
        d = _ctrl().decide(m)
        assert d.rationale and len(d.rationale) > 5


def test_adaptive_loop_respects_budget(imported_db, monkeypatch):
    # An end-to-end offline run must not exceed its query budget.
    from orchestration.workflow import InvestigationWorkflow
    wf = InvestigationWorkflow(db=imported_db)
    result = wf.investigate("V-002", profile="deep")
    run = imported_db.query_one("SELECT queries_used, query_budget FROM investigation_runs WHERE run_id=?",
                                (result["run_id"],))
    assert run["queries_used"] <= run["query_budget"]
