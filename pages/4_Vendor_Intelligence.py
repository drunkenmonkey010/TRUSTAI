"""Page 4 - Vendor Intelligence (profile, classification, graph, risk findings)."""
from __future__ import annotations

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui_common import db, page_header

page_header("Vendor Intelligence", "Per-vendor AI usage, relationships and evidence-backed data flow")
database = db()

vs = database.query("SELECT vendor_id, vendor_name FROM vendors ORDER BY vendor_id")
if not vs:
    st.info("Import vendors first.")
    st.stop()

label = {f"{v['vendor_id']} · {v['vendor_name']}": v["vendor_id"] for v in vs}
vid = label[st.selectbox("Vendor", list(label.keys()))]
run = database.query_one(
    "SELECT * FROM investigation_runs WHERE vendor_id=? ORDER BY created_at DESC LIMIT 1", (vid,))
if not run:
    st.warning("No investigation run for this vendor yet.")
    st.stop()
run_id = run["run_id"]

vendor = database.query_one("SELECT * FROM vendors WHERE vendor_id=?", (vid,))
ai = database.query_one(
    "SELECT * FROM ai_usage_classifications WHERE run_id=? ORDER BY classification_id DESC LIMIT 1", (run_id,))
flow = database.query_one(
    "SELECT * FROM data_flow_findings WHERE run_id=? ORDER BY finding_id DESC LIMIT 1", (run_id,))
risk = database.query_one(
    "SELECT * FROM risk_assessments WHERE run_id=? ORDER BY assessment_id DESC LIMIT 1", (run_id,))

c1, c2, c3 = st.columns(3)
c1.metric("AI usage", ai["label"] if ai else "-")
c2.metric("Priority", risk["overall_priority"] if risk else "-")
c3.metric("AI confidence", ai["confidence"] if ai else "-")

st.subheader("Profile")
st.write({k: vendor.get(k) for k in ("vendor_name", "category", "website", "service_provided",
                                     "business_process", "data_classification", "criticality_tier")})

# 12-dimension criticality breakdown (from the criticality agent output).
crit_out = database.query_one(
    "SELECT output FROM agent_runs WHERE run_id=? AND agent_name='criticality' "
    "ORDER BY agent_run_id DESC LIMIT 1", (run_id,))
if crit_out and crit_out.get("output"):
    import json as _json
    crit = _json.loads(crit_out["output"])
    with st.expander(f"Criticality: {crit.get('criticality_tier')} "
                     f"(12-dimension assessment, mean {crit.get('mean_dimension_score')}/3)"):
        st.caption(crit.get("rationale", ""))
        dims = crit.get("dimensions", {})
        if dims:
            st.dataframe(pd.DataFrame([
                {"dimension": k.replace("_", " ").title(), "score (0-3)": d["score"],
                 "status": d["status"], "basis": d["basis"]}
                for k, d in dims.items()
            ]), use_container_width=True, hide_index=True)

if ai:
    st.subheader("AI-use classification")
    st.write(f"**{ai['label']}** — {ai.get('deployment_context','')}")
    st.caption(ai.get("rationale", ""))

st.subheader("Relationships (confirmed vs inferred)")
rels = database.query("SELECT * FROM vendor_relationships WHERE run_id=?", (run_id,))
if rels:
    st.dataframe(pd.DataFrame(rels)[["source_entity", "relation_type", "target_entity",
                 "evidence_status", "confidence"]], use_container_width=True, hide_index=True)
    # Graph
    G = nx.DiGraph()
    for r in rels:
        G.add_edge(r["source_entity"], r["target_entity"],
                   status=r["evidence_status"], rel=r["relation_type"])
    pos = nx.spring_layout(G, seed=42)
    edge_x, edge_y = [], []
    for a, b in G.edges():
        edge_x += [pos[a][0], pos[b][0], None]
        edge_y += [pos[a][1], pos[b][1], None]
    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                             line=dict(width=1, color="#888"), hoverinfo="none"))
    fig.add_trace(go.Scatter(x=node_x, y=node_y, mode="markers+text",
                             text=list(G.nodes()), textposition="top center",
                             marker=dict(size=18, color="#2a6")))
    fig.update_layout(showlegend=False, height=420, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Graph is a reasoning aid, not independent evidence.")
else:
    st.caption("No provider relationships established from public sources.")

if flow:
    st.subheader("Data-flow finding")
    st.write(flow["description"])
    st.write(f"Customer data involved: **{flow['customer_data_involved']}** | "
             f"Transfer established: **{flow['transfer_established']}**")
    if flow.get("open_questions"):
        st.info("Open questions: " + flow["open_questions"])

st.subheader("Key claims & contradictions")
claims = database.query("SELECT * FROM claims WHERE run_id=? ORDER BY claim_id", (run_id,))
st.dataframe(pd.DataFrame(claims)[["claim_id", "claim_type", "claim_text", "supported"]]
             if claims else pd.DataFrame(), use_container_width=True, hide_index=True)
