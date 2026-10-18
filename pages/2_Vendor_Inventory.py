"""Page 2 - Vendor Inventory (import, mapping, validation, investigation control)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from config.settings import PROJECT_ROOT
from imports.workbook import build_field_mapping, import_file, normalize_records, parse_csv, parse_workbook
from orchestration.workflow import InvestigationWorkflow
from ui_common import db, page_header, registry, vendors

page_header("Vendor Inventory", "Import, validate, map fields, and run investigations")
database = db()

tab_import, tab_table, tab_run = st.tabs(["Import & mapping", "Vendor table", "Run investigations"])

# --------------------------------------------------------------------------- #
with tab_import:
    st.subheader("Upload a workbook (.xlsx) or CSV")
    up = st.file_uploader("Vendor file", type=["xlsx", "csv"])
    if st.button("Use bundled sample workbook"):
        res = import_file(str(PROJECT_ROOT / "samples" / "Meridian_Vendor_Input.xlsx"), db=database)
        st.success(f"Imported {res.valid_count} vendors ({len(res.invalid_rows)} invalid, "
                   f"{len(res.duplicates)} potential duplicate pair(s)).")

    if up is not None:
        suffix = Path(up.name).suffix
        if suffix == ".csv":
            headers, raw = parse_csv(up.getvalue())
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(up.getvalue())
                tmp_path = tmp.name
            headers, raw = parse_workbook(tmp_path)
        mapping = build_field_mapping(headers)
        st.write("**Detected field mapping** (adjust if needed):")
        edited = {}
        options = ["(none)"] + headers
        for logical, src in mapping.items():
            idx = options.index(src) if src in options else 0
            edited[logical] = st.selectbox(logical, options, index=idx, key=f"map_{logical}")
        edited = {k: (None if v == "(none)" else v) for k, v in edited.items()}
        result = normalize_records(headers, raw, edited)
        result.source_filename = up.name
        st.write(f"Preview: **{result.valid_count}** valid, **{len(result.invalid_rows)}** invalid rows.")
        st.dataframe(pd.DataFrame([{k: r.get(k) for k in
                      ("vendor_id", "vendor_name", "category", "website")} for r in result.records]),
                     use_container_width=True, hide_index=True)
        if result.duplicates:
            st.warning("Potential duplicates:")
            st.dataframe(pd.DataFrame(result.duplicates,
                         columns=["vendor_a", "vendor_b", "score", "kind"]), hide_index=True)
        if result.invalid_rows:
            st.error(f"{len(result.invalid_rows)} invalid row(s) will be skipped.")
        if st.button("Confirm import"):
            from imports.workbook import persist_import
            persist_import(result, db=database)
            st.success(f"Imported {result.valid_count} vendors.")

# --------------------------------------------------------------------------- #
with tab_table:
    vs = vendors()
    if not vs:
        st.info("No vendors imported yet.")
    else:
        df = pd.DataFrame(vs)[[
            "vendor_id", "vendor_name", "category", "website", "operational_dependency",
            "data_classification", "criticality_tier", "is_example"]]
        cat = st.multiselect("Filter by category", sorted(df["category"].dropna().unique()))
        if cat:
            df = df[df["category"].isin(cat)]
        st.dataframe(df, use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------- #
with tab_run:
    vs = vendors()
    if not vs:
        st.info("Import vendors first.")
    else:
        mode = registry().execution_mode()
        st.caption(f"Execution mode: **{mode.upper()}**")
        ids = [v["vendor_id"] for v in vs]
        chosen = st.multiselect("Vendors to investigate", ids, default=ids)
        profile = st.radio(
            "Depth profile", ["auto", "baseline", "enhanced", "deep"], horizontal=True, index=0,
            help="'auto' derives depth from each vendor's computed criticality tier "
                 "(Critical/High → deep, Medium → enhanced, Low → baseline). The others force a depth.")
        if profile == "auto":
            st.caption("Auto: depth is chosen per vendor from the 12-dimension criticality assessment.")
        manual_text = st.text_area(
            "Optional: analyst-provided source URL(s) or pasted text (one URL per line). "
            "Used as real evidence in offline mode.", height=80)
        manual_sources = []
        for line in (manual_text or "").splitlines():
            line = line.strip()
            if line.startswith("http"):
                manual_sources.append({"url": line})
            elif line:
                manual_sources.append({"text": line, "title": "analyst note"})

        if st.button("Run investigation(s)", type="primary"):
            wf = InvestigationWorkflow(db=database)
            prog = st.progress(0.0)
            for i, vid in enumerate(chosen):
                with st.spinner(f"Investigating {vid}..."):
                    r = wf.investigate(vid, profile=profile, manual_sources=manual_sources)
                s = r["summary"]
                depth = s.get("resolved_profile", profile)
                depth_note = f"depth {depth}" + (" (auto)" if profile == "auto" else "")
                st.write(f"**{vid}** [{depth_note}]: {s['ai_usage_label']} | "
                         f"priority {s['overall_priority']} | QA {s['qa_reliability']}")
                prog.progress((i + 1) / len(chosen))
            st.success("Investigation(s) complete. See Vendor Intelligence / Risk pages.")

        st.divider()
        st.subheader("Freeze automated results")
        st.caption("Freezing creates an immutable, hashed snapshot required before benchmark unlock.")
        for v in vs:
            run = database.query_one(
                "SELECT run_id, status FROM investigation_runs WHERE vendor_id=? ORDER BY created_at DESC LIMIT 1",
                (v["vendor_id"],))
            if run and run["status"] == "completed":
                if st.button(f"Freeze {v['vendor_id']} ({v['vendor_name'][:30]})", key=f"freeze_{v['vendor_id']}"):
                    from orchestration.run_manager import RunManager
                    sid = RunManager(database).freeze_snapshot(run["run_id"])
                    st.success(f"Frozen snapshot {sid[:8]} (hash verifiable).")
            elif run and run["status"] == "frozen":
                st.caption(f"✅ {v['vendor_id']} already frozen.")
