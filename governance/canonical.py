from __future__ import annotations

import datetime
import hashlib
import json
import math
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

CANONICALIZATION_VERSION = "typed-canonical-json-v1"
RUNTIME_FINGERPRINT_VERSION = "research-runtime-v1"


def canonical_value(value: Any) -> Any:
    """Return a JSON-safe, type-tagged value without pandas string coercion."""
    if value is None or value is pd.NA or value is pd.NaT:
        return {"type": "null", "value": None}
    if isinstance(value, (float, np.floating)) and math.isnan(float(value)):
        return {"type": "null", "value": None}
    if isinstance(value, (bool, np.bool_)):
        return {"type": "bool", "value": bool(value)}
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("canonical floats must be finite")
        return {"type": "float64", "value": number.hex()}
    if isinstance(value, (datetime.datetime, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise ValueError("canonical timestamps must be timezone-aware")
        return {"type": "datetime", "value": timestamp.tz_convert("UTC").isoformat()}
    if isinstance(value, (datetime.date, np.datetime64)):
        return {"type": "date", "value": pd.Timestamp(value).date().isoformat()}
    if isinstance(value, BaseModel):
        return canonical_value(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {
            "type": "object",
            "value": {
                str(k): canonical_value(v)
                for k, v in sorted(value.items(), key=lambda item: str(item[0]))
            },
        }
    if isinstance(value, (list, tuple)):
        return {"type": "array", "value": [canonical_value(item) for item in value]}
    return {"type": "string", "value": str(value)}


def typed_hash(value: Any) -> str:
    payload = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "payload": canonical_value(value),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def typed_frame_hash(frame: pd.DataFrame, keys: list[str]) -> str:
    missing = sorted(set(keys) - set(frame.columns))
    if missing:
        raise ValueError(f"canonical frame keys missing: {', '.join(missing)}")
    columns = sorted(frame.columns)
    records = [
        {column: canonical_value(row[column]) for column in columns}
        for _, row in frame.sort_values(keys, kind="stable").loc[:, columns].iterrows()
    ]
    return typed_hash({"columns": columns, "records": records})


class RuntimeFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = RUNTIME_FINGERPRINT_VERSION
    git_commit_sha: str = Field(pattern=r"^(?:[0-9a-f]{40}|UNAVAILABLE)$")
    requirements_lock_sha256: str = Field(pattern=r"^(?:[0-9a-f]{64}|UNAVAILABLE)$")
    python_version: str
    pandas_version: str
    numpy_version: str
    platform: str
    implementation: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_fingerprint(self) -> RuntimeFingerprint:
        identity = self.model_dump(mode="python", exclude={"fingerprint"})
        if typed_hash(identity) != self.fingerprint:
            raise ValueError("runtime fingerprint does not match its canonical payload")
        return self


def runtime_fingerprint(repo_root: Path | None = None) -> RuntimeFingerprint:
    root = repo_root or Path(__file__).resolve().parents[1]
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_sha = "UNAVAILABLE"
    lock = root / "requirements.lock"
    lock_hash = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else "UNAVAILABLE"
    identity = {
        "schema_version": RUNTIME_FINGERPRINT_VERSION,
        "git_commit_sha": git_sha,
        "requirements_lock_sha256": lock_hash,
        "python_version": platform.python_version(),
        "pandas_version": pd.__version__,
        "numpy_version": np.__version__,
        "platform": platform.platform(),
        "implementation": sys.implementation.name,
    }
    return RuntimeFingerprint(**identity, fingerprint=typed_hash(identity))
