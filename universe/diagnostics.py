from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from typing import Any

import pandas as pd

from universe.validation import UniverseRules, validate_universe


@dataclass(frozen=True)
class UniverseHealthRules:
    minimum_eligible_assets: int = 1
    minimum_eligible_ratio: float = 0.25
    maximum_group_concentration: float = 0.60
    maximum_top_10_market_cap_concentration: float = 0.80
    maximum_stress_coverage_loss: float = 0.35

    def __post_init__(self) -> None:
        if self.minimum_eligible_assets < 1:
            raise ValueError("minimum_eligible_assets must be positive")
        ratios = (
            self.minimum_eligible_ratio,
            self.maximum_group_concentration,
            self.maximum_top_10_market_cap_concentration,
            self.maximum_stress_coverage_loss,
        )
        if any(value < 0 or value > 1 for value in ratios):
            raise ValueError("universe health ratios must be between zero and one")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    values = frame[column].fillna("UNKNOWN").replace("", "UNKNOWN").astype(str)
    return {str(key): int(value) for key, value in values.value_counts().sort_index().items()}


def _market_cap_buckets(frame: pd.DataFrame) -> dict[str, int]:
    labels = ["unknown", "micro_lt_300m", "small_300m_2b", "mid_2b_10b", "large_ge_10b"]
    cap = pd.to_numeric(frame["market_cap"], errors="coerce")
    bucket = pd.cut(
        cap,
        bins=[-float("inf"), 300_000_000, 2_000_000_000, 10_000_000_000, float("inf")],
        labels=labels[1:],
        right=False,
    ).astype("string").fillna(labels[0])
    counts = bucket.value_counts()
    return {label: int(counts.get(label, 0)) for label in labels}


