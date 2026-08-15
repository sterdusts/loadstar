"""Shared domain enumerations.

String values are intentionally stable because they are persisted, exported and exposed by
the API. Renaming a member therefore requires a migration.
"""

from enum import StrEnum


class RecordStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class VersionStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class NodeType(StrEnum):
    MODULE = "MODULE"
    CONCEPT = "CONCEPT"
    SKILL = "SKILL"
    PROCEDURE = "PROCEDURE"
    PROJECT = "PROJECT"
    ASSESSMENT = "ASSESSMENT"
    # Framework nodes used when the goal is to understand a field rather than
    # follow a course.
    QUESTION = "QUESTION"
    ENTITY = "ENTITY"
    MECHANISM = "MECHANISM"
    EVIDENCE = "EVIDENCE"
    # Execution nodes used when the goal is to make or change something.
    MILESTONE = "MILESTONE"
    DECISION = "DECISION"
    DELIVERABLE = "DELIVERABLE"
    RISK = "RISK"


class RelationType(StrEnum):
    CONTAINS = "CONTAINS"
    PREREQUISITE = "PREREQUISITE"
    RELATED = "RELATED"
    APPLIES_TO = "APPLIES_TO"
    EXTENDS = "EXTENDS"
    ALTERNATIVE_TO = "ALTERNATIVE_TO"
    CAUSES = "CAUSES"
    SUPPORTS = "SUPPORTS"
    CONSTRAINS = "CONSTRAINS"
    VALIDATES = "VALIDATES"
    ENABLES = "ENABLES"


class MasterySource(StrEnum):
    SELF_REPORT = "SELF_REPORT"
    EXERCISE = "EXERCISE"
    ASSESSMENT = "ASSESSMENT"
    AI_EVALUATION = "AI_EVALUATION"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class EvidenceType(StrEnum):
    SELF_REPORT = "SELF_REPORT"
    NOTE = "NOTE"
    EXERCISE_RESULT = "EXERCISE_RESULT"
    ASSESSMENT_RESULT = "ASSESSMENT_RESULT"
    CODE_ARTIFACT = "CODE_ARTIFACT"
    PROJECT_ARTIFACT = "PROJECT_ARTIFACT"
    EXPLANATION = "EXPLANATION"
    RESOURCE_COMPLETION = "RESOURCE_COMPLETION"
    AI_EVALUATION = "AI_EVALUATION"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class SuggestionType(StrEnum):
    KNOWLEDGE_MAP = "KNOWLEDGE_MAP"
    LEARNING_PLAN = "LEARNING_PLAN"
    MIND_MAP = "MIND_MAP"
    MISSING_NODE = "MISSING_NODE"
    EDGE = "EDGE"
    NODE_MERGE = "NODE_MERGE"
    PATH_EXPLANATION = "PATH_EXPLANATION"
    EXPLANATION_EVALUATION = "EXPLANATION_EVALUATION"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MODIFIED_ACCEPTED = "MODIFIED_ACCEPTED"
    REVERTED = "REVERTED"
    CONFLICT = "CONFLICT"


class GoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class GoalIntent(StrEnum):
    """The goal-specific navigation lens inferred from the user's intent.

    This is deliberately stored on each goal rather than configured as a product-wide
    mode: one user may learn a subject, understand an industry, and deliver a project in
    parallel.  Values are persisted and therefore must remain stable.
    """

    LEARN = "LEARN"
    UNDERSTAND = "UNDERSTAND"
    DO = "DO"


class PathStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class PathValidityStatus(StrEnum):
    VALID = "VALID"
    STALE = "STALE"
    INVALID = "INVALID"


class PathOrigin(StrEnum):
    """Who authored a path revision.

    A revision can be copied and edited without losing the provenance of the
    revision it was based on.  ``LEGACY`` is reserved for rows created before
    path revisions became user editable.
    """

    LEGACY = "LEGACY"
    ALGORITHM_GENERATED = "ALGORITHM_GENERATED"
    AI_GENERATED = "AI_GENERATED"
    USER_EDITED = "USER_EDITED"
    MIXED = "MIXED"


class PathStepSource(StrEnum):
    LEGACY = "LEGACY"
    ALGORITHM_GENERATED = "ALGORITHM_GENERATED"
    AI_GENERATED = "AI_GENERATED"
    INHERITED = "INHERITED"
    USER_CREATED = "USER_CREATED"
    USER_EDITED = "USER_EDITED"


class PathActionKind(StrEnum):
    LEARN = "LEARN"
    EXPLORE = "EXPLORE"
    EXECUTE = "EXECUTE"
    PRACTICE = "PRACTICE"
    REVIEW = "REVIEW"
    VERIFY = "VERIFY"


class RoutePreference(StrEnum):
    FOUNDATION_COMPLETE = "FOUNDATION_COMPLETE"
    SHORTEST_FEASIBLE = "SHORTEST_FEASIBLE"
    PROJECT_FIRST = "PROJECT_FIRST"
    THEORY_FIRST = "THEORY_FIRST"
    MANUAL = "MANUAL"


class ComputedNodeStatus(StrEnum):
    MASTERED = "MASTERED"
    IN_PROGRESS = "IN_PROGRESS"
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"
    NOT_RELEVANT = "NOT_RELEVANT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
