"""Deterministic text-signal analysis for AI-usage detection.

Operates on retrieved page text / snippets (treated as untrusted data). Returns
structured signals with the exact matched phrases so every downstream claim can
cite an excerpt. No fabrication: if the text contains nothing, nothing is
returned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

# Signal vocabularies. Matched as whole words / phrases, case-insensitive.
AI_TERMS = [
    "artificial intelligence", "machine learning", "deep learning", "neural network",
    r"\bai\b", r"\bml\b", "predictive model", "natural language processing", r"\bnlp\b",
    "computer vision", "anomaly detection", "intelligent automation",
]
GENERATIVE_TERMS = [
    "generative ai", "genai", "large language model", r"\bllm\b", "copilot", "co-pilot",
    "chatbot", "virtual assistant", "gpt", "foundation model", "prompt", "summarise",
    "summarize", "draft", "conversational ai", "agentic", "ai agent",
]
INTEGRATION_TERMS = [
    "ai-powered", "ai powered", "powered by ai", "ai feature", "ai assistant",
    "ai capabilities", "embedded ai", "built-in ai",
]
DEPLOYMENT_STATUS = {
    "released": ["generally available", "now available", "ga ", "launched", "in production"],
    "beta": ["beta", "preview", "early access", "pilot"],
    "planned": ["coming soon", "roadmap", "planned", "will introduce", "upcoming"],
    "discontinued": ["deprecated", "discontinued", "sunset", "retired"],
}
# Named model / AI providers (association only - never proof of data flow).
PROVIDER_NAMES = [
    "openai", "anthropic", "claude", "azure openai", "google cloud ai", "vertex ai",
    "aws bedrock", "amazon bedrock", "cohere", "mistral", "hugging face", "databricks",
    "sagemaker", "palantir", "ibm watson", "gemini",
]
DATA_FLOW_TERMS = [
    "sub-processor", "subprocessor", "data processing", "processes your data",
    "third-party provider", "shared with", "transmit", "sends data", "api",
]
RETENTION_TERMS = [
    "retention", "retain", "deleted after", "not used for training",
    "used to train", "model training", "data residency", "stored in",
]


@dataclass
class SignalHit:
    category: str
    phrase: str
    excerpt: str


@dataclass
class SignalReport:
    hits: List[SignalHit] = field(default_factory=list)
    providers: List[str] = field(default_factory=list)
    deployment_status: List[str] = field(default_factory=list)

    def categories(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for h in self.hits:
            out[h.category] = out.get(h.category, 0) + 1
        return out

    @property
    def has_generative(self) -> bool:
        return any(h.category == "generative" for h in self.hits)

    @property
    def has_ai(self) -> bool:
        return any(h.category in ("ai", "generative", "integration") for h in self.hits)


def _excerpt(text: str, start: int, end: int, window: int = 90) -> str:
    a = max(0, start - window)
    b = min(len(text), end + window)
    snippet = text[a:b].strip()
    return ("..." if a > 0 else "") + snippet + ("..." if b < len(text) else "")


def _scan(text: str, terms: List[str], category: str, report: SignalReport) -> None:
    for term in terms:
        pattern = term if term.startswith("\\b") or "\\b" in term else re.escape(term)
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            report.hits.append(
                SignalHit(category=category, phrase=m.group(0).strip(),
                          excerpt=_excerpt(text, m.start(), m.end()))
            )
            break  # one hit per term is enough to cite


def analyze_text(text: str | None) -> SignalReport:
    report = SignalReport()
    if not text:
        return report
    _scan(text, AI_TERMS, "ai", report)
    _scan(text, GENERATIVE_TERMS, "generative", report)
    _scan(text, INTEGRATION_TERMS, "integration", report)
    _scan(text, DATA_FLOW_TERMS, "data_flow", report)
    _scan(text, RETENTION_TERMS, "retention", report)

    low = text.lower()
    for provider in PROVIDER_NAMES:
        if re.search(r"\b" + re.escape(provider) + r"\b", low):
            report.providers.append(provider)
    for status, markers in DEPLOYMENT_STATUS.items():
        if any(mk in low for mk in markers):
            report.deployment_status.append(status)
    return report
