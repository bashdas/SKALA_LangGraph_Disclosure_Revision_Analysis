from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from disclosure_impact_agent.models import ComparisonBasis, FieldName, StructuredField, ValueState

_EMPTY = {"", "-", "—"}
_WITHHELD = {"유보", "비공개", "기재유보"}
_UNDISCLOSED = {"미공개", "미정", "미기재"}
_UNIT_MULTIPLIERS = {"원": Decimal(1), "천원": Decimal(1_000), "백만원": Decimal(1_000_000), "억원": Decimal(100_000_000)}


def classify_text(raw: str) -> ValueState:
    value = raw.strip()
    if value in _EMPTY:
        return ValueState.EMPTY
    if value in _WITHHELD:
        return ValueState.WITHHELD
    if value in _UNDISCLOSED:
        return ValueState.UNDISCLOSED
    return ValueState.PRESENT


def normalize_amount(name: FieldName, raw: str, evidence_id: str) -> StructuredField:
    state = classify_text(raw)
    if state != ValueState.PRESENT:
        return StructuredField(name=name, raw_value=raw, value_state=state, evidence_id=evidence_id)
    compact = re.sub(r"\s+", "", raw)
    match = re.search(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(억원|백만원|천원|원)", compact)
    currency = "KRW"
    if not match:
        match = re.search(r"(?:USD|US\$|\$)([-+]?\d[\d,]*(?:\.\d+)?)", compact, re.IGNORECASE)
        currency = "USD"
    if not match:
        return StructuredField(name=name, raw_value=raw, value_state=ValueState.PARSE_FAILED, evidence_id=evidence_id)
    try:
        multiplier = _UNIT_MULTIPLIERS[match.group(2)] if currency == "KRW" else Decimal(1)
        value = Decimal(match.group(1).replace(",", "")) * multiplier
    except InvalidOperation:
        return StructuredField(name=name, raw_value=raw, value_state=ValueState.PARSE_FAILED, evidence_id=evidence_id)
    normalized = int(value) if value == value.to_integral_value() else value
    state = ValueState.ZERO if value == 0 else ValueState.PRESENT
    year_match = re.search(r"(20\d{2})년", raw)
    scope = "consolidated" if "연결" in raw else "separate" if "별도" in raw else None
    vat = True if "부가세 포함" in raw else False if "부가세 제외" in raw else None
    amount_status = "conditional" if "조건부" in raw else "confirmed" if "확정" in raw else None
    basis = ComparisonBasis(
        currency=currency,
        unit=match.group(2) if currency == "KRW" else "USD",
        fiscal_year=int(year_match.group(1)) if year_match else None,
        consolidation=scope,
        vat_included=vat,
        amount_status=amount_status,
    )
    return StructuredField(name=name, raw_value=raw, normalized_value=normalized, value_state=state, basis=basis, evidence_id=evidence_id)


def normalize_date(name: FieldName, raw: str, evidence_id: str) -> StructuredField:
    state = classify_text(raw)
    if state != ValueState.PRESENT:
        return StructuredField(name=name, raw_value=raw, value_state=state, evidence_id=evidence_id)
    match = re.fullmatch(r"\s*(\d{4})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})일?\s*", raw)
    if not match:
        return StructuredField(name=name, raw_value=raw, value_state=ValueState.PARSE_FAILED, evidence_id=evidence_id)
    try:
        value = date(*(int(part) for part in match.groups()))
    except ValueError:
        return StructuredField(name=name, raw_value=raw, value_state=ValueState.PARSE_FAILED, evidence_id=evidence_id)
    return StructuredField(name=name, raw_value=raw, normalized_value=value, value_state=ValueState.PRESENT, evidence_id=evidence_id)


def normalize_ratio(raw: str, evidence_id: str) -> StructuredField:
    state = classify_text(raw)
    if state != ValueState.PRESENT:
        return StructuredField(name=FieldName.DISCLOSED_SALES_RATIO, raw_value=raw, value_state=state, evidence_id=evidence_id)
    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%", raw)
    if not match:
        return StructuredField(name=FieldName.DISCLOSED_SALES_RATIO, raw_value=raw, value_state=ValueState.PARSE_FAILED, evidence_id=evidence_id)
    value = Decimal(match.group(1))
    return StructuredField(
        name=FieldName.DISCLOSED_SALES_RATIO,
        raw_value=raw,
        normalized_value=value,
        value_state=ValueState.ZERO if value == 0 else ValueState.PRESENT,
        evidence_id=evidence_id,
    )


def normalize_text(name: FieldName, raw: str, evidence_id: str) -> StructuredField:
    state = classify_text(raw)
    return StructuredField(
        name=name,
        raw_value=raw,
        normalized_value=raw.strip() if state == ValueState.PRESENT else None,
        value_state=state,
        evidence_id=evidence_id,
    )


def normalize_field(name: FieldName, raw: str, evidence_id: str) -> StructuredField:
    if name in {FieldName.CONTRACT_AMOUNT, FieldName.SALES_AMOUNT}:
        return normalize_amount(name, raw, evidence_id)
    if name in {FieldName.CONTRACT_START_DATE, FieldName.CONTRACT_END_DATE}:
        return normalize_date(name, raw, evidence_id)
    if name == FieldName.DISCLOSED_SALES_RATIO:
        return normalize_ratio(raw, evidence_id)
    return normalize_text(name, raw, evidence_id)
