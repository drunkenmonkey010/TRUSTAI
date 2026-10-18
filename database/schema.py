"""Versioned SQLite schema for the Meridian engine.

Migrations are an ordered list of ``(version, [sql statements])``. The runner in
``connection.py`` applies every migration whose version is greater than the
database's current ``user_version``. This keeps operational, evidence and
benchmark data in clearly separated tables.
"""
from __future__ import annotations

from typing import List, Tuple

# --------------------------------------------------------------------------- #
# Migration 1 - initial schema.
# --------------------------------------------------------------------------- #
_V1: List[str] = [
    # ---- operational input ----
    """
    CREATE TABLE IF NOT EXISTS vendor_imports (
        import_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        source_filename TEXT NOT NULL,
        imported_at     TEXT NOT NULL,
        row_count       INTEGER NOT NULL DEFAULT 0,
        valid_count     INTEGER NOT NULL DEFAULT 0,
        invalid_count   INTEGER NOT NULL DEFAULT 0,
        field_mapping   TEXT,                 -- JSON: logical->source column
        notes           TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS vendors (
        vendor_id        TEXT PRIMARY KEY,     -- e.g. V-001
        import_id        INTEGER,
        vendor_name      TEXT NOT NULL,
        normalized_name  TEXT NOT NULL,
        description      TEXT,
        service_provided TEXT,
        category         TEXT,
        website          TEXT,
        business_process TEXT,
        operational_dependency TEXT,
        data_classification    TEXT,
        data_volume      TEXT,
        criticality_tier TEXT,                 -- provided or derived
        raw_record       TEXT,                 -- JSON: original row, preserved verbatim
        is_example       INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL,
        FOREIGN KEY (import_id) REFERENCES vendor_imports(import_id)
    );
    """,
    # ---- investigation lifecycle ----
    """
    CREATE TABLE IF NOT EXISTS investigation_runs (
        run_id        TEXT PRIMARY KEY,         -- uuid
        vendor_id     TEXT NOT NULL,
        profile       TEXT NOT NULL,            -- baseline|enhanced|deep
        status        TEXT NOT NULL,            -- pending|running|completed|failed|frozen
        live_mode     INTEGER NOT NULL DEFAULT 0,
        started_at    TEXT,
        completed_at  TEXT,
        query_budget  INTEGER NOT NULL DEFAULT 0,
        queries_used  INTEGER NOT NULL DEFAULT 0,
        summary       TEXT,                     -- JSON
        created_at    TEXT NOT NULL,
        FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
        agent_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT NOT NULL,
        agent_name   TEXT NOT NULL,
        status       TEXT NOT NULL,             -- pending|running|completed|failed|skipped
        started_at   TEXT,
        finished_at  TEXT,
        retries      INTEGER NOT NULL DEFAULT 0,
        current_action TEXT,
        error        TEXT,
        output       TEXT,                      -- JSON
        FOREIGN KEY (run_id) REFERENCES investigation_runs(run_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS investigation_queries (
        query_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      TEXT NOT NULL,
        layer       INTEGER,
        connector   TEXT,
        query_text  TEXT NOT NULL,
        rationale   TEXT,
        executed_at TEXT,
        result_count INTEGER NOT NULL DEFAULT 0,
        status      TEXT NOT NULL DEFAULT 'planned',
        FOREIGN KEY (run_id) REFERENCES investigation_runs(run_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS connector_runs (
        connector_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      TEXT,
        connector   TEXT NOT NULL,
        query       TEXT,
        requested_at TEXT NOT NULL,
        http_status INTEGER,
        retrieval_status TEXT,                  -- ok|error|rate_limited|unavailable|offline
        result_count INTEGER NOT NULL DEFAULT 0,
        error_code  TEXT,
        error_message TEXT,
        latency_ms  INTEGER
    );
    """,
    # ---- evidence & findings ----
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT,
        vendor_id     TEXT,
        connector_name TEXT,
        url           TEXT,
        canonical_url TEXT,
        title         TEXT,
        source_type   TEXT,
        source_owner  TEXT,
        published_at  TEXT,
        retrieved_at  TEXT,
        snippet       TEXT,
        extracted_text TEXT,
        http_status   INTEGER,
        retrieval_status TEXT,
        content_hash  TEXT,
        is_sample     INTEGER NOT NULL DEFAULT 0,
        error_code    TEXT,
        error_message TEXT,
        metadata      TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS claims (
        claim_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        claim_text    TEXT NOT NULL,
        claim_type    TEXT,                     -- observation|extracted|inference|judgment
        subject       TEXT,
        action        TEXT,
        product       TEXT,
        qualifiers    TEXT,
        supported     INTEGER NOT NULL DEFAULT 0,
        created_by_agent TEXT,
        created_at    TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES investigation_runs(run_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence (
        evidence_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        claim_id      INTEGER,
        source_id     INTEGER,
        url           TEXT,
        canonical_url TEXT,
        title         TEXT,
        source_owner  TEXT,
        source_type   TEXT,
        published_at  TEXT,
        retrieved_at  TEXT,
        excerpt       TEXT,
        content_hash  TEXT,
        relation      TEXT,                     -- supports|contradicts|neutral
        directness    TEXT,                     -- direct|indirect
        authority     TEXT,                     -- first_party|independent|aggregator|unknown
        freshness     TEXT,
        independence  TEXT,
        confidence_rationale TEXT,
        extraction_method TEXT,
        verification_status TEXT,
        is_sample     INTEGER NOT NULL DEFAULT 0,
        error_note    TEXT,
        created_by_agent TEXT,
        created_at    TEXT NOT NULL,
        FOREIGN KEY (claim_id) REFERENCES claims(claim_id),
        FOREIGN KEY (source_id) REFERENCES sources(source_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS vendor_relationships (
        rel_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        source_entity TEXT NOT NULL,
        target_entity TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        confidence    REAL,
        evidence_status TEXT,                   -- confirmed|probable|disputed|unknown
        evidence_ids  TEXT,                     -- JSON list
        source_timestamp TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_usage_classifications (
        classification_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        label         TEXT NOT NULL,
        deployment_context TEXT,
        confidence    REAL,
        evidence_ids  TEXT,
        rationale     TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS data_flow_findings (
        finding_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        description   TEXT,
        data_category TEXT,
        destination   TEXT,
        customer_data_involved TEXT,            -- yes|no|unknown
        transfer_established TEXT,              -- yes|no|unknown
        processing_context TEXT,
        retention_terms TEXT,
        training_terms TEXT,
        confidence    REAL,
        evidence_ids  TEXT,
        open_questions TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_assessments (
        assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        model_version TEXT NOT NULL,
        weights       TEXT NOT NULL,            -- JSON
        dimension_scores TEXT NOT NULL,         -- JSON
        inherent_risk REAL,
        residual_risk REAL,
        evidence_confidence REAL,
        investigation_uncertainty REAL,
        overall_priority TEXT,
        explanation   TEXT,
        missing_information TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendations (
        rec_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        category      TEXT,
        finding       TEXT,
        rationale     TEXT,
        action        TEXT,
        priority      TEXT,
        responsible_role TEXT,
        time_horizon  TEXT,
        supporting_evidence TEXT,
        closure_conditions TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS adaptive_decisions (
        decision_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT NOT NULL,
        step          INTEGER NOT NULL,
        layer         INTEGER,
        state_summary TEXT,
        gaps_considered TEXT,
        proposed_action TEXT,
        action_value  TEXT,
        expected_uncertainty_reduction REAL,
        budget_cost   INTEGER,
        decision      TEXT,                     -- continue|stop|escalate
        human_review_trigger INTEGER NOT NULL DEFAULT 0,
        rationale     TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    # ---- frozen snapshots (isolated from benchmark) ----
    """
    CREATE TABLE IF NOT EXISTS frozen_snapshots (
        snapshot_id   TEXT PRIMARY KEY,         -- uuid
        run_id        TEXT NOT NULL,
        vendor_id     TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        content_hash  TEXT NOT NULL,
        payload       TEXT NOT NULL,            -- JSON (frozen findings)
        frozen_at     TEXT NOT NULL,
        is_locked     INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (run_id) REFERENCES investigation_runs(run_id)
    );
    """,
    # ---- benchmark storage (physically separate tables) ----
    """
    CREATE TABLE IF NOT EXISTS benchmark_records (
        benchmark_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_id     TEXT,
        source_file   TEXT NOT NULL,
        file_hash     TEXT NOT NULL,
        loaded_at     TEXT NOT NULL,
        ai_usage_label TEXT,
        named_providers TEXT,
        risk_classification TEXT,
        raw_excerpt   TEXT,
        structured    TEXT                      -- JSON of parsed fields
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS benchmark_evaluations (
        evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id   TEXT NOT NULL,
        vendor_id     TEXT,
        evaluated_at  TEXT NOT NULL,
        match_type    TEXT,                     -- exact|partial|missed|false_positive|incomparable
        dimension     TEXT,
        automated_value TEXT,
        benchmark_value TEXT,
        notes         TEXT,
        metrics       TEXT                      -- JSON (precision/recall/f1 when applicable)
    );
    """,
    # ---- audit & settings ----
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at TEXT NOT NULL,
        category    TEXT NOT NULL,
        action      TEXT NOT NULL,
        subject     TEXT,
        detail      TEXT,
        run_id      TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS application_settings (
        key         TEXT PRIMARY KEY,
        value       TEXT,
        updated_at  TEXT NOT NULL
    );
    """,
    # ---- indexes ----
    "CREATE INDEX IF NOT EXISTS idx_vendors_norm ON vendors(normalized_name);",
    "CREATE INDEX IF NOT EXISTS idx_runs_vendor ON investigation_runs(vendor_id);",
    "CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence(claim_id);",
    "CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);",
    "CREATE INDEX IF NOT EXISTS idx_snapshot_run ON frozen_snapshots(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_benchmark_vendor ON benchmark_records(vendor_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_unique ON audit_events(event_id);",
]

# --------------------------------------------------------------------------- #
# Migration 2 - structured claim fields for claim-level AI classification (V2.1).
# Adds columns to the existing `claims` table; historical data is preserved.
# --------------------------------------------------------------------------- #
_V2: List[str] = [
    "ALTER TABLE claims ADD COLUMN classification TEXT;",
    "ALTER TABLE claims ADD COLUMN context_label TEXT;",
    "ALTER TABLE claims ADD COLUMN deployment_status TEXT;",
    "ALTER TABLE claims ADD COLUMN temporal_scope TEXT;",
    "ALTER TABLE claims ADD COLUMN data_flow_implication TEXT;",
    "ALTER TABLE claims ADD COLUMN source_reliability TEXT;",
    "ALTER TABLE claims ADD COLUMN freshness TEXT;",
    "ALTER TABLE claims ADD COLUMN corroboration_status TEXT;",
    "ALTER TABLE claims ADD COLUMN confidence REAL;",
    "ALTER TABLE claims ADD COLUMN classification_rationale TEXT;",
    "ALTER TABLE claims ADD COLUMN verification_status TEXT;",
    "ALTER TABLE claims ADD COLUMN review_status TEXT;",
    "CREATE INDEX IF NOT EXISTS idx_claims_classification ON claims(classification);",
]

# --------------------------------------------------------------------------- #
# Migration 3 - V2.1 feature tables (questionnaires, remediation, monitoring,
# controls, frameworks, contracts, threat modeling, attack paths, eval metrics).
# --------------------------------------------------------------------------- #
_V3: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS questionnaires (
        question_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT,
        vendor_id     TEXT NOT NULL,
        product       TEXT,
        risk_domain   TEXT,
        evidence_gap  TEXT,
        question_text TEXT NOT NULL,
        business_rationale TEXT,
        priority      TEXT,
        response_type TEXT,
        required_evidence TEXT,
        validation_rules TEXT,
        reviewer_role TEXT,
        closure_criteria TEXT,
        status        TEXT NOT NULL DEFAULT 'draft',
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS vendor_responses (
        response_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id   INTEGER NOT NULL,
        vendor_id     TEXT NOT NULL,
        answer_text   TEXT,
        response_type TEXT,
        evidence_ref  TEXT,
        submitted_by  TEXT,
        submitted_at  TEXT,
        validation_result TEXT,
        verification_status TEXT,
        notes         TEXT,
        FOREIGN KEY (question_id) REFERENCES questionnaires(question_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS remediation_findings (
        finding_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT,
        vendor_id     TEXT NOT NULL,
        source_rec_id INTEGER,
        risk_category TEXT,
        severity      TEXT,
        confidence    REAL,
        business_impact TEXT,
        description   TEXT,
        recommendation TEXT,
        responsible_role TEXT,
        due_date      TEXT,
        status        TEXT NOT NULL DEFAULT 'open',
        closure_criteria TEXT,
        closure_evidence TEXT,
        notes         TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS finding_history (
        history_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_id    INTEGER NOT NULL,
        actor         TEXT,
        action        TEXT,
        from_status   TEXT,
        to_status     TEXT,
        rationale     TEXT,
        occurred_at   TEXT NOT NULL,
        FOREIGN KEY (finding_id) REFERENCES remediation_findings(finding_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_decisions (
        decision_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_id     TEXT NOT NULL,
        finding_id    INTEGER,
        decision_type TEXT,
        decision_maker TEXT,
        justification TEXT,
        accepted_risk TEXT,
        scope         TEXT,
        conditions    TEXT,
        compensating_controls TEXT,
        expiry_date   TEXT,
        approvals     TEXT,
        original_conclusion TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS vendor_baselines (
        baseline_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_id     TEXT NOT NULL,
        run_id        TEXT,
        captured_at   TEXT NOT NULL,
        content       TEXT NOT NULL,   -- JSON: normalized evidence fingerprint
        content_hash  TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS change_events (
        event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_id     TEXT NOT NULL,
        baseline_id   INTEGER,
        detected_at   TEXT NOT NULL,
        change_type   TEXT,
        field         TEXT,
        previous_value TEXT,
        new_value     TEXT,
        materiality   TEXT,            -- material|cosmetic
        risk_impact   TEXT,
        confidence    REAL,
        recommended_action TEXT,
        reassessment_required INTEGER NOT NULL DEFAULT 0,
        source_url    TEXT,
        diff_hash     TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS control_assessments (
        control_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT,
        vendor_id     TEXT NOT NULL,
        domain        TEXT,
        objective     TEXT,
        applicability TEXT,
        status        TEXT,
        evidence_quality TEXT,
        validation_method TEXT,
        confidence    REAL,
        uncertainty   TEXT,
        gap           TEXT,
        required_action TEXT,
        framework_refs TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS framework_mappings (
        mapping_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT,
        vendor_id     TEXT NOT NULL,
        framework     TEXT,
        version       TEXT,
        control_identifier TEXT,
        control_objective TEXT,
        finding       TEXT,
        evidence      TEXT,
        status        TEXT,
        limitations   TEXT,
        recommended_action TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS contract_documents (
        doc_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_id     TEXT NOT NULL,
        filename      TEXT NOT NULL,
        file_hash     TEXT NOT NULL,
        uploaded_at   TEXT NOT NULL,
        text_len      INTEGER,
        content       TEXT,
        notes         TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS contract_findings (
        finding_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id        INTEGER NOT NULL,
        vendor_id     TEXT NOT NULL,
        section_ref   TEXT,
        excerpt       TEXT,
        clause_category TEXT,
        status        TEXT,
        interpretation TEXT,
        confidence    REAL,
        related_risk  TEXT,
        missing_details TEXT,
        recommended_followup TEXT,
        legal_review  INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES contract_documents(doc_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS threat_scenarios (
        scenario_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT,
        vendor_id     TEXT NOT NULL,
        asset         TEXT,
        ai_component  TEXT,
        threat        TEXT,
        preconditions TEXT,
        impact        TEXT,
        existing_evidence TEXT,
        existing_controls TEXT,
        evidence_gaps TEXT,
        likelihood_rationale TEXT,
        impact_rationale TEXT,
        mitigations   TEXT,
        scenario_type TEXT,            -- confirmed_vuln|control_gap|plausible|hypothetical
        human_review  INTEGER NOT NULL DEFAULT 0,
        owasp_ref     TEXT,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS attack_paths (
        path_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id        TEXT,
        vendor_id     TEXT NOT NULL,
        nodes         TEXT,
        edges         TEXT,
        evidence_ids  TEXT,
        assumptions   TEXT,
        unknown_links TEXT,
        business_impact TEXT,
        rationale     TEXT,
        validation_steps TEXT,
        path_type     TEXT,            -- hypothetical|evidence_supported
        rank          INTEGER,
        created_at    TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS eval_metrics (
        metric_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset       TEXT,
        metric_name   TEXT,
        value         REAL,
        sample_size   INTEGER,
        computed_at   TEXT NOT NULL,
        notes         TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_quest_vendor ON questionnaires(vendor_id);",
    "CREATE INDEX IF NOT EXISTS idx_remed_vendor ON remediation_findings(vendor_id);",
    "CREATE INDEX IF NOT EXISTS idx_change_vendor ON change_events(vendor_id);",
    "CREATE INDEX IF NOT EXISTS idx_control_vendor ON control_assessments(vendor_id);",
    "CREATE INDEX IF NOT EXISTS idx_threat_vendor ON threat_scenarios(vendor_id);",
]

# Ordered migrations. Append new tuples for future schema changes.
MIGRATIONS: List[Tuple[int, List[str]]] = [
    (1, _V1),
    (2, _V2),
    (3, _V3),
]

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1][0]
