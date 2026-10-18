"""Page 8 - Benchmark Evaluation (strictly gated behind freeze + explicit unlock)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from benchmark.access_control import BenchmarkAccessController, BenchmarkLockedError
from benchmark.evaluator import BenchmarkEvaluator
from ui_common import db, page_header

page_header("Benchmark Evaluation", "Held-out benchmark - isolated until results are frozen and unlocked")
database = db()
ctrl = BenchmarkAccessController(database)

state = ctrl.state().value
has_snapshot = ctrl.has_frozen_snapshot()
st.subheader("Benchmark status")
col1, col2 = st.columns(2)
col1.metric("Access state", state.upper())
col2.metric("Frozen snapshot exists", "yes" if has_snapshot else "no")

if not has_snapshot:
    st.warning(
        "Benchmark is **LOCKED**. Evaluation is unavailable until automated results are frozen.\n\n"
        "**Required steps:**\n"
        "1. Import vendors (Vendor Inventory)\n"
        "2. Run investigations\n"
        "3. **Freeze** each vendor's automated results (Vendor Inventory → Freeze)\n"
        "4. Return here to unlock evaluation", icon="🔒")
    st.stop()

if state == "locked":
    st.info("A frozen snapshot exists. You may now explicitly unlock benchmark evaluation.")
    reason = st.text_input("Reason for unlock (audited)", "Post-freeze benchmark evaluation")
    if st.button("Unlock benchmark evaluation", type="primary"):
        try:
            ctrl.unlock(reason)
            st.success("Benchmark unlocked. Reloading...")
            st.rerun()
        except BenchmarkLockedError as e:
            st.error(str(e))
    st.stop()

# Unlocked
st.success("Benchmark is UNLOCKED. The frozen snapshot is read-only and will not be modified.", icon="🔓")
st.caption("A frozen snapshot records what the system found - it is NOT proof the findings are correct. "
           "The benchmark independently reveals missed findings, false positives and overconfidence.")

if st.button("Run benchmark evaluation", type="primary"):
    with st.spinner("Loading benchmark PDF, parsing, and comparing against frozen snapshots..."):
        summary = BenchmarkEvaluator(database).evaluate()
    st.session_state["bench_summary"] = summary

summary = st.session_state.get("bench_summary")
if summary:
    st.subheader("Detection metrics (AI-usage, benchmark 'yes' = positive)")
    m = st.columns(4)
    m[0].metric("Precision", summary["precision"] if summary["precision"] is not None else "n/a")
    m[1].metric("Recall", summary["recall"] if summary["recall"] is not None else "n/a")
    m[2].metric("F1", summary["f1"] if summary["f1"] is not None else "n/a")
    m[3].metric("Vendors evaluated", summary["vendors_evaluated"])
    st.caption(f"TP={summary['true_positives']} FP={summary['false_positives']} "
               f"FN={summary['false_negatives']} TN={summary['true_negatives']}")

    st.subheader("Per-item comparison")
    df = pd.DataFrame(summary["items"])
    if not df.empty:
        dim = st.multiselect("Dimension", sorted(df["dimension"].unique()),
                             default=sorted(df["dimension"].unique()))
        st.dataframe(df[df["dimension"].isin(dim)], use_container_width=True, hide_index=True)

    missed = df[df["match_type"] == "missed"] if not df.empty else pd.DataFrame()
    fps = df[df["match_type"] == "false_positive"] if not df.empty else pd.DataFrame()
    st.subheader("Missed findings (benchmark found, automated did not)")
    st.dataframe(missed if not missed.empty else pd.DataFrame({"note": ["none"]}),
                 use_container_width=True, hide_index=True)
    st.subheader("False positives / overconfidence")
    oc = df[df["dimension"] == "confidence_calibration"] if not df.empty else pd.DataFrame()
    st.dataframe(pd.concat([fps, oc]) if not (fps.empty and oc.empty) else
                 pd.DataFrame({"note": ["none"]}), use_container_width=True, hide_index=True)

st.divider()
if st.button("Re-lock benchmark"):
    ctrl.relock()
    st.rerun()
