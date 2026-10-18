"""Agent 1 - Vendor Intake and Identity."""
from __future__ import annotations

from typing import Any, Dict

from agents.base import BaseAgent, InvestigationContext
from evidence.schemas import Claim, ClaimType
from imports.normalization import normalize_name

# Lightweight suffix hints that a name denotes a subsidiary/parent relationship.
_PARENT_HINTS = ["subsidiary", "a division of", "part of", "owned by", "d/b/a", "dba"]


class VendorIntakeAgent(BaseAgent):
    name = "vendor_intake"

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        v = ctx.vendor
        display_name = v.get("vendor_name", "")
        normalized = v.get("normalized_name") or normalize_name(display_name)

        ambiguities = []
        if not v.get("website"):
            ambiguities.append("No public website supplied; official domain unresolved.")
        # Detect parenthetical alternate names, e.g. "FSSI".
        aliases = []
        if "(" in display_name and ")" in display_name:
            alias = display_name[display_name.find("(") + 1 : display_name.find(")")].strip()
            if alias and alias.lower() not in ("fictional, do not edit",):
                aliases.append(alias)

        parent_hint = None
        desc = (v.get("description") or "").lower()
        for hint in _PARENT_HINTS:
            if hint in desc:
                parent_hint = hint
                ambiguities.append(f"Description suggests a corporate relationship ('{hint}'); parent unresolved from case data.")
                break

        profile = {
            "vendor_id": v["vendor_id"],
            "display_name": display_name,
            "normalized_name": normalized,
            "aliases": aliases,
            "website": v.get("website"),
            "category": v.get("category"),
            "description": v.get("description"),
            "service_provided": v.get("service_provided"),
            "parent_hint": parent_hint,
            "identity_ambiguities": ambiguities,
            "is_example": bool(v.get("is_example")),
        }
        ctx.state["identity"] = profile

        # Record an OBSERVATION claim grounded in the operational input (not OSINT).
        ctx.ledger.record_claim(
            Claim(
                run_id=ctx.run_id,
                vendor_id=v["vendor_id"],
                claim_text=f"Vendor '{display_name}' provides: {v.get('service_provided') or v.get('description')}",
                claim_type=ClaimType.OBSERVATION,
                subject=display_name,
                supported=True,  # grounded in supplied operational record
                created_by_agent=self.name,
            )
        )
        ctx.db.audit("agent", "identity_resolved", subject=v["vendor_id"], run_id=ctx.run_id,
                     detail={"aliases": aliases, "ambiguities": len(ambiguities)})
        return profile
