from __future__ import annotations

import hashlib
from decimal import Decimal

from disclosure_impact_agent.models import (
    ChangeStatus,
    ContractRelationCandidate,
    ExtractionIssue,
    FieldChange,
    FieldName,
    FilingDocument,
    IssueCode,
    RatioCalculation,
    RelationEvidence,
    RelationStatus,
    SequenceComparison,
    StructuredField,
    ValueState,
)

COMPARABLE_FIELDS = (
    FieldName.CONTRACT_AMOUNT,
    FieldName.CONTRACT_START_DATE,
    FieldName.CONTRACT_END_DATE,
    FieldName.COUNTERPARTY,
    FieldName.SALES_AMOUNT,
    FieldName.DISCLOSED_SALES_RATIO,
)


def _known_equal(left: StructuredField | None, right: StructuredField | None) -> bool:
    return bool(
        left and right
        and left.value_state in {ValueState.PRESENT, ValueState.ZERO}
        and right.value_state in {ValueState.PRESENT, ValueState.ZERO}
        and left.normalized_value == right.normalized_value
    )


def relate_contracts(
    earlier: FilingDocument,
    later: FilingDocument,
    *,
    user_confirmed: bool = False,
) -> ContractRelationCandidate:
    link_match = later.corrects_document_id == earlier.document_id
    content_match = _known_equal(earlier.field(FieldName.CONTRACT_CONTENT), later.field(FieldName.CONTRACT_CONTENT))
    counterparty_match = _known_equal(earlier.field(FieldName.COUNTERPARTY), later.field(FieldName.COUNTERPARTY))
    start_match = _known_equal(earlier.field(FieldName.CONTRACT_START_DATE), later.field(FieldName.CONTRACT_START_DATE))
    evidence = [
        RelationEvidence(criterion="explicit_correction_link", matched=link_match, detail=f"corrects_document_id={later.corrects_document_id!r}"),
        RelationEvidence(
            criterion="contract_content", matched=content_match, detail="normalized contract content comparison",
            evidence_ids=[field.evidence_id for field in (earlier.field(FieldName.CONTRACT_CONTENT), later.field(FieldName.CONTRACT_CONTENT)) if field],
        ),
        RelationEvidence(
            criterion="counterparty", matched=counterparty_match, detail="known counterparty comparison",
            evidence_ids=[field.evidence_id for field in (earlier.field(FieldName.COUNTERPARTY), later.field(FieldName.COUNTERPARTY)) if field],
        ),
        RelationEvidence(
            criterion="contract_start_date", matched=start_match, detail="known start-date comparison",
            evidence_ids=[field.evidence_id for field in (earlier.field(FieldName.CONTRACT_START_DATE), later.field(FieldName.CONTRACT_START_DATE)) if field],
        ),
    ]
    conflicts = []
    for name in (FieldName.CONTRACT_CONTENT, FieldName.COUNTERPARTY, FieldName.CONTRACT_START_DATE):
        left, right = earlier.field(name), later.field(name)
        if left and right and left.value_state == right.value_state == ValueState.PRESENT and left.normalized_value != right.normalized_value:
            conflicts.append(f"{name.value} differs")
    if user_confirmed:
        status = RelationStatus.USER_CONFIRMED
    elif link_match and content_match and (counterparty_match or start_match) and not conflicts:
        status = RelationStatus.VERIFIED_AUTOMATIC
    elif conflicts and not link_match:
        status = RelationStatus.REJECTED
    else:
        status = RelationStatus.CANDIDATE
    return ContractRelationCandidate(
        earlier_document_id=earlier.document_id,
        later_document_id=later.document_id,
        status=status,
        evidence=evidence,
        conflicts=conflicts,
    )


def reconcile_correction_body(document: FilingDocument) -> FilingDocument:
    issues = list(document.issues)
    for entry in document.correction_entries:
        body = document.field(entry.field_name)
        if not body or body.value_state not in {ValueState.PRESENT, ValueState.ZERO}:
            continue
        if entry.after.value_state in {ValueState.PRESENT, ValueState.ZERO} and entry.after.normalized_value != body.normalized_value:
            issues.append(ExtractionIssue(
                code=IssueCode.CORRECTION_BODY_CONFLICT,
                message=f"Correction table after-value conflicts with body for {entry.field_name.value}",
                field_name=entry.field_name,
                evidence_ids=[entry.after.evidence_id, body.evidence_id],
            ))
    return document.model_copy(update={
        "issues": issues,
        "extraction_complete": document.extraction_complete and not any(issue.blocking for issue in issues),
    })


