"""Import pipeline tests."""
from __future__ import annotations

from imports.normalization import detect_duplicates, name_similarity, normalize_name
from imports.workbook import build_field_mapping, normalize_records, parse_csv


def test_workbook_parsing_and_mapping(imported_db):
    vendors = imported_db.query("SELECT * FROM vendors ORDER BY vendor_id")
    ids = [v["vendor_id"] for v in vendors]
    assert "V-001" in ids and "V-006" in ids
    # service field was correctly mapped despite the tricky "id" substring.
    v2 = imported_db.query_one("SELECT * FROM vendors WHERE vendor_id='V-002'")
    assert v2["service_provided"]
    assert v2["category"] == "Core Platform"


def test_field_mapping_word_boundary():
    headers = ["Vendor ID", "Vendor Name", "Service / Product Provided", "Category"]
    mapping = build_field_mapping(headers)
    assert mapping["service_provided"] == "Service / Product Provided"
    assert mapping["vendor_id"] == "Vendor ID"


def test_missing_required_columns_are_invalid():
    headers = ["Vendor Name", "Category"]
    rows = [{"Vendor Name": "Acme", "Category": "X"}]
    result = normalize_records(headers, rows)
    # no vendor_id -> invalid
    assert result.valid_count == 0
    assert len(result.invalid_rows) == 1
    assert "vendor_id" in result.invalid_rows[0]["missing"]


def test_empty_values_skip_blank_rows():
    headers = ["Vendor ID", "Vendor Name"]
    rows = [{"Vendor ID": "V-1", "Vendor Name": "A"}, {"Vendor ID": "", "Vendor Name": ""}]
    result = normalize_records(headers, rows)
    assert result.valid_count == 1


def test_duplicate_detection():
    records = [
        {"vendor_id": "V-1", "vendor_name": "Fiserv, Inc."},
        {"vendor_id": "V-2", "vendor_name": "Fiserv Inc"},
        {"vendor_id": "V-3", "vendor_name": "Completely Different Co"},
    ]
    dupes = detect_duplicates(records)
    assert any(d[3] in ("exact", "probable") for d in dupes)
    assert name_similarity("Fiserv, Inc.", "Fiserv Inc") > 0.9


def test_csv_import():
    csv = "Vendor ID,Vendor Name,Category\nV-9,TestCo,Payments\n"
    headers, rows = parse_csv(csv)
    result = normalize_records(headers, rows)
    assert result.valid_count == 1
    assert result.records[0]["vendor_id"] == "V-9"


def test_normalize_name_strips_suffixes():
    assert normalize_name("Acme Corporation Ltd.") == "acme"
