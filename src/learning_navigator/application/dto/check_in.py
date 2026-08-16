"""Strict AI output used for evidence-aware progress feedback."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CheckInDimensionEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    comment: str = Field(min_length=1, max_length=160)


class CheckInAIEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=280)
    concept_understanding: CheckInDimensionEvaluation
    procedural_skill: CheckInDimensionEvaluation
    application_skill: CheckInDimensionEvaluation
    memory_strength: CheckInDimensionEvaluation
    limitations: str | None = Field(default=None, max_length=240)
