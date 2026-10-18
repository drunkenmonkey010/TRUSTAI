"""Claim-level AI classification (V2.1).

This is the core fix for keyword false-positives. A keyword match is a DISCOVERY
signal only; it never, by itself, establishes confirmed AI use. For every signal
hit we analyse the surrounding context and resolve:

  * context    - is this a product claim, policy/discussion, marketing, a future
                 plan, a historical/discontinued feature, a customer-controlled
                 integration, a third-party partnership, or a job advert?
  * temporal   - present / planned / historical
  * deployment - released / beta / planned / discontinued / unknown
  * data-flow implication
  * directness & authority of the source

and only then choose a classification. A first-party page that *mentions* AI in a
security policy, a blog that *discusses* AI, or marketing that *advertises* AI are
NOT confirmed use.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from agents.signals import GENERATIVE_TERMS, PROVIDER_NAMES, SignalHit
from evidence.schemas import AIUsageLabel, Authority, ClaimType, Directness

# --------------------------------------------------------------------------- #
# Context vocabularies (matched on the excerpt, lower-cased)
# --------------------------------------------------------------------------- #
_POLICY = ["policy", "prohibit", "prohibited", "not permitted", "must not", "do not use",
           "acceptable use", "guideline", "we restrict", "restricted", "banned", "is banned",
           "disallow", "code of conduct", "employees may not", "staff must not"]
_DISCUSSION = ["what is ", "how ai", "ai is transforming", "the future of", "explained",
               "introduction to", "benefits of ai", "glossary", "understanding ai",
               "thought leadership", "our perspective on", "a guide to", "trends in ai"]
_FUTURE = ["will launch", "will introduce", "will add", "coming soon", "roadmap", "plan to",
           "plans to", "planned", "intend to", "intends to", "in the coming", "future release",
           "upcoming", "we are building", "we're building", "soon be", "later this year",
           "next quarter", "will be available"]
_HISTORICAL = ["previously", "used to", "no longer", "discontinued", "deprecated", "retired",
               "sunset", "formerly", "has been removed", "was removed", "end of life",
               "end-of-life", "in the past"]
_CUSTOMER = ["bring your own", "byo", "you can connect", "optional integration",
             "customers can enable", "configure your own", "your own api key", "opt-in",
             "opt in", "you may integrate", "connect your own", "customer-managed",
             "customer managed", "if you choose to enable", "disabled by default"]
_PARTNERSHIP = ["partnership with", "partnered with", "partnering with", "collaboration with",
                "in collaboration", "strategic partner", "announced a partnership",
                "teamed up with", "alliance with"]
_JOBAD = ["we are hiring", "we're hiring", "now hiring", "job description", "responsibilities",
          "requirements", "apply now", "join our team", "we are looking for", "ideal candidate",
          "years of experience", "qualifications"]
_MARKETING = ["revolutionary", "cutting-edge", "cutting edge", "next-generation", "next generation",
              "transform your", "unlock", "supercharge", "world-class", "world class",
              "game-changing", "game changing", "best-in-class", "reimagine", "empower your"]
# Functional verbs = the AI actually DOES something in the product (present tense).
_ACTION_VERBS = ["draft", "summar", "detect", "generat", "classif", "predict", "recommend",
                 "automat", "transcrib", "analy", "progress", "orchestrat", "respond",
                 "answer", "route", "flag", "extract", "translate", "personaliz"]

_FIRST_PARTY_TYPES = {"social_post", "careers_page", "web_page", "sec_filing", "analyst_provided"}


@dataclass
class ClaimAnalysis:
    classification: Optional[AIUsageLabel]
    claim_type: ClaimType
    context_label: str                       # product|policy|discussion|future|historical|customer|partnership|jobad|marketing|mention
    subject: Optional[str] = None
    product: Optional[str] = None
    action: Optional[str] = None             # signal category (ai|generative|integration)
    deployment_status: str = "unknown"       # released|beta|planned|discontinued|unknown
    temporal_scope: str = "present"          # present|planned|historical
    data_flow_implication: str = "unknown"   # vendor|customer_controlled|third_party|unknown
    directness: Directness = Directness.INDIRECT
    authority: Authority = Authority.UNKNOWN
    confidence: float = 0.0
    rationale: str = ""
    providers: List[str] = field(default_factory=list)


def _authority_for(source_type: Optional[str]) -> Authority:
    if source_type in ("corporate_registry",):
        return Authority.INDEPENDENT
    if source_type == "web_search_result":
        return Authority.AGGREGATOR
    if source_type in _FIRST_PARTY_TYPES:
        return Authority.FIRST_PARTY
    return Authority.UNKNOWN


def _detect_context(excerpt: str, source_type: Optional[str]) -> str:
    low = excerpt.lower()
    if any(k in low for k in _POLICY):
        return "policy"
    if any(k in low for k in _DISCUSSION):
        return "discussion"
    if any(k in low for k in _HISTORICAL):
        return "historical"
    if any(k in low for k in _FUTURE):
        return "future"
    if any(k in low for k in _CUSTOMER):
        return "customer"
    if any(k in low for k in _PARTNERSHIP):
        return "partnership"
    if source_type == "careers_page" or any(k in low for k in _JOBAD):
        return "jobad"
    if any(v in low for v in _ACTION_VERBS):
        return "product"
    if any(k in low for k in _MARKETING):
        return "marketing"
    return "mention"


def classify_claim(*, vendor_name: str, source: dict, hit: SignalHit) -> Optional[ClaimAnalysis]:
    """Classify a single AI signal hit in context. Returns None for non-AI hits."""
    if hit.category not in ("ai", "generative", "integration"):
        return None

    excerpt = hit.excerpt or ""
    low = excerpt.lower()
    source_type = source.get("source_type")
    authority = _authority_for(source_type)
    first_party = authority == Authority.FIRST_PARTY
    is_generative = (hit.category == "generative") or any(
        re.search(t if t.startswith("\\b") else re.escape(t), low) for t in GENERATIVE_TERMS)
    providers = [p for p in PROVIDER_NAMES if re.search(r"\b" + re.escape(p) + r"\b", low)]

    ctx = _detect_context(excerpt, source_type)
    temporal = "present"
    deployment = "unknown"
    data_flow = "vendor"
    directness = Directness.INDIRECT
    claim_type = ClaimType.INFERENCE
    rationale = ""

    if ctx == "policy":
        cls = AIUsageLabel.MENTION_ONLY
        claim_type = ClaimType.OBSERVATION
        rationale = "AI mentioned in a policy / prohibition context, not a product capability."
    elif ctx == "discussion":
        cls = AIUsageLabel.MENTION_ONLY
        claim_type = ClaimType.OBSERVATION
        rationale = "AI discussed educationally / thought-leadership, not a vendor capability."
    elif ctx == "historical":
        cls = AIUsageLabel.NOT_ESTABLISHED
        temporal = "historical"
        deployment = "discontinued"
        rationale = "Feature described as historical / discontinued; current use not established."
    elif ctx == "future":
        cls = AIUsageLabel.ADVERTISED_UNVERIFIED
        temporal = "planned"
        deployment = "planned"
        rationale = "Capability announced as planned / future; deployment unverified."
    elif ctx == "customer":
        cls = AIUsageLabel.ADVERTISED_UNVERIFIED
        data_flow = "customer_controlled"
        rationale = "Customer-controlled / optional AI integration; not the vendor's own AI use."
    elif ctx == "partnership":
        cls = AIUsageLabel.THIRD_PARTY_RELATIONSHIP
        data_flow = "third_party"
        rationale = "Third-party AI partnership stated; deployment in the consumed product unverified."
    elif ctx == "jobad":
        cls = AIUsageLabel.INDIRECT
        rationale = "AI skills in a job advert imply AI work but do not establish a deployed feature."
    elif ctx == "product" and first_party:
        directness = Directness.DIRECT
        claim_type = ClaimType.EXTRACTED
        deployment = "released"
        if is_generative:
            cls = AIUsageLabel.CONFIRMED_GENAI
            rationale = "First-party statement of a functioning generative-AI capability."
        elif hit.category == "integration" or "api" in low:
            cls = AIUsageLabel.CONFIRMED_INTEGRATION
            rationale = "First-party statement of an integrated AI capability/API."
        else:
            cls = AIUsageLabel.CONFIRMED_PRODUCT_FEATURE
            rationale = "First-party statement of a functioning AI product feature."
    elif ctx == "product" and not first_party:
        cls = AIUsageLabel.INDIRECT
        rationale = "Functional AI claim from a non-first-party source; corroboration needed."
    elif ctx == "marketing":
        cls = AIUsageLabel.ADVERTISED_UNVERIFIED
        rationale = "AI advertised with marketing language but no functional capability stated."
    else:  # mention
        cls = AIUsageLabel.MENTION_ONLY
        claim_type = ClaimType.OBSERVATION
        rationale = "AI term present without a functional, deployed capability claim."

    # Confidence: deterministic, driven by authority + directness + context certainty.
    confidence = 0.2
    if cls in (AIUsageLabel.CONFIRMED_GENAI, AIUsageLabel.CONFIRMED_PRODUCT_FEATURE,
               AIUsageLabel.CONFIRMED_INTEGRATION):
        confidence = 0.75
    elif cls in (AIUsageLabel.THIRD_PARTY_RELATIONSHIP, AIUsageLabel.INDIRECT):
        confidence = 0.5
    elif cls == AIUsageLabel.ADVERTISED_UNVERIFIED:
        confidence = 0.4
    elif cls in (AIUsageLabel.MENTION_ONLY, AIUsageLabel.NOT_ESTABLISHED):
        confidence = 0.15

    return ClaimAnalysis(
        classification=cls, claim_type=claim_type, context_label=ctx,
        subject=vendor_name, product=None, action=hit.category,
        deployment_status=deployment, temporal_scope=temporal, data_flow_implication=data_flow,
        directness=directness, authority=authority, confidence=round(confidence, 2),
        rationale=rationale, providers=providers,
    )


_CONFIRMED_LABELS = {
    AIUsageLabel.CONFIRMED_GENAI, AIUsageLabel.CONFIRMED_PRODUCT_FEATURE,
    AIUsageLabel.CONFIRMED_INTEGRATION, AIUsageLabel.CONFIRMED_AI,
}
_DOWNGRADE_MARKERS = _POLICY + _DISCUSSION + _FUTURE + _HISTORICAL + _CUSTOMER


def verify_support(classification: AIUsageLabel, excerpt: str, source_type: Optional[str]):
    """Independent check that the excerpt actually supports a CONFIRMED claim.

    Returns (verified: bool, effective_label: AIUsageLabel, rationale: str). A
    confirmed claim is downgraded to 'AI mention only' unless the excerpt is
    first-party, states a functional capability, and carries no negating /
    future / historical / policy / customer-controlled markers.
    """
    if classification not in _CONFIRMED_LABELS:
        return True, classification, "non-confirmed claim; no downgrade gate applied"
    low = (excerpt or "").lower()
    first_party = _authority_for(source_type) == Authority.FIRST_PARTY
    has_action = any(v in low for v in _ACTION_VERBS)
    has_negation = any(m in low for m in _DOWNGRADE_MARKERS)
    if first_party and has_action and not has_negation:
        return True, classification, "excerpt first-party, functional, and un-negated"
    reasons = []
    if not first_party:
        reasons.append("not first-party")
    if not has_action:
        reasons.append("no functional capability stated")
    if has_negation:
        reasons.append("negating/future/historical/policy context present")
    return False, AIUsageLabel.MENTION_ONLY, "downgraded: " + ", ".join(reasons)
