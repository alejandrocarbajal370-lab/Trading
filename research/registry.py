from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResearchExperiment:
    experiment_id: str
    hypothesis: str
    outcome_metric: str
    universe: str
    sample_start: str
    sample_end: str
    preregistered_at: str
    status: str = "REGISTERED"


class ResearchRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def register(self, experiment: ResearchExperiment) -> None:
        existing = self.read_all()
        if any(item["experiment_id"] == experiment.experiment_id for item in existing):
            raise ValueError(f"duplicate experiment_id: {experiment.experiment_id}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(experiment), sort_keys=True) + "\n")

    def read_all(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line
        ]
