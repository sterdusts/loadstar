"""Evidence-driven, replayable multi-dimensional mastery rules.

The original mastery model exposes one aggregate score.  This module deliberately
does not replace it yet: it provides a persistence-independent v2 projection that
can be introduced behind the existing application service without making route
decisions from an arithmetic average.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import ClassVar


class MasteryDimension(StrEnum):
    """Stable persistence keys for the four first-generation mastery dimensions."""

    CONCEPT_UNDERSTANDING = "concept_understanding"
    PROCEDURAL_SKILL = "procedural_skill"
    APPLICATION_SKILL = "application_skill"
    MEMORY_STRENGTH = "memory_strength"


class VerificationStatus(StrEnum):
    """How strongly the current projection is supported."""

    UNASSESSED = "UNASSESSED"
    SELF_REPORTED = "SELF_REPORTED"
    VERIFIED = "VERIFIED"
    STALE = "STALE"


class MasteryEvidenceKind(StrEnum):
    """Evidence kinds accepted by the v2 mastery projection."""

    SELF_REPORT = "SELF_REPORT"
    EXERCISE = "EXERCISE"
    PROJECT = "PROJECT"
    RECALL = "RECALL"


class RouteGateBlockReason(StrEnum):
    """Machine-readable reasons why a required dimension did not pass."""

    UNASSESSED = "UNASSESSED"
    STALE = "STALE"
    VERIFICATION_INSUFFICIENT = "VERIFICATION_INSUFFICIENT"
    SCORE_BELOW_THRESHOLD = "SCORE_BELOW_THRESHOLD"
    CONFIDENCE_BELOW_THRESHOLD = "CONFIDENCE_BELOW_THRESHOLD"


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DimensionMasteryState:
    """Persistable projection for one learner, node and mastery dimension."""

    dimension: MasteryDimension
    score: float = 0.0
    confidence: float = 0.0
    evidence_count: int = 0
    verified_evidence_count: int = 0
    last_learning_time: datetime | None = None
    next_review_at: datetime | None = None
    verification_status: VerificationStatus = VerificationStatus.UNASSESSED
    algorithm_version: str = "mastery-dimensions-v1"

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 100.0:
            raise ValueError("score must be between 0 and 100")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.evidence_count < 0:
            raise ValueError("evidence_count cannot be negative")
        if not 0 <= self.verified_evidence_count <= self.evidence_count:
            raise ValueError("verified_evidence_count must be between 0 and evidence_count")
        if not self.algorithm_version.strip():
            raise ValueError("algorithm_version cannot be blank")
        if self.last_learning_time is not None:
            _require_aware(self.last_learning_time, "last_learning_time")
        if self.next_review_at is not None:
            _require_aware(self.next_review_at, "next_review_at")

        if self.verification_status is VerificationStatus.UNASSESSED:
            if any(
                (
                    self.score != 0.0,
                    self.confidence != 0.0,
                    self.evidence_count != 0,
                    self.verified_evidence_count != 0,
                    self.last_learning_time is not None,
                    self.next_review_at is not None,
                )
            ):
                raise ValueError("UNASSESSED state cannot contain inferred mastery data")
        elif self.evidence_count == 0 or self.last_learning_time is None:
            raise ValueError("assessed state requires evidence and last_learning_time")

        if (
            self.verification_status is VerificationStatus.SELF_REPORTED
            and self.verified_evidence_count != 0
        ):
            raise ValueError("SELF_REPORTED state cannot contain verified evidence")
        if (
            self.verification_status is VerificationStatus.VERIFIED
            and self.verified_evidence_count == 0
        ):
            raise ValueError("VERIFIED state requires verified evidence")


@dataclass(frozen=True, slots=True)
class NodeMasteryState:
    """A complete four-dimensional projection for one knowledge node."""

    node_id: str
    dimensions: tuple[DimensionMasteryState, ...]
    algorithm_version: str = "mastery-dimensions-v1"
    applied_evidence_ids: tuple[str, ...] = ()
    projected_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ValueError("node_id cannot be blank")
        if not self.algorithm_version.strip():
            raise ValueError("algorithm_version cannot be blank")
        if self.projected_at is not None:
            _require_aware(self.projected_at, "projected_at")
        if len(self.applied_evidence_ids) != len(set(self.applied_evidence_ids)):
            raise ValueError("applied_evidence_ids must be unique")

        dimension_keys = [state.dimension for state in self.dimensions]
        if len(dimension_keys) != len(set(dimension_keys)):
            raise ValueError("node mastery dimensions must be unique")
        if set(dimension_keys) != set(MasteryDimension):
            raise ValueError("node mastery state must contain all four mastery dimensions")
        if any(state.algorithm_version != self.algorithm_version for state in self.dimensions):
            raise ValueError("dimension state algorithm versions must match the node projection")

    def state_for(self, dimension: MasteryDimension) -> DimensionMasteryState:
        return next(state for state in self.dimensions if state.dimension is dimension)


@dataclass(frozen=True, slots=True)
class EvidenceMeasurement:
    """A 0-100 observation for one mastery dimension."""

    dimension: MasteryDimension
    score: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 100.0:
            raise ValueError("measurement score must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class MasteryEvidence:
    """An immutable event used to rebuild a node mastery projection."""

    evidence_id: str
    node_id: str
    kind: MasteryEvidenceKind
    observed_at: datetime
    measurements: tuple[EvidenceMeasurement, ...]
    evidence_confidence: float = 1.0
    source_algorithm_version: str = "evidence-schema-v1"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id cannot be blank")
        if not self.node_id.strip():
            raise ValueError("node_id cannot be blank")
        if not self.source_algorithm_version.strip():
            raise ValueError("source_algorithm_version cannot be blank")
        _require_aware(self.observed_at, "observed_at")
        if not 0.0 < self.evidence_confidence <= 1.0:
            raise ValueError("evidence_confidence must be greater than 0 and at most 1")
        if not self.measurements:
            raise ValueError("evidence must contain at least one dimension measurement")
        dimensions = [measurement.dimension for measurement in self.measurements]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("evidence measurements must use unique dimensions")


@dataclass(frozen=True, slots=True)
class DimensionRequirement:
    """A route prerequisite for a single dimension."""

    dimension: MasteryDimension
    minimum_score: float
    minimum_confidence: float = 0.0
    require_verified: bool = True

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_score <= 100.0:
            raise ValueError("minimum_score must be greater than 0 and at most 100")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class DimensionGateGap:
    """One dimension's current values and all failed route conditions."""

    dimension: MasteryDimension
    current_score: float
    required_score: float
    current_confidence: float
    required_confidence: float
    verification_status: VerificationStatus
    reasons: tuple[RouteGateBlockReason, ...]