def _group_concentration(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    if frame.empty:
        return {"largest_group": None, "largest_group_share": 0.0, "hhi": 0.0}
    shares = frame[column].fillna("UNKNOWN").replace("", "UNKNOWN").value_counts(normalize=True)
    return {
        "largest_group": str(shares.index[0]),
        "largest_group_share": round(float(shares.iloc[0]), 6),
        "hhi": round(float((shares**2).sum()), 6),
    }


def _market_cap_concentration(frame: pd.DataFrame) -> dict[str, float]:
    cap = pd.to_numeric(frame["market_cap"], errors="coerce").dropna().clip(lower=0)
    total = float(cap.sum())
    if total == 0:
        return {"top_1_share": 0.0, "top_10_share": 0.0}
    ordered = cap.sort_values(ascending=False)
    return {
        "top_1_share": round(float(ordered.iloc[:1].sum() / total), 6),
        "top_10_share": round(float(ordered.iloc[:10].sum() / total), 6),
    }


def compare_membership(
    current: pd.DataFrame,
    previous: pd.DataFrame | None,
    *,
    current_ruleset_version: str,
    previous_ruleset_version: str | None = None,
) -> dict[str, Any]:
    if previous is None:
        return {
            "previous_snapshot": False,
            "current_ruleset_version": current_ruleset_version,
            "previous_ruleset_version": None,
            "ruleset_changed": False,
            "entries": [],
            "exits": [],
            "changes": [],
        }
    current_status = current.set_index("symbol")["eligibility_status"].to_dict()
    previous_status = previous.set_index("symbol")["eligibility_status"].to_dict()
    current_eligible = {symbol for symbol, status in current_status.items() if status == "ELIGIBLE"}
    previous_eligible = {symbol for symbol, status in previous_status.items() if status == "ELIGIBLE"}
    changes = []
    current_by_symbol = current.set_index("symbol")
    previous_by_symbol = previous.set_index("symbol")
    for symbol in sorted(set(current_status) | set(previous_status)):
        before = previous_status.get(symbol, "NOT_PRESENT")
        after = current_status.get(symbol, "NOT_PRESENT")
        if before != after:
            row = current_by_symbol.loc[symbol] if symbol in current_by_symbol.index else previous_by_symbol.loc[symbol]
            changes.append(
                {
                    "symbol": symbol,
                    "from": before,
                    "to": after,
                    "reason": str(row.get("exclusion_reason", "")) or "eligible_or_not_present",
                }
            )
    return {
        "previous_snapshot": True,
        "current_ruleset_version": current_ruleset_version,
        "previous_ruleset_version": previous_ruleset_version,
        "ruleset_changed": previous_ruleset_version != current_ruleset_version,
        "entries": sorted(current_eligible - previous_eligible),
        "exits": sorted(previous_eligible - current_eligible),
        "changes": changes,
    }


def stress_test_universe(
    records: pd.DataFrame, *, rules: UniverseRules, as_of: pd.Timestamp
) -> list[dict[str, Any]]:
    baseline = validate_universe(records, rules=rules, as_of=as_of)
    baseline_count = int((baseline["eligibility_status"] == "ELIGIBLE").sum())
    scenarios: list[tuple[str, UniverseRules]] = []
    for field in ("minimum_market_cap", "minimum_average_volume", "minimum_average_dollar_volume"):
        value = getattr(rules, field)
        if value is not None:
            scenarios.extend(
                [
                    (f"{field}_minus_20pct", replace(rules, **{field: value * 0.8})),
                    (f"{field}_plus_20pct", replace(rules, **{field: value * 1.2})),
                ]
            )
    results = []
    for name, scenario_rules in scenarios:
        membership = validate_universe(records, rules=scenario_rules, as_of=as_of)
        eligible = int((membership["eligibility_status"] == "ELIGIBLE").sum())
        loss = 0.0 if baseline_count == 0 else max(0.0, (baseline_count - eligible) / baseline_count)
        results.append(
            {
                "scenario": name,
                "eligible": eligible,
                "eligible_change": eligible - baseline_count,
                "coverage_loss": round(loss, 6),
                "rules": scenario_rules.to_dict(),
            }
        )
    return results


def diagnose_universe(
    membership: pd.DataFrame,
    *,
    rules: UniverseRules,
    health_rules: UniverseHealthRules,
    stress_tests: list[dict[str, Any]],
    previous: pd.DataFrame | None = None,
    previous_ruleset_version: str | None = None,
) -> dict[str, Any]:
    eligible = membership.loc[membership["eligibility_status"] == "ELIGIBLE"].copy()
    total = len(membership)
    eligible_count = len(eligible)
    ratio = 0.0 if total == 0 else eligible_count / total
    distributions = {
        column: _counts(eligible, column)
        for column in ("sector", "industry", "country", "exchange")
    }
    distributions["market_cap_bucket"] = _market_cap_buckets(eligible)
    concentration = {
        column: _group_concentration(eligible, column)
        for column in ("sector", "industry", "country", "exchange")
    }
    concentration["market_cap"] = _market_cap_concentration(eligible)
    reasons: list[dict[str, str]] = []
    if eligible_count == 0:
        reasons.append({"severity": "FAIL", "code": "empty_eligible_universe"})
    elif eligible_count < health_rules.minimum_eligible_assets:
        reasons.append({"severity": "FAIL", "code": "eligible_universe_too_small"})
    if total and ratio < health_rules.minimum_eligible_ratio:
        reasons.append({"severity": "WARNING", "code": "filters_destroy_coverage"})
    for column in ("sector", "industry", "country", "exchange"):
        if concentration[column]["largest_group_share"] > health_rules.maximum_group_concentration:
            reasons.append({"severity": "WARNING", "code": f"excessive_{column}_concentration"})
    if (
        concentration["market_cap"]["top_10_share"]
        > health_rules.maximum_top_10_market_cap_concentration
    ):
        reasons.append({"severity": "WARNING", "code": "excessive_market_cap_concentration"})
    if any(test["coverage_loss"] > health_rules.maximum_stress_coverage_loss for test in stress_tests):
        reasons.append({"severity": "WARNING", "code": "threshold_sensitivity_excessive"})
    status = "FAIL" if any(reason["severity"] == "FAIL" for reason in reasons) else (
        "WARNING" if reasons else "PASS"
    )
    exclusion_reasons = (
        membership.loc[membership["exclusion_reason"] != "", "exclusion_reason"]
        .str.split(";").explode().value_counts().sort_index().to_dict()
    )
    return {
        "status": status,
        "reasons": reasons,
        "counts": {"total": total, "eligible": eligible_count, "excluded": total - eligible_count},
        "eligible_ratio": round(ratio, 6),
        "distributions": distributions,
        "concentration": concentration,
        "changes": compare_membership(
            membership,
            previous,
            current_ruleset_version=rules.ruleset_version,
            previous_ruleset_version=previous_ruleset_version,
        ),
        "stress_tests": stress_tests,
        "exclusion_reasons": {str(key): int(value) for key, value in exclusion_reasons.items()},
        "rules": rules.to_dict(),
        "health_rules": health_rules.to_dict(),
        "lineage_digest": hashlib.sha256(
            "".join(sorted(membership.get("lineage", pd.Series(dtype=str)).astype(str))).encode()
        ).hexdigest(),
        "trade_decision": "NO_TRADE",
        "live_execution_enabled": False,
    }