def _basis_compatible(field_name: FieldName, before: StructuredField, after: StructuredField) -> tuple[bool, str]:
    if field_name in {FieldName.CONTRACT_AMOUNT, FieldName.SALES_AMOUNT}:
        checks = {
            "currency": (before.basis.currency, after.basis.currency),
            "vat_included": (before.basis.vat_included, after.basis.vat_included),
            "amount_status": (before.basis.amount_status, after.basis.amount_status),
        }
        if field_name == FieldName.SALES_AMOUNT:
            checks.update({
                "fiscal_year": (before.basis.fiscal_year, after.basis.fiscal_year),
                "consolidation": (before.basis.consolidation, after.basis.consolidation),
            })
        differences = [name for name, (left, right) in checks.items() if left != right]
        if differences:
            return False, "comparison basis differs: " + ", ".join(differences)
    return True, "comparison basis compatible"


def compare_documents(
    baseline: FilingDocument,
    target: FilingDocument,
    relation: ContractRelationCandidate,
    *,
    comparison_kind: str = "previous",
) -> list[FieldChange]:
    relation_ok = relation.status in {RelationStatus.VERIFIED_AUTOMATIC, RelationStatus.USER_CONFIRMED}
    conflict_fields = {
        issue.field_name for issue in target.issues if issue.code == IssueCode.CORRECTION_BODY_CONFLICT
    }
    correction_before_conflicts: set[FieldName] = set()
    for entry in target.correction_entries:
        baseline_field = baseline.field(entry.field_name)
        if (
            baseline_field
            and baseline_field.value_state in {ValueState.PRESENT, ValueState.ZERO}
            and entry.before.value_state in {ValueState.PRESENT, ValueState.ZERO}
            and baseline_field.normalized_value != entry.before.normalized_value
        ):
            correction_before_conflicts.add(entry.field_name)
    changes = []
    for name in COMPARABLE_FIELDS:
        before, after = baseline.field(name), target.field(name)
        digest = hashlib.sha256(f"{baseline.document_id}|{target.document_id}|{comparison_kind}|{name.value}".encode()).hexdigest()[:16]
        evidence_ids = [item.evidence_id for item in (before, after) if item]
        status = ChangeStatus.UNRESOLVED
        reason = ""
        if not relation_ok:
            reason = "contract relation is not verified"
        elif name in conflict_fields:
            reason = "correction table and corrected body conflict"
        elif name in correction_before_conflicts:
            reason = "correction table before-value conflicts with baseline body"
        elif before is None or after is None:
            reason = "field missing from one or both documents"
        elif before.value_state not in {ValueState.PRESENT, ValueState.ZERO} or after.value_state not in {ValueState.PRESENT, ValueState.ZERO}:
            reason = f"non-comparable value state: {before.value_state.value}/{after.value_state.value}"
        else:
            compatible, basis_reason = _basis_compatible(name, before, after)
            if not compatible:
                reason = basis_reason
            elif before.normalized_value == after.normalized_value:
                status, reason = ChangeStatus.UNCHANGED, "normalized values are equal"
            else:
                status, reason = ChangeStatus.CHANGED, "normalized values differ"
        changes.append(FieldChange(
            change_id=f"chg-{digest}", field_name=name,
            baseline_document_id=baseline.document_id, target_document_id=target.document_id,
            comparison_kind=comparison_kind, status=status, before=before, after=after,
            evidence_ids=evidence_ids, reason=reason,
        ))
    return changes


