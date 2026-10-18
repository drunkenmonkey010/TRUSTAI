"""AI contract and policy gap analyzer (V2.1 §8).

Analyses AUTHORIZED, uploaded vendor documents (DPAs, privacy policies, AI terms)
for clause-level findings. Uploaded document text is treated strictly as DATA and
never as instructions. 'Not found' means not found in the reviewed material - NOT
that the obligation does not exist elsewhere. No definitive legal conclusions are
made; findings are flagged for authorized legal/procurement review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from database.connection import Database, get_db, utcnow
from evidence.provenance import content_hash


@dataclass
class _Clause:
    category: str
    keywords: List[str]
    related_risk: str
    legal_review: bool


_CLAUSES: List[_Clause] = [
    _Clause("Training use", ["train", "training", "fine-tune", "model improvement", "improve our models"],
            "Customer data used to train models", True),
    _Clause("Retention", ["retention", "retain", "retained", "stored for", "store your data"],
            "Undefined retention of prompts/outputs", True),
    _Clause("Deletion", ["delete", "deletion", "erase", "removal of data", "right to be forgotten"],
            "No deletion guarantee", True),
    _Clause("Subprocessor disclosure", ["subprocessor", "sub-processor", "third party", "third-party provider"],
            "Undisclosed / changeable sub-processors", True),
    _Clause("Audit rights", ["audit", "right to audit", "inspection", "assessment rights"],
            "No audit rights", True),
    _Clause("Incident notification", ["notify", "notification", "breach", "security incident", "within 72 hours"],
            "No incident-notification obligation", True),
    _Clause("Data location & transfer", ["data location", "data residency", "cross-border", "transfer", "region"],
            "Unknown data location / transfers", True),
    _Clause("Confidentiality", ["confidential", "confidentiality", "non-disclosure"],
            "Weak confidentiality terms", False),
    _Clause("Security obligations", ["security measures", "safeguards", "encryption", "technical and organizational"],
            "Unspecified security obligations", False),
    _Clause("AI output responsibility", ["output", "accuracy", "no warranty", "as is", "responsibility for"],
            "Unclear responsibility for AI output", True),
    _Clause("Model / provider changes", ["change the model", "model provider", "replace", "modify the service"],
            "Unnotified model/provider change", True),
    _Clause("Data portability", ["portability", "export your data", "data export"],
            "No data portability", False),
    _Clause("Termination & deletion", ["termination", "terminate", "upon termination", "end of the agreement"],
            "No deletion on termination", True),
    _Clause("Human oversight", ["human review", "human oversight", "human-in-the-loop", "manual review"],
            "No human oversight of AI output", True),
]

_AMBIGUOUS = ["may", "reasonable", "commercially reasonable", "from time to time", "as appropriate",
              "where feasible", "endeavour", "endeavor", "generally", "typically", "subject to"]
_AFFIRM = ["will", "shall", "must", "agrees to", "is required", "provides", "guarantees", "ensures"]
_NEGATE = ["not", "no", "without", "never", "excludes", "prohibits"]


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _has_word(words: List[str], text_low: str) -> bool:
    """Whole-word / phrase match so 'not' does not match inside 'notify'."""
    for w in words:
        w = w.strip()
        if re.search(r"\b" + re.escape(w) + r"\b", text_low):
            return True
    return False


def extract_text(filename: str, data: bytes) -> str:
    """Extract text from an uploaded .txt or .pdf (untrusted DATA)."""
    if filename.lower().endswith(".pdf"):
        try:
            import io

            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception:
            return ""
    try:
        return data.decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def ingest_document(vendor_id: str, filename: str, data: bytes,
                    db: Optional[Database] = None) -> int:
    db = db or get_db()
    text = extract_text(filename, data)
    doc_id = db.insert("contract_documents", {
        "vendor_id": vendor_id, "filename": filename, "file_hash": content_hash(text) or "",
        "uploaded_at": utcnow(), "text_len": len(text), "content": text[:200000],
        "notes": "treated as untrusted data"})
    db.audit("contract", "ingest", subject=vendor_id, detail={"doc_id": doc_id, "filename": filename})
    return doc_id


def _status_for(sentence: str) -> Tuple[str, float]:
    low = sentence.lower()
    if _has_word(_AMBIGUOUS, low):
        return "present_but_ambiguous", 0.4
    if _has_word(_AFFIRM, low):
        return "present_explicit", 0.7
    return "present_but_ambiguous", 0.45


def analyze_document(doc_id: int, db: Optional[Database] = None) -> List[dict]:
    db = db or get_db()
    doc = db.query_one("SELECT * FROM contract_documents WHERE doc_id=?", (doc_id,))
    if not doc:
        raise ValueError("document not found")
    text = doc.get("content") or ""
    sentences = _sentences(text)
    out: List[dict] = []
    for clause in _CLAUSES:
        matches = [s for s in sentences if any(k in s.lower() for k in clause.keywords)]
        if not matches:
            status, excerpt, interp, conf = ("not_found", None,
                "Not found in the reviewed material (may exist elsewhere).", 0.3)
            missing = "Clause not located in this document."
            followup = "Request the governing clause from the vendor."
        else:
            # Conflicting if both affirmative and negating sentences present.
            aff = any(_has_word(_AFFIRM, m.lower()) for m in matches)
            neg = any(_has_word(_NEGATE, m.lower()) for m in matches)
            excerpt = matches[0][:400]
            if aff and neg:
                status, conf = "conflicting", 0.35
                interp = "Affirmative and negating language both present; clause conflicts."
            else:
                status, conf = _status_for(matches[0])
                interp = ("Clause appears present and reasonably explicit."
                          if status == "present_explicit" else
                          "Clause present but uses hedged/ambiguous language.")
            missing = None if status == "present_explicit" else "Specific terms unclear."
            followup = "Confirm scope and obligations with legal/procurement."
        fid = db.insert("contract_findings", {
            "doc_id": doc_id, "vendor_id": doc["vendor_id"], "section_ref": None, "excerpt": excerpt,
            "clause_category": clause.category, "status": status, "interpretation": interp,
            "confidence": conf, "related_risk": clause.related_risk, "missing_details": missing,
            "recommended_followup": followup, "legal_review": int(clause.legal_review),
            "created_at": utcnow()})
        out.append({"finding_id": fid, "category": clause.category, "status": status})
    db.audit("contract", "analyze", subject=doc["vendor_id"], detail={"doc_id": doc_id, "clauses": len(out)})
    return out
