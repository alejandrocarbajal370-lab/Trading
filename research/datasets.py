from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from research.registry import DatasetRegistration


class DatasetVersionError(ValueError):
    """A registered research dataset no longer matches its immutable identity."""


@dataclass(frozen=True)
class VerifiedDataset:
    registration: DatasetRegistration
    resolved_path: Path
    observed_sha256: str


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
