"""Page 11 - Control Maturity and Framework Mapping (V2.1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from frameworks.crosswalk import assess_controls, map_frameworks
from ui_common import db, page_header, select_run

page_header("Control Maturity & Framework Mapping",
            "Evidence-based control assessment and framework crosswalk (not a compliance audit)")
database = db()
run_id, vendor_id = select_run("ctrl_run")
if not run_id:
    st.stop()

controls = database.query("SELECT * FROM control_assessments WHERE run_id=? ORDER BY control_id", (run_id,))
if not controls:
    if st.button("Run control assessment"):
        assess_controls(run_id, database)
        map_frameworks(run_id, database)
        st.rerun()
    st.info("No control assessment yet.")
    st.stop()

st.subheader("Control maturity matrix")
df = pd.DataFrame(controls)[["domain", "status", "evidence_quality", "validation_method",
                             "confidence", "uncertainty", "required_action"]]
st.dataframe(df, use_container_width=True, hide_index=True)
st.caption("A control is never marked absent merely because OSINT found no documentation "
           "('not_verified' ≠ 'absent'). Documentation volume is not maturity.")

st.subheader("Framework crosswalk")
maps = database.query("SELECT framework, control_identifier, control_objective, status, "
                     "recommended_action FROM framework_mappings WHERE run_id=? ORDER BY framework", (run_id,))
mdf = pd.DataFrame(maps)
if not mdf.empty:
    fw = st.multiselect("Framework", sorted(mdf["framework"].unique()))
    if fw:
        mdf = mdf[mdf["framework"].isin(fw)]
    st.dataframe(mdf, use_container_width=True, hide_index=True)
    st.caption("Identifiers are objective references (NIST AI RMF / CSF, ISO/IEC 27001 & 42001, "
               "OWASP LLM). Mappings are evidence-based, not certification or compliance determinations.")
