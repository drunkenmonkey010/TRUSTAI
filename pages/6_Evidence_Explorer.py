"""Page 6 - Evidence Explorer (sources, claims, evidence, failures)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui_common import db, page_header

page_header("Evidence Explorer", "Trace every conclusion back to a cited source")
database = db()

runs = database.query("SELECT run_id, vendor_id, created_at FROM investigation_runs ORDER BY created_at DESC")
if not runs:
    st.info("No runs yet.")
    st.stop()
label = {f"{r['vendor_id']} · {r['created_at'][:19]}": r["run_id"] for r in runs}
run_id = label[st.selectbox("Run", list(label.keys()))]

tabs = st.tabs(["Claims", "Evidence", "Sources", "Unsupported", "Retrieval failures"])

with tabs[0]:
    claims = database.query("SELECT claim_id, claim_type, claim_text, supported, created_by_agent "
                            "FROM claims WHERE run_id=? ORDER BY claim_id", (run_id,))
    st.dataframe(pd.DataFrame(claims), use_container_width=True, hide_index=True)
    st.caption("Open a claim's evidence below.")
    if claims:
        cid = st.selectbox("Claim id", [c["claim_id"] for c in claims])
        ev = database.query("SELECT evidence_id, relation, directness, authority, verification_status, "
                            "excerpt, url FROM evidence WHERE claim_id=?", (cid,))
        st.dataframe(pd.DataFrame(ev), use_container_width=True, hide_index=True)

with tabs[1]:
    ev = database.query("SELECT evidence_id, claim_id, relation, directness, authority, "
                        "verification_status, source_type, url, excerpt FROM evidence WHERE run_id=? "
                        "ORDER BY evidence_id", (run_id,))
    df = pd.DataFrame(ev)
    if not df.empty:
        auth = st.multiselect("Authority", sorted(df["authority"].dropna().unique()))
        if auth:
            df = df[df["authority"].isin(auth)]
    st.dataframe(df, use_container_width=True, hide_index=True)

with tabs[2]:
    src = database.query("SELECT source_id, connector_name, retrieval_status, source_type, url, "
                        "title, published_at, retrieved_at, is_sample FROM sources WHERE run_id=? "
                        "ORDER BY source_id", (run_id,))
    st.dataframe(pd.DataFrame(src), use_container_width=True, hide_index=True)
    st.caption("`published_at` (when the content was published) is kept distinct from `retrieved_at`.")

with tabs[3]:
    uns = database.query("SELECT claim_id, claim_type, claim_text FROM claims "
                        "WHERE run_id=? AND supported=0", (run_id,))
    st.write(f"{len(uns)} unsupported claim(s).")
    st.dataframe(pd.DataFrame(uns), use_container_width=True, hide_index=True)

with tabs[4]:
    fails = database.query("SELECT source_id, connector_name, retrieval_status, url, error_code, "
                          "error_message FROM sources WHERE run_id=? AND retrieval_status NOT IN ('ok') "
                          "ORDER BY source_id", (run_id,))
    st.dataframe(pd.DataFrame(fails) if fails else pd.DataFrame({"note": ["no retrieval failures"]}),
                 use_container_width=True, hide_index=True)
