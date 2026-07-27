from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd
import pytest

from company_quality.lab.model_competition import FrozenPreOOSCandidate
from company_quality.lab.oos_release_gate import evaluate_one_shot_oos_gate


ROOT = Path(__file__).parents[2]


def _freeze() -> FrozenPreOOSCandidate:
    return FrozenPreOOSCandidate(
        generation_id="g1",
        final_oos_start="2023-01-01",
        frozen_through="2021-06-30",
        champion_candidate_id="champion",
        champion_score=0.1,
        candidate_scores=[{
            "candidate_id": "champion", "mean_absolute_error": 0.1,
            "outperform_brier": 0.1, "outperform_auc": 0.8,
            "selection_score": 0.2, "row_count": 400,
        }],
        fixed_baselines=[
            {
                "baseline_id": "no_company_data_temporal_median",
                "mean_absolute_error": 0.5,
                "official_benchmark_guess_mean_absolute_error": 0.5,
                "uses_company_features": False, "frozen": True,
            },
            {
                "baseline_id": "same_data_normalized_linear",
                "mean_absolute_error": 0.2, "uses_company_features": True,
                "feature_ids": ["x"], "frozen": True,
            },
        ],
        star_weights={
            "official_outperform_probability": 0.4,
            "predicted_p50_return": 0.3,
            "confidence": 0.3,
        },
        confidence_weights={
            "data_completeness": 0.35, "interval_precision": 0.25,
            "industry_sample": 0.2, "cross_year_stability": 0.2,
        },
        cross_year_stability=0.9,
        selection_row_count=400,
        selection_years=[2018, 2019, 2020, 2021],
    )


def _final_rows() -> pd.DataFrame:
    rows = []
    for market, industry in (("TWSE", "24"), ("TPEx", "31")):
        for offset in range(100):
            actual = (offset - 49.5) / 50.0
            misses_interval = offset >= 80
            predicted = actual + (0.4 if misses_interval else 0.0)
            probability = 1.0 / (1.0 + np.exp(-5.0 * actual))
            rows.append({
                "candidate_id": "champion",
                "issuer_id": f"{market}-{offset:03d}",
                "market": market,
                "industry_code": industry,
                "industry_status": "eligible",
                "decision_date": "2023-06-30",
                "trained_through": "2021-06-29",
                "generation_id": "g1",
                "actual_total_return": actual,
                "official_benchmark_return": 0.0,
                "predicted_p10_return": predicted - 0.2,
                "predicted_p50_return": predicted,
                "predicted_p90_return": predicted + 0.2,
                "positive_return_probability": probability,
                "outperform_probability": probability,
                "star": np.nan,
                "result_status": "research_only",
                "industry_train_observations": 600,
                "frozen_naive_prediction": 0.0,
                "frozen_naive_positive_probability": 0.5,
                "frozen_linear_prediction": actual + 0.15,
                "naive_baseline_id": "no_company_data_temporal_median",
                "linear_baseline_id": "same_data_normalized_linear",
                "baseline_frozen_through": "2021-06-30",
            })
    return pd.DataFrame(rows)


def test_all_thresholds_pass_but_only_candidate_eligibility_is_granted(
    tmp_path: Path,
) -> None:
    report = evaluate_one_shot_oos_gate(
        _final_rows(), _freeze(), evaluation_record_path=tmp_path / "gate.json"
    )

    assert report.gate_passed is True
    assert report.publication_candidate_eligible is True
    assert report.publishable is False
    assert report.formal_stars_emitted is False
    assert report.release_authorized is False
    assert report.t23_authorized is False
    assert report.missing_markets == []
    assert len(report.markets) == 2
    assert len(report.eligible_industries) == 2
    assert all(bool(item["passed"]) for item in report.markets)
    assert all(bool(item["passed"]) for item in report.eligible_industries)
    assert report.overall["p10_p90_interval_coverage"] == pytest.approx(0.8)

    schema = json.loads(
        (ROOT / "src/company_quality/lab/contracts/OneShotOOSGateReport.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(asdict(report))


def test_tpex_failure_cannot_be_hidden_by_twse(tmp_path: Path) -> None:
    rows = _final_rows()
    failed = rows["market"].eq("TPEx")
    rows.loc[failed, "predicted_p50_return"] = -rows.loc[failed, "actual_total_return"]
    rows.loc[failed, "predicted_p10_return"] = rows.loc[failed, "predicted_p50_return"] - 0.2
    rows.loc[failed, "predicted_p90_return"] = rows.loc[failed, "predicted_p50_return"] + 0.2
    rows.loc[failed, "outperform_probability"] = 1.0 - rows.loc[failed, "outperform_probability"]

    report = evaluate_one_shot_oos_gate(
        rows, _freeze(), evaluation_record_path=tmp_path / "failed-gate.json"
    )
    by_scope = {str(item["scope"]): item for item in report.markets}
    assert bool(by_scope["market:TWSE"]["passed"]) is True
    assert bool(by_scope["market:TPEx"]["passed"]) is False
    assert report.gate_passed is False
    assert report.publication_candidate_eligible is False
    assert report.publishable is False


def test_missing_market_and_ineligible_sample_fail_closed(tmp_path: Path) -> None:
    rows = _final_rows()
    missing_market = rows.loc[rows["market"].eq("TWSE")]
    report = evaluate_one_shot_oos_gate(
        missing_market, _freeze(),
        evaluation_record_path=tmp_path / "missing-market.json",
    )
    assert report.missing_markets == ["TPEx"]
    assert report.gate_passed is False

    rows.loc[rows["market"].eq("TPEx"), "industry_train_observations"] = 499
    report = evaluate_one_shot_oos_gate(
        rows, _freeze(), evaluation_record_path=tmp_path / "sample-failure.json"
    )
    tpex_industry = next(
        item for item in report.eligible_industries if item["scope"] == "industry:TPEx:31"
    )
    checks = tpex_industry["checks"]
    assert isinstance(checks, dict)
    assert checks["industry_train_sample_at_least_500"] is False
    assert report.gate_passed is False


def test_only_frozen_champion_and_one_evaluation_are_allowed(tmp_path: Path) -> None:
    rows = _final_rows()
    freeze = _freeze()
    record = tmp_path / "one-shot.json"
    report = evaluate_one_shot_oos_gate(
        rows, freeze, evaluation_record_path=record
    )

    with pytest.raises(ValueError, match="retest is forbidden"):
        evaluate_one_shot_oos_gate(
            rows, freeze, evaluation_record_path=record, prior_reports=[report]
        )
    wrong = rows.copy()
    wrong["candidate_id"] = "challenger"
    with pytest.raises(ValueError, match="frozen champion"):
        evaluate_one_shot_oos_gate(
            wrong, freeze, evaluation_record_path=tmp_path / "wrong.json"
        )
    refit = rows.copy()
    refit["baseline_frozen_through"] = "2022-01-01"
    with pytest.raises(ValueError, match="baseline was refit"):
        evaluate_one_shot_oos_gate(
            refit, freeze, evaluation_record_path=tmp_path / "refit.json"
        )
