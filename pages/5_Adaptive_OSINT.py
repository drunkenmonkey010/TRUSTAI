"""Page 5 - Adaptive OSINT Explorer (seven layers, decisions, budget)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui_common import db, page_header

page_header("Adaptive OSINT Explorer", "Seven-layer coverage, decisions and stop rationale")
database = db()

runs = database.query(
    "SELECT r.run_id, r.vendor_id, r.profile, r.created_at FROM investigation_runs r ORDER BY created_at DESC")
if not runs:
    st.info("No runs yet.")
    st.stop()
label = {f"{r['vendor_id']} · {r['profile']} · {r['created_at'][:19]}": r["run_id"] for r in runs}
run_id = label[st.selectbox("Run", list(label.keys()))]

run = database.query_one("SELECT * FROM investigation_runs WHERE run_id=?", (run_id,))
st.caption(f"Profile: **{run['profile']}** | mode: {'LIVE' if run['live_mode'] else 'OFFLINE'} | "
           f"queries {run['queries_used']}/{run['query_budget']}")

st.subheader("Queries executed per layer")
queries = database.query(
    "SELECT layer, connector, query_text, rationale, status, result_count FROM investigation_queries "
    "WHERE run_id=? ORDER BY layer", (run_id,))
qdf = pd.DataFrame(queries)
if not qdf.empty:
    for layer in sorted(qdf["layer"].dropna().unique()):
        with st.expander(f"Layer {int(layer)}"):
            st.dataframe(qdf[qdf["layer"] == layer][["connector", "query_text", "rationale",
                         "status", "result_count"]], use_container_width=True, hide_index=True)
else:
    st.caption("No queries recorded.")

st.subheader("Adaptive decisions (continue / stop / escalate)")
dec = database.query("SELECT step, layer, decision, proposed_action, action_value, "
                     "expected_uncertainty_reduction, budget_cost, human_review_trigger, rationale "
                     "FROM adaptive_decisions WHERE run_id=? ORDER BY step", (run_id,))
if dec:
    st.dataframe(pd.DataFrame(dec), use_container_width=True, hide_index=True)
    stopped = [d for d in dec if d["decision"] == "stop"]
    if stopped:
        st.success(f"**Stop rationale:** {stopped[-1]['rationale']}")
else:
    st.caption("No adaptive decisions recorded.")

st.subheader("Separate quality signals (layers != quality)")
verif = database.query_one(
    "SELECT output FROM agent_runs WHERE run_id=? AND agent_name='evidence_verification' "
    "ORDER BY agent_run_id DESC LIMIT 1", (run_id,))
cov = database.query_one(
    "SELECT output FROM agent_runs WHERE run_id=? AND agent_name='adaptive_depth' "
    "ORDER BY agent_run_id DESC LIMIT 1", (run_id,))
import json
coverage = json.loads(cov["output"]).get("coverage", {}) if cov and cov.get("output") else {}
v = json.loads(verif["output"]) if verif and verif.get("output") else {}
cols = st.columns(4)
cols[0].metric("Layers visited", str(coverage.get("layers_visited", [])))
cols[1].metric("Mean evidence quality", v.get("mean_quality", 0.0))
cols[2].metric("Contradictions", v.get("contradictions", 0))
cols[3].metric("Independent corroboration", v.get("independent_corroboration", 0))

st.subheader("Conditions that would reopen this investigation")
for c in coverage.get("reopen_conditions", []):
    st.write(f"- {c}")
