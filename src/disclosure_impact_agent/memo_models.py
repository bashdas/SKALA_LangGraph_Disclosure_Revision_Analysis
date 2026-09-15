from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from disclosure_impact_agent.models import FieldName


class ClaimKind(StrEnum):
    FACT = "fact"
    CALCULATION = "calculation"
    FORECAST = "forecast"


class ClaimTime(StrEnum):
    CURRENT = "current"
    HISTORICAL = "historical"
    HYPOTHETICAL = "hypothetical"


class ImpactClass(StrEnum):
    DIRECT_FACT_CHANGE = "DIRECT_FACT_CHANGE"
    DERIVED_VALUE_CHANGE = "DERIVED_VALUE_CHANGE"
    INTERPRETATION_REVIEW = "INTERPRETATION_REVIEW"
    NO_IMPACT = "NO_IMPACT"
    UNRESOLVED = "UNRESOLVED"


class TextSpan(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str

    @model_validator(mode="after")
    def valid_span(self):
        if self.end < self.start:
            raise ValueError("span end precedes start")
        return self


class MemoSentence(BaseModel):
    model_config = ConfigDict(frozen=True)
    sentence_id: str
    span: TextSpan


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim_id: str
    sentence_id: str
    span: TextSpan
    value_span: TextSpan | None = None
    company: str | None = None
    contract: str | None = None
    kind: ClaimKind
    time_context: ClaimTime
    field_name: FieldName | None = None
    claimed_value: str | None = None
    reference_evidence_ids: list[str] = Field(default_factory=list)


class ClaimBatch(BaseModel):
    sentences: list[MemoSentence]
    claims: list[Claim]


class EvidenceAssessment(BaseModel):
    existence_verified: bool
    semantic_support_verified: bool
    evidence_ids: list[str]
    note: str


class Impact(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim_id: str
    change_ids: list[str] = Field(default_factory=list)
    evidence: EvidenceAssessment
    classification: ImpactClass
    reason_summary: str
    missing_information: list[str] = Field(default_factory=list)
    revision_allowed: bool = False


class RevisionEdit(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: int
    end: int
    original_text: str
    replacement_text: str
    source_field: FieldName
    source_change_id: str
    evidence_ids: list[str]


class RevisionProposal(BaseModel):
    model_config = ConfigDict(frozen=True)
    proposal_id: str
    sentence_id: str
    original_sentence: str
    proposed_sentence: str
    claim_ids: list[str]
    edits: list[RevisionEdit]
    evidence: EvidenceAssessment


class AnalysisFailure(BaseModel):
    stage: str
    code: str
    message: str
    retryable: bool = False


class MemoAnalysisResult(BaseModel):
    data_class: str
    llm_mode: str
    model: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    impacts: list[Impact] = Field(default_factory=list)
    proposals: list[RevisionProposal] = Field(default_factory=list)
    failures: list[AnalysisFailure] = Field(default_factory=list)
    reviewed_claim_count: int = 0
    unresolved_claim_count: int = 0
