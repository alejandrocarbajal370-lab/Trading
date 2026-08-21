from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ResearchContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactorResearchInput(ResearchContract):
    experiment_id: str
    experiment_version: str
    universe_snapshot_id: str
    ruleset_version: str
    dataset_snapshot_ids: tuple[str, ...]
    analysis_start: str
    analysis_end: str
    lineage: tuple[str, ...]


class FactorResearchOutput(ResearchContract):
    experiment_id: str
    observations: int = Field(ge=0)
    metrics: dict[str, float | int | str | None]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class ResearchEvaluation(ResearchContract):
    health: Literal["PASS", "WARNING", "FAIL"]
    expected_result: str
    observed_result: str
    decision: Literal["KEEP", "DISCARD", "REVIEW"]
    metrics: dict[str, Any]


class FactorResearchProtocol(Protocol):
    """Interface for future factor researchers; Phase 4 ships no implementation."""

    def evaluate(self, inputs: FactorResearchInput) -> FactorResearchOutput: ...
