"""Page 12 - Vendor Questionnaire and Evidence Validation (V2.1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from questionnaires.engine import generate_questions, validate_response
from ui_common import db, page_header, select_run

page_header("Vendor Questionnaire & Evidence Validation",
            "Gap-driven questions and self-attestation vs verified evidence")
database = db()
run_id, vendor_id = select_run("q_run")
if not run_id:
    st.stop()

qs = database.query("SELECT * FROM questionnaires WHERE run_id=? ORDER BY question_id", (run_id,))
if not qs:
    if st.button("Generate questions from evidence gaps"):
        generate_questions(run_id, database)
        st.rerun()
    st.info("No questions yet (generated automatically when AI use is established).")
    st.stop()

st.subheader("Questionnaire")
st.dataframe(pd.DataFrame(qs)[["question_id", "priority", "risk_domain", "evidence_gap",
             "status", "question_text"]], use_container_width=True, hide_index=True)
st.download_button("Export questionnaire (CSV)",
                   pd.DataFrame(qs).to_csv(index=False).encode(), f"questionnaire_{vendor_id}.csv")

st.subheader("Record a vendor response")
qid = st.selectbox("Question", [q["question_id"] for q in qs])
q = next(x for x in qs if x["question_id"] == qid)
st.caption(f"{q['question_text']}  (expected: {q['response_type']})")
answer = st.text_area("Vendor answer", height=90)
evidence = st.text_input("Evidence reference (document / URL), if provided")
if st.button("Validate response"):
    res = validate_response(qid, answer, evidence_ref=evidence or None, db=database)
    st.write(f"Verification: **{res['verification_status']}**  ·  status: {res['status']}")
    if res["issues"]:
        st.warning("Issues: " + "; ".join(res["issues"]))
    st.caption("Self-attestation is kept distinct from independently verified evidence.")

resp = database.query("SELECT r.question_id, r.verification_status, r.validation_result, r.answer_text "
                     "FROM vendor_responses r JOIN questionnaires q ON q.question_id=r.question_id "
                     "WHERE q.run_id=? ORDER BY r.response_id DESC", (run_id,))
if resp:
    st.subheader("Responses")
    st.dataframe(pd.DataFrame(resp), use_container_width=True, hide_index=True)
