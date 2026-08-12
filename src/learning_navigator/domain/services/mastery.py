"""Transparent and versioned first-generation mastery update rules."""

from datetime import UTC, datetime, timedelta
from typing import ClassVar

from learning_navigator.domain.entities import LearnerSnapshot, MasteryUpdate
from learning_navigator.domain.enums import MasterySource


class MasteryService:
    """Update separate level, score and confidence dimensions with auditable rules."""

    REVIEW_INTERVALS: ClassVar[dict[int, int | None]] = {
        0: None,
        1: 7,
        2: 14,
        3: 30,
        4: 60,
        5: 120,
    }

    def __init__(
        self,
        *,
        review_after_days: int = 30,
        algorithm_version: str = "mastery-rule-v1",
        self_report_weight: float = 0.20,
        exercise_weight: float = 0.25,
    ) -> None:
        # Retain the central setting as the level-3 interval while keeping all intervals explicit.
        self.review_intervals = {**self.REVIEW_INTERVALS, 3: review_after_days}
        self.algorithm_version = algorithm_version
        self.self_report_weight = self_report_weight
        self.exercise_weight = exercise_weight

    def apply_self_report(self, current: LearnerSnapshot, confidence: float) -> MasteryUpdate:
        bounded = min(1.0, max(0.0, confidence))
        has_prior_evidence = any(
            (
                current.mastery_level > 0,
                current.mastery_score > 0,
                current.confidence > 0,
                current.last_studied_at is not None,
            )
        )
        updated_confidence = (
            current.confidence + self.self_report_weight * (bounded - current.confidence)
            if has_prior_evidence
            else bounded
        )
        return MasteryUpdate(
            mastery_level=current.mastery_level,
            mastery_score=current.mastery_score,
            confidence=round(updated_confidence, 6),
            source=MasterySource.SELF_REPORT.value,
            manually_overridden=False,
            algorithm_version=self.algorithm_version,
            next_review_at=current.next_review_at,
            audit_details={
                "rule": "self-report changes confidence only",
                "weight": self.self_report_weight,
                "reported_confidence": bounded,
            },
        )

    def apply_exercise_result(
        self,
        current: LearnerSnapshot,
        score: float,
        *,
        evidence_confidence: float = 1.0,
        now: datetime | None = None,
    ) -> MasteryUpdate:
        bounded_score = min(1.0, max(0.0, score))
        bounded_evidence_confidence = min(1.0, max(0.0, evidence_confidence))
        alpha = self.exercise_weight * bounded_evidence_confidence
        has_numeric_evidence = current.numeric_evidence_count > 0 or current.mastery_score > 0
        updated_score = (
            current.mastery_score + alpha * (bounded_score - current.mastery_score)
            if has_numeric_evidence
            else bounded_score
        )
        updated_confidence = 1 - (1 - current.confidence) * (1 - alpha)
        evidence_time = now or datetime.now(UTC)
        return MasteryUpdate(
            mastery_level=current.mastery_level,
            mastery_score=round(updated_score, 6),
            confidence=round(updated_confidence, 6),
            source=MasterySource.EXERCISE.value,
            manually_overridden=False,
            algorithm_version=self.algorithm_version,
            next_review_at=self._next_review(current.mastery_level, evidence_time),
            audit_details={
                "rule": "exercise updates continuous score and confidence only",
                "weight": self.exercise_weight,
                "evidence_confidence": bounded_evidence_confidence,
                "alpha": alpha,
                "first_numeric_evidence": not has_numeric_evidence,
            },
        )

    def apply_manual_review(
        self,
        current: LearnerSnapshot,
        mastery_level: int,
        *,
        confidence: float | None = None,
        verified_score: float | None = None,
        now: datetime | None = None,
        override: bool = False,
    ) -> MasteryUpdate:
        if not 0 <= mastery_level <= 5:
            raise ValueError("mastery_level must be between 0 and 5")
        reviewed_at = now or datetime.now(UTC)
        supplied_confidence = (
            current.confidence if confidence is None else min(1.0, max(0.0, confidence))
        )
        updated_score = current.mastery_score
        if verified_score is not None:
            updated_score = min(1.0, max(0.0, verified_score))
        source = MasterySource.MANUAL_OVERRIDE if override else MasterySource.MANUAL_REVIEW
        return MasteryUpdate(
            mastery_level=mastery_level,
            mastery_score=updated_score,
            confidence=max(supplied_confidence, 0.90),
            source=source.value,
            manually_overridden=override,
            algorithm_version=self.algorithm_version,
            next_review_at=self._next_review(mastery_level, reviewed_at),
            audit_details={
                "rule": "discrete mastery changed by explicit human action",
                "verified_score": verified_score,
                "review_interval_days": self.review_intervals[mastery_level],
            },
        )

    def _next_review(self, mastery_level: int, reviewed_at: datetime) -> datetime | None:
        interval = self.review_intervals[mastery_level]
        return reviewed_at + timedelta(days=interval) if interval is not None else None
