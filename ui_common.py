"""Shared helpers for the Streamlit interface."""
from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from config.settings import get_settings
from connectors.registry import ConnectorRegistry
from database.connection import get_db
from orchestration.run_manager import RunManager


def db():
    return get_db()


def settings():
    return get_settings()


def registry() -> ConnectorRegistry:
    return ConnectorRegistry(get_settings(), get_db())


def run_manager() -> RunManager:
    return RunManager(get_db())


_THEME_CSS = """
<style>
:root { --mrd-bg:#0f141b; --mrd-panel:#161d27; --mrd-accent:#2dd4bf; --mrd-text:#d7dee6; }
.stApp { background: #0f141b; }
section[data-testid="stSidebar"] { background:#131a23; border-right:1px solid #222c38; }
h1, h2, h3 { color:#eef3f8 !important; letter-spacing:-0.01em; }
.stApp, .stMarkdown, p, label, span { color:#c7d0da; }
[data-testid="stMetric"] { background:#161d27; border:1px solid #222c38; border-radius:10px;
    padding:12px 14px; }
[data-testid="stMetricValue"] { color:#2dd4bf; }
.stDataFrame, .stTable { border-radius:8px; }
.stTabs [data-baseweb="tab"] { font-size:14px; }
div.stButton > button { border:1px solid #2b3744; background:#1a232e; color:#d7dee6; border-radius:8px; }
div.stButton > button:hover { border-color:#2dd4bf; color:#2dd4bf; }
hr { border-color:#222c38; }
</style>
"""


def inject_theme() -> None:
    try:
        st.markdown(_THEME_CSS, unsafe_allow_html=True)
    except Exception:
        pass


def page_header(title: str, subtitle: str = "") -> None:
    st.set_page_config(page_title=f"Meridian - {title}", layout="wide")
    inject_theme()
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    mode_banner()


def mode_banner() -> None:
    reg = registry()
    mode = reg.execution_mode()
    s = settings()
    if mode == "live":
        st.success("LIVE OSINT mode - a live search provider is configured.", icon="🟢")
    else:
        st.warning(
            "OFFLINE / DEMO mode - no live search provider configured. "
            "Results use analyst-provided or clearly-labelled SAMPLE sources only; "
            "this is NOT live OSINT.", icon="🟠")
    if not s.llm_enabled:
        st.caption("LLM: disabled (deterministic processing). Classifications and scores are rule-based.")


def vendors() -> List[Dict[str, Any]]:
    return get_db().query("SELECT * FROM vendors ORDER BY vendor_id")


def select_run(key: str = "run"):
    """Render a run selector; returns (run_id, vendor_id) or (None, None)."""
    rows = get_db().query(
        "SELECT r.run_id, r.vendor_id, v.vendor_name, r.created_at, r.status "
        "FROM investigation_runs r JOIN vendors v ON v.vendor_id=r.vendor_id "
        "ORDER BY r.created_at DESC")
    if not rows:
        st.info("No investigation runs yet. Run one on the Vendor Inventory page.")
        return None, None
    labels = {f"{r['vendor_id']} · {r['vendor_name'][:30]} · {r['status']} · {r['created_at'][:19]}":
              (r["run_id"], r["vendor_id"]) for r in rows}
    choice = st.selectbox("Investigation run", list(labels.keys()), key=key)
    return labels[choice]


def ensure_sample_loaded_widget() -> None:
    if not vendors():
        st.info("No vendors imported yet.")
        if st.button("Load bundled sample workbook (Meridian_Vendor_Input.xlsx)"):
            from config.settings import PROJECT_ROOT
            from imports.workbook import import_file
            path = PROJECT_ROOT / "samples" / "Meridian_Vendor_Input.xlsx"
            res = import_file(str(path), db=get_db())
            st.success(f"Imported {res.valid_count} vendors.")
            st.rerun()
