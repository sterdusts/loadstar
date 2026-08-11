"""Persistence-safe DTOs for multi-dimensional mastery and route gating."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from learning_navigator.domain.services.mastery_dimensions import (
    DimensionGateGap,
    DimensionMasteryState,
    DimensionRequirement,
    EvidenceMeasurement,
    MasteryDimension,
    MasteryEvidence,
    MasteryEvidenceKind,
    NodeMasteryState,
    RouteGateResult,
    VerificationStatus,
)

Score = Annotated[float, Field(ge=0.0, le=100.0)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class MasteryDTO(BaseModel):
    """Strict base model whose JSON output can be stored without lossy coercion."""

    model_config = ConfigDict(extra="forbid")


class DimensionMasteryStateDTO(MasteryDTO):
    dimension: MasteryDimension
    score: Score = 0.0
    confidence: Confidence = 0.0
    evidence_count: int = Field(default=0, ge=0)
    verified_evidence_count: int = Field(default=0, ge=0)
    last_learning_time: datetime | None = None
    next_review_at: datetime | None = None
    verification_status: VerificationStatus = VerificationStatus.UNASSESSED
    algorithm_version: str = Field(default="mastery-dimensions-v1", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_domain_invariants(self) -> DimensionMasteryStateDTO:
        self.to_domain()
        return self

    @classmethod
    def from_domain(cls, state: DimensionMasteryState) -> DimensionMasteryStateDTO:
        return cls(
            dimension=state.dimension,
            score=state.score,
            confidence=state.confidence,
            evidence_count=state.evidence_count,
            verified_evidence_count=state.verified_evidence_count,
            last_learning_time=state.last_learning_time,
            next_review_at=state.next_review_at,
            verification_status=state.verification_status,
            algorithm_version=state.algorithm_version,
        )

    def to_domain(self) -> DimensionMasteryState:
        return DimensionMasteryState(
            dimension=self.dimension,
            score=self.score,
            confidence=self.confidence,
            evidence_count=self.evidence_count,
            verified_evidence_count=self.verified_evidence_count,
            last_learning_time=self.last_learning_time,
            next_review_at=self.next_review_at,
            verification_status=self.verification_status,
            algorithm_version=self.algorithm_version,
        )


class NodeMasteryStateDTO(MasteryDTO):
    node_id: str = Field(min_length=1, max_length=100)
    dimensions: list[DimensionMasteryStateDTO]
    algorithm_version: str = Field(default="mastery-dimensions-v1", min_length=1, max_length=100)
    applied_evidence_ids: list[str] = Field(default_factory=list)
    projected_at: datetime | None = None

    @model_validator(mode="after")
    def validate_domain_invariants(self) -> NodeMasteryStateDTO:
        self.to_domain()
        return self

    @classmethod
    def from_domain(cls, state: NodeMasteryState) -> NodeMasteryStateDTO:
        return cls(
            node_id=state.node_id,
            dimensions=[DimensionMasteryStateDTO.from_domain(item) for item in state.dimensions],
            algorithm_version=state.algorithm_version,
            applied_evidence_ids=list(state.applied_evidence_ids),
            projected_at=state.projected_at,
        )

    def to_domain(self) -> NodeMasteryState:
        return NodeMasteryState(
            node_id=self.node_id,
            dimensions=tuple(item.to_domain() for item in self.dimensions),
            algorithm_version=self.algorithm_version,
            applied_evidence_ids=tuple(self.applied_evidence_ids),
            projected_at=self.projected_at,
        )


class EvidenceMeasurementDTO(MasteryDTO):
    dimension: MasteryDimension
    score: Score

    @classmethod
    def from_domain(cls, measurement: EvidenceMeasurement) -> EvidenceMeasurementDTO:
        return cls(dimension=measurement.dimension, score=measurement.score)

    def to_domain(self) -> EvidenceMeasurement:
        return EvidenceMeasurement(dimension=self.dimension, score=self.score)


class MasteryEvidenceDTO(MasteryDTO):
    evidence_id: str = Field(min_length=1, max_length=100)
    node_id: str = Field(min_length=1, max_length=100)
    kind: MasteryEvidenceKind
    observed_at: datetime
    measurements: list[EvidenceMeasurementDTO] = Field(min_length=1, max_length=4)
    evidence_confidence: Confidence = 1.0
    source_algorithm_version: str = Field(
        default="evidence-schema-v1", min_length=1, max_length=100
    )
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_domain_invariants(self) -> MasteryEvidenceDTO:
        self.to_domain()
        return self

    @classmethod
    def from_domain(cls, evidence: MasteryEvidence) -> MasteryEvidenceDTO:
        return cls(
            evidence_id=evidence.evidence_id,
            node_id=evidence.node_id,
            kind=evidence.kind,
            observed_at=evidence.observed_at,
            measurements=[
                EvidenceMeasurementDTO.from_domain(item) for item in evidence.measurements
            ],
            evidence_confidence=evidence.evidence_confidence,
            source_algorithm_version=evidence.source_algorithm_version,
            metadata=dict(evidence.metadata),
        )

    def to_domain(self) -> MasteryEvidence:
        return MasteryEvidence(
            evidence_id=self.evidence_id,
            node_id=self.node_id,
            kind=self.kind,
            observed_at=self.observed_at,
            measurements=tuple(item.to_domain() for item in self.measurements),
            evidence_confidence=self.evidence_confidence,
            source_algorithm_version=self.source_algorithm_version,
            metadata=self.metadata,
        )


class DimensionRequirementDTO(MasteryDTO):
    dimension: MasteryDimension
    minimum_score: Annotated[float, Field(gt=0.0, le=100.0)]
    minimum_confidence: Confidence = 0.0
    require_verified: bool = True

    @classmethod
    def from_domain(cls, requirement: DimensionRequirement) -> DimensionRequirementDTO:
        return cls(
            dimension=requirement.dimension,
            minimum_score=requirement.minimum_score,
            minimum_confidence=requirement.minimum_confidence,
            require_verified=requirement.require_verified,
        )

    def to_domain(self) -> DimensionRequirement:
        return DimensionRequirement(
            dimension=self.dimension,
            minimum_score=self.minimum_score,
            minimum_confidence=self.minimum_confidence,
            require_verified=self.require_verified,
        )


class DimensionGateGapDTO(MasteryDTO):
    dimension: MasteryDimension
    current_score: Score
    required_score: Score
    current_confidence: Confidence
    required_confidence: Confidence
    verification_status: VerificationStatus
    reasons: list[str]

    @classmethod
    def from_domain(cls, gap: DimensionGateGap) -> DimensionGateGapDTO:
        return cls(
            dimension=gap.dimension,
            current_score=gap.current_score,
            required_score=gap.required_score,
            current_confidence=gap.current_confidence,
            required_confidence=gap.required_confidence,
            verification_status=gap.verification_status,
            reasons=[reason.value for reason in gap.reasons],
        )


class RouteGateResultDTO(MasteryDTO):
    allowed: bool
    readiness_score: Score
    blocking_dimensions: list[MasteryDimension]
    gaps: list[DimensionGateGapDTO]
    algorithm_version: str

    @classmethod
    def from_domain(cls, result: RouteGateResult) -> RouteGateResultDTO:
        return cls(
            allowed=result.allowed,
            readiness_score=result.readiness_score,
            blocking_dimensions=list(result.blocking_dimensions),
            gaps=[DimensionGateGapDTO.from_domain(gap) for gap in result.gaps],
            algorithm_version=result.algorithm_version,
        )
