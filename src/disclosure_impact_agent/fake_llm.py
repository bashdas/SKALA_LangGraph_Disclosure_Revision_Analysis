from __future__ import annotations

import re

from disclosure_impact_agent.interfaces import ClaimExtractor
from disclosure_impact_agent.memo_models import Claim, ClaimBatch, ClaimKind, ClaimTime, MemoSentence, TextSpan
from disclosure_impact_agent.models import FieldName

SUPPORTED_SCENARIO = "synthetic-a-company-contract-v1"


class UnsupportedFakeFixtureError(ValueError):
    pass


class FixtureClaimExtractor(ClaimExtractor):
    """Deterministic test double restricted to one explicitly identified fixture."""

    def extract(self, memo: str, *, scenario_id: str | None = None) -> ClaimBatch:
        if scenario_id != SUPPORTED_SCENARIO:
            raise UnsupportedFakeFixtureError("fake extractor only supports the declared synthetic fixture")
        specs = [
            ("120억원", ClaimKind.FACT, ClaimTime.CURRENT, FieldName.CONTRACT_AMOUNT, "120억원", "가상 A사", "산업용 장비 공급"),
            ("15%", ClaimKind.CALCULATION, ClaimTime.CURRENT, FieldName.DISCLOSED_SALES_RATIO, "15%", "가상 A사", "산업용 장비 공급"),
            ("2026년 말", ClaimKind.FACT, ClaimTime.CURRENT, FieldName.CONTRACT_END_DATE, "2026년 말", "가상 A사", "산업용 장비 공급"),
            ("2026년 매출로 반영될 전망", ClaimKind.FORECAST, ClaimTime.CURRENT, FieldName.CONTRACT_END_DATE, None, "가상 A사", "산업용 장비 공급"),
            ("산업용 장비 제조업체", ClaimKind.FACT, ClaimTime.CURRENT, None, None, "가상 A사", None),
        ]
        sentence_matches = list(re.finditer(r"(?m)^\s*\d+\.\s*(.+)$", memo))
        if len(sentence_matches) != 5:
            raise UnsupportedFakeFixtureError("fixture memo text no longer matches the declared five-sentence shape")
        sentences, claims = [], []
        for index, (match, spec) in enumerate(zip(sentence_matches, specs), start=1):
            sentence_text = match.group(1)
            sentence_start = match.start(1)
            sentence = MemoSentence(sentence_id=f"sent-{index}", span=TextSpan(start=sentence_start, end=sentence_start + len(sentence_text), text=sentence_text))
            sentences.append(sentence)
            needle, kind, time_context, field_name, claimed_value, company, contract = spec
            local_start = sentence_text.index(needle)
            absolute_start = sentence_start + local_start
            claim_span = TextSpan(start=absolute_start, end=absolute_start + len(needle), text=needle)
            claims.append(Claim(
                claim_id=f"claim-{index}", sentence_id=sentence.sentence_id, span=claim_span,
                value_span=claim_span if claimed_value else None, company=company, contract=contract,
                kind=kind, time_context=time_context, field_name=field_name, claimed_value=claimed_value,
            ))
        return ClaimBatch(sentences=sentences, claims=claims)
