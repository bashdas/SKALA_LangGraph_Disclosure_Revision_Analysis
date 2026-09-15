from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from disclosure_impact_agent.interfaces import ImpactAnalyzer, RevisionProposer
from disclosure_impact_agent.memo_models import (
    Claim,
    ClaimBatch,
    ClaimKind,
    ClaimTime,
    EvidenceAssessment,
    Impact,
    ImpactClass,
    RevisionEdit,
    RevisionProposal,
)
from disclosure_impact_agent.models import ChangeStatus, EvidenceBlock, FieldChange, FieldName, RatioCalculation, ValueState
from disclosure_impact_agent.normalization import normalize_field


def _claim_normalized(claim: Claim):
    if not claim.field_name or not claim.claimed_value:
        return None
    if claim.field_name == FieldName.CONTRACT_END_DATE and re.fullmatch(r"\d{4}년 말", claim.claimed_value):
        return date(int(claim.claimed_value[:4]), 12, 31)
    field = normalize_field(claim.field_name, claim.claimed_value, "memo")
    return field.normalized_value if field.value_state in {ValueState.PRESENT, ValueState.ZERO} else None


def _assess_evidence(change: FieldChange, evidence: dict[str, EvidenceBlock]) -> EvidenceAssessment:
    blocks = [evidence.get(evidence_id) for evidence_id in change.evidence_ids]
    existence = bool(blocks) and all(block is not None for block in blocks)
    semantic = bool(
        existence and change.after and change.after.evidence_id in evidence
        and evidence[change.after.evidence_id].raw_text == change.after.raw_value
    )
    return EvidenceAssessment(
        existence_verified=existence, semantic_support_verified=semantic,
        evidence_ids=change.evidence_ids,
        note="location and structured after-value verified" if semantic else "evidence missing or not semantically linked",
    )


class DeterministicImpactAnalyzer(ImpactAnalyzer):
    def analyze(
        self, claims: ClaimBatch, changes: list[FieldChange], ratio: RatioCalculation,
        evidence: dict[str, EvidenceBlock],
    ) -> list[Impact]:
        by_field = {change.field_name: change for change in changes}
        impacts = []
        for claim in claims.claims:
            change = by_field.get(claim.field_name) if claim.field_name else None
            empty_evidence = EvidenceAssessment(existence_verified=True, semantic_support_verified=True, evidence_ids=[], note="no changed filing field is referenced")
            if claim.time_context == ClaimTime.HISTORICAL:
                impacts.append(Impact(claim_id=claim.claim_id, evidence=empty_evidence, classification=ImpactClass.NO_IMPACT, reason_summary="historical statement is not overwritten by a current correction"))
                continue
            if claim.kind == ClaimKind.FORECAST:
                if change and change.status == ChangeStatus.CHANGED:
                    impacts.append(Impact(
                        claim_id=claim.claim_id, change_ids=[change.change_id], evidence=_assess_evidence(change, evidence),
                        classification=ImpactClass.INTERPRETATION_REVIEW,
                        reason_summary="the corrected field is a premise of this forecast, but does not prove the forecast",
                        missing_information=["revenue recognition basis"], revision_allowed=False,
                    ))
                elif change and change.status == ChangeStatus.UNRESOLVED:
                    impacts.append(self._unresolved(claim, change, evidence))
                else:
                    impacts.append(Impact(claim_id=claim.claim_id, evidence=empty_evidence, classification=ImpactClass.NO_IMPACT, reason_summary="no verified changed premise is linked"))
                continue
            if claim.kind == ClaimKind.CALCULATION and claim.field_name == FieldName.DISCLOSED_SALES_RATIO:
                if not ratio.eligible or ratio.recalculated_ratio is None:
                    assessment = _assess_evidence(change, evidence) if change else empty_evidence
                    impacts.append(Impact(
                        claim_id=claim.claim_id, change_ids=[change.change_id] if change else [], evidence=assessment,
                        classification=ImpactClass.UNRESOLVED, reason_summary="calculation inputs or comparison basis are incomplete",
                        missing_information=[ratio.reason], revision_allowed=False,
                    ))
                else:
                    claimed = _claim_normalized(claim)
                    changed = claimed != ratio.recalculated_ratio
                    inputs_exist = bool(ratio.evidence_ids) and all(item in evidence for item in ratio.evidence_ids)
                    assessment = EvidenceAssessment(
                        existence_verified=inputs_exist,
                        semantic_support_verified=inputs_exist and ratio.eligible,
                        evidence_ids=ratio.evidence_ids,
                        note="server calculation numerator, denominator, and disclosed ratio verified" if inputs_exist else "calculation evidence is missing",
                    )
                    impacts.append(Impact(
                        claim_id=claim.claim_id, change_ids=[change.change_id] if change else [], evidence=assessment,
                        classification=ImpactClass.DERIVED_VALUE_CHANGE if changed else ImpactClass.NO_IMPACT,
                        reason_summary="server-recalculated ratio differs" if changed else "claim already matches server-recalculated ratio",
                        revision_allowed=changed and assessment.semantic_support_verified,
                    ))
                continue
            if not change:
                impacts.append(Impact(claim_id=claim.claim_id, evidence=empty_evidence, classification=ImpactClass.NO_IMPACT, reason_summary="claim is outside the verified changed fields"))
            elif change.status == ChangeStatus.UNRESOLVED:
                impacts.append(self._unresolved(claim, change, evidence))
            elif change.status == ChangeStatus.UNCHANGED:
                impacts.append(Impact(claim_id=claim.claim_id, change_ids=[change.change_id], evidence=_assess_evidence(change, evidence), classification=ImpactClass.NO_IMPACT, reason_summary="linked filing field is unchanged"))
            else:
                assessment = _assess_evidence(change, evidence)
                claimed = _claim_normalized(claim)
                if change.after and claimed == change.after.normalized_value:
                    classification, reason, allowed = ImpactClass.NO_IMPACT, "claim already reflects the corrected value", False
                elif change.before and claimed == change.before.normalized_value:
                    classification, reason, allowed = ImpactClass.DIRECT_FACT_CHANGE, "current fact claim matches the superseded value", assessment.semantic_support_verified
                else:
                    classification, reason, allowed = ImpactClass.UNRESOLVED, "claim value does not match either verified filing value", False
                impacts.append(Impact(
                    claim_id=claim.claim_id, change_ids=[change.change_id], evidence=assessment,
                    classification=classification, reason_summary=reason,
                    missing_information=[] if classification != ImpactClass.UNRESOLVED else ["claim-to-value alignment"],
                    revision_allowed=allowed,
                ))
        return impacts

    @staticmethod
    def _unresolved(claim: Claim, change: FieldChange, evidence: dict[str, EvidenceBlock]) -> Impact:
        return Impact(
            claim_id=claim.claim_id, change_ids=[change.change_id], evidence=_assess_evidence(change, evidence),
            classification=ImpactClass.UNRESOLVED, reason_summary="linked filing change is unresolved",
            missing_information=[change.reason], revision_allowed=False,
        )


