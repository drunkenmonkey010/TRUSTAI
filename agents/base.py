"""Agent base class and shared investigation context.

Agents are small, typed units with explicit dependencies. Each records an
``agent_runs`` row with status, timestamps, retries, current action and a
structured JSON output so the Agent Monitor can show real (not fake) progress.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agents.llm import LLMClient
from config.logging_config import get_logger
from config.settings import Settings, get_settings
from connectors.registry import ConnectorRegistry
from database.connection import Database, get_db, utcnow
from evidence.ledger import EvidenceLedger


@dataclass
class QueryBudget:
    total: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.used)

    def can_spend(self, cost: int = 1) -> bool:
        return self.used + cost <= self.total

    def spend(self, cost: int = 1) -> bool:
        if not self.can_spend(cost):
            return False
        self.used += cost
        return True


@dataclass
class InvestigationContext:
    run_id: str
    vendor: Dict[str, Any]
    profile: str
    live_mode: bool
    registry: ConnectorRegistry
    ledger: EvidenceLedger
    db: Database
    llm: LLMClient
    settings: Settings
    budget: QueryBudget
    # Shared, growing state across agents.
    state: Dict[str, Any] = field(default_factory=dict)
    # Optional analyst-provided source URLs / pasted text (offline enrichment).
    manual_sources: List[Dict[str, str]] = field(default_factory=list)

    @property
    def vendor_id(self) -> str:
        return self.vendor["vendor_id"]

    def log(self) -> Any:
        return get_logger(f"agent.{self.run_id[:8]}")


@dataclass
class AgentResult:
    agent_name: str
    status: str
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    retries: int = 0


class BaseAgent:
    name: str = "base_agent"
    #: names of agents that must have completed before this one
    depends_on: List[str] = []
    max_retries: int = 1

    def __init__(self):
        self.log = get_logger(f"agent.{self.name}")

    # ------------------------------------------------------------------ #
    def run(self, ctx: InvestigationContext) -> AgentResult:
        agent_run_id = ctx.db.insert(
            "agent_runs",
            {
                "run_id": ctx.run_id,
                "agent_name": self.name,
                "status": "running",
                "started_at": utcnow(),
                "current_action": "starting",
            },
        )
        attempt = 0
        last_err: Optional[str] = None
        while attempt <= self.max_retries:
            try:
                output = self.execute(ctx) or {}
                ctx.db.execute(
                    "UPDATE agent_runs SET status=?, finished_at=?, retries=?, current_action=?, output=? "
                    "WHERE agent_run_id=?",
                    ("completed", utcnow(), attempt, "done",
                     json.dumps(output, ensure_ascii=False, default=str), agent_run_id),
                )
                ctx.state[self.name] = output
                return AgentResult(self.name, "completed", output, retries=attempt)
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                self.log.warning("agent=%s attempt=%s error=%s", self.name, attempt, last_err)
                self.log.debug(traceback.format_exc())
                attempt += 1
        ctx.db.execute(
            "UPDATE agent_runs SET status=?, finished_at=?, retries=?, error=? WHERE agent_run_id=?",
            ("failed", utcnow(), attempt, last_err, agent_run_id),
        )
        return AgentResult(self.name, "failed", {}, error=last_err, retries=attempt)

    # ------------------------------------------------------------------ #
    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError
