"""Benchmark evaluator.

Compares FROZEN automated snapshots against parsed benchmark records. It reads
the snapshot read-only and never writes back to it. It independently reveals
missed findings, false positives, unsupported conclusions and confidence
calibration problems.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from benchmark.access_control import BenchmarkAccessController, BenchmarkLockedError
from benchmark.pdf_parser import parse_benchmark
from benchmark.schemas import (
    BenchmarkRecord,
    EvaluationItem,
    EvaluationMetrics,
    MatchType,
)
from database.connection import Database, get_db, utcnow
from orchestration.run_manager import RunManager

# Map automated AIUsageLabel values -> yes | no | inconclusive
_AUTO_MAP = {
    "Confirmed AI use": "yes",
    "Confirmed generative AI use": "yes",
    "Confirmed AI product integration": "yes",
    "Confirmed AI product feature": "yes",
    "Third-party AI relationship confirmed": "yes",
    "AI capability advertised; deployment unverified": "inconclusive",
    "AI use indicated by indirect evidence": "inconclusive",
    "AI mention only": "inconclusive",
    "Conflicting evidence": "inconclusive",
    "Insufficient evidence": "inconclusive",
    "AI use not established": "no",
}


class BenchmarkEvaluator:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()
        self.controller = BenchmarkAccessController(self.db)
        self.run_manager = RunManager(self.db)

    # ------------------------------------------------------------------ #
    def evaluate(self) -> Dict:
        if not self.controller.is_unlocked():
            raise BenchmarkLockedError("Benchmark evaluation is locked. Freeze results and unlock first.")

        benchmark_records = parse_benchmark(self.db)
        bench_by_vendor: Dict[str, BenchmarkRecord] = {
            r.vendor_id: r for r in benchmark_records if r.vendor_id
        }

        items: List[EvaluationItem] = []
        metrics = EvaluationMetrics()

        for vendor_id, bench in bench_by_vendor.items():
            snap = self.run_manager.latest_snapshot_for_vendor(vendor_id)
            if not snap:
                items.append(EvaluationItem(
                    vendor_id=vendor_id, dimension="ai_usage", automated_value=None,
                    benchmark_value=bench.ai_usage_label, match_type=MatchType.MISSED,
                    notes="No frozen automated snapshot for this vendor."))
                if bench.ai_usage_label == "yes":
                    metrics.false_negatives += 1
                continue

            payload = json.loads(snap["payload"])
            auto_label_raw = (payload.get("ai_usage") or {}).get("label")
            auto_val = _AUTO_MAP.get(auto_label_raw, "inconclusive") if auto_label_raw else None

            # --- AI usage dimension ---
            item, mtype = self._compare_ai_usage(vendor_id, auto_val, bench.ai_usage_label, auto_label_raw)
            items.append(item)
            self._tally(metrics, auto_val, bench.ai_usage_label)

            # --- providers dimension ---
            auto_providers = sorted({
                r.get("target_entity", "").lower()
                for r in payload.get("relationships", [])
                if r.get("relation_type") == "uses_ai_provider"
            })
            items.append(self._compare_set(
                vendor_id, "providers", auto_providers, [p.lower() for p in bench.named_providers]))

            # --- risk classification dimension ---
            auto_risk = (payload.get("risk") or {}).get("overall_priority")
            items.append(self._compare_simple(
                vendor_id, "risk", (auto_risk or "").lower() or None,
                (bench.risk_classification or "").lower() or None))

            # --- confidence calibration note ---
            auto_conf = (payload.get("ai_usage") or {}).get("confidence")
            if auto_conf is not None and auto_val and bench.ai_usage_label:
                correct = auto_val == bench.ai_usage_label
                if (auto_conf >= 0.7 and not correct):
                    items.append(EvaluationItem(
                        vendor_id=vendor_id, dimension="confidence_calibration",
                        automated_value=f"confidence={auto_conf}", benchmark_value=bench.ai_usage_label,
                        match_type=MatchType.INCOMPARABLE,
                        notes="High automated confidence on an incorrect verdict (overconfidence)."))

        summary = {
            "precision": metrics.precision, "recall": metrics.recall, "f1": metrics.f1,
            "true_positives": metrics.true_positives, "false_positives": metrics.false_positives,
            "false_negatives": metrics.false_negatives, "true_negatives": metrics.true_negatives,
            "vendors_evaluated": len(bench_by_vendor),
            "items": [i.model_dump() for i in items],
        }
        self._persist(items, summary)
        self.db.audit("benchmark", "evaluate", detail={
            "precision": metrics.precision, "recall": metrics.recall, "f1": metrics.f1})
        return summary

    # ------------------------------------------------------------------ #
    def _compare_ai_usage(self, vendor_id, auto_val, bench_val, raw):
        if auto_val is None or bench_val is None:
            mtype = MatchType.INCOMPARABLE
        elif auto_val == bench_val:
            mtype = MatchType.EXACT
        elif "inconclusive" in (auto_val, bench_val):
            mtype = MatchType.PARTIAL
        elif bench_val == "yes" and auto_val == "no":
            mtype = MatchType.MISSED
        elif bench_val == "no" and auto_val == "yes":
            mtype = MatchType.FALSE_POSITIVE
        else:
            mtype = MatchType.PARTIAL
        return EvaluationItem(
            vendor_id=vendor_id, dimension="ai_usage", automated_value=f"{auto_val} ({raw})",
            benchmark_value=bench_val, match_type=mtype), mtype

    def _compare_set(self, vendor_id, dim, auto_set, bench_set):
        a, b = set(auto_set), set(bench_set)
        if not a and not b:
            mtype = MatchType.INCOMPARABLE
        elif a == b and a:
            mtype = MatchType.EXACT
        elif a & b:
            mtype = MatchType.PARTIAL
        elif b and not a:
            mtype = MatchType.MISSED
        elif a and not b:
            mtype = MatchType.FALSE_POSITIVE
        else:
            mtype = MatchType.INCOMPARABLE
        return EvaluationItem(
            vendor_id=vendor_id, dimension=dim, automated_value=", ".join(sorted(a)) or None,
            benchmark_value=", ".join(sorted(b)) or None, match_type=mtype)

    def _compare_simple(self, vendor_id, dim, auto_val, bench_val):
        if auto_val is None or bench_val is None:
            mtype = MatchType.INCOMPARABLE
        elif auto_val == bench_val:
            mtype = MatchType.EXACT
        elif auto_val in (bench_val or "") or (bench_val in (auto_val or "")):
            mtype = MatchType.PARTIAL
        else:
            mtype = MatchType.PARTIAL
        return EvaluationItem(vendor_id=vendor_id, dimension=dim, automated_value=auto_val,
                              benchmark_value=bench_val, match_type=mtype)

    def _tally(self, metrics: EvaluationMetrics, auto_val, bench_val):
        if bench_val is None or auto_val is None:
            return
        bench_pos = bench_val == "yes"
        auto_pos = auto_val == "yes"
        if auto_pos and bench_pos:
            metrics.true_positives += 1
        elif auto_pos and not bench_pos:
            metrics.false_positives += 1
        elif not auto_pos and bench_pos:
            metrics.false_negatives += 1
        else:
            metrics.true_negatives += 1

    def _persist(self, items: List[EvaluationItem], summary: Dict):
        for it in items:
            snap = self.run_manager.latest_snapshot_for_vendor(it.vendor_id) if it.vendor_id else None
            self.db.insert("benchmark_evaluations", {
                "snapshot_id": snap["snapshot_id"] if snap else "none",
                "vendor_id": it.vendor_id, "evaluated_at": utcnow(),
                "match_type": it.match_type.value, "dimension": it.dimension,
                "automated_value": it.automated_value, "benchmark_value": it.benchmark_value,
                "notes": it.notes,
                "metrics": summary if it.dimension == "ai_usage" else None,
            })