def calculate_sales_ratio(document: FilingDocument) -> RatioCalculation:
    amount = document.field(FieldName.CONTRACT_AMOUNT)
    sales = document.field(FieldName.SALES_AMOUNT)
    disclosed = document.field(FieldName.DISCLOSED_SALES_RATIO)
    evidence_ids = [field.evidence_id for field in (amount, sales, disclosed) if field]
    disclosed_value = None
    if disclosed and disclosed.value_state in {ValueState.PRESENT, ValueState.ZERO}:
        disclosed_value = Decimal(disclosed.normalized_value)
    if not amount or not sales:
        return RatioCalculation(document_id=document.document_id, disclosed_ratio=disclosed_value, recalculated_ratio=None, eligible=False, reason="amount or sales denominator is missing", evidence_ids=evidence_ids)
    if amount.value_state not in {ValueState.PRESENT, ValueState.ZERO} or sales.value_state not in {ValueState.PRESENT, ValueState.ZERO}:
        return RatioCalculation(document_id=document.document_id, disclosed_ratio=disclosed_value, recalculated_ratio=None, eligible=False, reason="amount or denominator is not a numeric value", evidence_ids=evidence_ids)
    if not sales.basis.fiscal_year or sales.basis.consolidation not in {"consolidated", "separate"}:
        return RatioCalculation(document_id=document.document_id, disclosed_ratio=disclosed_value, recalculated_ratio=None, eligible=False, reason="sales fiscal year or consolidation basis is unconfirmed", evidence_ids=evidence_ids)
    if amount.basis.currency != sales.basis.currency:
        return RatioCalculation(document_id=document.document_id, disclosed_ratio=disclosed_value, recalculated_ratio=None, eligible=False, reason="amount and sales currencies differ", evidence_ids=evidence_ids)
    denominator = Decimal(sales.normalized_value)
    if denominator == 0:
        return RatioCalculation(document_id=document.document_id, disclosed_ratio=disclosed_value, recalculated_ratio=None, eligible=False, reason="sales denominator is zero", evidence_ids=evidence_ids)
    numerator = Decimal(amount.normalized_value)
    result = numerator / denominator * Decimal(100)
    return RatioCalculation(
        document_id=document.document_id, disclosed_ratio=disclosed_value,
        recalculated_ratio=result, eligible=True,
        formula=f"{numerator} / {denominator} * 100", reason="required denominator basis is confirmed",
        evidence_ids=evidence_ids,
    )


def compare_sequence(documents: list[FilingDocument], *, baseline_index: int = 0) -> SequenceComparison:
    if not documents:
        return SequenceComparison(document_order=[], relations=[], previous_changes=[], cumulative_changes=[], issues=[
            ExtractionIssue(code=IssueCode.DOCUMENT_MISSING, message="No documents supplied")
        ])
    if not 0 <= baseline_index < len(documents):
        raise ValueError("baseline_index is outside document sequence")
    documents = [reconcile_correction_body(document) for document in documents]
    relations = [relate_contracts(documents[index - 1], documents[index]) for index in range(1, len(documents))]
    previous = []
    for index, relation in enumerate(relations, start=1):
        previous.extend(compare_documents(documents[index - 1], documents[index], relation, comparison_kind="previous"))
    cumulative = []
    for index in range(baseline_index + 1, len(documents)):
        relation = relate_contracts(documents[baseline_index], documents[index])
        chain = relations[baseline_index:index]
        if (
            relation.status == RelationStatus.CANDIDATE
            and chain
            and all(item.status in {RelationStatus.VERIFIED_AUTOMATIC, RelationStatus.USER_CONFIRMED} for item in chain)
        ):
            relation = relation.model_copy(update={
                "status": RelationStatus.VERIFIED_AUTOMATIC,
                "evidence": relation.evidence + [RelationEvidence(
                    criterion="verified_relation_chain", matched=True,
                    detail=" -> ".join(doc.document_id for doc in documents[baseline_index:index + 1]),
                )],
            })
        cumulative.extend(compare_documents(documents[baseline_index], documents[index], relation, comparison_kind="cumulative"))
    issues = []
    for earlier, later in zip(documents, documents[1:]):
        if earlier.submitted_on and later.submitted_on and later.submitted_on < earlier.submitted_on:
            issues.append(ExtractionIssue(
                code=IssueCode.CHRONOLOGY_CONFLICT,
                message=f"Submission order conflicts with sequence: {earlier.document_id} -> {later.document_id}",
            ))
    for relation in relations:
        if relation.status not in {RelationStatus.VERIFIED_AUTOMATIC, RelationStatus.USER_CONFIRMED}:
            issues.append(ExtractionIssue(
                code=IssueCode.RELATION_UNCONFIRMED,
                message=f"Relation unconfirmed: {relation.earlier_document_id} -> {relation.later_document_id}",
            ))
    issues.extend(issue for document in documents for issue in document.issues)
    return SequenceComparison(
        document_order=[document.document_id for document in documents],
        relations=relations, previous_changes=previous, cumulative_changes=cumulative, issues=issues,
    )