def _replacement(claim: Claim, change: FieldChange, ratio: RatioCalculation) -> str | None:
    if claim.kind == ClaimKind.CALCULATION and ratio.recalculated_ratio is not None:
        value = ratio.recalculated_ratio.normalize()
        return f"{format(value, 'f')}%"
    if not change.after:
        return None
    value = change.after.normalized_value
    if claim.field_name == FieldName.CONTRACT_AMOUNT and isinstance(value, int):
        if claim.claimed_value and "억원" in claim.claimed_value and value % 100_000_000 == 0:
            return f"{value // 100_000_000}억원"
        return f"{value:,}원"
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if value is not None else None


class DeterministicRevisionProposer(RevisionProposer):
    def propose(
        self, memo: str, claims: ClaimBatch, impacts: list[Impact], changes: list[FieldChange],
        evidence: dict[str, EvidenceBlock], ratio: RatioCalculation | None = None,
    ) -> list[RevisionProposal]:
        ratio = ratio or RatioCalculation(document_id="unknown", disclosed_ratio=None, recalculated_ratio=None, eligible=False, reason="not provided")
        impact_by_claim = {impact.claim_id: impact for impact in impacts}
        change_by_id = {change.change_id: change for change in changes}
        claim_by_id = {claim.claim_id: claim for claim in claims.claims}
        sentence_by_id = {sentence.sentence_id: sentence for sentence in claims.sentences}
        groups: dict[str, list[tuple[Claim, Impact, FieldChange, str]]] = defaultdict(list)
        for impact in impacts:
            if not impact.revision_allowed or impact.classification not in {ImpactClass.DIRECT_FACT_CHANGE, ImpactClass.DERIVED_VALUE_CHANGE}:
                continue
            claim = claim_by_id[impact.claim_id]
            if not claim.value_span or not impact.change_ids:
                continue
            change = change_by_id.get(impact.change_ids[0])
            replacement = _replacement(claim, change, ratio) if change else None
            if change and replacement is not None:
                groups[claim.sentence_id].append((claim, impact, change, replacement))
        proposals = []
        for sentence_id, items in groups.items():
            sentence = sentence_by_id[sentence_id]
            items.sort(key=lambda item: item[0].value_span.start)
            if any(left[0].value_span.end > right[0].value_span.start for left, right in zip(items, items[1:])):
                continue
            proposed = sentence.span.text
            edits = []
            for claim, impact, change, replacement in reversed(items):
                span = claim.value_span
                local_start, local_end = span.start - sentence.span.start, span.end - sentence.span.start
                if memo[span.start:span.end] != span.text:
                    continue
                proposed = proposed[:local_start] + replacement + proposed[local_end:]
                edits.append(RevisionEdit(
                    start=span.start, end=span.end, original_text=span.text, replacement_text=replacement,
                    source_field=change.field_name, source_change_id=change.change_id,
                    evidence_ids=impact.evidence.evidence_ids,
                ))
            if not edits:
                continue
            edits.reverse()
            evidence_ids = list(dict.fromkeys(item for edit in edits for item in edit.evidence_ids))
            digest = hashlib.sha256(f"{sentence_id}|{proposed}|{'|'.join(evidence_ids)}".encode()).hexdigest()[:16]
            proposals.append(RevisionProposal(
                proposal_id=f"prop-{digest}", sentence_id=sentence_id,
                original_sentence=sentence.span.text, proposed_sentence=proposed,
                claim_ids=[claim.claim_id for claim, *_ in items], edits=edits,
                evidence=EvidenceAssessment(
                    existence_verified=all(item in evidence for item in evidence_ids),
                    semantic_support_verified=all(impact.evidence.semantic_support_verified for _, impact, _, _ in items),
                    evidence_ids=evidence_ids, note="proposal values originate from verified fields or server calculation",
                ),
            ))
        return proposals
