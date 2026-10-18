"""Meridian Vendor AI Intelligence Engine - Streamlit entry point.

Run with:  streamlit run app.py
The nine analyst pages live in ./pages and appear in the sidebar.
"""
from __future__ import annotations

import streamlit as st

from config.logging_config import configure_logging
from database.connection import get_db
from ui_common import ensure_sample_loaded_widget, mode_banner, registry, vendors

configure_logging()
st.set_page_config(page_title="Meridian Vendor AI Intelligence", layout="wide")

# Ensure DB/migrations are initialized.
get_db()

st.title("Meridian Vendor AI Intelligence Engine")
st.caption("Agentic OSINT · AI-usage detection · third-party risk · adaptive investigation · benchmark evaluation")

mode_banner()

st.markdown(
    """
This workbench investigates vendors using **permitted public information**, determines what can be
**substantiated** about their AI usage and data flows, assesses third-party risk with a transparent
deterministic model, adapts investigation depth to uncertainty and criticality, preserves verifiable
evidence, and evaluates itself against a **strictly isolated held-out benchmark**.

**Workflow**
1. Import & validate vendor data → **Vendor Inventory**
2. Configure OSINT / LLM providers → (environment / `.env`)
3. Select scope & depth, run investigations → **Vendor Inventory**
4. Review evidence, uncertainty, risk, recommendations → **Vendor Intelligence / Evidence / Risk**
5. **Freeze** automated results (per vendor)
6. **Unlock** benchmark evaluation explicitly → **Benchmark Evaluation**
7. Load benchmark, compare, generate evaluation report
8. Export artifacts → **Export Center**
"""
)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Vendors imported", len(vendors()))
with col2:
    runs = get_db().query_one("SELECT COUNT(*) c FROM investigation_runs")
    st.metric("Investigation runs", runs["c"] if runs else 0)
with col3:
    snaps = get_db().query_one("SELECT COUNT(*) c FROM frozen_snapshots")
    st.metric("Frozen snapshots", snaps["c"] if snaps else 0)

ensure_sample_loaded_widget()

st.subheader("V2.1 capabilities")
st.markdown(
    "- **Claim-level AI classification** — context-aware; keyword mentions never become confirmed use\n"
    "- **Vendor questionnaires** — gap-driven questions + evidence validation\n"
    "- **Risk register & remediation** — findings lifecycle, risk decisions, audit history\n"
    "- **Control maturity & framework crosswalk** — NIST AI RMF/CSF, ISO 27001/42001, OWASP LLM\n"
    "- **Threat modeling & attack paths** — OWASP-aligned scenarios, typed hypothetical/plausible\n"
    "- **Change detection** — versioned baselines + material-change risk diff\n"
    "- **Supply-chain intelligence** — shared-provider concentration & single points of failure\n"
    "- **Evidence quality lab** — classifier regression metrics with sample sizes"
)

st.subheader("Connector health")
for h in registry().health():
    icon = "🟢" if h.available else "⚪"
    st.write(f"{icon} **{h.name}** — {h.detail}" + (" (no key required)" if not h.requires_key else ""))

st.info("Use the sidebar to open the analyst pages. Secrets are read from the environment and never displayed.")
