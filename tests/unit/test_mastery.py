"""Unit tests for the documented ``mastery-rule-v1`` update rules."""

from datetime import UTC, datetime, timedelta

import pytest

from learning_navigator.domain.entities import LearnerSnapshot
from learning_navigator.domain.enums import MasterySource
from learning_navigator.domain.services.mastery import MasteryService


def test_learner_snapshot_has_an_unmastered_default_state() -> None:
    snapshot = LearnerSnapshot(node_id="python-loops")

    assert snapshot.node_id == "python-loops"
    assert snapshot.mastery_level == 0
    assert snapshot.mastery_score == 0.0
    assert snapshot.confidence == 0.0
    assert snapshot.last_studied_at is None
    assert snapshot.next_review_at is None


@pytest.mark.parametrize(
    ("reported_confidence", "expected_confidence"),
    [
        pytest.param(-0.25, 0.0, id="below-zero"),
        pytest.param(0.0, 0.0, id="lower-bound"),
        pytest.param(0.65, 0.65, id="inside-range"),
        pytest.param(1.0, 1.0, id="upper-bound"),
        pytest.param(1.25, 1.0, id="above-one"),
    ],
)
def test_first_self_report_uses_bounded_reported_confidence(
    reported_confidence: float,
    expected_confidence: float,
) -> None:
    update = MasteryService().apply_self_report(
        LearnerSnapshot(node_id="python-loops"),
        reported_confidence,
    )

    assert update.confidence == expected_confidence
    assert update.mastery_level == 0
    assert update.mastery_score == 0.0
    assert update.source == MasterySource.SELF_REPORT.value
    assert update.manually_overridden is False


@pytest.mark.parametrize(
    ("reported_confidence", "expected_confidence"),
    [
        pytest.param(-1.0, 0.32, id="bounded-low-report-can-reduce-confidence"),
        pytest.param(0.65, 0.45, id="smooth-toward-report"),
        pytest.param(2.0, 0.52, id="bounded-high-report"),
    ],
)
def test_later_self_report_smooths_confidence_by_twenty_percent_only(
    reported_confidence: float,
    expected_confidence: float,
) -> None:
    review_at = datetime(2026, 8, 20, 9, 30, tzinfo=UTC)
    current = LearnerSnapshot(
        node_id="python-loops",
        mastery_level=3,
        mastery_score=0.72,
        confidence=0.4,
        last_studied_at=datetime(2026, 7, 31, 9, 30, tzinfo=UTC),
        next_review_at=review_at,
    )

    update = MasteryService().apply_self_report(current, reported_confidence)

    assert update.mastery_level == current.mastery_level
    assert update.mastery_score == current.mastery_score
    assert update.confidence == pytest.approx(expected_confidence)
    assert update.next_review_at == review_at


@pytest.mark.parametrize(
    ("exercise_score", "expected_score"),
    [
        pytest.param(-0.5, 0.0, id="clamp-below-zero"),
        pytest.param(0.0, 0.0, id="lower-bound"),
        pytest.param(0.8, 0.8, id="first-result-is-not-diluted"),
        pytest.param(1.0, 1.0, id="upper-bound"),
        pytest.param(1.5, 1.0, id="clamp-above-one"),
    ],
)
def test_first_exercise_sets_normalized_score_and_accumulates_confidence(
    exercise_score: float,
    expected_score: float,
) -> None:
    current = LearnerSnapshot(node_id="python-loops")

    update = MasteryService().apply_exercise_result(current, exercise_score)

    assert update.mastery_score == expected_score
    assert update.confidence == pytest.approx(0.25)
    assert update.mastery_level == 0
    assert update.source == MasterySource.EXERCISE.value
    assert update.manually_overridden is False


def test_self_report_does_not_make_first_exercise_a_prior_numeric_result() -> None:
    current = LearnerSnapshot(
        node_id="python-loops",
        mastery_score=0.0,
        confidence=0.8,
    )

    update = MasteryService().apply_exercise_result(current, 1.0)

    assert update.mastery_score == 1.0
    assert update.confidence == pytest.approx(0.85)
    assert update.audit_details["first_numeric_evidence"] is True


def test_later_exercise_uses_weight_times_evidence_confidence() -> None:
    current = LearnerSnapshot(
        node_id="python-loops",
        mastery_level=2,
        mastery_score=0.8,
        confidence=0.25,
    )

    update = MasteryService().apply_exercise_result(
        current,
        0.2,
        evidence_confidence=0.5,
    )

    assert update.mastery_score == pytest.approx(0.725)
    assert update.confidence == pytest.approx(0.34375)
    assert update.mastery_level == current.mastery_level
    assert update.audit_details["weight"] == pytest.approx(0.25)
    assert update.audit_details["evidence_confidence"] == pytest.approx(0.5)
    assert update.audit_details["alpha"] == pytest.approx(0.125)


