from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from company_quality.industry.fine_industry_upside import (
    FineIndustryDispositionError,
    build_fine_industry_upside_disposition,
)


ROOT = Path(__file__).parents[2]
PILOT = ROOT / "artifacts/real_data/tpex-f000-primary-business-pilot.json"
DISPOSITION = ROOT / "artifacts/real_data/f000-fine-industry-upside-disposition.json"


def _source() -> dict[str, object]:
    decisions = []
    for year in range(2014, 2023):
        day = f"{year}-06-30"
        if year in (2014, 2015):
            status, fresh, snapshot = "NO_PRE_DECISION_SNAPSHOT", None, None
        elif year == 2022:
            status, fresh, snapshot = "STALE_AUDIT_ONLY", False, "2021-06-19T00:23:56+00:00"
        else:
            status, fresh, snapshot = "AVAILABLE", True, f"{year}-06-01T00:00:00+00:00"
        decisions.append({
            "decision_date": day,
            "snapshot_at": snapshot,
            "status": status,
            "fresh_within_365d": fresh,
        })
    memberships = [
        {
            "decision_date": f"{year}-06-30",
            "snapshot_at": f"{year}-06-01T00:00:00+00:00",
            "security_code": code,
            "node_code": node,
            "fresh_within_365d": True,
            "security_market": market,
        }
        for year in range(2016, 2022)
        for code, market, node in (("1001", "TWSE", "F100"), ("7001", "TPEx", "F100"))
    ]
    return {
        "schema_version": "TPExF000Materialization.v1",
        "historical": {
            "decisions": decisions,
            "memberships": memberships,
            "report": {
                "schema_version": "TPExF000HistoricalPITReport.v1",
                "current_fill_used": False,
                "market_is_not_route_key": True,
            },
        },
    }


def _comparison() -> dict[str, object]:
    metrics = {
        "n": 204,
        "mae": 0.3262230537,
        "naive_mae": 0.3485700539,
        "linear_mae": 0.3264509022,
        "spearman": 0.508333,
        "direction_pp": 7.3529,
        "auc": 0.594724,
        "coverage": 0.789216,
    }
    gates = {
        "mae_5pct_better_than_naive_and_linear": False,
        "spearman_at_least_0_10": True,
        "direction_improvement_at_least_5pp": True,
        "auc_at_least_0_62": False,
        "interval_coverage_0_75_to_0_85": True,
    }
    return {
        "schema_version": "F000PITMultiLabelUpsideComparison.v1",
        "status": "research_only",
        "publishable": False,
        "formal_stars_enabled": False,
        "final_oos_read": False,
        "route_key": "official_industry_code=25",
        "market_used_as_route_key": False,
        "market_used_as_model_feature": False,
        "observation_key": ["issuer_id", "security_code", "decision_date"],
        "duplicate_candidate_observation_count": 0,
        "eligible_decision_dates": [f"{year}-06-30" for year in range(2016, 2022)],
        "excluded_decision_dates": {
            "2014-06-30": "NO_PRE_DECISION_SNAPSHOT",
            "2015-06-30": "NO_PRE_DECISION_SNAPSHOT",
            "2022-06-30": "STALE_AUDIT_ONLY",
        },
        "fixed_model_contract": {"gate_tuning_performed": False},
        "baseline_feature_ids": ["core__roe_after_tax", "context__momentum_12m"],
        "node_coverage": {"duplicate_membership_rows_removed": 0},
        "comparisons": {
            "f000_multilabel_partial_pooling_ridge_v1": {
                "metrics": metrics,
                "gates": gates,
                "all_gates_pass": False,
            }
        },
    }


def _pilot() -> dict[str, object]:
    return json.loads(PILOT.read_text(encoding="utf-8"))


