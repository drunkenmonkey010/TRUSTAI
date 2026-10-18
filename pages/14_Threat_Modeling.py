"""Page 14 - Threat Modeling and Attack-Path Analysis (V2.1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from threat_modeling.engine import build_attack_paths, generate_scenarios
from ui_common import db, page_header, select_run

page_header("AI Threat Modeling & Attack-Path Analysis",
            "Scenarios typed hypothetical/plausible — never presented as observed vulnerabilities")
database = db()
run_id, vendor_id = select_run("threat_run")
if not run_id:
    st.stop()

scen = database.query("SELECT * FROM threat_scenarios WHERE run_id=? ORDER BY scenario_id", (run_id,))
if not scen:
    if st.button("Generate threat scenarios"):
        generate_scenarios(run_id, database)
        build_attack_paths(run_id, database)
        st.rerun()
    st.info("No scenarios (generated only when AI use is established).")
    st.stop()

st.subheader("Threat scenarios (OWASP LLM-aligned)")
df = pd.DataFrame(scen)
counts = df["scenario_type"].value_counts().to_dict()
cols = st.columns(3)
cols[0].metric("Plausible", counts.get("plausible", 0))
cols[1].metric("Hypothetical", counts.get("hypothetical", 0))
cols[2].metric("Human-review flagged", int(df["human_review"].sum()))
st.dataframe(df[["threat", "scenario_type", "owasp_ref", "asset", "impact", "mitigations"]],
             use_container_width=True, hide_index=True)
st.caption("Scenario types: plausible (evidence-backed concern) / hypothetical (requires validation). "
           "None are observed vulnerabilities; no exploitation is performed.")

paths = database.query("SELECT * FROM attack_paths WHERE run_id=? ORDER BY rank", (run_id,))
if paths:
    st.subheader("Evidence-based risk paths")
    for p in paths:
        import json
        nodes = json.loads(p["nodes"]) if p["nodes"] else []
        st.markdown(f"**Path #{p['rank']}** ({p['path_type']}): " + " → ".join(nodes))
        st.caption(f"Unknown links: {p['unknown_links']} · impact: {p['business_impact']} · "
                   f"assumptions: {p['assumptions']}")
