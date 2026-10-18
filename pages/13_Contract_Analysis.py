"""Page 13 - Contract and Policy Analysis (V2.1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from contracts.analyzer import analyze_document, ingest_document
from ui_common import db, page_header, vendors

page_header("Contract & Policy Analysis",
            "Clause-level gap analysis of authorized vendor documents (not legal advice)")
database = db()
vs = vendors()
if not vs:
    st.info("Import vendors first.")
    st.stop()

label = {f"{v['vendor_id']} · {v['vendor_name']}": v["vendor_id"] for v in vs}
vid = label[st.selectbox("Vendor", list(label.keys()))]

st.subheader("Upload a document (.txt or .pdf)")
st.caption("Uploaded text is treated as untrusted data and never executed as instructions. "
           "'Not found' means not found in THIS document — the obligation may exist elsewhere.")
up = st.file_uploader("Vendor agreement / DPA / privacy policy / AI terms", type=["txt", "pdf"])
if up is not None and st.button("Ingest & analyze"):
    doc_id = ingest_document(vid, up.name, up.getvalue(), db=database)
    analyze_document(doc_id, db=database)
    st.success(f"Analyzed '{up.name}'.")
    st.rerun()

docs = database.query("SELECT * FROM contract_documents WHERE vendor_id=? ORDER BY doc_id DESC", (vid,))
if not docs:
    st.info("No documents analyzed for this vendor yet.")
    st.stop()

doc_label = {f"{d['filename']} ({d['uploaded_at'][:19]})": d["doc_id"] for d in docs}
doc_id = doc_label[st.selectbox("Document", list(doc_label.keys()))]
findings = database.query("SELECT clause_category, status, interpretation, excerpt, related_risk, "
                         "legal_review, recommended_followup FROM contract_findings WHERE doc_id=? "
                         "ORDER BY finding_id", (doc_id,))
st.subheader("Clause findings")
st.dataframe(pd.DataFrame(findings), use_container_width=True, hide_index=True)
flagged = [f for f in findings if f["legal_review"]]
st.caption(f"{len(flagged)} clause(s) flagged for authorized legal/procurement review. "
           "No definitive legal conclusions are made.")
