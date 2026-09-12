"""Fail-closed admission for research-only backtesting inputs.

This module is deliberately independent from Step 6 ``EvidenceGate``/``GateState``.
Research admission is not production admission and carries no execution authority.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from research.datasets import DatasetVersionError, verify_dataset, verify_universe_snapshot
from research.registry import DatasetRegistration, RegistryValidationError


class ResearchDataGrade(StrEnum):
    RESEARCH_GRADE = "RESEARCH_GRADE"
    INSUFFICIENT_RESEARCH_DATA = "INSUFFICIENT_RESEARCH_DATA"
    FAILED_RESEARCH_DATA = "FAILED_RESEARCH_DATA"


class ResearchBacktestingAuthorization(StrEnum):
    RESEARCH_BACKTESTING_AUTHORIZED = "RESEARCH_BACKTESTING_AUTHORIZED"
    RESEARCH_BACKTESTING_NOT_AUTHORIZED = "RESEARCH_BACKTESTING_NOT_AUTHORIZED"


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
        if admitted:
            raise ValueError(
                "RESEARCH_GRADE is unavailable until every control has canonical verification"
            )
        expected_consumers = ("RESEARCH", "RESEARCH_BACKTESTING") if admitted else ("RESEARCH",)
        if self.permitted_consumers != expected_consumers:
            raise ValueError("research consumer boundary does not match admission state")
        if admitted and self.reasons:
            raise ValueError("RESEARCH_GRADE cannot carry insufficiency or failure reasons")
        if not admitted and not self.reasons:
            raise ValueError("non-admission requires explicit reasons")
        return self


_UNVERIFIABLE_CONTROLS = (
    "pit_no_lookahead:not_canonically_verifiable",
    "provenance_lineage:not_content_bound",
    "reproducibility:not_canonically_verifiable",
    "restatement_handling:applicability_not_canonically_verifiable",
    "corporate_action_handling:applicability_not_canonically_verifiable",
    "no_silent_imputation:not_canonically_verifiable",
)


def assess_research_grade(
    registration: DatasetRegistration,
    *,
    registry_root: Path,
    universe_snapshot_dir: Path | None = None,
) -> ResearchGradeAdmission:
    """Verify canonical artifacts and fail closed for controls the repo cannot yet prove.

    Caller-declared control states, fingerprints, and ``NOT_REQUIRED`` reasons are not
    accepted. Dataset identity is recomputed from the registered file by the existing
    dataset verifier. A supplied universe snapshot is likewise checked by the existing
    canonical verifier. Those primitives do not yet prove every research-grade control,
    so a valid current artifact remains insufficient rather than earning authorization.
    """

    reasons: list[str] = []
    failed = False
    try:
        verify_dataset(registration, registry_root=registry_root, mismatch_policy="fail")
    except (DatasetVersionError, RegistryValidationError, OSError) as error:
        failed = True
        reasons.append(f"dataset_identity_checksums:failed:{error}")

    if universe_snapshot_dir is None:
        reasons.append("universe_survivorship:verified_snapshot_required")
    else:
        try:
            verify_universe_snapshot(universe_snapshot_dir)
        except (DatasetVersionError, OSError) as error:
            failed = True
            reasons.append(f"universe_survivorship:failed:{error}")

    reasons.extend(_UNVERIFIABLE_CONTROLS)
    grade = (
        ResearchDataGrade.FAILED_RESEARCH_DATA
        if failed
        else ResearchDataGrade.INSUFFICIENT_RESEARCH_DATA
    )
    return ResearchGradeAdmission(
        dataset_id=registration.dataset_id,
        snapshot_id=registration.snapshot_id,
        research_data_grade=grade,
        research_backtesting_authorization=(
            ResearchBacktestingAuthorization.RESEARCH_BACKTESTING_NOT_AUTHORIZED
        ),
        reasons=tuple(reasons),
        permitted_consumers=("RESEARCH",),
    )


def require_production_grade(value: object) -> None:
    """Future portfolio/execution boundary: research admission is always rejected."""

    if isinstance(value, ResearchGradeAdmission):
        raise TypeError(
            "RESEARCH_GRADE is never valid production, portfolio, or execution authority"
        )
    raise TypeError("a separate PRODUCTION_GRADE contract is required")
