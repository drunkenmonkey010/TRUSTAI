"""Tests for V2.1 post-processing services (questionnaires, remediation, controls,
frameworks, threat modeling, attack paths, supply chain, evaluation)."""
from __future__ import annotations

import pytest

from contracts.analyzer import analyze_document, ingest_document
from evaluation.lab import run_classifier_eval, run_evidence_metrics
from frameworks.crosswalk import assess_controls, map_frameworks
from monitoring.change_detector import capture_baseline, detect_changes
from questionnaires.engine import generate_questions, validate_response
from remediation.manager import InvalidTransition, RemediationManager
from reports.supply_chain import concentration_analysis
from threat_modeling.engine import build_attack_paths, generate_scenarios


# --- Questionnaire ------------------------------------------------------ #
def test_questions_are_gap_driven(ai_run):
    db, run_id = ai_run
    qs = db.query("SELECT * FROM questionnaires WHERE run_id=?", (run_id,))
    assert qs  # AI established -> questions generated
    domains = {q["risk_domain"] for q in qs}
    assert "Data flow" in domains or "Model provider" in domains
    for q in qs:
        assert q["evidence_gap"] and q["closure_criteria"] and q["priority"]


def test_response_validation_distinguishes_attestation(ai_run):
    db, run_id = ai_run
    q = db.query_one("SELECT question_id FROM questionnaires WHERE run_id=? LIMIT 1", (run_id,))
    empty = validate_response(q["question_id"], "", db=db)
    assert empty["status"] == "needs_revision"
    good = validate_response(q["question_id"], "Yes, data is retained for 30 days and not used for training.",
                             db=db)
    assert good["verification_status"].startswith("self_attested") or \
           good["verification_status"].startswith("consistent")


# --- Remediation state machine ------------------------------------------ #
def test_findings_created_from_recommendations(ai_run):
    db, run_id = ai_run
    findings = db.query("SELECT * FROM remediation_findings WHERE run_id=?", (run_id,))
    assert findings
    assert all(f["status"] == "open" for f in findings)


def test_invalid_transition_rejected(ai_run):
    db, run_id = ai_run
    f = db.query_one("SELECT finding_id FROM remediation_findings WHERE run_id=? LIMIT 1", (run_id,))
    mgr = RemediationManager(db)
    with pytest.raises(InvalidTransition):
        mgr.transition(f["finding_id"], "closed", "analyst")  # open->closed not allowed


def test_close_requires_evidence_and_history(ai_run):
    db, run_id = ai_run
    f = db.query_one("SELECT finding_id FROM remediation_findings WHERE run_id=? LIMIT 1", (run_id,))
    mgr = RemediationManager(db)
    mgr.transition(f["finding_id"], "in_progress", "analyst", rationale="starting")
    with pytest.raises(InvalidTransition):
        mgr.transition(f["finding_id"], "closed", "analyst")  # no evidence
    mgr.transition(f["finding_id"], "closed", "analyst", closure_evidence="ticket #42 verified")
    hist = mgr.history(f["finding_id"])
    assert len(hist) >= 3  # create + in_progress + closed


def test_risk_acceptance_preserves_original(ai_run):
    db, run_id = ai_run
    f = db.query_one("SELECT finding_id, description FROM remediation_findings WHERE run_id=? LIMIT 1", (run_id,))
    mgr = RemediationManager(db)
    did = mgr.accept_risk(f["finding_id"], "CISO", "accepted pending Q4 review", "residual AI risk",
                          "V-000", expiry_date="2027-01-01")
    dec = db.query_one("SELECT * FROM risk_decisions WHERE decision_id=?", (did,))
    assert dec["original_conclusion"] == f["description"]
    assert dec["decision_maker"] == "CISO"


# --- Controls & frameworks ---------------------------------------------- #
def test_controls_not_marked_absent_without_evidence(ai_run):
    db, run_id = ai_run
    controls = db.query("SELECT * FROM control_assessments WHERE run_id=?", (run_id,))
    assert len(controls) == 13
    # No control is marked a hard 'absent'; unknowns are 'not_verified'.
    assert all(c["status"] in ("partially_evidenced", "not_verified") for c in controls)
    assert any(c["status"] == "not_verified" for c in controls)


