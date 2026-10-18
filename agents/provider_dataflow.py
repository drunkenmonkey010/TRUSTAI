"""Agent 8 - Provider and Data-Flow Analysis.

Builds publicly substantiated relationships (vendor -> provider / subprocessor /
cloud) and data-flow findings. It NEVER claims customer data flows to a
particular AI provider unless the evidence supports that specific claim: when a
provider is named but data transmission is undocumented, the provider
relationship is recorded while customer-data flow is marked 'unknown'.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agents.base import BaseAgent, InvestigationContext
from database.connection import utcnow
from evidence.schemas import (
    DataFlowFinding,
    EvidenceStatus,
    Relationship,
    TriState,
)


class ProviderDataflowAgent(BaseAgent):
    name = "provider_dataflow"
    depends_on = ["ai_classification"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        vendor_name = ctx.vendor["vendor_name"]
        provider_candidates = ctx.state.get("provider_candidates", {})
        relationships: List[Dict] = []

        # Build provider relationships from evidence-backed candidates.
        named_any = False
        for sid, providers in provider_candidates.items():
            source = ctx.db.query_one("SELECT * FROM sources WHERE source_id=?", (int(sid),))
            ev = ctx.db.query_one(
                "SELECT evidence_id FROM evidence WHERE source_id=? LIMIT 1", (int(sid),)
            )
            ev_ids = [ev["evidence_id"]] if ev else []
            for provider in set(providers):
                named_any = True
                status = EvidenceStatus.PROBABLE
                # Direct subprocessor/trust docs -> confirmed relationship.
                if source and source.get("source_type") in ("web_page",) and \
                        any(k in (source.get("url") or "") for k in ("subprocessor", "trust", "privacy")):
                    status = EvidenceStatus.CONFIRMED
                rel = Relationship(
                    vendor_id=ctx.vendor_id, run_id=ctx.run_id,
                    source_entity=vendor_name, target_entity=provider,
                    relation_type="uses_ai_provider", confidence=0.6 if status == EvidenceStatus.PROBABLE else 0.8,
                    evidence_status=status, evidence_ids=ev_ids,
                    source_timestamp=source.get("retrieved_at") if source else None,
                )
                self._persist_rel(ctx, rel)
                relationships.append(rel.model_dump())

        # Always record the vendor->Meridian service relationship (operational fact).
        self._persist_rel(ctx, Relationship(
            vendor_id=ctx.vendor_id, run_id=ctx.run_id, source_entity=vendor_name,
            target_entity="Meridian", relation_type="provides_service_to",
            confidence=1.0, evidence_status=EvidenceStatus.CONFIRMED,
        ))

        # Data-flow finding.
        classification = ctx.state.get("ai_classification", {})
        label = classification.get("label", "")
        ai_present = label.startswith("Confirmed") or "indirect" in label.lower()

        data_category = ctx.vendor.get("data_classification")
        # Whether customer data is involved in the AI processing: only 'yes' if
        # documented; otherwise 'unknown'. Never inferred from provider naming.
        customer_data = TriState.UNKNOWN
        transfer = TriState.UNKNOWN
        open_q: List[str] = []
        if ai_present:
            open_q.append("Is Meridian/customer data processed by the AI feature? (not established from public sources)")
            if named_any:
                open_q.append("Is customer data transmitted to the named AI provider(s)? (undocumented)")
            else:
                open_q.append("Which model/AI provider is used? (not named publicly)")
            open_q.append("What are retention and model-training terms for any data processed?")

        retention_hits = [e for e in ctx.ledger.evidence_for_run(ctx.run_id)
                          if "retention" in (e.get("confidence_rationale") or "").lower()
                          or (e.get("source_type") and "privacy" in (e.get("url") or ""))]
        retention_known = bool(retention_hits)

        finding = DataFlowFinding(
            vendor_id=ctx.vendor_id, run_id=ctx.run_id,
            description=(f"AI usage classified as '{label}'. "
                         "Customer-data involvement in AI processing is not established from public sources."
                         if ai_present else
                         "No AI data-flow established from public sources."),
            data_category=data_category,
            destination="; ".join(sorted({p for ps in provider_candidates.values() for p in ps})) or None,
            customer_data_involved=customer_data,
            transfer_established=transfer,
            processing_context=classification.get("deployment_context"),
            retention_terms="documented" if retention_known else "not found in public sources",
            training_terms="not found in public sources",
            confidence=0.4 if ai_present else 0.2,
            evidence_ids=classification.get("evidence_ids", []),
            open_questions="; ".join(open_q) or None,
        )
        ctx.db.insert("data_flow_findings", {
            "run_id": ctx.run_id, "vendor_id": ctx.vendor_id, "description": finding.description,
            "data_category": finding.data_category, "destination": finding.destination,
            "customer_data_involved": finding.customer_data_involved.value,
            "transfer_established": finding.transfer_established.value,
            "processing_context": finding.processing_context,
            "retention_terms": finding.retention_terms, "training_terms": finding.training_terms,
            "confidence": finding.confidence, "evidence_ids": finding.evidence_ids,
            "open_questions": finding.open_questions, "created_at": utcnow(),
        })

        ctx.state["provider_named"] = named_any
        ctx.state["data_flow"] = finding.model_dump()
        ctx.state["data_flow"]["customer_data_involved"] = finding.customer_data_involved.value
        ctx.state["data_flow"]["transfer_established"] = finding.transfer_established.value
        ctx.state["retention_training_known"] = retention_known
        return {
            "relationships": len(relationships),
            "providers_named": named_any,
            "open_questions": open_q,
            "customer_data_involved": customer_data.value,
        }

    def _persist_rel(self, ctx: InvestigationContext, rel: Relationship) -> None:
        ctx.db.insert("vendor_relationships", {
            "run_id": rel.run_id, "vendor_id": rel.vendor_id, "source_entity": rel.source_entity,
            "target_entity": rel.target_entity, "relation_type": rel.relation_type,
            "confidence": rel.confidence, "evidence_status": rel.evidence_status.value,
            "evidence_ids": rel.evidence_ids, "source_timestamp": rel.source_timestamp,
            "created_at": utcnow(),
        })
