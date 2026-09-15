from datetime import date
from decimal import Decimal
from pathlib import Path

from disclosure_impact_agent.analysis import (
    calculate_sales_ratio,
    compare_documents,
    compare_sequence,
    reconcile_correction_body,
    relate_contracts,
)
from disclosure_impact_agent.models import (
    ChangeStatus,
    DocumentFormat,
    FieldName,
    RelationStatus,
    SourceKind,
)
from disclosure_impact_agent.parser import parse_filing
from test_stage1_parsing import _contract_html

FIXTURE = Path(__file__).parents[1] / "fixtures/synthetic/a_company_contract"


def parse_html(raw: str, document_id: str, corrects: str | None = None, submitted: date | None = None):
    return parse_filing(
        raw.encode(), document_id=document_id, original_filename=f"{document_id}.html",
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, corrects_document_id=corrects, submitted_on=submitted,
    )


def fixture_pair():
    original = parse_html((FIXTURE / "original.html").read_text(), "original", submitted=date(2026, 1, 1))
    correction = parse_html((FIXTURE / "correction.html").read_text(), "correction", "original", date(2026, 6, 1))
    return original, reconcile_correction_body(correction)


def change(changes, field_name):
    return next(item for item in changes if item.field_name == field_name)


def test_verified_relation_and_amount_date_changes():
    original, correction = fixture_pair()
    relation = relate_contracts(original, correction)
    changes = compare_documents(original, correction, relation)

    assert relation.status == RelationStatus.VERIFIED_AUTOMATIC
    assert change(changes, FieldName.CONTRACT_AMOUNT).status == ChangeStatus.CHANGED
    assert change(changes, FieldName.CONTRACT_END_DATE).status == ChangeStatus.CHANGED
    assert change(changes, FieldName.COUNTERPARTY).status == ChangeStatus.UNCHANGED
    assert change(changes, FieldName.CONTRACT_AMOUNT).before.normalized_value == 12_000_000_000
    assert change(changes, FieldName.CONTRACT_AMOUNT).after.normalized_value == 9_000_000_000


def test_notation_only_change_is_unchanged():
    earlier = parse_html(_contract_html(amount="120억원"), "a")
    later = parse_html(_contract_html(amount="12,000,000,000원"), "b", "a")
    changes = compare_documents(earlier, later, relate_contracts(earlier, later))

    assert change(changes, FieldName.CONTRACT_AMOUNT).status == ChangeStatus.UNCHANGED


def test_vat_basis_difference_is_unresolved_not_decrease():
    earlier = parse_html(_contract_html(amount="120억원 (부가세 포함)"), "a")
    later = parse_html(_contract_html(amount="90억원 (부가세 제외)"), "b", "a")
    changes = compare_documents(earlier, later, relate_contracts(earlier, later))

    result = change(changes, FieldName.CONTRACT_AMOUNT)
    assert result.status == ChangeStatus.UNRESOLVED
    assert "vat_included" in result.reason


def test_currency_difference_is_unresolved_not_decrease():
    earlier = parse_html(_contract_html(amount="USD1,000"), "a")
    later = parse_html(_contract_html(amount="90억원"), "b", "a")
    changes = compare_documents(earlier, later, relate_contracts(earlier, later))

    result = change(changes, FieldName.CONTRACT_AMOUNT)
    assert result.status == ChangeStatus.UNRESOLVED
    assert "currency" in result.reason


def test_sales_denominator_basis_change_is_unresolved():
    earlier = parse_html(_contract_html(sales="800억원 (2025년 연결 기준)"), "a")
    later = parse_html(_contract_html(sales="900억원 (2026년 별도 기준)"), "b", "a")
    changes = compare_documents(earlier, later, relate_contracts(earlier, later))

    result = change(changes, FieldName.SALES_AMOUNT)
    assert result.status == ChangeStatus.UNRESOLVED
    assert "fiscal_year" in result.reason and "consolidation" in result.reason


def test_ratio_requires_confirmed_denominator_basis():
    eligible = parse_html(_contract_html(amount="90억원", sales="800억원 (2025년 연결 기준)"), "eligible")
    unknown = parse_html(_contract_html(amount="90억원", sales="800억원"), "unknown")

    assert calculate_sales_ratio(eligible).recalculated_ratio == Decimal("11.2500")
    unresolved = calculate_sales_ratio(unknown)
    assert not unresolved.eligible
    assert unresolved.recalculated_ratio is None


def test_different_contract_is_not_merged():
    earlier = parse_html(_contract_html(content="장비 A 공급", counterparty="가상 B사"), "a")
    later = parse_html(_contract_html(content="장비 C 공급", counterparty="가상 D사"), "b")
    relation = relate_contracts(earlier, later)
    changes = compare_documents(earlier, later, relation)

    assert relation.status == RelationStatus.REJECTED
    assert all(item.status == ChangeStatus.UNRESOLVED for item in changes)


def test_company_or_title_metadata_cannot_confirm_relation():
    earlier = parse_html(_contract_html(), "a")
    later = parse_html(_contract_html(), "b")

    assert relate_contracts(earlier, later).status == RelationStatus.CANDIDATE


def test_correction_table_before_conflict_blocks_field_change():
    original, correction = fixture_pair()
    raw = (FIXTURE / "correction.html").read_text().replace("12,000,000,000원</td><td>9,000", "11,000,000,000원</td><td>9,000")
    correction = reconcile_correction_body(parse_html(raw, "correction", "original"))
    changes = compare_documents(original, correction, relate_contracts(original, correction))

    result = change(changes, FieldName.CONTRACT_AMOUNT)
    assert result.status == ChangeStatus.UNRESOLVED
    assert "before-value" in result.reason


def test_repeated_correction_has_previous_and_cumulative_views():
    original, first = fixture_pair()
    second = parse_html(
        _contract_html(amount="80억원", end="2027-06-30"), "second", "correction", date(2026, 9, 1)
    )
    result = compare_sequence([original, first, second])

    assert [relation.status for relation in result.relations] == [
        RelationStatus.VERIFIED_AUTOMATIC, RelationStatus.VERIFIED_AUTOMATIC
    ]
    previous_amounts = [item for item in result.previous_changes if item.field_name == FieldName.CONTRACT_AMOUNT]
    cumulative_amounts = [item for item in result.cumulative_changes if item.field_name == FieldName.CONTRACT_AMOUNT]
    assert [(item.before.normalized_value, item.after.normalized_value) for item in previous_amounts] == [
        (12_000_000_000, 9_000_000_000), (9_000_000_000, 8_000_000_000)
    ]
    assert cumulative_amounts[0].comparison_kind == "cumulative"
    assert cumulative_amounts[1].status == ChangeStatus.CHANGED
    assert (cumulative_amounts[1].before.normalized_value, cumulative_amounts[1].after.normalized_value) == (
        12_000_000_000, 8_000_000_000
    )
    assert result.document_order == ["original", "correction", "second"]


def test_empty_sequence_returns_document_missing_issue():
    result = compare_sequence([])
    assert result.issues[0].code.value == "document_missing"
