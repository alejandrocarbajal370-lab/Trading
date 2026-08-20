from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.run_context import RunContext


@dataclass(frozen=True)
class ValidationManifest:
    context: RunContext
    overall_status: str
    critical_errors: int
    warnings: int
    checks: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.context.to_dict(),
            "overall_status": self.overall_status,
            "critical_errors": self.critical_errors,
            "warnings": self.warnings,
            "checks": self.checks,
        }


def write_manifest(manifest: ValidationManifest, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "validation_manifest.json"
    path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path
