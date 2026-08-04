"""Production boundary for the evidence-backed F000 upside disposition.

This module deliberately integrates only source/model status.  A failed pre-OOS
candidate cannot freeze weights, read Final OOS, or publish formal stars.
"""

from __future__ import annotations

from math import isfinite
from typing import cast

from company_quality.industry.primary_business import (
    PrimaryBusinessEvidenceError,
    validate_primary_business_pilot,
)


_CANDIDATE_ID = "f000_multilabel_partial_pooling_ridge_v1"
_GATE_ORDER = (
    "mae_5pct_better_than_naive_and_linear",
    "spearman_at_least_0_10",
    "direction_improvement_at_least_5pp",
    "auc_at_least_0_62",
    "interval_coverage_0_75_to_0_85",
)


class FineIndustryDispositionError(ValueError):
    """Raised when source/model evidence cannot support a safe disposition."""


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise FineIndustryDispositionError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _rows(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise FineIndustryDispositionError(f"{field} must be an array of objects")
    return cast(list[dict[str, object]], value)


def _official_source_status(materialization: dict[str, object]) -> dict[str, object]:
    if materialization.get("schema_version") != "TPExF000Materialization.v1":
        raise FineIndustryDispositionError("official TPEx F000 materialization required")
    historical = _mapping(materialization.get("historical"), "historical")
    report = _mapping(historical.get("report"), "historical.report")
    if report.get("schema_version") != "TPExF000HistoricalPITReport.v1":
        raise FineIndustryDispositionError("official TPEx F000 PIT report required")
    if report.get("current_fill_used") is not False:
        raise FineIndustryDispositionError("current backfill is prohibited")
    if report.get("market_is_not_route_key") is not True:
        raise FineIndustryDispositionError("market cannot route official F000 PIT data")

    decisions = _rows(historical.get("decisions"), "historical.decisions")
    by_day: dict[str, dict[str, object]] = {}
    for row in decisions:
        day = str(row.get("decision_date", ""))
        if not day or day in by_day:
            raise FineIndustryDispositionError("unique official PIT decision dates required")
        by_day[day] = row

    memberships = _rows(historical.get("memberships"), "historical.memberships")
    membership_keys: set[tuple[str, str, str, str]] = set()
    fresh_markets: set[str] = set()
    for row in memberships:
        key = (
            str(row.get("decision_date", "")),
            str(row.get("snapshot_at", "")),
            str(row.get("security_code", "")),
            str(row.get("node_code", "")),
        )
        if not all(key) or key in membership_keys:
            raise FineIndustryDispositionError("duplicate official membership or incomplete key")
        membership_keys.add(key)
        decision = by_day.get(key[0])
        if decision is None:
            raise FineIndustryDispositionError("membership decision missing from official PIT status")
        if bool(row.get("fresh_within_365d")) != bool(decision.get("fresh_within_365d")):
            raise FineIndustryDispositionError("membership freshness disagrees with official PIT status")
        if row.get("fresh_within_365d") is True:
            fresh_markets.add(str(row.get("security_market", "")))

    if not {"TWSE", "TPEx"}.issubset(fresh_markets):
        raise FineIndustryDispositionError("cross-market TWSE/TPEx pooling evidence required")

    fresh = sorted(
        day for day, row in by_day.items()
        if row.get("status") == "AVAILABLE" and row.get("fresh_within_365d") is True
    )
    excluded = {
        day: str(row.get("status"))
        for day, row in sorted(by_day.items())
        if row.get("status") != "AVAILABLE"
    }
    return {
        "fresh_decision_dates": fresh,
        "excluded_decision_dates": excluded,
        "fresh_decision_count": len(fresh),
        "deduplicated_membership_count": len(membership_keys),
        "current_backfill_used": False,
    }


def _recompute_gates(metrics: dict[str, object]) -> dict[str, bool]:
    try:
        mae = float(metrics["mae"])
        naive_mae = float(metrics["naive_mae"])
        linear_mae = float(metrics["linear_mae"])
        spearman = float(metrics["spearman"])
        direction_pp = float(metrics["direction_pp"])
        auc = float(metrics["auc"])
        coverage = float(metrics["coverage"])
        n = int(metrics["n"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FineIndustryDispositionError("complete finite pre-OOS metrics required") from exc
    if not all(isfinite(value) for value in (
        mae, naive_mae, linear_mae, spearman, direction_pp, auc, coverage
    )):
        raise FineIndustryDispositionError("complete finite pre-OOS metrics required")
    if n <= 0:
        raise FineIndustryDispositionError("industry_sample_insufficient")
    return {
        "mae_5pct_better_than_naive_and_linear": (
            mae <= 0.95 * naive_mae and mae <= 0.95 * linear_mae
        ),
        "spearman_at_least_0_10": spearman >= 0.10,
        "direction_improvement_at_least_5pp": direction_pp >= 5.0,
        "auc_at_least_0_62": auc >= 0.62,
        "interval_coverage_0_75_to_0_85": 0.75 <= coverage <= 0.85,
    }


def build_fine_industry_upside_disposition(
    f000_materialization: dict[str, object],
    primary_business_pilot: dict[str, object],
    comparison_report: dict[str, object],
) -> dict[str, object]:
    """Validate official inputs and emit the non-publishable #175 disposition."""
    source_status = _official_source_status(f000_materialization)
    try:
        primary_status = validate_primary_business_pilot(primary_business_pilot)
    except PrimaryBusinessEvidenceError as exc:
        raise FineIndustryDispositionError(str(exc)) from exc

    if comparison_report.get("schema_version") != "F000PITMultiLabelUpsideComparison.v1":
        raise FineIndustryDispositionError("accepted F000 multi-label comparison required")
    if comparison_report.get("status") != "research_only":
        raise FineIndustryDispositionError("comparison must remain research_only")
    if _mapping(comparison_report.get("fixed_model_contract"), "fixed_model_contract").get(
        "gate_tuning_performed"
    ) is not False:
        raise FineIndustryDispositionError("gate tuning is prohibited")
    if comparison_report.get("final_oos_read") is not False:
        raise FineIndustryDispositionError("Final OOS must remain unread")
    if comparison_report.get("publishable") is not False or comparison_report.get(
        "formal_stars_enabled"
    ) is not False:
        raise FineIndustryDispositionError("unfrozen comparison cannot publish stars")
    if comparison_report.get("market_used_as_route_key") is not False or comparison_report.get(
        "market_used_as_model_feature"
    ) is not False:
        raise FineIndustryDispositionError("market cannot be a route key or model feature")
    if comparison_report.get("route_key") != "official_industry_code=25":
        raise FineIndustryDispositionError("cross-market official-industry route required")
    if comparison_report.get("observation_key") != [
        "issuer_id", "security_code", "decision_date"
    ] or comparison_report.get("duplicate_candidate_observation_count") != 0:
        raise FineIndustryDispositionError("candidate observations must be unique without market")
    feature_ids = comparison_report.get("baseline_feature_ids")
    if not isinstance(feature_ids, list) or any("market" in str(item).lower() for item in feature_ids):
        raise FineIndustryDispositionError("market cannot be a model feature")

    if comparison_report.get("eligible_decision_dates") != source_status["fresh_decision_dates"]:
        raise FineIndustryDispositionError("comparison does not consume official fresh PIT decisions")
    if comparison_report.get("excluded_decision_dates") != source_status["excluded_decision_dates"]:
        raise FineIndustryDispositionError("comparison exclusions disagree with official PIT status")
    _mapping(comparison_report.get("node_coverage"), "node_coverage")

    comparisons = _mapping(comparison_report.get("comparisons"), "comparisons")
    candidate = _mapping(comparisons.get(_CANDIDATE_ID), f"comparisons.{_CANDIDATE_ID}")
    metrics = _mapping(candidate.get("metrics"), "candidate.metrics")
    reported_gates = _mapping(candidate.get("gates"), "candidate.gates")
    recomputed = _recompute_gates(metrics)
    if set(reported_gates) != set(_GATE_ORDER) or any(
        reported_gates[name] is not recomputed[name] for name in _GATE_ORDER
    ):
        raise FineIndustryDispositionError("pre-OOS gate result mismatch")
    all_pass = all(recomputed.values())
    if candidate.get("all_gates_pass") is not all_pass:
        raise FineIndustryDispositionError("pre-OOS all-gates result mismatch")
    if all_pass:
        raise FineIndustryDispositionError(
            "passing candidate must be frozen before Final OOS; research-only disposition refused"
        )

    failed = [name for name in _GATE_ORDER if not recomputed[name]]
    return {
        "schema_version": "FineIndustryUpsideDisposition.v1",
        "status": "research_only",
        "reason": "pre_oos_gates_failed",
        "publishable": False,
        "formal_stars_enabled": False,
        "final_oos_read": False,
        "champion_candidate_id": None,
        "candidate_id": _CANDIDATE_ID,
        "failed_gates": failed,
        "diagnostics": {"metrics": dict(metrics), "gates": recomputed},
        "source_status": source_status,
        "primary_business_status": primary_status,
        "routing": {
            "route_key": str(comparison_report.get("route_key")),
            "cross_market_pooling": True,
            "market_used_as_route_key": False,
            "market_used_as_model_feature": False,
            "observation_key_excludes_market": True,
        },
    }


__all__ = [
    "FineIndustryDispositionError",
    "build_fine_industry_upside_disposition",
]