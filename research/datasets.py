from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research.registry import DatasetRegistration


class DatasetVersionError(ValueError):
    """A registered research dataset no longer matches its immutable identity."""


@dataclass(frozen=True)
class VerifiedDataset:
    registration: DatasetRegistration
    resolved_path: Path
    observed_sha256: str


@dataclass(frozen=True)
class VerifiedUniverseSnapshot:
    directory: Path
    membership_path: Path
    membership_sha256: str
    validation_sha256: str
    metadata: dict[str, Any]
    validation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": True,
            "directory": str(self.directory),
            "as_of": self.metadata.get("as_of"),
            "membership_sha256": self.membership_sha256,
            "validation_sha256": self.validation_sha256,
            "health": self.validation.get("status"),
            "ruleset_version": self.metadata.get("ruleset", {}).get("version"),
        }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_dataset(
    registration: DatasetRegistration,
    *,
    registry_root: Path,
    mismatch_policy: str = "fail",
) -> tuple[VerifiedDataset, str | None]:
    registration.validate()
    path = Path(registration.path)
    resolved = path if path.is_absolute() else registry_root / path
    if not resolved.is_file():
        raise DatasetVersionError(f"dataset not found: {registration.dataset_id}: {resolved}")
    observed = file_sha256(resolved)
    warning = None
    if observed != registration.sha256:
        message = (
            f"dataset version mismatch for {registration.dataset_id} "
            f"(snapshot {registration.snapshot_id}): expected {registration.sha256}, observed {observed}"
        )
        if mismatch_policy == "fail":
            raise DatasetVersionError(message)
        if mismatch_policy != "warn":
            raise ValueError("mismatch_policy must be 'fail' or 'warn'")
        warning = message
    return VerifiedDataset(registration, resolved.resolve(), observed), warning


def verify_universe_snapshot(directory: Path) -> VerifiedUniverseSnapshot:
    """Verify the immutable universe membership, validation checksum, ruleset and health."""
    resolved = directory.resolve()
    membership_path = resolved / "universe_membership.csv"
    metadata_path = resolved / "snapshot_metadata.json"
    validation_path = resolved / "universe_validation.json"
    missing = [
        path.name
        for path in (membership_path, metadata_path, validation_path)
        if not path.is_file()
    ]
    if missing:
        raise DatasetVersionError(
            f"governed universe snapshot missing files: {', '.join(sorted(missing))}"
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DatasetVersionError(f"invalid governed universe JSON: {error.msg}") from error
    membership_sha = file_sha256(membership_path)
    validation_sha = file_sha256(validation_path)
    if membership_sha != metadata.get("membership_sha256"):
        raise DatasetVersionError("governed universe membership checksum mismatch")
    if validation_sha != metadata.get("validation_sha256"):
        raise DatasetVersionError("governed universe validation checksum mismatch")
    status = str(validation.get("status", ""))
    if status not in {"PASS", "WARNING"}:
        raise DatasetVersionError(f"governed universe health is not usable: {status or 'MISSING'}")
    ruleset_version = metadata.get("ruleset", {}).get("version")
    if not ruleset_version:
        raise DatasetVersionError("governed universe ruleset version is missing")
    if metadata.get("trade_decision") != "NO_TRADE" or metadata.get("live_execution_enabled") is not False:
        raise DatasetVersionError("governed universe snapshot violates research-only safety state")
    return VerifiedUniverseSnapshot(
        directory=resolved,
        membership_path=membership_path,
        membership_sha256=membership_sha,
        validation_sha256=validation_sha,
        metadata=metadata,
        validation=validation,
    )
