"""Agent 4 - Public OSINT Collection.

Executes the planned queries for the current layer. In LIVE mode it calls the
configured search connector and retrieves top public pages. In OFFLINE mode it
uses only (a) analyst-supplied manual sources and (b) clearly-labelled SAMPLE
sources for the fictional example vendor. It NEVER fabricates results; failures
and inaccessible sources are recorded honestly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from agents.base import BaseAgent, InvestigationContext
from config.settings import PROJECT_ROOT
from connectors.base import ConnectorResult
from evidence.schemas import RetrievalStatus, SourceRecord

_SAMPLE_PATH = PROJECT_ROOT / "samples" / "offline_sources.json"


def _load_sample_sources(vendor_id: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(Path(_SAMPLE_PATH).read_text(encoding="utf-8"))
        return data.get(vendor_id, [])
    except Exception:
        return []


class CollectionAgent(BaseAgent):
    name = "collection"
    depends_on = ["osint_strategy"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        layer = int(ctx.state.get("current_layer", 1))
        plan = ctx.state.get("layer_plan", {}).get(str(layer), [])
        new_source_ids: List[int] = []
        failures: List[str] = []

        if ctx.live_mode:
            new_source_ids, failures = self._collect_live(ctx, layer, plan)
        else:
            new_source_ids, failures = self._collect_offline(ctx, layer)

        ctx.state.setdefault("sources", []).extend(new_source_ids)
        ctx.state.setdefault("collected_by_layer", {})[str(layer)] = new_source_ids
        return {
            "layer": layer,
            "mode": "live" if ctx.live_mode else "offline",
            "new_sources": len(new_source_ids),
            "failures": failures,
        }

    # ------------------------------------------------------------------ #
    def _persist_result(self, ctx: InvestigationContext, r: ConnectorResult, is_sample: bool = False) -> int:
        return ctx.ledger.record_source(
            SourceRecord(
                run_id=ctx.run_id,
                vendor_id=ctx.vendor_id,
                connector_name=r.connector_name,
                url=r.url,
                canonical_url=r.canonical_url,
                title=r.title,
                source_type=r.source_type,
                source_owner=r.source_owner,
                published_at=r.published_at,
                retrieved_at=r.retrieved_at,
                snippet=r.snippet,
                extracted_text=r.extracted_text,
                http_status=r.http_status,
                retrieval_status=r.retrieval_status,
                content_hash=r.content_hash,
                is_sample=is_sample,
                error_code=r.error_code,
                error_message=r.error_message,
                metadata=r.metadata,
            )
        )

    # ------------------------------------------------------------------ #
    def _collect_live(self, ctx: InvestigationContext, layer: int, plan: List[Dict[str, str]]):
        source_ids: List[int] = []
        failures: List[str] = []
        search = ctx.registry.select_search_connector()
        retrieved_urls: set = set()

        for q in plan:
            if not ctx.budget.can_spend():
                failures.append("query budget exhausted")
                break
            connector_name = q["connector"]
            conn = ctx.registry.get(connector_name)
            if connector_name in ("brave_search", "tavily_search"):
                conn = search or conn  # prefer available search provider
            if not conn or not conn.is_available():
                continue
            ctx.budget.spend()
            results = conn.run(q["query"], vendor_id=ctx.vendor_id, run_id=ctx.run_id)
            self._mark_query_executed(ctx, layer, q["query"], len(results))
            for r in results:
                if r.retrieval_status in (RetrievalStatus.OK,) or r.extracted_text or r.snippet:
                    sid = self._persist_result(ctx, r)
                    source_ids.append(sid)
                else:
                    failures.append(f"{connector_name}: {r.error_code or r.retrieval_status.value}")
                # For search hits in AI-relevant layers, retrieve the page itself.
                if (r.source_type == "web_search_result" and r.url
                        and r.url not in retrieved_urls and layer in (2, 3, 4, 5)
                        and ctx.budget.can_spend()):
                    retrieved_urls.add(r.url)
                    pub = ctx.registry.get("public_web")
                    if pub and pub.is_available():
                        ctx.budget.spend()
                        for page in pub.run(r.url, vendor_id=ctx.vendor_id, run_id=ctx.run_id):
                            source_ids.append(self._persist_result(ctx, page))
        return source_ids, failures

    # ------------------------------------------------------------------ #
    def _collect_offline(self, ctx: InvestigationContext, layer: int):
        source_ids: List[int] = []
        failures: List[str] = ["offline mode: no live search provider configured"]

        # (a) sample sources for the fictional example vendor only (layer 1).
        if ctx.vendor.get("is_example") and layer == 1:
            for s in _load_sample_sources(ctx.vendor_id):
                sid = ctx.ledger.record_source(
                    SourceRecord(
                        run_id=ctx.run_id,
                        vendor_id=ctx.vendor_id,
                        connector_name="offline_sample",
                        url=s.get("url"),
                        title=s.get("title"),
                        source_type=s.get("source_type"),
                        source_owner=s.get("source_owner"),
                        published_at=s.get("published_at"),
                        extracted_text=s.get("extracted_text"),
                        retrieval_status=RetrievalStatus.OK,
                        is_sample=True,
                        metadata={"authority": s.get("authority"), "directness": s.get("directness")},
                    )
                )
                source_ids.append(sid)

        # (b) analyst-supplied manual sources (real, fetched or pasted).
        if layer == 1 and ctx.manual_sources:
            pub = ctx.registry.get("public_web")
            for ms in ctx.manual_sources:
                url = ms.get("url")
                text = ms.get("text")
                if text:
                    sid = ctx.ledger.record_source(
                        SourceRecord(
                            run_id=ctx.run_id, vendor_id=ctx.vendor_id,
                            connector_name="manual_paste", url=url,
                            title=ms.get("title") or "analyst-provided text",
                            source_type="analyst_provided", extracted_text=text,
                            retrieval_status=RetrievalStatus.OK,
                        )
                    )
                    source_ids.append(sid)
                elif url and pub:
                    for page in pub.run(url, vendor_id=ctx.vendor_id, run_id=ctx.run_id):
                        source_ids.append(self._persist_result(ctx, page))
        return source_ids, failures

    # ------------------------------------------------------------------ #
    def _mark_query_executed(self, ctx, layer, query_text, count):
        from database.connection import utcnow
        ctx.db.execute(
            "UPDATE investigation_queries SET status='executed', executed_at=?, result_count=? "
            "WHERE run_id=? AND layer=? AND query_text=? AND status='planned'",
            (utcnow(), count, ctx.run_id, layer, query_text),
        )
