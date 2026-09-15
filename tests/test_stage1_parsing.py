from datetime import date
from decimal import Decimal
from pathlib import Path

from disclosure_impact_agent.analysis import calculate_sales_ratio, reconcile_correction_body
from disclosure_impact_agent.models import DocumentFormat, FieldName, IssueCode, SourceKind, ValueState
from disclosure_impact_agent.parser import parse_filing, validate_evidence_integrity

FIXTURE = Path(__file__).parents[1] / "fixtures/synthetic/a_company_contract"


def parse_fixture(name: str, document_id: str, corrects: str | None = None):
    return parse_filing(
        (FIXTURE / name).read_bytes(), document_id=document_id, original_filename=name,
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, corrects_document_id=corrects,
    )


def test_parses_source_html_with_metadata_and_evidence():
    document = parse_fixture("original.html", "original")

    assert document.extraction_complete
    assert len(document.document_hash) == 64
    assert document.parser_version == "contract-table-v1"
    assert document.synthetic and document.source_kind == SourceKind.SYNTHETIC
    assert document.field(FieldName.CONTRACT_AMOUNT).normalized_value == 12_000_000_000
    assert document.field(FieldName.CONTRACT_END_DATE).normalized_value == date(2026, 12, 31)
    assert document.field(FieldName.SALES_AMOUNT).basis.fiscal_year == 2025
    assert document.field(FieldName.SALES_AMOUNT).basis.consolidation == "consolidated"
    assert validate_evidence_integrity(document) == []
    for field in document.fields:
        block = next(block for block in document.evidence_blocks if block.evidence_id == field.evidence_id)
        assert block.document_hash == document.document_hash
        assert block.raw_text == field.raw_value


def test_correction_table_and_exact_server_ratio_are_separate():
    document = reconcile_correction_body(parse_fixture("correction.html", "correction", "original"))
    amount_entry = next(entry for entry in document.correction_entries if entry.field_name == FieldName.CONTRACT_AMOUNT)
    ratio = calculate_sales_ratio(document)

    assert amount_entry.before.normalized_value == 12_000_000_000
    assert amount_entry.after.normalized_value == 9_000_000_000
    assert ratio.eligible
    assert ratio.disclosed_ratio == Decimal("11.25")
    assert ratio.recalculated_ratio == Decimal("11.25")
    assert ratio.rounding_policy == "no rounding; exact Decimal result"
    assert validate_evidence_integrity(document) == []


def test_amount_units_normalize_equally():
    html = _contract_html(amount="120억원")
    document = parse_filing(html.encode(), document_id="unit", original_filename="unit.html", document_format=DocumentFormat.HTML)

    assert document.field(FieldName.CONTRACT_AMOUNT).normalized_value == 12_000_000_000


def test_undisclosed_counterparty_is_not_empty_or_zero():
    document = parse_filing(
        _contract_html(counterparty="미공개").encode(), document_id="hidden",
        original_filename="hidden.html", document_format=DocumentFormat.HTML,
    )

    field = document.field(FieldName.COUNTERPARTY)
    assert field.value_state == ValueState.UNDISCLOSED
    assert field.normalized_value is None
    assert field.raw_value == "미공개"


def test_zero_empty_withheld_and_parse_failure_are_distinct():
    values = {
        "zero": ("0원", ValueState.ZERO),
        "empty": ("-", ValueState.EMPTY),
        "withheld": ("유보", ValueState.WITHHELD),
        "failed": ("많음", ValueState.PARSE_FAILED),
    }
    for document_id, (amount, expected) in values.items():
        document = parse_filing(
            _contract_html(amount=amount).encode(), document_id=document_id,
            original_filename=f"{document_id}.html", document_format=DocumentFormat.HTML,
        )
        assert document.field(FieldName.CONTRACT_AMOUNT).value_state == expected


def test_unsupported_table_does_not_guess_fields():
    document = parse_filing(
        b"<html><table id='other'><tr><td>\xea\xb3\x84\xec\x95\xbd\xea\xb8\x88\xec\x95\xa1</td><td>12000000000</td></tr></table></html>",
        document_id="unsupported", original_filename="unsupported.html", document_format=DocumentFormat.HTML,
    )

    assert not document.extraction_complete
    assert document.fields == []
    assert document.issues[0].code == IssueCode.UNSUPPORTED_FORMAT


def test_manual_text_registration_is_unverified_and_preserves_locations():
    raw = "계약 내용: 산업용 장비 공급\n계약 상대방: 가상 B사\n계약금액: 120억원\n계약 종료일: 2026-12-31"
    document = parse_filing(
        raw.encode(), document_id="manual", original_filename="manual.txt",
        document_format=DocumentFormat.TEXT, source_kind=SourceKind.USER_UPLOAD,
        source_verified=False,
    )

    assert document.extraction_complete
    assert not document.source_verified
    assert document.field(FieldName.CONTRACT_AMOUNT).normalized_value == 12_000_000_000
    assert all(block.locator.table_id == "manual-text" for block in document.evidence_blocks)


def test_correction_body_conflict_is_explicit():
    raw = (FIXTURE / "correction.html").read_text().replace(">9,000,000,000원</td></tr>\n<tr><th>최근", ">8,000,000,000원</td></tr>\n<tr><th>최근")
    document = parse_filing(raw.encode(), document_id="conflict", original_filename="conflict.html", document_format=DocumentFormat.HTML)
    reconciled = reconcile_correction_body(document)

    issue = next(issue for issue in reconciled.issues if issue.code == IssueCode.CORRECTION_BODY_CONFLICT)
    assert not reconciled.extraction_complete
    assert len(issue.evidence_ids) == 2


def test_xml_external_entity_declaration_is_blocked():
    document = parse_filing(
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]><x>&ext;</x>',
        document_id="xxe", original_filename="xxe.xml", document_format=DocumentFormat.XML,
    )

    assert document.issues[0].code == IssueCode.UNSAFE_UPLOAD
    assert not document.extraction_complete


def _contract_html(
    *, amount: str = "12,000,000,000원", counterparty: str = "가상 B사",
    content: str = "산업용 장비 공급", sales: str = "80,000,000,000원 (2025년 연결 기준)",
    start: str = "2026-01-01", end: str = "2026-12-31",
) -> str:
    return f"""<!doctype html><html><body><table id="contract">
    <tr><th>계약 내용</th><td>{content}</td></tr>
    <tr><th>계약 상대방</th><td>{counterparty}</td></tr>
    <tr><th>계약금액</th><td>{amount}</td></tr>
    <tr><th>최근 매출액</th><td>{sales}</td></tr>
    <tr><th>매출액 대비</th><td>15%</td></tr>
    <tr><th>계약 시작일</th><td>{start}</td></tr>
    <tr><th>계약 종료일</th><td>{end}</td></tr>
    </table><p class="footnote">※ 합성 각주</p></body></html>"""
