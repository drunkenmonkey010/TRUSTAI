"""Page 1 - Executive Overview."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ui_common import db, page_header, registry

page_header("Executive Overview", "Portfolio-level AI usage and risk posture")

database = db()
rows = database.query(
    """
    SELECT v.vendor_id, v.vendor_name, v.criticality_tier,
           (SELECT label FROM ai_usage_classifications a WHERE a.vendor_id=v.vendor_id ORDER BY classification_id DESC LIMIT 1) AS ai_label,
           (SELECT overall_priority FROM risk_assessments r WHERE r.vendor_id=v.vendor_id ORDER BY assessment_id DESC LIMIT 1) AS priority,
           (SELECT investigation_uncertainty FROM risk_assessments r WHERE r.vendor_id=v.vendor_id ORDER BY assessment_id DESC LIMIT 1) AS uncertainty,
           (SELECT status FROM investigation_runs ir WHERE ir.vendor_id=v.vendor_id ORDER BY created_at DESC LIMIT 1) AS run_status
    FROM vendors v ORDER BY v.vendor_id
    """
)
df = pd.DataFrame(rows)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Imported vendors", len(df))
investigated = df["run_status"].notna().sum() if not df.empty else 0
c2.metric("Investigated", int(investigated))
high = df["priority"].isin(["Critical", "High"]).sum() if not df.empty else 0
c3.metric("High-priority vendors", int(high))
insuff = df["ai_label"].eq("Insufficient evidence").sum() if not df.empty else 0
c4.metric("Insufficient evidence", int(insuff))

if df.empty:
    st.info("No vendors yet - import on the Vendor Inventory page.")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    st.subheader("AI-use classification distribution")
    dist = df["ai_label"].fillna("(not investigated)").value_counts().reset_index()
    dist.columns = ["label", "count"]
    st.plotly_chart(px.bar(dist, x="count", y="label", orientation="h"), use_container_width=True)
with col2:
    st.subheader("Risk priority distribution")
    pr = df["priority"].fillna("(none)").value_counts().reset_index()
    pr.columns = ["priority", "count"]
    st.plotly_chart(px.pie(pr, names="priority", values="count"), use_container_width=True)

st.subheader("Investigation depth distribution")
depths = database.query("SELECT profile, COUNT(*) c FROM investigation_runs GROUP BY profile")
if depths:
    st.dataframe(pd.DataFrame(depths), use_container_width=True, hide_index=True)

st.subheader("Contradictions & unknowns")
contra = database.query(
    "SELECT cl.vendor_id AS vendor_id, COUNT(*) c FROM claims cl JOIN evidence e ON e.claim_id=cl.claim_id "
    "WHERE e.relation='contradicts' GROUP BY cl.vendor_id")
st.write(f"Vendors with contradicting evidence: {len(contra)}")
unknown_vendors = df[df["uncertainty"].fillna(0) >= 0.5]["vendor_id"].tolist()
st.write(f"Vendors with high investigation uncertainty (>=0.5): {', '.join(unknown_vendors) or 'none'}")

st.subheader("Connector health")
hc = [{"connector": h.name, "available": h.available, "detail": h.detail} for h in registry().health()]
st.dataframe(pd.DataFrame(hc), use_container_width=True, hide_index=True)

st.subheader("Recent runs")
recent = database.query(
    "SELECT run_id, vendor_id, profile, status, live_mode, created_at FROM investigation_runs "
    "ORDER BY created_at DESC LIMIT 10")
st.dataframe(pd.DataFrame(recent), use_container_width=True, hide_index=True)