def test_perfect_exercise_does_not_automatically_promote_mastery_level() -> None:
    current = LearnerSnapshot(
        node_id="python-loops",
        mastery_level=0,
        mastery_score=0.99,
        confidence=0.8,
    )

    update = MasteryService().apply_exercise_result(current, 1.0)

    assert update.mastery_score > current.mastery_score
    assert update.mastery_level == 0


@pytest.mark.parametrize(
    ("mastery_level", "review_days"),
    [
        pytest.param(0, None, id="unmastered-has-no-review"),
        pytest.param(1, 7, id="level-one"),
        pytest.param(2, 14, id="level-two"),
        pytest.param(3, 30, id="level-three"),
        pytest.param(4, 60, id="level-four"),
        pytest.param(5, 120, id="level-five"),
    ],
)
def test_manual_review_uses_level_specific_review_interval(
    mastery_level: int,
    review_days: int | None,
) -> None:
    reviewed_at = datetime(2026, 7, 31, 15, 45, tzinfo=UTC)
    current = LearnerSnapshot(
        node_id="python-loops",
        mastery_level=1,
        mastery_score=0.58,
        confidence=0.35,
        next_review_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    update = MasteryService().apply_manual_review(
        current,
        mastery_level=mastery_level,
        now=reviewed_at,
    )

    expected_review_at = None if review_days is None else reviewed_at + timedelta(days=review_days)
    assert update.mastery_level == mastery_level
    assert update.mastery_score == current.mastery_score
    assert update.confidence == pytest.approx(0.9)
    assert update.source == MasterySource.MANUAL_REVIEW.value
    assert update.manually_overridden is False
    assert update.next_review_at == expected_review_at


@pytest.mark.parametrize(
    ("old_confidence", "review_confidence", "expected_confidence"),
    [
        pytest.param(0.2, None, 0.9, id="raise-default-to-minimum"),
        pytest.param(0.95, None, 0.95, id="preserve-higher-current-value"),
        pytest.param(0.2, 0.4, 0.9, id="explicit-value-cannot-lower-minimum"),
        pytest.param(0.2, 1.4, 1.0, id="explicit-value-is-bounded"),
    ],
)
def test_manual_review_confidence_is_at_least_ninety_percent(
    old_confidence: float,
    review_confidence: float | None,
    expected_confidence: float,
) -> None:
    current = LearnerSnapshot(node_id="python-loops", confidence=old_confidence)

    update = MasteryService().apply_manual_review(
        current,
        mastery_level=3,
        confidence=review_confidence,
        now=datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert update.confidence == pytest.approx(expected_confidence)


def test_manual_override_is_flagged_and_uses_override_source() -> None:
    reviewed_at = datetime(2026, 7, 31, 15, 45, tzinfo=UTC)
    current = LearnerSnapshot(
        node_id="python-loops",
        mastery_level=2,
        mastery_score=0.42,
        confidence=0.63,
    )

    update = MasteryService().apply_manual_review(
        current,
        mastery_level=5,
        now=reviewed_at,
        override=True,
    )

    assert update.mastery_level == 5
    assert update.mastery_score == current.mastery_score
    assert update.confidence == pytest.approx(0.9)
    assert update.source == MasterySource.MANUAL_OVERRIDE.value
    assert update.manually_overridden is True


@pytest.mark.parametrize("invalid_level", [-1, 6])
def test_manual_review_rejects_mastery_level_outside_supported_range(
    invalid_level: int,
) -> None:
    current = LearnerSnapshot(node_id="python-loops")

    with pytest.raises(ValueError, match="mastery_level must be between 0 and 5"):
        MasteryService().apply_manual_review(current, invalid_level)


def test_manual_review_uses_an_aware_utc_time_when_now_is_omitted() -> None:
    before = datetime.now(UTC) + timedelta(days=7)

    update = MasteryService().apply_manual_review(
        LearnerSnapshot(node_id="python-loops"),
        mastery_level=1,
    )

    after = datetime.now(UTC) + timedelta(days=7)
    assert update.next_review_at is not None
    assert update.next_review_at.tzinfo is UTC
    assert before <= update.next_review_at <= after


def test_every_update_reports_the_configured_algorithm_and_audit_rule() -> None:
    current = LearnerSnapshot(node_id="python-loops")
    service = MasteryService(algorithm_version="mastery-rule-test")

    updates = (
        service.apply_self_report(current, 0.6),
        service.apply_exercise_result(current, 0.8),
        service.apply_manual_review(
            current,
            mastery_level=2,
            now=datetime(2026, 7, 31, tzinfo=UTC),
        ),
    )

    assert all(update.algorithm_version == "mastery-rule-test" for update in updates)
    assert all(update.audit_details.get("rule") for update in updates)
