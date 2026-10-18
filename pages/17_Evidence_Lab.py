"""Page 17 - Evidence Quality Benchmark and Regression Lab (V2.1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from evaluation.lab import run_classifier_eval, run_evidence_metrics
from ui_common import db, page_header, select_run

page_header("Evidence Quality Lab",
            "Classifier regression metrics on labelled fixtures, with sample sizes")
database = db()

st.subheader("Claim-classifier regression (labelled fixtures)")
st.caption("Measures the confirmed-vs-not decision on a manually labelled fixture set. "
           "Metrics are shown with their sample size; the held-out OPTIV benchmark is NOT used here.")
if st.button("Run classifier evaluation"):
    m = run_classifier_eval(database)
    st.session_state["clf_eval"] = m

m = st.session_state.get("clf_eval")
if m:
    cols = st.columns(4)
    cols[0].metric("Precision", m["precision"])
    cols[1].metric("Recall", m["recall"])
    cols[2].metric("F1", m["f1"])
    cols[3].metric("False-positive rate", m["false_positive_rate"])
    st.caption(f"n={m['sample_size']} · TP={m['tp']} FP={m['fp']} FN={m['fn']} TN={m['tn']}")
    if m["false_positive_rate"] == 0.0:
        st.success("Zero false positives: no keyword-only document was classified as confirmed AI use.")

st.divider()
st.subheader("Per-run evidence metrics")
run_id, _ = select_run("lab_run")
if run_id and st.button("Compute evidence metrics for this run"):
    em = run_evidence_metrics(run_id, database)
    st.json(em)

hist = database.query("SELECT dataset, metric_name, value, sample_size, computed_at "
                     "FROM eval_metrics ORDER BY metric_id DESC LIMIT 40")
if hist:
    st.subheader("Metric history")
    st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True)
