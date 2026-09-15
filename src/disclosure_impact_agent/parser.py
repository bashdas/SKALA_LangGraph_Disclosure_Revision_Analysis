from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html.parser import HTMLParser

from disclosure_impact_agent.models import (
    CorrectionEntry,
    DocumentFormat,
    EvidenceBlock,
    EvidenceLocator,
    ExtractionIssue,
    FieldName,
    FilingDocument,
    IssueCode,
    SourceKind,
    ValueState,
)
from disclosure_impact_agent.normalization import normalize_field

PARSER_VERSION = "contract-table-v1"

LABELS = {
    "계약 내용": FieldName.CONTRACT_CONTENT,
    "계약내용": FieldName.CONTRACT_CONTENT,
    "계약 상대방": FieldName.COUNTERPARTY,
    "계약상대방": FieldName.COUNTERPARTY,
    "계약금액": FieldName.CONTRACT_AMOUNT,
    "최근 매출액": FieldName.SALES_AMOUNT,
    "최근매출액": FieldName.SALES_AMOUNT,
    "매출액 대비": FieldName.DISCLOSED_SALES_RATIO,
    "매출액대비": FieldName.DISCLOSED_SALES_RATIO,
    "계약 시작일": FieldName.CONTRACT_START_DATE,
    "계약시작일": FieldName.CONTRACT_START_DATE,
    "계약 종료일": FieldName.CONTRACT_END_DATE,
    "계약종료일": FieldName.CONTRACT_END_DATE,
}


@dataclass
class _Table:
    table_id: str
    rows: list[list[str]] = field(default_factory=list)


class _StructureCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.paragraphs: list[tuple[str, str, bool]] = []
        self._table: _Table | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._paragraph_parts: list[str] | None = None
        self._paragraph_id: str | None = None
        self._paragraph_footnote = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            self._table = _Table(attributes.get("id") or f"table-{len(self.tables)}")
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
        elif tag in {"p", "div"} and self._table is None:
            self._paragraph_parts = []
            self._paragraph_id = attributes.get("id") or f"paragraph-{len(self.paragraphs)}"
            self._paragraph_footnote = "footnote" in (attributes.get("class") or "").split()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell_parts is not None and self._row is not None:
            self._row.append(_clean(" ".join(self._cell_parts)))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        elif tag in {"p", "div"} and self._paragraph_parts is not None:
            text = _clean(" ".join(self._paragraph_parts))
            if text:
                footnote = self._paragraph_footnote or text.startswith(("주)", "※", "*"))
                self.paragraphs.append((self._paragraph_id or "paragraph", text, footnote))
            self._paragraph_parts = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        elif self._paragraph_parts is not None:
            self._paragraph_parts.append(data)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _evidence_id(document_id: str, location: str) -> str:
    return f"{document_id}:{location}"


def _field_from_cells(field_name: FieldName, raw: str, evidence: EvidenceBlock):
    return normalize_field(field_name, raw, evidence.evidence_id)


