"""Fourth-party / AI supply-chain graph analytics (V2.1 §7).

Analyses evidence-backed relationships across the portfolio: shared-provider
concentration, single points of failure and critical downstream dependencies.
Edges carry provenance and status; uncertainty is kept visible (no invented
edges to make the graph look complete).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from database.connection import Database, get_db


def _latest_runs(db: Database) -> List[Dict[str, Any]]:
    return db.query(
        """
        SELECT r.run_id, r.vendor_id, v.vendor_name, v.criticality_tier
        FROM investigation_runs r JOIN vendors v ON v.vendor_id = r.vendor_id
        WHERE r.status IN ('completed','frozen')
        GROUP BY r.vendor_id HAVING MAX(r.created_at)
        """)


def concentration_analysis(db: Optional[Database] = None) -> Dict[str, Any]:
    db = db or get_db()
    runs = _latest_runs(db)
    provider_vendors: Dict[str, set] = defaultdict(set)
    provider_status: Dict[str, set] = defaultdict(set)
    critical_providers: Dict[str, set] = defaultdict(set)
    edges: List[Dict[str, Any]] = []

    for r in runs:
        tier = (r.get("criticality_tier") or "").lower()
        for rel in db.query(
            "SELECT target_entity, evidence_status, confidence FROM vendor_relationships "
            "WHERE run_id=? AND relation_type='uses_ai_provider'", (r["run_id"],)):
            provider = (rel["target_entity"] or "").lower()
            if not provider:
                continue
            provider_vendors[provider].add(r["vendor_id"])
            provider_status[provider].add(rel.get("evidence_status"))
            if tier in ("critical", "high"):
                critical_providers[provider].add(r["vendor_id"])
            edges.append({"vendor": r["vendor_name"], "provider": rel["target_entity"],
                          "status": rel.get("evidence_status"), "confidence": rel.get("confidence")})

    shared = {p: sorted(v) for p, v in provider_vendors.items() if len(v) > 1}
    spof = {p: sorted(v) for p, v in critical_providers.items() if len(v) >= 2}
    critical_deps = {p: sorted(v) for p, v in critical_providers.items()}
    return {
        "vendor_count": len(runs),
        "provider_count": len(provider_vendors),
        "shared_providers": shared,              # provider -> >1 vendor (concentration)
        "single_points_of_failure": spof,        # provider -> >=2 critical vendors
        "critical_dependencies": critical_deps,  # provider -> critical vendors
        "edges": edges,
        "note": "Edges are evidence-backed relationships; absence of an edge is not proof of none.",
    }


def impact_if_provider_changes(provider: str, db: Optional[Database] = None) -> Dict[str, Any]:
    """Which vendors are affected if a shared provider changes/fails."""
    db = db or get_db()
    analysis = concentration_analysis(db)
    p = provider.lower()
    affected = analysis["shared_providers"].get(p) or analysis["critical_dependencies"].get(p) or []
    return {"provider": provider, "affected_vendors": affected, "count": len(affected)}
