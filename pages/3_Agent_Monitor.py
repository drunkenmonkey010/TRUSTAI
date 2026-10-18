"""Page 3 - Agent Monitor (real agent/connector activity, no fake progress)."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ui_common import db, page_header

page_header("Agent Monitor", "Real agent and connector activity for a run")
database = db()

runs = database.query(
    "SELECT r.run_id, r.vendor_id, v.vendor_name, r.profile, r.status, r.created_at "
    "FROM investigation_runs r JOIN vendors v ON v.vendor_id=r.vendor_id ORDER BY r.created_at DESC")
if not runs:
    st.info("No runs yet.")
    st.stop()

labels = {f"{r['vendor_id']} · {r['profile']} · {r['status']} · {r['created_at'][:19]}": r["run_id"]
          for r in runs}
choice = st.selectbox("Run", list(labels.keys()))
run_id = labels[choice]

agents = database.query(
    "SELECT agent_name, status, started_at, finished_at, retries, current_action, error "
    "FROM agent_runs WHERE run_id=? ORDER BY agent_run_id", (run_id,))
st.subheader("Agents")
st.dataframe(pd.DataFrame(agents), use_container_width=True, hide_index=True)

st.subheader("Connector requests & budget")
conn = database.query(
    "SELECT connector, query, http_status, retrieval_status, result_count, error_code, latency_ms, requested_at "
    "FROM connector_runs WHERE run_id=? ORDER BY connector_run_id", (run_id,))
if conn:
    st.dataframe(pd.DataFrame(conn), use_container_width=True, hide_index=True)
else:
    st.caption("No connector requests recorded (offline mode or no live calls).")

run = database.query_one("SELECT queries_used, query_budget FROM investigation_runs WHERE run_id=?", (run_id,))
if run:
    used, budget = run["queries_used"] or 0, run["query_budget"] or 0
    st.progress(min(1.0, used / budget) if budget else 0.0,
                text=f"Query budget consumed: {used}/{budget}")

st.subheader("Human-review requirement")
dec = database.query(
    "SELECT COUNT(*) c FROM adaptive_decisions WHERE run_id=? AND human_review_trigger=1", (run_id,))
st.write("⚠️ Human review flagged" if dec and dec[0]["c"] else "No human-review trigger raised.")

st.subheader("Agent outputs")
for a in agents:
    out = database.query_one(
        "SELECT output FROM agent_runs WHERE run_id=? AND agent_name=? ORDER BY agent_run_id DESC LIMIT 1",
        (run_id, a["agent_name"]))
    with st.expander(f"{a['agent_name']} ({a['status']})"):
        if out and out.get("output"):
            try:
                st.json(json.loads(out["output"]))
            except Exception:
                st.write(out["output"])
