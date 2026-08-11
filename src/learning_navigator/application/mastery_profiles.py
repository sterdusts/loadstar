"""Application use case for evidence-backed multi-dimensional mastery profiles."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from learning_navigator.application.dto.mastery_dimensions import (
    NodeMasteryStateDTO,
    RouteGateResultDTO,
)
from learning_navigator.domain.services.mastery_dimensions import (
    DimensionRequirement,
    EvidenceMeasurement,
    MasteryDimension,
    MasteryDimensionsService,
    MasteryEvidence,
    MasteryEvidenceKind,
    NodeMasteryState,
    VerificationStatus,
)
from learning_navigator.infrastructure.database.models import LearningEvidenceModel
from learning_navigator.infrastructure.repositories.sqlalchemy import (
    SqlAlchemyKnowledgeRepository,
)

PROFILE_METADATA_KEY = "mastery_dimensions_v1"

EVIDENCE_TYPE_BY_KIND = {
    MasteryEvidenceKind.SELF_REPORT: "SELF_REPORT",
    MasteryEvidenceKind.EXERCISE: "EXERCISE_RESULT",
    MasteryEvidenceKind.PROJECT: "PROJECT_ARTIFACT",
    MasteryEvidenceKind.RECALL: "ASSESSMENT_RESULT",
}

DEFAULT_REQUIREMENTS = (
    DimensionRequirement(
        MasteryDimension.CONCEPT_UNDERSTANDING,
        minimum_score=60,
        minimum_confidence=0.30,
    ),
    DimensionRequirement(
        MasteryDimension.PROCEDURAL_SKILL,
        minimum_score=60,
        minimum_confidence=0.30,
    ),
    DimensionRequirement(
        MasteryDimension.APPLICATION_SKILL,
        minimum_score=60,
        minimum_confidence=0.30,
    ),
    DimensionRequirement(
        MasteryDimension.MEMORY_STRENGTH,
        minimum_score=50,
        minimum_confidence=0.30,
    ),
)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MasteryProfileApplicationService:
    """Append evidence, replay the profile, and maintain the legacy route projection."""

    def __init__(
        self,
        repository: SqlAlchemyKnowledgeRepository,
        *,
        algorithm_version: str = "mastery-dimensions-v1",
    ) -> None:
        self.repository = repository
        self.rules = MasteryDimensionsService(algorithm_version=algorithm_version)

    def get_profile(self, *, user_id: str, node_id: str) -> dict[str, Any]:
        self.repository.get_node_for_user(user_id, node_id)
        now = datetime.now(UTC)
        state, events = self._project(user_id=user_id, node_id=node_id, as_of=now)
        gate = self.rules.evaluate_route_gate(state, DEFAULT_REQUIREMENTS, as_of=now)
        states = {item.dimension.value: item for item in state.dimensions}
        last_times = [
            item.last_learning_time for item in state.dimensions if item.last_learning_time
        ]
        return {
            "node_id": node_id,
            "status": {
                key: {
                    "score": value.score,
                    "confidence": value.confidence,
                    "verification_status": value.verification_status.value,
                    "evidence_count": value.evidence_count,
                    "last_learning_time": value.last_learning_time.isoformat()
                    if value.last_learning_time
                    else None,
                    "next_review_at": value.next_review_at.isoformat()
                    if value.next_review_at
                    else None,
                }
                for key, value in states.items()
            },
            "dimensions": NodeMasteryStateDTO.from_domain(state).model_dump(mode="json")[
                "dimensions"
            ],
            "readiness": RouteGateResultDTO.from_domain(gate).model_dump(mode="json"),
            "review_needed": any(
                item.verification_status is VerificationStatus.STALE for item in state.dimensions
            ),
            "last_learning_time": max(last_times).isoformat() if last_times else None,
            "evidence_event_count": len(events),
            "algorithm_version": state.algorithm_version,
        }

    def record_evidence(
        self,
        *,
        user_id: str,
        node_id: str,
        kind: MasteryEvidenceKind,
        measurements: list[dict[str, Any]],
        evidence_confidence: float,
        note: str | None,
    ) -> dict[str, Any]:
        self.repository.get_node_for_user(user_id, node_id)
        prepared_measurements: list[dict[str, float | str]] = [
            {
                "dimension": MasteryDimension(item["dimension"]).value,
                "score": float(item["score"]),
            }
            for item in measurements
        ]
        payload: dict[str, Any] = {
            "schema_version": "mastery-dimensions-evidence-v1",
            "kind": kind.value,
            "measurements": prepared_measurements,
            "evidence_confidence": evidence_confidence,
            "source_algorithm_version": "evidence-schema-v1",
        }
        average_score = sum(float(item["score"]) for item in prepared_measurements) / len(
            prepared_measurements
        )
        evidence = self.repository.create_evidence(
            user_id=user_id,
            node_id=node_id,
            evidence_type=EVIDENCE_TYPE_BY_KIND[kind],
            title=f"多维掌握度 · {kind.value}",
            content=note,
            score=(average_score / 100 if kind is not MasteryEvidenceKind.SELF_REPORT else None),
            metadata_json={PROFILE_METADATA_KEY: payload},
            reviewed_by=user_id if kind is not MasteryEvidenceKind.SELF_REPORT else None,
            reviewed_at=datetime.now(UTC) if kind is not MasteryEvidenceKind.SELF_REPORT else None,
        )
        profile = self.get_profile(user_id=user_id, node_id=node_id)
        self._sync_legacy_projection(
            user_id=user_id,
            node_id=node_id,
            kind=kind,
            profile=profile,
        )
        self.repository.audit(
            user_id,
            "RECORD_DIMENSIONAL_MASTERY_EVIDENCE",
            "LearningEvidence",
            evidence.id,
            after={
                "node_id": node_id,
                "kind": kind.value,
                "dimensions": [item["dimension"] for item in prepared_measurements],
                "readiness_score": profile["readiness"]["readiness_score"],
            },
            details={"algorithm_version": profile["algorithm_version"]},
        )
        return {"evidence_id": evidence.id, "profile": profile}

    def _project(
        self,
        *,
        user_id: str,
        node_id: str,
        as_of: datetime,
    ) -> tuple[NodeMasteryState, list[MasteryEvidence]]:
        rows = list(
            self.repository.session.scalars(
                select(LearningEvidenceModel)
                .where(
                    LearningEvidenceModel.user_id == user_id,
                    LearningEvidenceModel.node_id == node_id,
                )
                .order_by(LearningEvidenceModel.created_at, LearningEvidenceModel.id)
            )
        )
        events: list[MasteryEvidence] = []
        for row in rows:
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            raw = metadata.get(PROFILE_METADATA_KEY)
            if not isinstance(raw, dict):
                continue
            try:
                measurements = tuple(
                    EvidenceMeasurement(
                        dimension=MasteryDimension(item["dimension"]),
                        score=float(item["score"]),
                    )
                    for item in raw["measurements"]
                    if isinstance(item, dict)
                )
                events.append(
                    MasteryEvidence(
                        evidence_id=row.id,
                        node_id=node_id,
                        kind=MasteryEvidenceKind(raw["kind"]),
                        observed_at=_aware(row.created_at),
                        measurements=measurements,
                        evidence_confidence=float(raw.get("evidence_confidence", 1.0)),
                        source_algorithm_version=str(
                            raw.get("source_algorithm_version", "evidence-schema-v1")
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError):
                # Malformed legacy metadata is not allowed to influence the projection.
                continue
        return self.rules.replay(node_id, events, as_of=as_of), events

    def _sync_legacy_projection(
        self,
        *,
        user_id: str,
        node_id: str,
        kind: MasteryEvidenceKind,
        profile: dict[str, Any],
    ) -> None:
        dimensions = list(profile["status"].values())
        verified = all(
            item["verification_status"] == VerificationStatus.VERIFIED.value for item in dimensions
        )
        weakest_score = min(float(item["score"]) for item in dimensions)
        confidence = min(float(item["confidence"]) for item in dimensions)
        current = self.repository.get_state(user_id, node_id)
        current_level = current.mastery_level if current else 0
        derived_level = 0
        if verified and bool(profile["readiness"]["allowed"]):
            derived_level = 5 if weakest_score >= 95 else 4 if weakest_score >= 80 else 3
        mastery_level = max(current_level, derived_level)
        next_reviews = [
            datetime.fromisoformat(item["next_review_at"])
            for item in dimensions
            if item["next_review_at"]
        ]
        last_times = [
            datetime.fromisoformat(item["last_learning_time"])
            for item in dimensions
            if item["last_learning_time"]
        ]
        before = (
            {
                "mastery_level": current.mastery_level,
                "mastery_score": current.mastery_score,
                "confidence": current.confidence,
            }
            if current
            else None
        )
        row = self.repository.save_state(
            user_id,
            node_id,
            {
                "mastery_level": mastery_level,
                "mastery_score": weakest_score / 100,
                "confidence": confidence,
                "numeric_evidence_count": int(profile["evidence_event_count"]),
                "last_studied_at": max(last_times) if last_times else None,
                "next_review_at": min(next_reviews) if next_reviews else None,
                "state_source": "SELF_REPORT"
                if kind is MasteryEvidenceKind.SELF_REPORT
                else "ASSESSMENT",
                "manually_overridden": current.manually_overridden if current else False,
                "algorithm_version": str(profile["algorithm_version"]),
            },
        )
        self.repository.audit(
            user_id,
            "PROJECT_DIMENSIONAL_MASTERY",
            "LearnerNodeState",
            row.id,
            before=before,
            after={
                "mastery_level": row.mastery_level,
                "mastery_score": row.mastery_score,
                "confidence": row.confidence,
            },
            details={
                "rule": "verified weakest-dimension route gate",
                "algorithm_version": profile["algorithm_version"],
            },
        )
