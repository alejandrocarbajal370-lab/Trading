"""Fail-closed admission contract for research-only backtesting inputs.

This module is deliberately independent from Step 6 ``EvidenceGate``/``GateState``.
Research admission is not production admission and carries no execution authority.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchDataGrade(StrEnum):
    RESEARCH_GRADE = "RESEARCH_GRADE"
    INSUFFICIENT_RESEARCH_DATA = "INSUFFICIENT_RESEARCH_DATA"
    FAILED_RESEARCH_DATA = "FAILED_RESEARCH_DATA"


class ResearchControlState(StrEnum):
    SATISFIED = "SATISFIED"
    NOT_REQUIRED = "NOT_REQUIRED"
    INSUFFICIENT = "INSUFFICIENT"
    FAILED = "FAILED"


class ResearchBacktestingAuthorization(StrEnum):
    RESEARCH_BACKTESTING_AUTHORIZED = "RESEARCH_BACKTESTING_AUTHORIZED"
    RESEARCH_BACKTESTING_NOT_AUTHORIZED = "RESEARCH_BACKTESTING_NOT_AUTHORIZED"


class ResearchGradeEvidence(BaseModel):
    """Versioned evidence for one complete research dataset snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["research-grade-evidence-v1"] = "research-grade-evidence-v1"
    dataset_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    dataset_checksums: tuple[str, ...] = Field(min_length=1)
    lineage: tuple[str, ...] = Field(min_length=1)
    reproducibility_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    pit_no_lookahead: ResearchControlState
    provenance_lineage: ResearchControlState
    dataset_identity_checksums: ResearchControlState
    reproducibility: ResearchControlState
    restatement_handling: ResearchControlState
    universe_survivorship: ResearchControlState
    corporate_action_handling: ResearchControlState
    no_silent_imputation: ResearchControlState

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if any(not item.strip() for item in self.lineage):
            raise ValueError("research lineage cannot contain blank entries")
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in self.dataset_checksums
        ):
            raise ValueError("dataset checksums must be lowercase sha256 values")
        always_required = (
            self.pit_no_lookahead,
            self.provenance_lineage,
            self.dataset_identity_checksums,
            self.reproducibility,
            self.universe_survivorship,
            self.no_silent_imputation,
        )
        if ResearchControlState.NOT_REQUIRED in always_required:
            raise ValueError("mandatory research controls cannot be NOT_REQUIRED")
        return self


class ResearchGradeAdmission(BaseModel):
    """Derived research-only authority; never a production promotion token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["research-grade-admission-v1"] = "research-grade-admission-v1"
    dataset_id: str
    snapshot_id: str
    research_data_grade: ResearchDataGrade
    research_backtesting_authorization: ResearchBacktestingAuthorization
    reasons: tuple[str, ...]
    permitted_consumers: tuple[Literal["RESEARCH", "RESEARCH_BACKTESTING"], ...]
    production_grade: Literal[False] = False
    implicit_production_promotion: Literal[False] = False
    portfolio_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False
    trade_decision: Literal["NO_TRADE"] = "NO_TRADE"
    signals_generated: Literal[False] = False
    execution_authority: Literal["HUMAN_ONLY"] = "HUMAN_ONLY"
    human_execution_required: Literal[True] = True
    live_execution_enabled: Literal[False] = False

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        admitted = self.research_data_grade is ResearchDataGrade.RESEARCH_GRADE
        authorized = (
            self.research_backtesting_authorization
            is ResearchBacktestingAuthorization.RESEARCH_BACKTESTING_AUTHORIZED
        )
        if admitted != authorized:
            raise ValueError("research backtesting authority must exactly match RESEARCH_GRADE")
        expected_consumers = ("RESEARCH", "RESEARCH_BACKTESTING") if admitted else ("RESEARCH",)
        if self.permitted_consumers != expected_consumers:
            raise ValueError("research consumer boundary does not match admission state")
        if admitted and self.reasons:
            raise ValueError("RESEARCH_GRADE cannot carry insufficiency or failure reasons")
        if not admitted and not self.reasons:
            raise ValueError("non-admission requires explicit reasons")
        return self


_CONTROL_NAMES = (
    "pit_no_lookahead",
    "provenance_lineage",
    "dataset_identity_checksums",
    "reproducibility",
    "restatement_handling",
    "universe_survivorship",
    "corporate_action_handling",
    "no_silent_imputation",
)


def assess_research_grade(evidence: ResearchGradeEvidence) -> ResearchGradeAdmission:
    """Derive research-only backtesting authority from complete, typed evidence."""

    evidence = ResearchGradeEvidence.model_validate(evidence.model_dump())
    reasons = tuple(
        f"{name}:{getattr(evidence, name).value}"
        for name in _CONTROL_NAMES
        if getattr(evidence, name)
        not in {
            ResearchControlState.SATISFIED,
            ResearchControlState.NOT_REQUIRED,
        }
    )
    failed = any(getattr(evidence, name) is ResearchControlState.FAILED for name in _CONTROL_NAMES)
    grade = (
        ResearchDataGrade.FAILED_RESEARCH_DATA
        if failed
        else ResearchDataGrade.INSUFFICIENT_RESEARCH_DATA
        if reasons
        else ResearchDataGrade.RESEARCH_GRADE
    )
    authorized = grade is ResearchDataGrade.RESEARCH_GRADE
    return ResearchGradeAdmission(
        dataset_id=evidence.dataset_id,
        snapshot_id=evidence.snapshot_id,
        research_data_grade=grade,
        research_backtesting_authorization=(
            ResearchBacktestingAuthorization.RESEARCH_BACKTESTING_AUTHORIZED
            if authorized
            else ResearchBacktestingAuthorization.RESEARCH_BACKTESTING_NOT_AUTHORIZED
        ),
        reasons=reasons,
        permitted_consumers=("RESEARCH", "RESEARCH_BACKTESTING") if authorized else ("RESEARCH",),
    )


def require_production_grade(value: object) -> None:
    """Future portfolio/execution boundary: research admission is always rejected."""

    if isinstance(value, ResearchGradeAdmission):
        raise TypeError(
            "RESEARCH_GRADE is never valid production, portfolio, or execution authority"
        )
    raise TypeError("a separate PRODUCTION_GRADE contract is required")
