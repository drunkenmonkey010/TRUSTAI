"""Page 16 - Provider and Data-Flow / Supply-Chain Intelligence (V2.1)."""
from __future__ import annotations

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from reports.supply_chain import concentration_analysis, impact_if_provider_changes
from ui_common import db, page_header

page_header("Supply-Chain Intelligence",
            "Shared-provider concentration, single points of failure and critical dependencies")
database = db()
a = concentration_analysis(database)

c = st.columns(3)
c[0].metric("Vendors assessed", a["vendor_count"])
c[1].metric("AI providers seen", a["provider_count"])
c[2].metric("Shared providers", len(a["shared_providers"]))

if not a["edges"]:
    st.info("No evidence-backed AI-provider relationships yet. Run live investigations to populate.")
    st.stop()

st.subheader("Portfolio AI supply-chain graph")
G = nx.DiGraph()
for e in a["edges"]:
    G.add_edge(e["vendor"], e["provider"], status=e["status"])
pos = nx.spring_layout(G, seed=7)
ex, ey = [], []
for u, v in G.edges():
    ex += [pos[u][0], pos[v][0], None]
    ey += [pos[u][1], pos[v][1], None]
fig = go.Figure()
fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=1, color="#3a4654"), hoverinfo="none"))
fig.add_trace(go.Scatter(x=[pos[n][0] for n in G.nodes()], y=[pos[n][1] for n in G.nodes()],
              mode="markers+text", text=list(G.nodes()), textposition="top center",
              marker=dict(size=16, color="#2dd4bf")))
fig.update_layout(showlegend=False, height=420, margin=dict(l=10, r=10, t=10, b=10),
                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
st.plotly_chart(fig, use_container_width=True)
st.caption(a["note"])

col1, col2 = st.columns(2)
with col1:
    st.subheader("Shared providers (concentration)")
    st.dataframe(pd.DataFrame([{"provider": k, "vendors": ", ".join(v)}
                 for k, v in a["shared_providers"].items()]) if a["shared_providers"]
                 else pd.DataFrame({"note": ["none"]}), use_container_width=True, hide_index=True)
with col2:
    st.subheader("Single points of failure (≥2 critical vendors)")
    st.dataframe(pd.DataFrame([{"provider": k, "critical_vendors": ", ".join(v)}
                 for k, v in a["single_points_of_failure"].items()]) if a["single_points_of_failure"]
                 else pd.DataFrame({"note": ["none"]}), use_container_width=True, hide_index=True)

st.subheader("Impact analysis")
prov = st.text_input("Provider name (e.g. openai)")
if prov:
    res = impact_if_provider_changes(prov, database)
    st.write(f"If **{prov}** changes/fails, affected vendors: "
             f"{', '.join(res['affected_vendors']) or 'none found'} ({res['count']}).")
