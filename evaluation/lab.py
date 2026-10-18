"""Evidence-quality benchmark and regression lab (V2.1 §14).

Measures whether the claim classifier is improving, against a MANUALLY LABELLED
fixture set. Reports precision / recall / F1 / false-positive rate for the
confirmed-vs-not decision, plus per-run citation-support and unsupported-claim
rates. Sample sizes are always reported; metrics are never presented without the
count behind them. Benchmark (OPTIV) findings are NOT used here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agents.signals import SignalHit
from database.connection import Database, get_db, utcnow
from evidence.claim_classifier import classify_claim
from evidence.schemas import AIUsageLabel

_CONFIRMED = {
    AIUsageLabel.CONFIRMED_GENAI, AIUsageLabel.CONFIRMED_PRODUCT_FEATURE,
    AIUsageLabel.CONFIRMED_INTEGRATION, AIUsageLabel.CONFIRMED_AI,
}


@dataclass
class _Fixture:
    excerpt: str
    category: str
    source_type: str
    expected_confirmed: bool


# Manually labelled fixtures (expected_confirmed = should this be a CONFIRMED label?).
FIXTURES: List[_Fixture] = [
    _Fixture("Artificial intelligence is transforming finance; this guide explains machine learning.", "ai", "web_page", False),
    _Fixture("Our acceptable use policy prohibits employees from using generative AI with client data.", "generative", "web_page", False),
    _Fixture("Our revolutionary AI-powered platform delivers cutting-edge, world-class intelligence.", "ai", "web_page", False),
    _Fixture("We will launch an AI assistant next quarter.", "ai", "web_page", False),
    _Fixture("We previously offered an AI feature but discontinued it in 2021.", "ai", "web_page", False),
    _Fixture("Customers can enable an optional integration to connect your own OpenAI API key.", "integration", "web_page", False),
    _Fixture("Acme announced a partnership with OpenAI to explore generative AI.", "generative", "web_page", False),
    _Fixture("We are hiring an Applied AI Engineer; requirements include large language models.", "generative", "careers_page", False),
    _Fixture("Our platform uses AI to automatically detect fraud in real time.", "ai", "web_page", True),
    _Fixture("Our product integrates the OpenAI API to generate document summaries for users.", "integration", "web_page", True),
    _Fixture("The assistant drafts and summarises borrower correspondence using generative AI.", "generative", "web_page", True),
    _Fixture("Our engine uses machine learning to classify transactions automatically.", "ai", "web_page", True),
]


def run_classifier_eval(db: Optional[Database] = None) -> Dict[str, Any]:
    db = db or get_db()
    tp = fp = fn = tn = 0
    for fx in FIXTURES:
        hit = SignalHit(category=fx.category, phrase="ai", excerpt=fx.excerpt)
        r = classify_claim(vendor_name="Acme", source={"source_type": fx.source_type}, hit=hit)
        predicted = bool(r and r.classification in _CONFIRMED)
        if predicted and fx.expected_confirmed:
            tp += 1
        elif predicted and not fx.expected_confirmed:
            fp += 1
        elif not predicted and fx.expected_confirmed:
            fn += 1
        else:
            tn += 1
    n = len(FIXTURES)
    precision = round(tp / (tp + fp), 3) if (tp + fp) else None
    recall = round(tp / (tp + fn), 3) if (tp + fn) else None
    f1 = round(2 * precision * recall / (precision + recall), 3) if (precision and recall) else None
    fpr = round(fp / (fp + tn), 3) if (fp + tn) else None
    metrics = {"dataset": "classifier_fixtures_v1", "sample_size": n,
               "precision": precision, "recall": recall, "f1": f1,
               "false_positive_rate": fpr, "tp": tp, "fp": fp, "fn": fn, "tn": tn}
    for name in ("precision", "recall", "f1", "false_positive_rate"):
        if metrics[name] is not None:
            db.insert("eval_metrics", {"dataset": metrics["dataset"], "metric_name": name,
                                       "value": metrics[name], "sample_size": n,
                                       "computed_at": utcnow(),
                                       "notes": f"tp={tp} fp={fp} fn={fn} tn={tn}"})
    db.audit("evaluation", "classifier_eval", detail={"f1": f1, "fpr": fpr, "n": n})
    return metrics


def run_evidence_metrics(run_id: str, db: Optional[Database] = None) -> Dict[str, Any]:
    db = db or get_db()
    claims = db.query("SELECT claim_id, supported, claim_type FROM claims WHERE run_id=?", (run_id,))
    n = len(claims)
    if n == 0:
        return {"run_id": run_id, "sample_size": 0}
    extracted = [c for c in claims if c.get("claim_type") in ("extracted", "inference")]
    supported = [c for c in claims if c.get("supported")]
    cited = 0
    for c in claims:
        if db.query_one("SELECT 1 FROM evidence WHERE claim_id=? LIMIT 1", (c["claim_id"],)):
            cited += 1
    unsupported_rate = round(len([c for c in extracted if not c.get("supported")]) / max(1, len(extracted)), 3)
    citation_rate = round(cited / n, 3)
    metrics = {"run_id": run_id, "sample_size": n, "citation_support_rate": citation_rate,
               "unsupported_claim_rate": unsupported_rate, "supported_claims": len(supported)}
    for name in ("citation_support_rate", "unsupported_claim_rate"):
        db.insert("eval_metrics", {"dataset": f"run:{run_id[:8]}", "metric_name": name,
                                   "value": metrics[name], "sample_size": n,
                                   "computed_at": utcnow(), "notes": None})
    return metrics
