"""Page 10 - Risk Register and Remediation (V2.1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from remediation.manager import STATUSES, InvalidTransition, RemediationManager
from ui_common import db, page_header, select_run

page_header("Risk Register & Remediation", "Findings lifecycle, risk decisions and audit history")
database = db()
run_id, vendor_id = select_run("remed_run")
if not run_id:
    st.stop()

mgr = RemediationManager(database)
findings = database.query("SELECT * FROM remediation_findings WHERE run_id=? ORDER BY finding_id", (run_id,))
if not findings:
    if st.button("Generate findings from recommendations"):
        mgr.create_findings_from_recommendations(run_id)
        st.rerun()
    st.info("No remediation findings yet for this run.")
    st.stop()

st.subheader("Findings")
st.dataframe(pd.DataFrame(findings)[["finding_id", "severity", "status", "risk_category",
             "responsible_role", "description"]], use_container_width=True, hide_index=True)

st.subheader("Manage a finding")
fid = st.selectbox("Finding", [f["finding_id"] for f in findings])
f = next(x for x in findings if x["finding_id"] == fid)
st.write(f"**{f['severity']}** · {f['status']} · {f['description']}")
st.caption(f"Recommendation: {f['recommendation']}  |  Closure: {f['closure_criteria']}")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Transition status**")
    to = st.selectbox("New status", STATUSES, key="to_status")
    actor = st.text_input("Actor", "analyst", key="t_actor")
    rationale = st.text_input("Rationale", key="t_rat")
    evidence = st.text_input("Closure evidence (required to close)", key="t_ev")
    if st.button("Apply transition"):
        try:
            mgr.transition(fid, to, actor, rationale=rationale, closure_evidence=evidence or None)
            st.success(f"Moved to {to}")
            st.rerun()
        except InvalidTransition as e:
            st.error(str(e))
with col2:
    st.markdown("**Accept risk** (preserves the automated conclusion)")
    dm = st.text_input("Decision maker", "CISO", key="r_dm")
    just = st.text_area("Business justification", key="r_just", height=70)
    expiry = st.text_input("Review / expiry date (YYYY-MM-DD)", key="r_exp")
    if st.button("Record risk acceptance"):
        if just.strip():
            mgr.accept_risk(fid, dm, just, f["description"], vendor_id, expiry_date=expiry or None)
            st.success("Risk acceptance recorded.")
            st.rerun()
        else:
            st.error("Justification required.")

st.subheader("History")
st.dataframe(pd.DataFrame(mgr.history(fid)), use_container_width=True, hide_index=True)

decs = database.query("SELECT * FROM risk_decisions WHERE finding_id=?", (fid,))
if decs:
    st.subheader("Risk decisions")
    st.dataframe(pd.DataFrame(decs)[["decision_type", "decision_maker", "justification",
                 "expiry_date", "original_conclusion"]], use_container_width=True, hide_index=True)
