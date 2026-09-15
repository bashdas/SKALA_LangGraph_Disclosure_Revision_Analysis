from __future__ import annotations

from datetime import date
from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from disclosure_impact_agent.analysis import calculate_sales_ratio, compare_documents, reconcile_correction_body, relate_contracts
from disclosure_impact_agent.fake_llm import SUPPORTED_SCENARIO
from disclosure_impact_agent.memo_models import MemoAnalysisResult
from disclosure_impact_agent.models import (
    ContractRelationCandidate,
    DocumentFormat,
    EvidenceBlock,
    FieldChange,
    FilingDocument,
    RatioCalculation,
    SourceKind,
)
from disclosure_impact_agent.parser import parse_filing
from disclosure_impact_agent.service import analyze_memo


class ReviewGraphState(TypedDict):
    original_html: str
    correction_html: str
    memo: str
    llm_mode: str
    model: str | None
    scenario_id: str | None
    timeout_seconds: NotRequired[float]
    max_retries: NotRequired[int]
    original: NotRequired[FilingDocument]
    correction: NotRequired[FilingDocument]
    relation: NotRequired[ContractRelationCandidate]
    changes: NotRequired[list[FieldChange]]
    ratio: NotRequired[RatioCalculation]
    evidence: NotRequired[dict[str, EvidenceBlock]]
    result: NotRequired[MemoAnalysisResult]
    outcome: NotRequired[str]
    events: NotRequired[list[str]]


def parse_filings(state: ReviewGraphState) -> dict:
    original = parse_filing(
        state["original_html"].encode(), document_id="demo-original", original_filename="original.html",
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, submitted_on=date(2026, 1, 1),
    )
    correction = reconcile_correction_body(parse_filing(
        state["correction_html"].encode(), document_id="demo-correction", original_filename="correction.html",
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, submitted_on=date(2026, 6, 1),
        corrects_document_id=original.document_id,
    ))
    return {"original": original, "correction": correction, "events": ["parse_filings"]}


def compare_changes(state: ReviewGraphState) -> dict:
    original, correction = state["original"], state["correction"]
    relation = relate_contracts(original, correction)
    changes = compare_documents(original, correction, relation)
    ratio = calculate_sales_ratio(correction)
    evidence = {block.evidence_id: block for document in (original, correction) for block in document.evidence_blocks}
    return {
        "relation": relation, "changes": changes, "ratio": ratio, "evidence": evidence,
        "events": state.get("events", []) + ["compare_changes"],
    }


def analyze_claims(state: ReviewGraphState) -> dict:
    result = analyze_memo(
        state["memo"], state["original"], state["correction"],
        scenario_id=state.get("scenario_id"), llm_mode=state["llm_mode"], model=state.get("model"),
        timeout_seconds=state.get("timeout_seconds", 30), max_retries=state.get("max_retries", 2),
        changes=state["changes"], ratio=state["ratio"], evidence=state["evidence"],
    )
    return {"result": result, "events": state.get("events", []) + ["analyze_claims"]}


def route_result(state: ReviewGraphState) -> Literal["complete", "needs_review"]:
    result = state["result"]
    return "needs_review" if result.failures or result.unresolved_claim_count else "complete"


def complete_review(state: ReviewGraphState) -> dict:
    return {"outcome": "complete", "events": state.get("events", []) + ["complete_review"]}


def mark_needs_review(state: ReviewGraphState) -> dict:
    return {"outcome": "needs_review", "events": state.get("events", []) + ["mark_needs_review"]}


def build_review_graph():
    builder = StateGraph(ReviewGraphState)
    builder.add_node("parse_filings", parse_filings)
    builder.add_node("compare_changes", compare_changes)
    builder.add_node("analyze_claims", analyze_claims)
    builder.add_node("complete_review", complete_review)
    builder.add_node("mark_needs_review", mark_needs_review)
    builder.add_edge(START, "parse_filings")
    builder.add_edge("parse_filings", "compare_changes")
    builder.add_edge("compare_changes", "analyze_claims")
    builder.add_conditional_edges(
        "analyze_claims", route_result,
        {"complete": "complete_review", "needs_review": "mark_needs_review"},
    )
    builder.add_edge("complete_review", END)
    builder.add_edge("mark_needs_review", END)
    return builder.compile()


review_graph = build_review_graph()


def run_review_graph(
    original_html: str,
    correction_html: str,
    memo: str,
    *,
    llm_mode: str = "fake",
    model: str | None = None,
    timeout_seconds: float = 30,
    max_retries: int = 2,
) -> ReviewGraphState:
    return review_graph.invoke({
        "original_html": original_html,
        "correction_html": correction_html,
        "memo": memo,
        "llm_mode": llm_mode,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
        "scenario_id": SUPPORTED_SCENARIO if llm_mode == "fake" else None,
        "events": [],
    })
