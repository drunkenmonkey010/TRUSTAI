"""Page 15 - Change Detection and Reassessment (V2.1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from monitoring.change_detector import capture_baseline, detect_changes, latest_baseline
from ui_common import db, page_header, vendors

page_header("Change Detection & Reassessment",
            "Versioned vendor baselines and material-change risk diff (manual refresh)")
database = db()
st.caption("No background scheduler is claimed — this is an explicit manual-refresh workflow. "
           "Previous assessments are never silently overwritten.")

vs = vendors()
if not vs:
    st.info("Import vendors first.")
    st.stop()
label = {f"{v['vendor_id']} · {v['vendor_name']}": v["vendor_id"] for v in vs}
vid = label[st.selectbox("Vendor", list(label.keys()))]

base = latest_baseline(vid, database)
if base:
    st.success(f"Baseline captured {base['captured_at'][:19]} (hash {base['content_hash'][:12]}…)")
else:
    st.warning("No baseline yet — run an investigation (a baseline is captured automatically).")

events = database.query("SELECT detected_at, change_type, field, previous_value, new_value, "
                       "materiality, risk_impact, reassessment_required, recommended_action "
                       "FROM change_events WHERE vendor_id=? ORDER BY event_id DESC", (vid,))
st.subheader("Change events")
if events:
    df = pd.DataFrame(events)
    material = df[df["materiality"] == "material"]
    st.metric("Material changes", len(material))
    st.dataframe(df, use_container_width=True, hide_index=True)
    if len(material):
        st.warning("Material changes detected — reassessment recommended for the affected findings.")
else:
    st.info("No change events recorded. Run a new investigation and compare against the baseline.")

latest_run = database.query_one(
    "SELECT run_id FROM investigation_runs WHERE vendor_id=? ORDER BY created_at DESC LIMIT 1", (vid,))
if latest_run and st.button("Diff latest run against baseline"):
    ev = detect_changes(vid, latest_run["run_id"], database)
    st.write(f"Detected {len(ev)} change event(s).")
    st.rerun()
