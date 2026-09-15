from __future__ import annotations

from abc import ABC, abstractmethod

from disclosure_impact_agent.memo_models import ClaimBatch, Impact, RevisionProposal
from disclosure_impact_agent.models import EvidenceBlock, FieldChange, RatioCalculation


class ClaimExtractor(ABC):
    @abstractmethod
    def extract(self, memo: str, *, scenario_id: str | None = None) -> ClaimBatch: ...


class ImpactAnalyzer(ABC):
    @abstractmethod
    def analyze(
        self, claims: ClaimBatch, changes: list[FieldChange], ratio: RatioCalculation,
        evidence: dict[str, EvidenceBlock],
    ) -> list[Impact]: ...


class RevisionProposer(ABC):
    @abstractmethod
    def propose(
        self, memo: str, claims: ClaimBatch, impacts: list[Impact], changes: list[FieldChange],
        evidence: dict[str, EvidenceBlock], ratio: RatioCalculation | None = None,
    ) -> list[RevisionProposal]: ...
