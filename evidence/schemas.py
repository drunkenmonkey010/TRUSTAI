"""Pydantic schemas for the evidence model and downstream findings.

These types draw a hard line between five kinds of statement:
observation -> extracted claim -> inference -> risk judgment -> recommendation.
Keeping them distinct is what lets the QA agent and the benchmark evaluator
detect unsupported conclusions.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class RetrievalStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    OFFLINE = "offline"
    INACCESSIBLE = "inaccessible"


class ClaimType(str, Enum):
    OBSERVATION = "observation"
    EXTRACTED = "extracted"
    INFERENCE = "inference"
    JUDGMENT = "judgment"
    RECOMMENDATION = "recommendation"


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class Directness(str, Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"


class Authority(str, Enum):
    FIRST_PARTY = "first_party"
    INDEPENDENT = "independent"
    AGGREGATOR = "aggregator"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    DISPUTED = "disputed"
    CIRCULAR = "circular"


class EvidenceStatus(str, Enum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class AIUsageLabel(str, Enum):
    CONFIRMED_AI = "Confirmed AI use"
    CONFIRMED_GENAI = "Confirmed generative AI use"
    CONFIRMED_INTEGRATION = "Confirmed AI product integration"
    CONFIRMED_PRODUCT_FEATURE = "Confirmed AI product feature"
    THIRD_PARTY_RELATIONSHIP = "Third-party AI relationship confirmed"
    ADVERTISED_UNVERIFIED = "AI capability advertised; deployment unverified"
    INDIRECT = "AI use indicated by indirect evidence"
    MENTION_ONLY = "AI mention only"
    NOT_ESTABLISHED = "AI use not established"
    CONFLICTING = "Conflicting evidence"
    INSUFFICIENT = "Insufficient evidence"


# Vendor-level aggregation precedence (strongest first).
AI_LABEL_PRECEDENCE = [
    AIUsageLabel.CONFIRMED_GENAI,
    AIUsageLabel.CONFIRMED_PRODUCT_FEATURE,
    AIUsageLabel.CONFIRMED_INTEGRATION,
    AIUsageLabel.CONFIRMED_AI,
    AIUsageLabel.THIRD_PARTY_RELATIONSHIP,
    AIUsageLabel.INDIRECT,
    AIUsageLabel.ADVERTISED_UNVERIFIED,
    AIUsageLabel.MENTION_ONLY,
    AIUsageLabel.NOT_ESTABLISHED,
    AIUsageLabel.INSUFFICIENT,
]


class TriState(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Core records
# --------------------------------------------------------------------------- #
class SourceRecord(BaseModel):
    source_id: Optional[int] = None
    run_id: Optional[str] = None
    vendor_id: Optional[str] = None
    connector_name: Optional[str] = None
    url: Optional[str] = None
    canonical_url: Optional[str] = None
    title: Optional[str] = None
    source_type: Optional[str] = None
    source_owner: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    snippet: Optional[str] = None
    extracted_text: Optional[str] = None
    http_status: Optional[int] = None
    retrieval_status: RetrievalStatus = RetrievalStatus.OK
    content_hash: Optional[str] = None
    is_sample: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[dict] = None


class Claim(BaseModel):
    claim_id: Optional[int] = None
    run_id: str
    vendor_id: str
    claim_text: str
    claim_type: ClaimType = ClaimType.EXTRACTED
    subject: Optional[str] = None
    action: Optional[str] = None
    product: Optional[str] = None
    qualifiers: Optional[str] = None
    supported: bool = False
    created_by_agent: Optional[str] = None


class EvidenceRecord(BaseModel):
    evidence_id: Optional[int] = None
    run_id: str
    vendor_id: str
    claim_id: Optional[int] = None
    source_id: Optional[int] = None
    url: Optional[str] = None
    canonical_url: Optional[str] = None
    title: Optional[str] = None
    source_owner: Optional[str] = None
    source_type: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    excerpt: Optional[str] = None
    content_hash: Optional[str] = None
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS
    directness: Directness = Directness.INDIRECT
    authority: Authority = Authority.UNKNOWN
    freshness: Optional[str] = None
    independence: Optional[str] = None
    confidence_rationale: Optional[str] = None
    extraction_method: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    is_sample: bool = False
    error_note: Optional[str] = None
    created_by_agent: Optional[str] = None


class Relationship(BaseModel):
    vendor_id: str
    run_id: str
    source_entity: str
    target_entity: str
    relation_type: str
    confidence: float = 0.0
    evidence_status: EvidenceStatus = EvidenceStatus.UNKNOWN
    evidence_ids: List[int] = Field(default_factory=list)
    source_timestamp: Optional[str] = None


class AIUsageClassification(BaseModel):
    vendor_id: str
    run_id: str
    label: AIUsageLabel
    deployment_context: Optional[str] = None
    confidence: float = 0.0
    evidence_ids: List[int] = Field(default_factory=list)
    rationale: Optional[str] = None


class DataFlowFinding(BaseModel):
    vendor_id: str
    run_id: str
    description: str
    data_category: Optional[str] = None
    destination: Optional[str] = None
    customer_data_involved: TriState = TriState.UNKNOWN
    transfer_established: TriState = TriState.UNKNOWN
    processing_context: Optional[str] = None
    retention_terms: Optional[str] = None
    training_terms: Optional[str] = None
    confidence: float = 0.0
    evidence_ids: List[int] = Field(default_factory=list)
    open_questions: Optional[str] = None


class Recommendation(BaseModel):
    vendor_id: str
    run_id: str
    category: str
    finding: str
    rationale: str
    action: str
    priority: str
    responsible_role: str
    time_horizon: str
    supporting_evidence: Optional[str] = None
    closure_conditions: Optional[str] = None
