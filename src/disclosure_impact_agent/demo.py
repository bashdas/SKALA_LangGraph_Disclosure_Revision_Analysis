from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import gradio as gr

from disclosure_impact_agent.analysis import compare_documents, reconcile_correction_body, relate_contracts
from disclosure_impact_agent.fake_llm import SUPPORTED_SCENARIO
from disclosure_impact_agent.models import DocumentFormat, SourceKind
from disclosure_impact_agent.parser import parse_filing
from disclosure_impact_agent.service import analyze_memo

PROJECT_ROOT = Path(__file__).parents[2]
FIXTURE_DIR = PROJECT_ROOT / "fixtures/synthetic/a_company_contract"


def example_values() -> tuple[str, str, str]:
    return (
        (FIXTURE_DIR / "original.html").read_text(),
        (FIXTURE_DIR / "correction.html").read_text(),
        (FIXTURE_DIR / "memo.md").read_text(),
    )


def run_demo(
    original_html: str,
    correction_html: str,
    memo: str,
    llm_mode: str,
    model: str,
) -> tuple[str, list[list[str]], list[list[str]], str]:
    """One demo path: parse -> compare -> connect memo claims -> show proposals."""
    original = parse_filing(
        original_html.encode(), document_id="demo-original", original_filename="original.html",
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, submitted_on=date(2026, 1, 1),
    )
    correction = reconcile_correction_body(parse_filing(
        correction_html.encode(), document_id="demo-correction", original_filename="correction.html",
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, submitted_on=date(2026, 6, 1),
        corrects_document_id=original.document_id,
    ))
    relation = relate_contracts(original, correction)
    changes = compare_documents(original, correction, relation)
    result = analyze_memo(
        memo, original, correction, scenario_id=SUPPORTED_SCENARIO if llm_mode == "fake" else None,
        llm_mode=llm_mode, model=model.strip() or None,
    )

    change_rows = [
        [
            change.field_name.value,
            change.before.raw_value if change.before else "-",
            change.after.raw_value if change.after else "-",
            change.status.value,
        ]
        for change in changes
        if change.status.value != "unchanged"
    ]
    claim_text = {claim.claim_id: claim.span.text for claim in result.claims}
    impact_rows = [
        [
            claim_text.get(impact.claim_id, impact.claim_id),
            impact.classification.value,
            impact.reason_summary,
            "가능" if impact.revision_allowed else "검토/제외",
        ]
        for impact in result.impacts
    ]
    if result.failures:
        message = "\n".join(f"- `{failure.code}`: {failure.message}" for failure in result.failures)
        status = f"### 분석 실패 또는 보류\n{message}\n\n실패를 영향 없음으로 처리하지 않았습니다."
    else:
        status = (
            f"### 분석 완료\n데이터: **synthetic** · LLM 모드: **{result.llm_mode}** · "
            f"검토 주장: **{result.reviewed_claim_count}** · 보류: **{result.unresolved_claim_count}**"
        )
    proposals = "\n".join(
        f"- ~~{proposal.original_sentence}~~  \n  → {proposal.proposed_sentence}"
        for proposal in result.proposals
    ) or "자동 수정안이 없습니다."
    return status, change_rows, impact_rows, proposals


def build_demo() -> gr.Blocks:
    original, correction, memo = example_values()
    with gr.Blocks(title="공시 정정 영향 추적 데모") as demo:
        gr.Markdown("# 공시 정정 영향 추적\n합성 공시의 변경이 분석 메모의 어느 주장에 영향을 주는지 확인합니다.")
        gr.Markdown("**주의:** 기본 예시는 mock/synthetic 데이터이며 실제 DART·실제 LLM 검증 결과가 아닙니다.")
        with gr.Row():
            llm_mode = gr.Radio(["fake", "openai"], value="fake", label="분석 모드")
            model = gr.Textbox(value=os.getenv("OPENAI_MODEL", ""), label="OpenAI 모델명", placeholder="openai 모드에서만 필요")
        with gr.Accordion("입력 데이터", open=False):
            original_input = gr.Code(value=original, language="html", label="정정 전 공시")
            correction_input = gr.Code(value=correction, language="html", label="정정 공시")
        memo_input = gr.Textbox(value=memo, lines=8, label="기업분석 메모")
        run_button = gr.Button("영향 분석", variant="primary")
        status = gr.Markdown()
        gr.Markdown("## 공시 변경")
        changes = gr.Dataframe(headers=["필드", "정정 전", "정정 후", "상태"], datatype="str", interactive=False)
        gr.Markdown("## 메모 주장별 영향")
        impacts = gr.Dataframe(headers=["주장", "분류", "근거 요약", "자동 수정"], datatype="str", interactive=False)
        gr.Markdown("## 검증된 수정안")
        proposals = gr.Markdown()
        run_button.click(
            run_demo,
            inputs=[original_input, correction_input, memo_input, llm_mode, model],
            outputs=[status, changes, impacts, proposals],
        )
    return demo


def main() -> None:
    build_demo().launch(
        server_name="127.0.0.1",
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        share=False,
        show_error=True,
    )


if __name__ == "__main__":
    main()
