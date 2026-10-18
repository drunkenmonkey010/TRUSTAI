"""Claim-level AI classification regression suite (V2.1, §3.4).

The central guarantee: an AI keyword in context that is NOT a deployed, functional,
first-party capability must never classify as confirmed AI use.
"""
from __future__ import annotations

from agents.signals import SignalHit
from evidence.claim_classifier import classify_claim, verify_support
from evidence.schemas import AIUsageLabel
from evidence.verification import (
    detect_circular_reporting,
    independent_corroboration_count,
)

_CONFIRMED = {
    AIUsageLabel.CONFIRMED_GENAI, AIUsageLabel.CONFIRMED_PRODUCT_FEATURE,
    AIUsageLabel.CONFIRMED_INTEGRATION, AIUsageLabel.CONFIRMED_AI,
}


def _c(excerpt, category="ai", source_type="web_page"):
    hit = SignalHit(category=category, phrase="ai", excerpt=excerpt)
    return classify_claim(vendor_name="Acme", source={"source_type": source_type}, hit=hit)


# --- the 12 mandatory cases --------------------------------------------- #
def test_general_discussion_is_mention_only():
    r = _c("Artificial intelligence is transforming finance. In this guide to AI we explain machine learning.")
    assert r.classification == AIUsageLabel.MENTION_ONLY
    assert r.classification not in _CONFIRMED


def test_security_policy_mention_not_confirmed():
    r = _c("Our acceptable use policy prohibits employees from using generative AI for client data.",
           category="generative")
    assert r.classification == AIUsageLabel.MENTION_ONLY
    assert r.classification not in _CONFIRMED


def test_marketing_without_capability_is_advertised():
    r = _c("Our revolutionary AI-powered platform delivers cutting-edge, world-class intelligence.")
    assert r.classification == AIUsageLabel.ADVERTISED_UNVERIFIED
    assert r.classification not in _CONFIRMED


def test_planned_feature_is_advertised_planned():
    r = _c("We will launch an AI assistant next quarter to help customers.")
    assert r.classification == AIUsageLabel.ADVERTISED_UNVERIFIED
    assert r.deployment_status == "planned"
    assert r.temporal_scope == "planned"


def test_historical_feature_not_established():
    r = _c("We previously offered an AI recommendation feature but it was discontinued in 2021.")
    assert r.classification == AIUsageLabel.NOT_ESTABLISHED
    assert r.temporal_scope == "historical"


def test_customer_controlled_integration():
    r = _c("Customers can enable an optional integration to connect your own OpenAI API key.",
           category="integration")
    assert r.classification == AIUsageLabel.ADVERTISED_UNVERIFIED
    assert r.data_flow_implication == "customer_controlled"
    assert r.classification not in _CONFIRMED


def test_provider_partnership_is_third_party_relationship():
    r = _c("Acme announced a partnership with OpenAI to explore generative AI solutions.",
           category="generative")
    assert r.classification == AIUsageLabel.THIRD_PARTY_RELATIONSHIP
    assert r.classification not in _CONFIRMED


def test_confirmed_product_feature():
    r = _c("Our platform uses AI to automatically detect fraud in real time.")
    assert r.classification == AIUsageLabel.CONFIRMED_PRODUCT_FEATURE
    assert r.directness.value == "direct"


def test_confirmed_api_integration_unknown_dataflow():
    r = _c("Our product integrates the OpenAI API to generate document summaries for users.",
           category="integration")
    assert r.classification == AIUsageLabel.CONFIRMED_INTEGRATION


def test_job_ad_is_indirect():
    r = _c("We are hiring an Applied AI Engineer. Requirements: experience with large language models.",
           category="generative", source_type="careers_page")
    assert r.classification == AIUsageLabel.INDIRECT
    assert r.classification not in _CONFIRMED


def test_repeated_press_release_not_extra_corroboration():
    # Same content hash twice => second is circular; independent corroboration = 1.
    rows = [
        {"evidence_id": 1, "content_hash": "h", "relation": "supports",
         "authority": "independent", "source_owner": "siteA"},
        {"evidence_id": 2, "content_hash": "h", "relation": "supports",
         "authority": "independent", "source_owner": "siteB"},
    ]
    assert 2 in detect_circular_reporting(rows)
    assert independent_corroboration_count(rows) == 1


def test_contradictory_current_vs_historical():
    current = _c("Our platform uses AI to detect fraud.")
    historical = _c("We previously used AI to detect fraud but discontinued it.")
    assert current.classification in _CONFIRMED
    assert historical.classification == AIUsageLabel.NOT_ESTABLISHED


# --- the core guarantee + verification gate ----------------------------- #
def test_keyword_only_never_confirmed():
    keyword_only = [
        _c("Artificial intelligence is transforming finance.", ),
        _c("Policy: staff must not use AI tools.", category="ai"),
        _c("We will add AI soon.", category="ai"),
        _c("Previously used machine learning.", category="ai"),
    ]
    for r in keyword_only:
        assert r.classification not in _CONFIRMED


def test_verification_downgrades_unsupported_confirmed():
    # A 'confirmed' label whose excerpt is actually a policy mention is downgraded.
    ok, label, _ = verify_support(AIUsageLabel.CONFIRMED_GENAI,
                                  "Our policy prohibits generative AI use.", "web_page")
    assert ok is False
    assert label == AIUsageLabel.MENTION_ONLY


def test_verification_passes_real_capability():
    ok, label, _ = verify_support(AIUsageLabel.CONFIRMED_PRODUCT_FEATURE,
                                  "Our platform uses AI to automatically detect fraud.", "web_page")
    assert ok is True
    assert label == AIUsageLabel.CONFIRMED_PRODUCT_FEATURE
