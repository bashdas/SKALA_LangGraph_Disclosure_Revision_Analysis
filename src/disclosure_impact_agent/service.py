from __future__ import annotations

from disclosure_impact_agent.analysis import calculate_sales_ratio, compare_documents, reconcile_correction_body, relate_contracts
from disclosure_impact_agent.fake_llm import FixtureClaimExtractor
from disclosure_impact_agent.interfaces import ClaimExtractor
from disclosure_impact_agent.memo_analysis import DeterministicImpactAnalyzer, DeterministicRevisionProposer
from disclosure_impact_agent.memo_models import AnalysisFailure, ImpactClass, MemoAnalysisResult
from disclosure_impact_agent.models import EvidenceBlock, FieldChange, FilingDocument, RatioCalculation


def analyze_memo(
    memo: str,
    original: FilingDocument,
    correction: FilingDocument,
    *,
    scenario_id: str | None,
    llm_mode: str = "fake",
    model: str | None = None,
    extractor: ClaimExtractor | None = None,
    timeout_seconds: float = 30,
    max_retries: int = 2,
    max_memo_chars: int = 5_000,
    changes: list[FieldChange] | None = None,
    ratio: RatioCalculation | None = None,
    evidence: dict[str, EvidenceBlock] | None = None,
) -> MemoAnalysisResult:
    if len(memo) > max_memo_chars:
        return _failure(llm_mode, model, "input_validation", "memo_too_large", f"memo exceeds {max_memo_chars} characters")
    correction = reconcile_correction_body(correction)
    if changes is None:
        relation = relate_contracts(original, correction)
        changes = compare_documents(original, correction, relation)
    ratio = ratio or calculate_sales_ratio(correction)
    evidence = evidence or {block.evidence_id: block for document in (original, correction) for block in document.evidence_blocks}
    if extractor is None:
        if llm_mode == "fake":
            extractor = FixtureClaimExtractor()
        elif llm_mode == "openai":
            if not model:
                return _failure(llm_mode, model, "configuration", "missing_model", "OPENAI_MODEL is required")
            from disclosure_impact_agent.openai_llm import OpenAIClaimExtractor
            extractor = OpenAIClaimExtractor(model=model, timeout_seconds=timeout_seconds, max_retries=max_retries)
        elif llm_mode == "langchain":
            if not model:
                return _failure(llm_mode, model, "configuration", "missing_model", "OPENAI_MODEL is required")
            from disclosure_impact_agent.langchain_components import LangChainClaimExtractor
            extractor = LangChainClaimExtractor(model=model, timeout_seconds=timeout_seconds, max_retries=max_retries)
        else:
            return _failure(llm_mode, model, "configuration", "invalid_mode", f"unsupported LLM mode: {llm_mode}")
    try:
        claims = extractor.extract(memo, scenario_id=scenario_id)
        impacts = DeterministicImpactAnalyzer().analyze(claims, changes, ratio, evidence)
        proposals = DeterministicRevisionProposer().propose(memo, claims, impacts, changes, evidence, ratio)
    except Exception as exc:
        if isinstance(exc, TimeoutError) or type(exc).__name__ == "APITimeoutError":
            return _failure(llm_mode, model, "claim_extraction", "timeout", str(exc) or "claim extraction timed out", True)
        code = "schema_or_provider_error" if llm_mode == "openai" else "fixture_mismatch"
        return _failure(llm_mode, model, "claim_extraction", code, str(exc))
    if not original.extraction_complete or not correction.extraction_complete:
        impacts = [
            impact.model_copy(update={
                "classification": ImpactClass.UNRESOLVED,
                "reason_summary": "filing extraction is incomplete",
                "missing_information": list(dict.fromkeys(impact.missing_information + ["complete filing extraction"])),
                "revision_allowed": False,
            }) if impact.classification == ImpactClass.NO_IMPACT else impact
            for impact in impacts
        ]
        proposals = [proposal for proposal in proposals if all(
            next(item for item in impacts if item.claim_id == claim_id).revision_allowed
            for claim_id in proposal.claim_ids
        )]
    unresolved = sum(impact.classification == ImpactClass.UNRESOLVED for impact in impacts)
    return MemoAnalysisResult(
        data_class="synthetic" if original.synthetic and correction.synthetic else "non_synthetic",
        llm_mode=llm_mode, model=model, claims=claims.claims, impacts=impacts, proposals=proposals,
        reviewed_claim_count=len(claims.claims), unresolved_claim_count=unresolved,
    )


def _failure(mode: str, model: str | None, stage: str, code: str, message: str, retryable: bool = False):
    return MemoAnalysisResult(
        data_class="unknown", llm_mode=mode, model=model,
        failures=[AnalysisFailure(stage=stage, code=code, message=message, retryable=retryable)],
        unresolved_claim_count=1,
    )
