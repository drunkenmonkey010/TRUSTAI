"""Page 7 - Risk and Recommendations (transparent, editable scoring model)."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from risk.weights import DEFAULT_WEIGHTS, validate_weights
from ui_common import db, page_header

page_header("Risk and Recommendations", "Inherent vs residual, confidence vs uncertainty, next actions")
database = db()

# ---- Scoring weights editor ----
with st.expander("Scoring model & weights (editable, versioned, stored)"):
    current = database.get_setting("risk_weights", None) or DEFAULT_WEIGHTS
    st.caption("Weights are normalized to sum to 1.0 and stored with each scoring run. "
               "The LLM never sets the final score - this deterministic model does.")
    new_weights = {}
    for k, v in current.items():
        new_weights[k] = st.slider(k, 0.0, 1.0, float(v), 0.01)
    if st.button("Save weights"):
        try:
            database.set_setting("risk_weights", validate_weights(new_weights))
            database.audit("risk", "weights_changed", detail=new_weights)
            st.success("Weights saved (normalized). Re-run investigations to apply.")
        except ValueError as e:
            st.error(str(e))

vs = database.query("SELECT vendor_id, vendor_name FROM vendors ORDER BY vendor_id")
if not vs:
    st.info("Import vendors first.")
    st.stop()
label = {f"{v['vendor_id']} · {v['vendor_name']}": v["vendor_id"] for v in vs}
vid = label[st.selectbox("Vendor", list(label.keys()))]
run = database.query_one("SELECT run_id FROM investigation_runs WHERE vendor_id=? ORDER BY created_at DESC LIMIT 1", (vid,))
if not run:
    st.warning("No run for this vendor.")
    st.stop()
risk = database.query_one(
    "SELECT * FROM risk_assessments WHERE run_id=? ORDER BY assessment_id DESC LIMIT 1", (run["run_id"],))
if not risk:
    st.warning("No risk assessment.")
    st.stop()

c = st.columns(5)
c[0].metric("Inherent risk", risk["inherent_risk"])
c[1].metric("Residual risk", risk["residual_risk"] if risk["residual_risk"] is not None else "n/a")
c[2].metric("Evidence confidence", risk["evidence_confidence"])
c[3].metric("Investigation uncertainty", risk["investigation_uncertainty"])
c[4].metric("Overall priority", risk["overall_priority"])

st.caption("Inherent risk, residual risk, evidence confidence and investigation uncertainty are "
           "separate concepts. Unknowns are scored via a documented policy, not treated as zero.")

import json
dims = json.loads(risk["dimension_scores"])
weights = json.loads(risk["weights"])
contrib = pd.DataFrame([
    {"dimension": k, "score": dims[k], "weight": weights.get(k, 0),
     "contribution": round(dims[k] * weights.get(k, 0) * 100, 1)}
    for k in dims
]).sort_values("contribution", ascending=False)
st.plotly_chart(px.bar(contrib, x="contribution", y="dimension", orientation="h",
                       title="Risk contribution (points of 100)"), use_container_width=True)

if risk.get("missing_information"):
    st.info("Missing information (scored by unknown policy): " + risk["missing_information"])

with st.expander("Full scoring explanation"):
    st.code(risk["explanation"])

st.subheader("Recommendations")
recs = database.query("SELECT category, priority, responsible_role, time_horizon, finding, action, "
                     "closure_conditions FROM recommendations WHERE run_id=? ORDER BY rec_id", (run["run_id"],))
if recs:
    st.dataframe(pd.DataFrame(recs), use_container_width=True, hide_index=True)
else:
    st.caption("No recommendations generated.")