def test_framework_identifiers_present(ai_run):
    db, run_id = ai_run
    maps = db.query("SELECT DISTINCT framework FROM framework_mappings WHERE run_id=?", (run_id,))
    frameworks = {m["framework"] for m in maps}
    assert any("NIST" in f for f in frameworks)
    assert any("ISO/IEC" in f for f in frameworks)
    assert any("OWASP" in f for f in frameworks)


# --- Threat modeling & attack paths ------------------------------------- #
def test_threat_scenarios_typed_not_confirmed_vuln(ai_run):
    db, run_id = ai_run
    scen = db.query("SELECT * FROM threat_scenarios WHERE run_id=?", (run_id,))
    assert scen
    assert all(s["scenario_type"] in ("plausible", "hypothetical", "control_gap") for s in scen)
    assert all("OWASP" in (s["owasp_ref"] or "") for s in scen)


def test_attack_path_marks_unknown_links(ai_run):
    db, run_id = ai_run
    paths = db.query("SELECT * FROM attack_paths WHERE run_id=?", (run_id,))
    assert paths
    assert paths[0]["unknown_links"]  # customer-data edge is not established


# --- Supply chain ------------------------------------------------------- #
def test_concentration_analysis_runs(ai_run):
    db, _ = ai_run
    a = concentration_analysis(db)
    assert "shared_providers" in a and "single_points_of_failure" in a


# --- Change detection --------------------------------------------------- #
def test_change_detection_material_vs_cosmetic(imported_db):
    from orchestration.workflow import InvestigationWorkflow
    wf = InvestigationWorkflow(db=imported_db)
    r1 = wf.investigate("V-000", profile="baseline")
    # First run captured a baseline; craft a changed fingerprint by inserting a
    # different AI label via a second run after tampering is not trivial, so test
    # the detector directly against a synthetic prior baseline.
    import json
    from database.connection import utcnow
    base = imported_db.query_one(
        "SELECT * FROM vendor_baselines WHERE vendor_id='V-000' ORDER BY captured_at DESC LIMIT 1")
    fp = json.loads(base["content"])
    fp["ai_label"] = "AI use not established"            # simulate a prior different label
    fp["providers"] = []
    imported_db.execute("UPDATE vendor_baselines SET content=? WHERE baseline_id=?",
                        (json.dumps(fp), base["baseline_id"]))
    events = detect_changes("V-000", r1["run_id"], imported_db)
    assert any(e["field"] == "ai_label" and e["materiality"] == "material" for e in events)


# --- Evaluation lab ----------------------------------------------------- #
def test_classifier_eval_zero_false_positives(tmp_db):
    m = run_classifier_eval(tmp_db)
    assert m["sample_size"] == 12
    assert m["false_positive_rate"] == 0.0   # no keyword-only doc confirmed
    assert m["recall"] == 1.0


def test_evidence_metrics(ai_run):
    db, run_id = ai_run
    m = run_evidence_metrics(run_id, db)
    assert m["sample_size"] > 0
    assert 0.0 <= m["citation_support_rate"] <= 1.0


# --- Contracts (no run needed) ------------------------------------------ #
def test_contract_clause_analysis(tmp_db):
    text = (b"This Data Processing Agreement. The Provider shall not use Customer Data to train models. "
            b"Sub-processors may change from time to time. The Provider will notify Customer of any "
            b"security incident within 72 hours. Data is retained for 30 days.")
    doc_id = ingest_document("V-001", "dpa.txt", text, db=tmp_db)
    findings = analyze_document(doc_id, db=tmp_db)
    cats = {f["category"]: f["status"] for f in findings}
    assert cats["Training use"] in ("present_explicit", "present_but_ambiguous", "conflicting")
    assert cats["Incident notification"] in ("present_explicit", "present_but_ambiguous")
    # A clause not in the document is 'not_found', not absent-as-proof.
    assert cats["Audit rights"] == "not_found"
