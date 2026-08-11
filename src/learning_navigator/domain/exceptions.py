"""Domain errors that can be mapped consistently at transport boundaries."""

from collections.abc import Sequence


class DomainError(Exception):
    """Base class for expected business-rule failures."""

    code = "domain_error"


class EntityNotFoundError(DomainError):
    code = "entity_not_found"

    def __init__(self, entity: str, entity_id: str) -> None:
        super().__init__(f"{entity} '{entity_id}' does not exist or is archived")
        self.entity = entity
        self.entity_id = entity_id


class DuplicateEdgeError(DomainError):
    code = "duplicate_edge"

    def __init__(self, source_id: str, target_id: str, relation_type: str) -> None:
        super().__init__(f"Active {relation_type} edge already exists: {source_id} -> {target_id}")


class InvalidEdgeError(DomainError):
    code = "invalid_edge"


class CircularPrerequisiteError(DomainError):
    code = "circular_prerequisite"

    def __init__(self, cycle_path: Sequence[str]) -> None:
        self.cycle_path = tuple(cycle_path)
        super().__init__("Prerequisite edge would create cycle: " + " -> ".join(cycle_path))


class InvalidStateTransitionError(DomainError):
    code = "invalid_state_transition"


class DuplicateProgressCheckInError(DomainError):
    code = "duplicate_progress_check_in"

    def __init__(self, *, check_in_date: str) -> None:
        self.check_in_date = check_in_date
        super().__init__(
            f"A progress check-in already exists for {check_in_date}; edit that record instead"
        )


class ProgressScoreRegressionError(DomainError):
    code = "progress_score_regression"

    def __init__(self, *, attempted_score: int, current_score: int) -> None:
        self.attempted_score = attempted_score
        self.current_score = current_score
        super().__init__(
            "A new progress check-in cannot reduce the score "
            f"(attempted {attempted_score}, current {current_score}); "
            "use the edit action to correct an existing record"
        )


class ProgressCheckInRevisionConflictError(DomainError):
    code = "progress_check_in_revision_conflict"

    def __init__(
        self,
        *,
        expected_revision: int | None,
        current_revision: int | None,
        expected_check_in_id: str | None = None,
        current_check_in_id: str | None = None,
    ) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        self.expected_check_in_id = expected_check_in_id
        self.current_check_in_id = current_check_in_id
        super().__init__(
            "Progress check-in changed while it was being edited "
            f"(expected {expected_check_in_id or '-'}@{expected_revision or '-'}, "
            f"current {current_check_in_id or '-'}@{current_revision or '-'})"
        )


class RevisionConflictError(DomainError):
    code = "revision_conflict"

    def __init__(self, *, expected_revision: int, current_revision: int) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__(
            "Path revision changed while it was being edited "
            f"(expected {expected_revision}, current {current_revision})"
        )


class ConcurrentRevisionConflictError(DomainError):
    code = "revision_conflict"

    def __init__(self) -> None:
        super().__init__(
            "Path revision changed concurrently; reload the current revision before retrying"
        )


class InvalidPathRevisionError(DomainError):
    code = "invalid_path_revision"

    def __init__(self, issues: Sequence[dict[str, object]]) -> None:
        self.issues = tuple(issues)
        super().__init__("Path revision cannot be activated until its validation issues are fixed")


class AIOutputValidationError(DomainError):
    code = "ai_output_validation_error"


class AIConfigurationError(DomainError):
    code = "ai_configuration_error"


class SuggestionReviewError(DomainError):
    code = "suggestion_review_error"
