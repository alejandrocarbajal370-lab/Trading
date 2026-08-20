from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from universe.validation import OUTPUT_COLUMNS, UniverseValidationError


def _canonical_csv(membership: pd.DataFrame) -> bytes:
    frame = membership.loc[:, OUTPUT_COLUMNS].sort_values("symbol").reset_index(drop=True)
    return frame.to_csv(index=False, lineterminator="\n", date_format="%Y-%m-%dT%H:%M:%S%z").encode()


class UniverseSnapshotStore:
    """Append-only, date-addressed storage for reproducible point-in-time universes."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def dates(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(path.name for path in self.root.iterdir() if path.is_dir())

    def previous_date(self, as_of: pd.Timestamp) -> str | None:
        key = pd.Timestamp(as_of).date().isoformat()
        prior = [date for date in self.dates() if date < key]
        return prior[-1] if prior else None

    def load(self, as_of: str | pd.Timestamp) -> pd.DataFrame:
        key = pd.Timestamp(as_of).date().isoformat()
        path = self.root / key / "universe_membership.csv"
        if not path.exists():
            raise UniverseValidationError(f"universe snapshot not found: {key}")
        metadata = json.loads((path.parent / "snapshot_metadata.json").read_text(encoding="utf-8"))
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != metadata["membership_sha256"]:
            raise UniverseValidationError(f"universe snapshot checksum mismatch: {key}")
        return pd.read_csv(path)

    def save(
        self,
        membership: pd.DataFrame,
        *,
        as_of: pd.Timestamp,
        validation: dict[str, Any],
    ) -> Path:
        key = pd.Timestamp(as_of).date().isoformat()
        directory = self.root / key
        payload = _canonical_csv(membership)
        digest = hashlib.sha256(payload).hexdigest()
        if directory.exists():
            metadata = json.loads((directory / "snapshot_metadata.json").read_text(encoding="utf-8"))
            if metadata["membership_sha256"] != digest:
                raise UniverseValidationError(f"immutable universe snapshot already exists: {key}")
            return directory
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "universe_membership.csv").write_bytes(payload)
        (directory / "universe_validation.json").write_text(
            json.dumps(validation, indent=2, sort_keys=True), encoding="utf-8"
        )
        metadata = {
            "as_of": pd.Timestamp(as_of).isoformat(),
            "membership_sha256": digest,
            "validation_sha256": hashlib.sha256(
                json.dumps(validation, sort_keys=True).encode()
            ).hexdigest(),
            "records": len(membership),
            "trade_decision": "NO_TRADE",
            "live_execution_enabled": False,
        }
        (directory / "snapshot_metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        )
        return directory
