from datetime import date
from pathlib import Path

from disclosure_impact_agent.memo_analysis import DeterministicImpactAnalyzer, DeterministicRevisionProposer
from disclosure_impact_agent.memo_models import (
    Claim, ClaimBatch, ClaimKind, ClaimTime, ImpactClass, MemoSentence, TextSpan,
)
from disclosure_impact_agent.models import DocumentFormat, FieldName, SourceKind
from disclosure_impact_agent.parser import parse_filing
from disclosure_impact_agent.service import analyze_memo

FIXTURE = Path(__file__).parents[1] / "fixtures/synthetic/a_company_contract"
SCENARIO = "synthetic-a-company-contract-v1"


def fixture_inputs(memo: str | None = None):
    original = parse_filing(
        (FIXTURE / "original.html").read_bytes(), document_id="original", original_filename="original.html",
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, submitted_on=date(2026, 1, 1),
    )
    correction = parse_filing(
        (FIXTURE / "correction.html").read_bytes(), document_id="correction", original_filename="correction.html",
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, submitted_on=date(2026, 6, 1), corrects_document_id="original",
    )
    return (memo if memo is not None else (FIXTURE / "memo.md").read_text()), original, correction


def test_fixture_pipeline_returns_five_impacts_and_verified_proposals():
    memo, original, correction = fixture_inputs()
    result = analyze_memo(memo, original, correction, scenario_id=SCENARIO)

    assert [impact.classification for impact in result.impacts] == [
        ImpactClass.DIRECT_FACT_CHANGE,
        ImpactClass.DERIVED_VALUE_CHANGE,
        ImpactClass.DIRECT_FACT_CHANGE,
        ImpactClass.INTERPRETATION_REVIEW,
        ImpactClass.NO_IMPACT,
    ]
    assert result.reviewed_claim_count == 5
    assert result.unresolved_claim_count == 0
    assert len(result.proposals) == 3
    assert any("90억원" in proposal.proposed_sentence for proposal in result.proposals)
    assert any("11.25%" in proposal.proposed_sentence for proposal in result.proposals)
    assert any("2027-03-31" in proposal.proposed_sentence for proposal in result.proposals)
    assert all(proposal.evidence.existence_verified for proposal in result.proposals)
    assert all(proposal.evidence.semantic_support_verified for proposal in result.proposals)


def test_claim_and_sentence_offsets_round_trip_to_original_memo():
    memo, original, correction = fixture_inputs()
    result = analyze_memo(memo, original, correction, scenario_id=SCENARIO)

    for claim in result.claims:
        assert memo[claim.span.start:claim.span.end] == claim.span.text
        if claim.value_span:
            assert memo[claim.value_span.start:claim.value_span.end] == claim.value_span.text


def test_fake_rejects_undeclared_fixture_instead_of_claiming_success():
    memo, original, correction = fixture_inputs()
    result = analyze_memo(memo, original, correction, scenario_id="unknown")

    assert result.impacts == []
    assert result.failures[0].code == "fixture_mismatch"
    assert result.unresolved_claim_count == 1


def test_extractor_timeout_is_failure_not_no_impact():
    class TimeoutExtractor:
        def extract(self, memo, *, scenario_id=None):
            raise TimeoutError("deadline")

    memo, original, correction = fixture_inputs()
    result = analyze_memo(memo, original, correction, scenario_id=None, extractor=TimeoutExtractor())

    assert result.failures[0].code == "timeout"
    assert result.impacts == []
    assert result.unresolved_claim_count == 1


def test_openai_mode_requires_explicit_model_without_calling_provider():
    memo, original, correction = fixture_inputs()
    result = analyze_memo(memo, original, correction, scenario_id=None, llm_mode="openai", model=None)

    assert result.failures[0].code == "missing_model"


def test_multiple_non_overlapping_edits_merge_and_preserve_other_clause():
    memo = "금액은 120억원이고 종료일은 2026년 말이며 상대방은 그대로다."
    _, original, correction = fixture_inputs(memo)
    amount_start, date_start = memo.index("120억원"), memo.index("2026년 말")
    sentence = MemoSentence(sentence_id="s", span=TextSpan(start=0, end=len(memo), text=memo))
    claims = ClaimBatch(sentences=[sentence], claims=[
        Claim(claim_id="a", sentence_id="s", span=TextSpan(start=amount_start, end=amount_start+len("120억원"), text="120억원"), value_span=TextSpan(start=amount_start, end=amount_start+len("120억원"), text="120억원"), kind=ClaimKind.FACT, time_context=ClaimTime.CURRENT, field_name=FieldName.CONTRACT_AMOUNT, claimed_value="120억원"),
        Claim(claim_id="d", sentence_id="s", span=TextSpan(start=date_start, end=date_start+len("2026년 말"), text="2026년 말"), value_span=TextSpan(start=date_start, end=date_start+len("2026년 말"), text="2026년 말"), kind=ClaimKind.FACT, time_context=ClaimTime.CURRENT, field_name=FieldName.CONTRACT_END_DATE, claimed_value="2026년 말"),
    ])
    from disclosure_impact_agent.analysis import calculate_sales_ratio, compare_documents, reconcile_correction_body, relate_contracts
    correction = reconcile_correction_body(correction)
    changes = compare_documents(original, correction, relate_contracts(original, correction))
    ratio = calculate_sales_ratio(correction)
    evidence = {b.evidence_id:b for doc in (original, correction) for b in doc.evidence_blocks}
    impacts = DeterministicImpactAnalyzer().analyze(claims, changes, ratio, evidence)
    proposals = DeterministicRevisionProposer().propose(memo, claims, impacts, changes, evidence, ratio)

    assert len(proposals) == 1
    assert proposals[0].proposed_sentence == "금액은 90억원이고 종료일은 2027-03-31이며 상대방은 그대로다."
    assert len(proposals[0].edits) == 2


def test_missing_calculation_basis_is_unresolved():
    memo, original, correction = fixture_inputs()
    sales = correction.field(FieldName.SALES_AMOUNT)
    correction = correction.model_copy(update={
        "fields": [
            field.model_copy(update={"basis": field.basis.model_copy(update={"fiscal_year": None})}) if field is sales else field
            for field in correction.fields
        ]
    })
    result = analyze_memo(memo, original, correction, scenario_id=SCENARIO)

    ratio_impact = result.impacts[1]
    assert ratio_impact.classification == ImpactClass.UNRESOLVED
    assert not ratio_impact.revision_allowed
