"""Flexible vendor workbook / CSV import and normalization pipeline.

Discovers the header row, maps logical fields to the columns that genuinely
exist (nothing is assumed), preserves original values, detects duplicates and
reports invalid rows. Maintains a traceable link between imported rows and the
persisted vendor records.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from database.connection import Database, get_db, utcnow
from imports.normalization import detect_duplicates, normalize_name, normalize_vendor_id

# Logical field -> candidate header labels (case-insensitive, substring match).
FIELD_ALIASES: Dict[str, List[str]] = {
    "vendor_id": ["vendor id", "vendorid", "id"],
    "vendor_name": ["vendor name", "name", "company"],
    "description": ["vendor description", "description"],
    "service_provided": ["service / product", "service/product", "service provided", "product provided"],
    "category": ["category"],
    "website": ["public website", "website", "domain", "url"],
    "business_process": ["business process supported", "business process"],
    "operational_dependency": ["operational dependency", "dependency"],
    "data_classification": ["data classification accessed", "data classification"],
    "data_volume": ["data volume (annual)", "data volume"],
    "criticality_tier": ["criticality tier"],
}

REQUIRED_FIELDS = ["vendor_id", "vendor_name"]


@dataclass
class ImportResult:
    source_filename: str
    field_mapping: Dict[str, Optional[str]]
    records: List[Dict[str, Any]] = field(default_factory=list)
    invalid_rows: List[Dict[str, Any]] = field(default_factory=list)
    duplicates: List[Tuple[str, str, float, str]] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    import_id: Optional[int] = None

    @property
    def valid_count(self) -> int:
        return len(self.records)

    @property
    def row_count(self) -> int:
        return len(self.records) + len(self.invalid_rows)


# --------------------------------------------------------------------------- #
def _match_header(header: str) -> Optional[str]:
    h = (header or "").strip().lower()
    if not h:
        return None
    for field_name, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if h == alias:
                return field_name
    # fall back to word-boundary match (longest alias first for specificity).
    # Word boundaries stop short aliases like "id" matching inside "provided".
    for field_name, aliases in FIELD_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if re.search(r"\b" + re.escape(alias) + r"\b", h):
                return field_name
    return None


def build_field_mapping(headers: List[str]) -> Dict[str, Optional[str]]:
    """Map each logical field to an actual header, or None if absent."""
    mapping: Dict[str, Optional[str]] = {f: None for f in FIELD_ALIASES}
    used: set = set()
    for logical in FIELD_ALIASES:
        for idx, header in enumerate(headers):
            if idx in used:
                continue
            if _match_header(header) == logical:
                mapping[logical] = header
                used.add(idx)
                break
    return mapping


def _find_header_row(rows: List[Tuple]) -> int:
    """Locate the row index whose cells contain a 'vendor id'-like label."""
    for i, row in enumerate(rows):
        cells = [str(c).strip().lower() if c is not None else "" for c in row]
        if any(c in ("vendor id", "vendorid") for c in cells):
            return i
    return 0


# --------------------------------------------------------------------------- #
def parse_workbook(path: str, sheet_name: Optional[str] = None) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Return (headers, raw row dicts) from an .xlsx file."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    hdr_idx = _find_header_row(rows)
    headers = [str(c).strip() if c is not None else "" for c in rows[hdr_idx]]
    data_rows = []
    for raw in rows[hdr_idx + 1 :]:
        record = {headers[i]: raw[i] for i in range(min(len(headers), len(raw)))}
        if any(v is not None and str(v).strip() for v in record.values()):
            data_rows.append(record)
    return headers, data_rows


def parse_csv(content: bytes | str) -> Tuple[List[str], List[Dict[str, Any]]]:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows = [dict(r) for r in reader]
    return headers, rows


# --------------------------------------------------------------------------- #
def normalize_records(
    headers: List[str],
    raw_rows: List[Dict[str, Any]],
    mapping: Optional[Dict[str, Optional[str]]] = None,
) -> ImportResult:
    mapping = mapping or build_field_mapping(headers)
    result = ImportResult(source_filename="", field_mapping=mapping, headers=headers)

    for raw in raw_rows:
        rec: Dict[str, Any] = {"raw_record": dict(raw)}
        for logical, source_col in mapping.items():
            rec[logical] = raw.get(source_col) if source_col else None

        vid = normalize_vendor_id(rec.get("vendor_id"))
        name = (rec.get("vendor_name") or "")
        name = str(name).strip() if name is not None else ""

        missing = [f for f in REQUIRED_FIELDS if not (rec.get(f) and str(rec.get(f)).strip())]
        if missing:
            result.invalid_rows.append({"raw": raw, "missing": missing})
            continue

        rec["vendor_id"] = vid
        rec["vendor_name"] = name
        rec["normalized_name"] = normalize_name(name)
        rec["is_example"] = 1 if (vid == "V-000" or "example" in name.lower()) else 0
        # Coerce remaining fields to clean strings (preserve None as None).
        for k in list(rec.keys()):
            if k in ("raw_record", "is_example"):
                continue
            v = rec[k]
            rec[k] = str(v).strip() if v is not None else None
        result.records.append(rec)

    result.duplicates = detect_duplicates(result.records)
    return result


# --------------------------------------------------------------------------- #
def persist_import(result: ImportResult, db: Optional[Database] = None) -> int:
    """Write the import + vendor rows, preserving originals. Returns import_id."""
    db = db or get_db()
    import_id = db.insert(
        "vendor_imports",
        {
            "source_filename": result.source_filename,
            "imported_at": utcnow(),
            "row_count": result.row_count,
            "valid_count": result.valid_count,
            "invalid_count": len(result.invalid_rows),
            "field_mapping": result.field_mapping,
            "notes": f"{len(result.duplicates)} potential duplicate pair(s) detected",
        },
    )
    result.import_id = import_id
    for rec in result.records:
        db.execute(
            """
            INSERT INTO vendors (vendor_id, import_id, vendor_name, normalized_name,
                description, service_provided, category, website, business_process,
                operational_dependency, data_classification, data_volume,
                criticality_tier, raw_record, is_example, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(vendor_id) DO UPDATE SET
                import_id=excluded.import_id,
                vendor_name=excluded.vendor_name,
                normalized_name=excluded.normalized_name,
                description=excluded.description,
                service_provided=excluded.service_provided,
                category=excluded.category,
                website=excluded.website,
                business_process=excluded.business_process,
                operational_dependency=excluded.operational_dependency,
                data_classification=excluded.data_classification,
                data_volume=excluded.data_volume,
                raw_record=excluded.raw_record
            """,
            (
                rec["vendor_id"], import_id, rec["vendor_name"], rec["normalized_name"],
                rec.get("description"), rec.get("service_provided"), rec.get("category"),
                rec.get("website"), rec.get("business_process"),
                rec.get("operational_dependency"), rec.get("data_classification"),
                rec.get("data_volume"), rec.get("criticality_tier"),
                __import__("json").dumps(rec["raw_record"], ensure_ascii=False, default=str),
                rec["is_example"], utcnow(),
            ),
        )
    db.audit("import", "persist", subject=result.source_filename,
             detail={"import_id": import_id, "valid": result.valid_count,
                     "invalid": len(result.invalid_rows)})
    return import_id


def import_file(path: str, db: Optional[Database] = None, sheet_name: Optional[str] = None) -> ImportResult:
    """High-level import for a file path (.xlsx or .csv)."""
    import os

    filename = os.path.basename(path)
    if path.lower().endswith((".xlsx", ".xlsm", ".xltx")):
        headers, raw = parse_workbook(path, sheet_name=sheet_name)
    elif path.lower().endswith((".csv", ".tsv")):
        with open(path, "rb") as fh:
            headers, raw = parse_csv(fh.read())
    else:
        raise ValueError(f"Unsupported file type: {filename}")
    result = normalize_records(headers, raw)
    result.source_filename = filename
    persist_import(result, db=db)
    return result
