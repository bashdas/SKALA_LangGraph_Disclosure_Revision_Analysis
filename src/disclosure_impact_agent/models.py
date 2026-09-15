from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SourceKind(StrEnum):
    SYNTHETIC = "synthetic"
    USER_UPLOAD = "user_upload"
    DART_API = "dart_api"


class DocumentFormat(StrEnum):
    HTML = "html"
    XML = "xml"
    TEXT = "text"


class ValueState(StrEnum):
    PRESENT = "present"
    ZERO = "zero"
    EMPTY = "empty"
    WITHHELD = "withheld"
    UNDISCLOSED = "undisclosed"
    PARSE_FAILED = "parse_failed"


class FieldName(StrEnum):
    CONTRACT_CONTENT = "contract_content"
    COUNTERPARTY = "counterparty"
    CONTRACT_AMOUNT = "contract_amount"
    SALES_AMOUNT = "sales_amount"
    DISCLOSED_SALES_RATIO = "disclosed_sales_ratio"
    CONTRACT_START_DATE = "contract_start_date"
    CONTRACT_END_DATE = "contract_end_date"


class IssueCode(StrEnum):
    UNSUPPORTED_FORMAT = "unsupported_format"
    MISSING_FIELD = "missing_field"
    PARSE_FAILED = "parse_failed"
    CORRECTION_BODY_CONFLICT = "correction_body_conflict"
    MEANING_BASIS_MISMATCH = "meaning_basis_mismatch"
    RELATION_UNCONFIRMED = "relation_unconfirmed"
    DOCUMENT_MISSING = "document_missing"
    UNSAFE_UPLOAD = "unsafe_upload"
    CHRONOLOGY_CONFLICT = "chronology_conflict"


class RelationStatus(StrEnum):
    VERIFIED_AUTOMATIC = "verified_automatic"
    CANDIDATE = "candidate"
    USER_CONFIRMED = "user_confirmed"
    REJECTED = "rejected"


class ChangeStatus(StrEnum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    UNRESOLVED = "unresolved"


class EvidenceLocator(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    table_id: str | None = None
    row_index: int | None = None
    cell_index: int | None = None
    paragraph_id: str | None = None


class EvidenceBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    document_id: str
    document_hash: str
    locator: EvidenceLocator
    raw_text: str


class ComparisonBasis(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str | None = None
    unit: str | None = None
    fiscal_year: int | None = None
    consolidation: str | None = None
    vat_included: bool | None = None
    amount_status: str | None = None


NormalizedValue = int | Decimal | date | str


class StructuredField(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: FieldName
    raw_value: str
    normalized_value: NormalizedValue | None = None
    value_state: ValueState
    basis: ComparisonBasis = Field(default_factory=ComparisonBasis)
    evidence_id: str


class CorrectionEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    field_name: FieldName
    before_raw: str
    after_raw: str
    before: StructuredField
    after: StructuredField


class ExtractionIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: IssueCode
    message: str
    field_name: FieldName | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    blocking: bool = True


class FilingDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    receipt_no: str | None = None
    source_kind: SourceKind
    source_verified: bool
    synthetic: bool
    collected_at: datetime
    submitted_on: date | None = None
    document_hash: str
    parser_version: str
    document_format: DocumentFormat
    original_filename: str
    corrects_document_id: str | None = None
    evidence_blocks: list[EvidenceBlock] = Field(default_factory=list)
    fields: list[StructuredField] = Field(default_factory=list)
    correction_entries: list[CorrectionEntry] = Field(default_factory=list)
    footnote_evidence_ids: list[str] = Field(default_factory=list)
    issues: list[ExtractionIssue] = Field(default_factory=list)
    extraction_complete: bool = False

    def field(self, name: FieldName) -> StructuredField | None:
        return next((field for field in self.fields if field.name == name), None)


class RelationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    criterion: str
    matched: bool
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)


class ContractRelationCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    earlier_document_id: str
    later_document_id: str
    status: RelationStatus
    evidence: list[RelationEvidence]
    conflicts: list[str] = Field(default_factory=list)


class FieldChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_id: str
    field_name: FieldName
    baseline_document_id: str
    target_document_id: str
    comparison_kind: str
    status: ChangeStatus
    before: StructuredField | None = None
    after: StructuredField | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str


class RatioCalculation(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    disclosed_ratio: Decimal | None
    recalculated_ratio: Decimal | None
    eligible: bool
    formula: str | None = None
    rounding_policy: str = "no rounding; exact Decimal result"
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class SequenceComparison(BaseModel):
    document_order: list[str] = Field(default_factory=list)
    relations: list[ContractRelationCandidate]
    previous_changes: list[FieldChange]
    cumulative_changes: list[FieldChange]
    issues: list[ExtractionIssue] = Field(default_factory=list)
