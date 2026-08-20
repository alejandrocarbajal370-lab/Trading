from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "America/Mexico_City"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    started_at: str
    mode: str
    model_version: str
    git_commit: str | None
    data_date: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_run_context(
    *,
    mode: str,
    model_version: str,
    git_commit: str | None = None,
    data_date: str | None = None,
    now: datetime | None = None,
) -> RunContext:
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    timestamp = now.astimezone(tz) if now else datetime.now(tz)
    seed = f"{timestamp.isoformat()}|{mode}|{model_version}|{git_commit}|{data_date}"
    suffix = sha256(seed.encode("utf-8")).hexdigest()[:8]
    run_id = f"{timestamp:%Y%m%d_%H%M%S}_{mode.upper()}_{suffix}"
    return RunContext(
        run_id=run_id,
        started_at=timestamp.isoformat(),
        mode=mode,
        model_version=model_version,
        git_commit=git_commit,
        data_date=data_date,
    )
