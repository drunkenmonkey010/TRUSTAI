"""Portfolio (cross-vendor) report generation."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from database.connection import Database, get_db


class PortfolioReport:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def build(self) -> Dict[str, Any]:
        # Latest completed/frozen run per vendor.
        rows = self.db.query(
            """
            SELECT r.*, v.vendor_name, v.category FROM investigation_runs r
            JOIN vendors v ON v.vendor_id = r.vendor_id
            WHERE r.status IN ('completed','frozen')
            GROUP BY r.vendor_id HAVING MAX(r.created_at)
            """
        )
        ai_labels: Counter = Counter()
        priorities: Counter = Counter()
        provider_concentration: Counter = Counter()
        unknowns: List[str] = []
        quality: List[float] = []

        for r in rows:
            ai = self.db.query_one(
                "SELECT label FROM ai_usage_classifications WHERE run_id=? ORDER BY classification_id DESC LIMIT 1",
                (r["run_id"],))
            risk = self.db.query_one(
                "SELECT overall_priority, evidence_confidence, investigation_uncertainty "
                "FROM risk_assessments WHERE run_id=? ORDER BY assessment_id DESC LIMIT 1", (r["run_id"],))
            label = (ai or {}).get("label", "Insufficient evidence")
            ai_labels[label] += 1
            priorities[(risk or {}).get("overall_priority", "?")] += 1
            if risk and (risk.get("investigation_uncertainty") or 0) >= 0.5:
                unknowns.append(r["vendor_id"])
            if risk and risk.get("evidence_confidence") is not None:
                quality.append(risk["evidence_confidence"])
            for rel in self.db.query(
                "SELECT target_entity FROM vendor_relationships WHERE run_id=? AND relation_type='uses_ai_provider'",
                (r["run_id"],)):
                provider_concentration[rel["target_entity"].lower()] += 1

        return {
            "vendor_count": len(rows),
            "ai_label_distribution": dict(ai_labels),
            "priority_distribution": dict(priorities),
            "provider_concentration": dict(provider_concentration.most_common()),
            "vendors_with_high_unknowns": unknowns,
            "mean_evidence_confidence": round(sum(quality) / len(quality), 3) if quality else None,
            "rows": rows,
        }

    def to_markdown(self) -> str:
        d = self.build()
        L = ["# Portfolio AI Risk Report", ""]
        L.append(f"- Vendors assessed: **{d['vendor_count']}**")
        L.append(f"- Mean evidence confidence: {d['mean_evidence_confidence']}")
        L.append("")
        L.append("## AI-use classification distribution")
        for k, v in d["ai_label_distribution"].items():
            L.append(f"- {k}: {v}")
        L.append("")
        L.append("## Risk priority distribution")
        for k, v in d["priority_distribution"].items():
            L.append(f"- {k}: {v}")
        L.append("")
        L.append("## External provider concentration")
        if d["provider_concentration"]:
            for k, v in d["provider_concentration"].items():
                L.append(f"- {k}: referenced for {v} vendor(s)")
        else:
            L.append("- No provider relationships established.")
        L.append("")
        L.append("## Vendors with significant unknowns (uncertainty >= 0.5)")
        L.append(", ".join(d["vendors_with_high_unknowns"]) or "none")
        return "\n".join(L)
