from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class RegistryValidationError(ValueError):
    """A research registry record is incomplete or internally inconsistent."""


class ExperimentState(StrEnum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ResearchDecision(StrEnum):
    KEEP = "KEEP"
    DISCARD = "DISCARD"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class DatasetRegistration:
    dataset_id: str
    snapshot_id: str
    path: str
    sha256: str
    lineage: tuple[str, ...]

    def validate(self) -> None:
        missing = [
            name
            for name in ("dataset_id", "snapshot_id", "path", "sha256")
            if not str(getattr(self, name)).strip()
        ]
        if missing:
            raise RegistryValidationError(
                f"missing dataset registry fields: {', '.join(sorted(missing))}"
            )
        if len(self.sha256) != 64 or any(character not in "0123456789abcdef" for character in self.sha256):
            raise RegistryValidationError(f"invalid sha256 for dataset {self.dataset_id}")
        if not self.lineage or any(not item.strip() for item in self.lineage):
            raise RegistryValidationError(f"incomplete lineage for dataset {self.dataset_id}")


@dataclass(frozen=True)
class ResearchExperiment:
    # The first seven fields retain the original registry constructor contract.
    experiment_id: str
    hypothesis: str
    outcome_metric: str
    universe: str
    sample_start: str
    sample_end: str
    preregistered_at: str
    status: str = "REGISTERED"
    experiment_version: str = ""
    created_at: str = ""
    universe_snapshot_id: str = ""
    ruleset_version: str = ""
    metrics_evaluated: tuple[str, ...] = ()
    expected_result: str = ""
    observed_result: str = "PENDING"
    decision: str = "REVIEW"
    datasets: tuple[DatasetRegistration, ...] = field(default_factory=tuple)
    data_lineage: tuple[str, ...] = field(default_factory=tuple)

    def validate(self, *, phase4: bool = True) -> None:
        common = (
            "experiment_id", "hypothesis", "outcome_metric", "universe",
            "sample_start", "sample_end", "preregistered_at",
        )
        phase4_fields = (
            "experiment_version", "created_at", "universe_snapshot_id",
            "ruleset_version", "expected_result",
        )
        required = common + phase4_fields if phase4 else common
        missing = [name for name in required if not str(getattr(self, name)).strip()]
        if phase4 and not self.metrics_evaluated:
            missing.append("metrics_evaluated")
        if phase4 and not self.datasets:
            missing.append("datasets")
        if phase4 and not self.data_lineage:
            missing.append("data_lineage")
        if missing:
            raise RegistryValidationError(
                f"missing registry fields: {', '.join(sorted(set(missing)))}"
            )
        try:
            start = datetime.date.fromisoformat(self.sample_start)
            end = datetime.date.fromisoformat(self.sample_end)
            datetime.datetime.fromisoformat(self.preregistered_at)
            if phase4:
                datetime.datetime.fromisoformat(self.created_at)
        except ValueError as error:
            raise RegistryValidationError(f"invalid registry date: {error}") from error
        if start > end:
            raise RegistryValidationError("sample_start must not be after sample_end")
        try:
            ExperimentState(self.status)
        except ValueError as error:
            raise RegistryValidationError(f"invalid experiment state: {self.status}") from error
        try:
            ResearchDecision(self.decision)
        except ValueError as error:
            raise RegistryValidationError(f"invalid research decision: {self.decision}") from error
        if phase4 and self.status not in {ExperimentState.REGISTERED, ExperimentState.READY}:
            raise RegistryValidationError(f"experiment state cannot be executed: {self.status}")
        for dataset in self.datasets:
            dataset.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchExperiment:
        document = dict(payload)
        document["metrics_evaluated"] = tuple(document.get("metrics_evaluated", ()))
        document["data_lineage"] = tuple(document.get("data_lineage", ()))
        document["datasets"] = tuple(
            DatasetRegistration(
                dataset_id=item.get("dataset_id", ""),
                snapshot_id=item.get("snapshot_id", ""),
                path=item.get("path", ""),
                sha256=item.get("sha256", ""),
                lineage=tuple(item.get("lineage", ())),
            )
            for item in document.get("datasets", ())
        )
        return cls(**document)


class ResearchRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def register(self, experiment: ResearchExperiment) -> None:
        experiment.validate(phase4=False)
        existing = self.read_all()
        identity = (experiment.experiment_id, experiment.experiment_version)
        if any(
            (str(item["experiment_id"]), str(item.get("experiment_version", ""))) == identity
            for item in existing
        ):
            raise ValueError(
                f"duplicate experiment_id/version: {experiment.experiment_id}/{experiment.experiment_version}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(experiment.to_dict(), sort_keys=True) + "\n")

    def get(self, experiment_id: str, experiment_version: str) -> ResearchExperiment:
        matches = [
            item for item in self.read_all()
            if item.get("experiment_id") == experiment_id
            and item.get("experiment_version") == experiment_version
        ]
        if not matches:
            raise RegistryValidationError(
                f"experiment not registered: {experiment_id}/{experiment_version}"
            )
        if len(matches) > 1:
            raise RegistryValidationError(
                f"duplicate experiment registry entries: {experiment_id}/{experiment_version}"
            )
        experiment = ResearchExperiment.from_dict(matches[0])
        experiment.validate(phase4=True)
        return experiment

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise RegistryValidationError(
                    f"invalid registry JSON at line {line_number}: {error.msg}"
                ) from error
        return records
