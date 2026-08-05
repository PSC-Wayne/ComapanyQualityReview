"""Fail-closed disposition for a primary-child challenger with no legal samples."""

from __future__ import annotations

from collections import Counter
from typing import Iterable


class PrimaryChildDispositionError(ValueError):
    """Raised when inputs cannot legally take the sample-insufficient path."""


def build_zero_sample_disposition(
    payloads: Iterable[dict[str, object]], *, input_artifacts: list[str]
) -> dict[str, object]:
    observations: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for payload in payloads:
        if (
            payload.get("current_fill_used") is not False
            or payload.get("fallback_used") is not False
            or payload.get("pooling_used") is not False
            or payload.get("final_oos_read") is not False
        ):
            raise PrimaryChildDispositionError("no-fallback PIT inputs required")
        rows = payload.get("observations")
        if not isinstance(rows, list):
            raise PrimaryChildDispositionError("observations required")
        for row in rows:
            if not isinstance(row, dict):
                raise PrimaryChildDispositionError("invalid observation")
            key = (
                str(row.get("issuer_id", "")),
                str(row.get("security_code", "")),
                str(row.get("decision_date", "")),
            )
            if not all(key) or key in seen:
                raise PrimaryChildDispositionError("unique issuer/security/decision required")
            seen.add(key)
            observations.append(row)

    admitted = [
        row
        for row in observations
        if row.get("status") == "attributed" and row.get("model_excluded") is False
    ]
    if admitted:
        raise PrimaryChildDispositionError(
            "attributed samples require the real pre-OOS competition, not zero-sample disposition"
        )
    status_counts = Counter(str(row.get("status")) for row in observations)
    attempted = len(observations)
    return {
        "schema_version": "F000PrimaryChildChallengerDisposition.v1",
        "status": "industry_sample_insufficient",
        "publication_status": "research_only",
        "input_artifacts": input_artifacts,
        "attempted_count": attempted,
        "admitted_training_count": 0,
        "excluded_count": attempted,
        "coverage_pct": 0.0,
        "exclusion_counts": dict(sorted(status_counts.items())),
        "route_results": [],
        "competition_run": False,
        "gate_results": {
            "mae_improvement_gte_5pct": "not_run_sample_insufficient",
            "spearman_gte_0_10": "not_run_sample_insufficient",
            "direction_improvement_gte_5pp": "not_run_sample_insufficient",
            "auc_gte_0_62": "not_run_sample_insufficient",
            "interval_coverage_75_to_85pct": "not_run_sample_insufficient",
        },
        "champion": None,
        "stars": None,
        "frozen_candidate": None,
        "current_backfill_used": False,
        "parent_fallback_used": False,
        "sibling_pooling_used": False,
        "hierarchical_pooling_used": False,
        "market_feature_used": False,
        "final_oos_read": False,
        "reason": "No official-evidence unique primary-child observation was admitted for 2016-2021.",
    }


__all__ = ["PrimaryChildDispositionError", "build_zero_sample_disposition"]
