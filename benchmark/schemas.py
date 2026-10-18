"""Benchmark data and evaluation schemas (kept separate from operational types)."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class MatchType(str, Enum):
    EXACT = "exact"
    PARTIAL = "partial"
    MISSED = "missed"              # benchmark found it, automated did not
    FALSE_POSITIVE = "false_positive"  # automated found it, benchmark did not
    INCOMPARABLE = "incomparable"


class BenchmarkRecord(BaseModel):
    vendor_id: Optional[str] = None
    source_file: str
    ai_usage_label: Optional[str] = None     # yes | no | inconclusive (benchmark's verdict)
    named_providers: List[str] = Field(default_factory=list)
    risk_classification: Optional[str] = None
    raw_excerpt: Optional[str] = None


class EvaluationItem(BaseModel):
    vendor_id: Optional[str]
    dimension: str                 # e.g. ai_usage | providers | risk
    automated_value: Optional[str]
    benchmark_value: Optional[str]
    match_type: MatchType
    notes: Optional[str] = None


class EvaluationMetrics(BaseModel):
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0

    @property
    def precision(self) -> Optional[float]:
        denom = self.true_positives + self.false_positives
        return round(self.true_positives / denom, 3) if denom else None

    @property
    def recall(self) -> Optional[float]:
        denom = self.true_positives + self.false_negatives
        return round(self.true_positives / denom, 3) if denom else None

    @property
    def f1(self) -> Optional[float]:
        p, r = self.precision, self.recall
        if not p or not r or (p + r) == 0:
            return None
        return round(2 * p * r / (p + r), 3)
