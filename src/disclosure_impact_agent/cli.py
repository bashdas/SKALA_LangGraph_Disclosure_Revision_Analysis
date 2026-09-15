from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from disclosure_impact_agent.analysis import calculate_sales_ratio, compare_sequence, reconcile_correction_body
from disclosure_impact_agent.environment import load_project_environment
from disclosure_impact_agent.models import DocumentFormat, SourceKind
from disclosure_impact_agent.parser import parse_filing, validate_evidence_integrity
from disclosure_impact_agent.service import analyze_memo


load_project_environment()


def inspect_pair(original_path: Path, correction_path: Path) -> dict:
    original = parse_filing(
        original_path.read_bytes(), document_id="synthetic-original",
        original_filename=original_path.name, document_format=DocumentFormat.HTML,
        source_kind=SourceKind.SYNTHETIC, source_verified=True, synthetic=True,
        submitted_on=date(2026, 1, 1),
    )
    correction = reconcile_correction_body(parse_filing(
        correction_path.read_bytes(), document_id="synthetic-correction",
        original_filename=correction_path.name, document_format=DocumentFormat.HTML,
        source_kind=SourceKind.SYNTHETIC, source_verified=True, synthetic=True,
        submitted_on=date(2026, 6, 1), corrects_document_id=original.document_id,
    ))
    comparison = compare_sequence([original, correction])
    ratio = calculate_sales_ratio(correction)
    return {
        "data_class": "synthetic",
        "llm_used": False,
        "documents": [
            {
                "document_id": item.document_id,
                "sha256": item.document_hash,
                "extraction_complete": item.extraction_complete,
                "evidence_integrity_errors": validate_evidence_integrity(item),
            }
            for item in (original, correction)
        ],
        "comparison": comparison.model_dump(mode="json"),
        "corrected_ratio": ratio.model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline filing and memo impact inspection")
    parser.add_argument("original", type=Path)
    parser.add_argument("correction", type=Path)
    parser.add_argument("--memo", type=Path, help="Analyze memo impacts (stage 2)")
    parser.add_argument("--scenario-id", default="synthetic-a-company-contract-v1")
    parser.add_argument("--llm-mode", choices=["fake", "openai"], default=os.getenv("LLM_MODE", "fake"))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL"), help="Required only for --llm-mode=openai")
    args = parser.parse_args()
    if not args.memo:
        print_json(inspect_pair(args.original, args.correction))
        return
    original = parse_filing(
        args.original.read_bytes(), document_id="synthetic-original", original_filename=args.original.name,
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, submitted_on=date(2026, 1, 1),
    )
    correction = parse_filing(
        args.correction.read_bytes(), document_id="synthetic-correction", original_filename=args.correction.name,
        document_format=DocumentFormat.HTML, source_kind=SourceKind.SYNTHETIC,
        source_verified=True, synthetic=True, submitted_on=date(2026, 6, 1),
        corrects_document_id=original.document_id,
    )
    result = analyze_memo(
        args.memo.read_text(), original, correction, scenario_id=args.scenario_id,
        llm_mode=args.llm_mode, model=args.model,
        timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        max_memo_chars=int(os.getenv("MAX_MEMO_CHARS", "5000")),
    )
    print_json(result.model_dump(mode="json"))


def print_json(value: dict) -> None:
    import json
    print(json.dumps(value, ensure_ascii=False, indent=2))