def parse_filing(
    content: bytes,
    *,
    document_id: str,
    original_filename: str,
    document_format: DocumentFormat,
    source_kind: SourceKind = SourceKind.USER_UPLOAD,
    source_verified: bool = False,
    synthetic: bool = False,
    receipt_no: str | None = None,
    collected_at: datetime | None = None,
    submitted_on: date | None = None,
    corrects_document_id: str | None = None,
) -> FilingDocument:
    document_hash = hashlib.sha256(content).hexdigest()
    collected_at = collected_at or datetime.now(timezone.utc)
    issues: list[ExtractionIssue] = []

    if document_format == DocumentFormat.XML and re.search(br"<!DOCTYPE|<!ENTITY", content, re.IGNORECASE):
        issues.append(ExtractionIssue(code=IssueCode.UNSAFE_UPLOAD, message="XML DTD/entity declaration is not allowed"))
        return FilingDocument(
            document_id=document_id, receipt_no=receipt_no, source_kind=source_kind,
            source_verified=source_verified, synthetic=synthetic, collected_at=collected_at,
            submitted_on=submitted_on, document_hash=document_hash, parser_version=PARSER_VERSION,
            document_format=document_format, original_filename=original_filename,
            corrects_document_id=corrects_document_id, issues=issues,
        )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("euc-kr")
        except UnicodeDecodeError:
            issues.append(ExtractionIssue(code=IssueCode.PARSE_FAILED, message="Document encoding is neither UTF-8 nor EUC-KR"))
            return FilingDocument(
                document_id=document_id, receipt_no=receipt_no, source_kind=source_kind,
                source_verified=source_verified, synthetic=synthetic, collected_at=collected_at,
                submitted_on=submitted_on, document_hash=document_hash, parser_version=PARSER_VERSION,
                document_format=document_format, original_filename=original_filename,
                corrects_document_id=corrects_document_id, issues=issues,
            )

    collector = _StructureCollector()
    if document_format in {DocumentFormat.HTML, DocumentFormat.XML}:
        collector.feed(text)
    else:
        rows = []
        for line in text.splitlines():
            parts = re.split(r"\s*[:|\t]\s*", line.strip(), maxsplit=1)
            if len(parts) == 2:
                rows.append(parts)
        if rows:
            collector.tables.append(_Table("manual-text", rows))

    evidence: list[EvidenceBlock] = []
    table_cell_evidence: dict[tuple[str, int, int], EvidenceBlock] = {}
    for table in collector.tables:
        for row_index, row in enumerate(table.rows):
            for cell_index, raw in enumerate(row):
                evidence_id = _evidence_id(document_id, f"table:{table.table_id}:row:{row_index}:cell:{cell_index}")
                block = EvidenceBlock(
                    evidence_id=evidence_id,
                    document_id=document_id,
                    document_hash=document_hash,
                    locator=EvidenceLocator(kind="table_cell", table_id=table.table_id, row_index=row_index, cell_index=cell_index),
                    raw_text=raw,
                )
                evidence.append(block)
                table_cell_evidence[(table.table_id, row_index, cell_index)] = block
    footnotes: list[str] = []
    for paragraph_id, raw, is_footnote in collector.paragraphs:
        evidence_id = _evidence_id(document_id, f"paragraph:{paragraph_id}")
        evidence.append(EvidenceBlock(
            evidence_id=evidence_id, document_id=document_id, document_hash=document_hash,
            locator=EvidenceLocator(kind="paragraph", paragraph_id=paragraph_id), raw_text=raw,
        ))
        if is_footnote:
            footnotes.append(evidence_id)

    contract = next((table for table in collector.tables if table.table_id == "contract"), None)
    if contract is None and document_format == DocumentFormat.TEXT:
        contract = next((table for table in collector.tables if table.table_id == "manual-text"), None)
    if contract is None:
        issues.append(ExtractionIssue(code=IssueCode.UNSUPPORTED_FORMAT, message="Required contract table was not found"))
        return FilingDocument(
            document_id=document_id, receipt_no=receipt_no, source_kind=source_kind,
            source_verified=source_verified, synthetic=synthetic, collected_at=collected_at,
            submitted_on=submitted_on, document_hash=document_hash, parser_version=PARSER_VERSION,
            document_format=document_format, original_filename=original_filename,
            corrects_document_id=corrects_document_id, evidence_blocks=evidence,
            footnote_evidence_ids=footnotes, issues=issues,
        )

    fields = []
    for row_index, row in enumerate(contract.rows):
        if len(row) < 2 or row[0] not in LABELS:
            continue
        block = table_cell_evidence[(contract.table_id, row_index, 1)]
        parsed = _field_from_cells(LABELS[row[0]], row[1], block)
        fields.append(parsed)
        if parsed.value_state == ValueState.PARSE_FAILED:
            issues.append(ExtractionIssue(
                code=IssueCode.PARSE_FAILED, message=f"Could not parse {parsed.name}",
                field_name=parsed.name, evidence_ids=[parsed.evidence_id],
            ))

    required = {FieldName.CONTRACT_CONTENT, FieldName.COUNTERPARTY, FieldName.CONTRACT_AMOUNT, FieldName.CONTRACT_END_DATE}
    present_names = {item.name for item in fields}
    for missing in sorted(required - present_names, key=str):
        issues.append(ExtractionIssue(code=IssueCode.MISSING_FIELD, message=f"Required field is missing: {missing}", field_name=missing))

    corrections: list[CorrectionEntry] = []
    correction_table = next((table for table in collector.tables if table.table_id == "correction-table"), None)
    if correction_table:
        for row_index, row in enumerate(correction_table.rows[1:], start=1):
            if len(row) < 3 or row[0] not in LABELS:
                continue
            name = LABELS[row[0]]
            before_ev = table_cell_evidence[(correction_table.table_id, row_index, 1)]
            after_ev = table_cell_evidence[(correction_table.table_id, row_index, 2)]
            corrections.append(CorrectionEntry(
                field_name=name, before_raw=row[1], after_raw=row[2],
                before=normalize_field(name, row[1], before_ev.evidence_id),
                after=normalize_field(name, row[2], after_ev.evidence_id),
            ))

    extraction_complete = not any(issue.blocking for issue in issues)
    return FilingDocument(
        document_id=document_id, receipt_no=receipt_no, source_kind=source_kind,
        source_verified=source_verified, synthetic=synthetic, collected_at=collected_at,
        submitted_on=submitted_on, document_hash=document_hash, parser_version=PARSER_VERSION,
        document_format=document_format, original_filename=original_filename,
        corrects_document_id=corrects_document_id, evidence_blocks=evidence, fields=fields,
        correction_entries=corrections, footnote_evidence_ids=footnotes,
        issues=issues, extraction_complete=extraction_complete,
    )


def validate_evidence_integrity(document: FilingDocument) -> list[str]:
    by_id = {block.evidence_id: block for block in document.evidence_blocks}
    errors = []
    referenced = [field.evidence_id for field in document.fields]
    referenced.extend(entry.before.evidence_id for entry in document.correction_entries)
    referenced.extend(entry.after.evidence_id for entry in document.correction_entries)
    referenced.extend(document.footnote_evidence_ids)
    for evidence_id in referenced:
        block = by_id.get(evidence_id)
        if block is None:
            errors.append(f"missing evidence: {evidence_id}")
        elif block.document_hash != document.document_hash:
            errors.append(f"hash mismatch: {evidence_id}")
    return errors