@dataclass(frozen=True, slots=True)
class RouteGateResult:
    """Deterministic prerequisite result for a route planner."""

    allowed: bool
    readiness_score: float
    gaps: tuple[DimensionGateGap, ...]
    algorithm_version: str

    @property
    def blocking_dimensions(self) -> tuple[MasteryDimension, ...]:
        return tuple(gap.dimension for gap in self.gaps)


class MasteryDimensionsService:
    """Build v2 mastery projections exclusively from immutable evidence events."""

    EVIDENCE_WEIGHTS: ClassVar[dict[MasteryEvidenceKind, float]] = {
        MasteryEvidenceKind.SELF_REPORT: 0.15,
        MasteryEvidenceKind.EXERCISE: 0.35,
        MasteryEvidenceKind.PROJECT: 0.50,
        MasteryEvidenceKind.RECALL: 0.40,
    }
    REVIEW_INTERVAL_DAYS: ClassVar[dict[MasteryEvidenceKind, int]] = {
        MasteryEvidenceKind.SELF_REPORT: 3,
        MasteryEvidenceKind.EXERCISE: 14,
        MasteryEvidenceKind.PROJECT: 30,
        MasteryEvidenceKind.RECALL: 7,
    }

    def __init__(
        self,
        *,
        algorithm_version: str = "mastery-dimensions-v1",
        evidence_weights: Mapping[MasteryEvidenceKind, float] | None = None,
        review_interval_days: Mapping[MasteryEvidenceKind, int] | None = None,
    ) -> None:
        if not algorithm_version.strip():
            raise ValueError("algorithm_version cannot be blank")
        self.algorithm_version = algorithm_version
        self.evidence_weights = {**self.EVIDENCE_WEIGHTS, **(evidence_weights or {})}
        self.review_interval_days = {
            **self.REVIEW_INTERVAL_DAYS,
            **(review_interval_days or {}),
        }
        if set(self.evidence_weights) != set(MasteryEvidenceKind):
            raise ValueError("an evidence weight is required for every evidence kind")
        if any(not 0.0 < weight <= 1.0 for weight in self.evidence_weights.values()):
            raise ValueError("evidence weights must be greater than 0 and at most 1")
        if set(self.review_interval_days) != set(MasteryEvidenceKind):
            raise ValueError("a review interval is required for every evidence kind")
        if any(days <= 0 for days in self.review_interval_days.values()):
            raise ValueError("review intervals must be positive")

    def empty_state(
        self, node_id: str, *, projected_at: datetime | None = None
    ) -> NodeMasteryState:
        """Return an explicit UNASSESSED state; absence never implies mastery."""

        return NodeMasteryState(
            node_id=node_id,
            dimensions=tuple(
                DimensionMasteryState(
                    dimension=dimension,
                    algorithm_version=self.algorithm_version,
                )
                for dimension in MasteryDimension
            ),
            algorithm_version=self.algorithm_version,
            projected_at=projected_at,
        )

    def replay(
        self,
        node_id: str,
        evidence_events: Iterable[MasteryEvidence],
        *,
        as_of: datetime,
    ) -> NodeMasteryState:
        """Rebuild a deterministic point-in-time projection from the evidence journal."""

        _require_aware(as_of, "as_of")
        events = sorted(evidence_events, key=lambda item: (item.observed_at, item.evidence_id))
        ids = [event.evidence_id for event in events]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique during replay")
        if any(event.node_id != node_id for event in events):
            raise ValueError("all evidence events must belong to the projected node")

        state = self.empty_state(node_id, projected_at=as_of)
        for event in events:
            if event.observed_at <= as_of:
                state = self.apply_evidence(state, event)
        return self.mark_stale(state, as_of=as_of)

    def apply_evidence(
        self,
        current: NodeMasteryState,
        evidence: MasteryEvidence,
    ) -> NodeMasteryState:
        """Apply one event; callers can persist both event and returned projection."""

        if current.node_id != evidence.node_id:
            raise ValueError("evidence node_id must match the mastery projection")
        if current.algorithm_version != self.algorithm_version:
            raise ValueError("replay is required before changing mastery algorithm versions")
        if evidence.evidence_id in current.applied_evidence_ids:
            return current

        current_at_event = self.mark_stale(current, as_of=evidence.observed_at)
        measured = {item.dimension: item.score for item in evidence.measurements}
        updated_dimensions = tuple(
            self._apply_measurement(state, evidence, measured[state.dimension])
            if state.dimension in measured
            else state
            for state in current_at_event.dimensions
        )
        return NodeMasteryState(
            node_id=current.node_id,
            dimensions=updated_dimensions,
            algorithm_version=self.algorithm_version,
            applied_evidence_ids=(*current.applied_evidence_ids, evidence.evidence_id),
            projected_at=evidence.observed_at,
        )

    def mark_stale(self, current: NodeMasteryState, *, as_of: datetime) -> NodeMasteryState:
        """Mark due dimensions stale without erasing their last measured score."""

        _require_aware(as_of, "as_of")
        dimensions = tuple(
            replace(state, verification_status=VerificationStatus.STALE)
            if (
                state.verification_status is not VerificationStatus.UNASSESSED
                and state.next_review_at is not None
                and as_of >= state.next_review_at
            )
            else state
            for state in current.dimensions
        )
        return replace(current, dimensions=dimensions, projected_at=as_of)

    def evaluate_route_gate(
        self,
        current: NodeMasteryState,
        requirements: Iterable[DimensionRequirement],
        *,
        as_of: datetime | None = None,
    ) -> RouteGateResult:
        """Evaluate every threshold; high dimensions cannot compensate for a weak one."""

        state = self.mark_stale(current, as_of=as_of) if as_of is not None else current
        required = tuple(requirements)
        keys = [item.dimension for item in required]
        if len(keys) != len(set(keys)):
            raise ValueError("route requirements must use unique dimensions")
        if not required:
            return RouteGateResult(
                allowed=True,
                readiness_score=100.0,
                gaps=(),
                algorithm_version=self.algorithm_version,
            )

        numeric_readiness: list[float] = []
        gaps: list[DimensionGateGap] = []
        for requirement in required:
            dimension_state = state.state_for(requirement.dimension)
            score_ratio = dimension_state.score / requirement.minimum_score
            confidence_ratio = (
                dimension_state.confidence / requirement.minimum_confidence
                if requirement.minimum_confidence > 0
                else 1.0
            )
            numeric_readiness.append(min(1.0, score_ratio, confidence_ratio))

            reasons: list[RouteGateBlockReason] = []
            if dimension_state.verification_status is VerificationStatus.UNASSESSED:
                reasons.append(RouteGateBlockReason.UNASSESSED)
            elif dimension_state.verification_status is VerificationStatus.STALE:
                reasons.append(RouteGateBlockReason.STALE)
            elif (
                requirement.require_verified
                and dimension_state.verification_status is not VerificationStatus.VERIFIED
            ):
                reasons.append(RouteGateBlockReason.VERIFICATION_INSUFFICIENT)
            if dimension_state.score < requirement.minimum_score:
                reasons.append(RouteGateBlockReason.SCORE_BELOW_THRESHOLD)
            if dimension_state.confidence < requirement.minimum_confidence:
                reasons.append(RouteGateBlockReason.CONFIDENCE_BELOW_THRESHOLD)
            if reasons:
                gaps.append(
                    DimensionGateGap(
                        dimension=requirement.dimension,
                        current_score=dimension_state.score,
                        required_score=requirement.minimum_score,
                        current_confidence=dimension_state.confidence,
                        required_confidence=requirement.minimum_confidence,
                        verification_status=dimension_state.verification_status,
                        reasons=tuple(reasons),
                    )
                )

        return RouteGateResult(
            allowed=not gaps,
            readiness_score=round(min(numeric_readiness) * 100.0, 6),
            gaps=tuple(gaps),
            algorithm_version=self.algorithm_version,
        )

    def _apply_measurement(
        self,
        current: DimensionMasteryState,
        evidence: MasteryEvidence,
        observed_score: float,
    ) -> DimensionMasteryState:
        is_self_report = evidence.kind is MasteryEvidenceKind.SELF_REPORT
        alpha = self.evidence_weights[evidence.kind] * evidence.evidence_confidence
        evidence_count = current.evidence_count + 1

        if is_self_report and current.verified_evidence_count > 0:
            # A subjective report remains in the journal but cannot overwrite or refresh an
            # objectively verified prerequisite.
            return replace(
                current,
                evidence_count=evidence_count,
                last_learning_time=evidence.observed_at,
            )

        if is_self_report:
            score = (
                observed_score
                if current.evidence_count == 0
                else current.score + alpha * (observed_score - current.score)
            )
            confidence = 1.0 - (1.0 - current.confidence) * (1.0 - alpha)
            status = VerificationStatus.SELF_REPORTED
            verified_evidence_count = current.verified_evidence_count
        else:
            # The first objective observation replaces any earlier self-estimate.  Later
            # objective evidence uses a bounded exponential update.
            score = (
                observed_score
                if current.verified_evidence_count == 0
                else current.score + alpha * (observed_score - current.score)
            )
            confidence = (
                alpha
                if current.verified_evidence_count == 0
                else 1.0 - (1.0 - current.confidence) * (1.0 - alpha)
            )
            status = VerificationStatus.VERIFIED
            verified_evidence_count = current.verified_evidence_count + 1

        return DimensionMasteryState(
            dimension=current.dimension,
            score=round(score, 6),
            confidence=round(confidence, 6),
            evidence_count=evidence_count,
            verified_evidence_count=verified_evidence_count,
            last_learning_time=evidence.observed_at,
            next_review_at=evidence.observed_at
            + timedelta(days=self.review_interval_days[evidence.kind]),
            verification_status=status,
            algorithm_version=self.algorithm_version,
        )