def test_evidence_backed_disposition_recomputes_unchanged_gates_and_stays_research_only() -> None:
    result = build_fine_industry_upside_disposition(_source(), _pilot(), _comparison())
    schema = json.loads((
        ROOT / "src/company_quality/industry/contracts/FineIndustryUpsideDisposition.schema.json"
    ).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(result)

    assert result["status"] == "research_only"
    assert result["reason"] == "pre_oos_gates_failed"
    assert result["champion_candidate_id"] is None
    assert result["formal_stars_enabled"] is False
    assert result["final_oos_read"] is False
    assert result["failed_gates"] == [
        "mae_5pct_better_than_naive_and_linear",
        "auc_at_least_0_62",
    ]
    assert result["diagnostics"]["metrics"]["n"] == 204
    assert result["source_status"]["fresh_decision_count"] == 6
    assert result["source_status"]["current_backfill_used"] is False
    assert result["primary_business_status"]["attributed_coverage"] == 0.875
    assert result["routing"] == {
        "route_key": "official_industry_code=25",
        "cross_market_pooling": True,
        "market_used_as_route_key": False,
        "market_used_as_model_feature": False,
        "observation_key_excludes_market": True,
    }


def test_rejects_current_backfill_market_feature_and_duplicate_official_membership() -> None:
    source = _source()
    source["historical"]["report"]["current_fill_used"] = True
    with pytest.raises(FineIndustryDispositionError, match="current backfill"):
        build_fine_industry_upside_disposition(source, _pilot(), _comparison())

    comparison = _comparison()
    comparison["market_used_as_model_feature"] = True
    with pytest.raises(FineIndustryDispositionError, match="market cannot"):
        build_fine_industry_upside_disposition(_source(), _pilot(), comparison)

    source = _source()
    source["historical"]["memberships"].append(
        deepcopy(source["historical"]["memberships"][0])
    )
    with pytest.raises(FineIndustryDispositionError, match="duplicate official membership"):
        build_fine_industry_upside_disposition(source, _pilot(), _comparison())


def test_rejects_tuned_or_misreported_gates_and_any_passing_candidate() -> None:
    comparison = _comparison()
    comparison["comparisons"]["f000_multilabel_partial_pooling_ridge_v1"]["gates"][
        "auc_at_least_0_62"
    ] = True
    with pytest.raises(FineIndustryDispositionError, match="gate result mismatch"):
        build_fine_industry_upside_disposition(_source(), _pilot(), comparison)

    comparison = _comparison()
    comparison["fixed_model_contract"]["gate_tuning_performed"] = True
    with pytest.raises(FineIndustryDispositionError, match="gate tuning"):
        build_fine_industry_upside_disposition(_source(), _pilot(), comparison)

    comparison = _comparison()
    candidate = comparison["comparisons"]["f000_multilabel_partial_pooling_ridge_v1"]
    candidate["metrics"].update({"mae": 0.30, "auc": 0.70})
    candidate["gates"].update({
        "mae_5pct_better_than_naive_and_linear": True,
        "auc_at_least_0_62": True,
    })
    candidate["all_gates_pass"] = True
    with pytest.raises(FineIndustryDispositionError, match="must be frozen"):
        build_fine_industry_upside_disposition(_source(), _pilot(), comparison)


def test_committed_real_disposition_matches_contract_and_verified_pre_oos_evidence() -> None:
    payload = json.loads(DISPOSITION.read_text(encoding="utf-8"))
    schema = json.loads((
        ROOT / "src/company_quality/industry/contracts/FineIndustryUpsideDisposition.schema.json"
    ).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)

    assert payload["status"] == "research_only"
    assert payload["formal_stars_enabled"] is False
    assert payload["final_oos_read"] is False
    assert payload["diagnostics"]["metrics"] == _comparison()["comparisons"][
        "f000_multilabel_partial_pooling_ridge_v1"
    ]["metrics"]
    assert payload["failed_gates"] == [
        "mae_5pct_better_than_naive_and_linear",
        "auc_at_least_0_62",
    ]