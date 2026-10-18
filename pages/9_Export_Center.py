"""Page 9 - Export Center."""
from __future__ import annotations

import streamlit as st

from benchmark.access_control import BenchmarkAccessController
from exports.export_manager import ExportManager
from ui_common import db, page_header

page_header("Export Center", "Download evidence, reports, risk register and traces")
database = db()
em = ExportManager(database)

runs = database.query("SELECT run_id, vendor_id, created_at FROM investigation_runs ORDER BY created_at DESC")
run_label = {f"{r['vendor_id']} · {r['created_at'][:19]}": r["run_id"] for r in runs}

st.subheader("Portfolio-level exports")
col = st.columns(4)
with col[0]:
    name, data = em.vendor_inventory("csv")
    st.download_button("Vendor inventory (CSV)", data, name, "text/csv")
with col[1]:
    name, data = em.risk_register("json")
    st.download_button("Risk register (JSON)", data, name, "application/json")
with col[2]:
    name, data = em.snapshot_manifest("csv")
    st.download_button("Snapshot manifest (CSV)", data, name, "text/csv")
with col[3]:
    name, data = em.portfolio_report_markdown()
    st.download_button("Portfolio report (MD)", data, name, "text/markdown")
col2 = st.columns(4)
with col2[0]:
    name, data = em.remediation_register("csv")
    st.download_button("Remediation register (CSV)", data, name, "text/csv")

st.divider()
st.subheader("Per-run exports")
if run_label:
    run_id = run_label[st.selectbox("Run", list(run_label.keys()))]
    fmt = st.radio("Format", ["csv", "json", "xlsx", "markdown"], horizontal=True)
    grid = st.columns(3)
    exporters = [
        ("Evidence ledger", lambda: em.evidence_ledger(run_id, fmt if fmt != "markdown" else "csv")),
        ("Provider graph", lambda: em.provider_graph(run_id, fmt if fmt != "markdown" else "csv")),
        ("Adaptive trace", lambda: em.adaptive_trace(run_id, fmt if fmt != "markdown" else "csv")),
        ("Recommendations", lambda: em.recommendations(run_id, fmt if fmt != "markdown" else "csv")),
        ("Investigation report", lambda: em.investigation_report(run_id, fmt)),
    ]
    exporters += [
        ("Control matrix", lambda: em.control_matrix(run_id, fmt if fmt != "markdown" else "csv")),
        ("Framework crosswalk", lambda: em.framework_crosswalk(run_id, fmt if fmt != "markdown" else "csv")),
        ("Questionnaire", lambda: em.questionnaire(run_id, fmt if fmt != "markdown" else "csv")),
        ("Threat scenarios", lambda: em.threat_scenarios(run_id, fmt if fmt != "markdown" else "csv")),
    ]
    for i, (label, fn) in enumerate(exporters):
        with grid[i % 3]:
            name, data = fn()
            st.download_button(label, data, name, key=f"exp_{label}")
else:
    st.info("No runs to export yet.")

st.divider()
st.subheader("Benchmark evaluation export")
if BenchmarkAccessController(database).is_unlocked():
    name, data = em.benchmark_evaluation("csv")
    st.download_button("Benchmark evaluation (CSV)", data, name, "text/csv")
else:
    st.caption("Benchmark evaluation export is available only after authorized unlock.")

st.caption("Every export is stamped with run id (where applicable), timestamp, scoring model version "
           "and an evidence-limitations note.")
