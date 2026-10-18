"""Simple batch scheduler: investigate several vendors sequentially.

Kept intentionally lightweight (no heavyweight agent framework). Each vendor is
an independent run; a failure in one does not abort the batch.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config.logging_config import get_logger
from orchestration.workflow import InvestigationWorkflow

log = get_logger("scheduler")


def investigate_batch(
    vendor_ids: List[str],
    profile: str = "baseline",
    workflow: Optional[InvestigationWorkflow] = None,
) -> List[Dict[str, Any]]:
    wf = workflow or InvestigationWorkflow()
    results: List[Dict[str, Any]] = []
    for vid in vendor_ids:
        try:
            results.append(wf.investigate(vid, profile=profile))
        except Exception as exc:  # pragma: no cover
            log.warning("batch vendor %s failed: %s", vid, exc)
            results.append({"vendor_id": vid, "status": "failed", "error": str(exc)})
    return results
