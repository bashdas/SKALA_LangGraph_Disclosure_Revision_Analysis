from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from disclosure_impact_agent.analysis import calculate_sales_ratio, compare_sequence, reconcile_correction_body
from disclosure_impact_agent.models import DocumentFormat, SourceKind
from disclosure_impact_agent.parser import parse_filing, validate_evidence_integrity


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
    parser = argparse.ArgumentParser(description="Offline stage-1 filing inspection")
    parser.add_argument("original", type=Path)
    parser.add_argument("correction", type=Path)
    args = parser.parse_args()
    print_json(inspect_pair(args.original, args.correction))


def print_json(value: dict) -> None:
    import json
    print(json.dumps(value, ensure_ascii=False, indent=2))
