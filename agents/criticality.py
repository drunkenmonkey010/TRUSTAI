"""Agent 2 - Business Criticality.

Derives a business-criticality tier by assessing twelve deep-criticality
dimensions from the OPERATIONAL INPUT only (vendor description, service, category,
business process, dependency, data classification, data volume). It never reads
the benchmark and does not require live OSINT - criticality is a business-impact
judgement from what Meridian already knows about the vendor.

Each dimension is scored 0-3 with a documented basis and a determinability
status (known / partial / unknown). Dimensions that cannot be established from the
case data are marked 'unknown' and listed - never invented. The overall tier
follows a transparent rubric so another analyst would reach the same answer.

Twelve dimensions:
 1 Business Function Centrality          7 Transaction Integrity Criticality
 2 System-of-Record / Process-of-Authority 8 Data Consequence
 3 Failure Blast Radius                   9 Exit and Substitutability
 4 Time Criticality                      10 Regulatory / Compliance Criticality
 5 Workaround Availability               11 Financial Materiality
 6 Recoverability                        12 Concentration / Dependency Risk
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from agents.base import BaseAgent, InvestigationContext

# ---- shared keyword cues (matched on the operational fields) ----
_DEPENDENCY = {"total": 3, "high": 2, "critical": 3, "moderate": 1, "medium": 1, "low": 0}

_SENSITIVITY_HIGH = ["health", "vulnerab", "financial", "account number", "payment",
                     "card", "credentials", "call audio", "ssn", "social security", "tax",
                     "balances", "transaction"]
_SENSITIVITY_MED = ["personal", "name", "address", "customer", "borrower", "pii"]

_PAYMENTS = ["payment", "clearing", "settlement", "rtp", "ach", "real-time payment",
             "real time payment", "transaction", "wire", "funds"]
_CORE = ["core banking", "core platform", "system of record", "system-of-record", "ledger",
         "account processing", "master", "authoritative", "servicing record", "core"]
_REALTIME = ["real-time", "real time", "nightly", "intraday", "same day", "streaming", "online"]


def _rank(text: str, highs: List[str], meds: List[str]) -> int:
    low = (text or "").lower()
    if "no direct customer data" in low or "in transit only" in low or "not applicable" in low:
        return 0
    if any(k in low for k in highs):
        return 2
    if any(k in low for k in meds):
        return 1
    return 0


def _volume_scale(text: str) -> Tuple[int, str]:
    """Return (0-3 score, status) for annual data volume magnitude."""
    low = (text or "").lower()
    if not low or "not applicable" in low:
        return 0, "unknown"
    if "billion" in low:
        return 3, "known"
    # pull the largest integer (handles '240,000', '1.4 million', '19 million').
    # Require a leading digit so a stray comma is not matched as a number.
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", low)]
    biggest = max(nums) if nums else 0
    if "million" in low or biggest >= 1_000_000:
        return 3, "known"
    if biggest >= 10_000:
        return 2, "known"
    if biggest > 0:
        return 1, "known"
    return 1, "partial"


class CriticalityAgent(BaseAgent):
    name = "criticality"
    depends_on = ["vendor_intake"]

    def execute(self, ctx: InvestigationContext) -> Dict[str, Any]:
        v = ctx.vendor
        provided_tier = (v.get("criticality_tier") or "").strip()

        text = " ".join(str(v.get(f) or "") for f in
                        ("description", "service_provided", "business_process")).lower()
        cat = (v.get("category") or "").lower()
        dep_raw = (v.get("operational_dependency") or "").strip().lower()
        data_cls = v.get("data_classification") or ""

        dep_score = _DEPENDENCY.get(dep_raw)
        dep_known = dep_score is not None
        if dep_score is None:
            dep_score = 1
        sens = _rank(data_cls, _SENSITIVITY_HIGH, _SENSITIVITY_MED)      # 0..2
        data_consequence = min(3, sens + (1 if sens == 2 else 0))        # 0..3
        vol_score, vol_status = _volume_scale(v.get("data_volume"))

        is_pay = any(k in (cat + " " + text) for k in _PAYMENTS)
        is_core = any(k in (cat + " " + text) for k in _CORE)
        is_infra = "infrastructure" in cat
        is_realtime = any(k in text for k in _REALTIME) or is_pay
        sole_hint = any(k in text for k in ["sole", "single provider", "only provider", "sole-source"])

        dims: Dict[str, Dict[str, Any]] = {}

        def add(name: str, score: int, status: str, basis: str) -> None:
            dims[name] = {"score": int(score), "status": status, "basis": basis}

        # 1 Business Function Centrality
        if is_core or is_pay or is_infra:
            add("business_function_centrality", 3, "known",
                "Core/payments/infrastructure vendor central to a primary process.")
        elif any(k in cat for k in ["data", "reporting", "document", "communication"]):
            add("business_function_centrality", 2, "known",
                "Supports an important reporting/communications process.")
        else:
            add("business_function_centrality", 1, "partial", "Supporting/professional service.")

        # 2 System-of-Record / Process-of-Authority Dependency
        if is_core:
            add("system_of_record_dependency", 3, "known",
                "Acts as or feeds a system/process of record (core/ledger/master).")
        elif any(k in text for k in ["reconcil", "reporting", "statement", "record"]):
            add("system_of_record_dependency", 2, "partial",
                "Produces records/reports but authority source unclear from case.")
        else:
            add("system_of_record_dependency", 1, "unknown",
                "Authority/system-of-record role not established from case data.")

        # 3 Failure Blast Radius (dependency x volume)
        blast = max(dep_score, vol_score) if (dep_known or vol_status == "known") else 1
        add("failure_blast_radius", min(3, blast),
            "known" if dep_known or vol_status == "known" else "unknown",
            f"Dependency={dep_raw or 'unknown'} ({dep_score}), volume score {vol_score}.")

        # 4 Time Criticality
        if is_realtime:
            add("time_criticality", 3, "known", "Real-time/payments/near-real-time processing.")
        elif any(k in text for k in ["batch", "schedul", "nightly", "cycle"]):
            add("time_criticality", 2, "known", "Scheduled/batch processing with time sensitivity.")
        else:
            add("time_criticality", 1, "unknown", "Time sensitivity not established from case data.")

        # 5 Workaround Availability (less workaround => higher criticality)
        if sole_hint:
            add("workaround_availability", 3, "known", "Case text indicates a sole/single provider.")
        else:
            add("workaround_availability", 2, "unknown",
                "Availability of an alternative/workaround not established from case data.")

        # 6 Recoverability (rarely derivable from case)
        add("recoverability", 2, "unknown",
            "Recovery time/architecture not available from case; carried to follow-up.")

        # 7 Transaction Integrity Criticality
        if is_pay or any(k in text for k in ["transaction", "ledger", "settlement", "posting"]):
            add("transaction_integrity", 3, "known", "Handles payment/transaction integrity.")
        elif any(k in text for k in ["calculation", "commission", "compensation", "accounting"]):
            add("transaction_integrity", 2, "known", "Performs financial calculations.")
        else:
            add("transaction_integrity", 1, "partial", "Limited transaction-integrity exposure.")

        # 8 Data Consequence
        add("data_consequence", data_consequence,
            "known" if data_cls else "unknown",
            f"Highest data sensitivity accessed: '{data_cls or 'unknown'}'.")

        # 9 Exit and Substitutability
        if is_core or is_infra:
            add("exit_substitutability", 3, "partial",
                "Core/infrastructure dependency is typically hard to exit; validation required.")
        elif "professional services" in cat:
            add("exit_substitutability", 2, "partial", "Specialist service; substitution effort unclear.")
        else:
            add("exit_substitutability", 2, "unknown", "Substitutability not established from case data.")

        # 10 Regulatory / Compliance Criticality
        if any(k in (data_cls.lower() + " " + text) for k in
               ["financial", "payment", "tax", "account number", "regulat", "borrower", "card"]):
            add("regulatory_compliance", 3, "known", "Regulated financial/payment/PII data involved.")
        elif sens >= 1:
            add("regulatory_compliance", 2, "known", "Personal data with compliance obligations.")
        else:
            add("regulatory_compliance", 1, "unknown", "Regulatory exposure not established from case data.")

        # 11 Financial Materiality (volume + payments)
        fin = vol_score
        if is_pay and vol_score >= 2:
            fin = 3
        add("financial_materiality", fin, vol_status,
            f"Annual volume: '{v.get('data_volume') or 'unknown'}' (score {vol_score}).")

        # 12 Concentration / Dependency Risk
        if dep_known and dep_score >= 2:
            score12 = 3 if sole_hint else 2
            add("concentration_dependency", score12, "known",
                f"High operational dependency ({dep_raw}){'; sole-source hint' if sole_hint else ''}.")
        else:
            add("concentration_dependency", 1 if dep_known else 2,
                "known" if dep_known else "unknown",
                "Concentration/sole-source status not fully established from case data.")

        # ---- aggregate to a tier ----
        scores = [d["score"] for d in dims.values()]
        mean = round(sum(scores) / len(scores), 2)
        critical_count = sum(1 for s in scores if s >= 3)
        if critical_count >= 5 or mean >= 2.3:
            derived = "Critical"
        elif critical_count >= 3 or mean >= 1.7:
            derived = "High"
        elif mean >= 1.1:
            derived = "Medium"
        else:
            derived = "Low"

        unknown_dims = [k for k, d in dims.items() if d["status"] == "unknown"]
        tier = provided_tier or derived

        top = sorted(dims.items(), key=lambda kv: kv[1]["score"], reverse=True)[:4]
        rationale = (
            f"Derived tier '{derived}' from 12 deep-criticality dimensions "
            f"(mean {mean}/3, {critical_count} rated Critical). "
            "Top drivers: " + "; ".join(f"{k.replace('_',' ')} ({d['score']})" for k, d in top) + ". "
            + (f"Unknown from case data: {', '.join(d.replace('_',' ') for d in unknown_dims)}. "
               if unknown_dims else "")
        )
        if provided_tier and provided_tier.lower() != derived.lower():
            rationale += f"NOTE: operational input supplied tier '{provided_tier}', differing from derived."

        result = {
            "criticality_tier": tier,
            "derived_tier": derived,
            "provided_tier": provided_tier or None,
            "rationale": rationale,
            "mean_dimension_score": mean,
            "critical_dimension_count": critical_count,
            "dimensions": dims,
            "unknown_dimensions": unknown_dims,
            "missing_fields": [f for f in ("operational_dependency", "data_classification")
                               if not v.get(f)],
            "data_sensitivity_rank": sens,
        }
        ctx.state["criticality"] = result
        ctx.db.execute("UPDATE vendors SET criticality_tier=? WHERE vendor_id=?",
                       (tier, v["vendor_id"]))
        ctx.vendor["criticality_tier"] = tier
        return result
