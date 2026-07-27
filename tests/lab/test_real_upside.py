from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker

from company_quality.lab.real_upside import build_upside_validation


def _inputs():
    issuers = [f"issuer-{i:02d}" for i in range(12)]
    codes = [f"{1000 + i}" for i in range(12)]
    decisions = ["2020-06-30", "2021-06-30", "2022-06-30", "2023-06-30"]
    labels = pd.DataFrame([
        {
            "issuer_id": issuer,
            "security_code": code,
            "market": "TWSE",
            "decision_date": decision,
            "fully_observed": True,
            "actual_total_return": 0.01 + rank * 0.015,
            "official_benchmark_return": 0.08,
            "official_excess_return": 0.01 + rank * 0.015 - 0.08,
            "same_market_median_return": 0.0925,
            "positive_return": True,
            "outperformed_official_market": 0.01 + rank * 0.015 > 0.08,
            "result_end_date": f"{int(decision[:4]) + 1}{decision[4:]}",
            "official_benchmark_source_ref": (
                "https://openapi.twse.com.tw/v1/indicesReport/MFI94U"
            ),
            "generation_id": "generation-upside-test",
        }
        for decision in decisions
        for rank, (issuer, code) in enumerate(zip(issuers, codes, strict=True))
    ])
    features = pd.DataFrame([
        {
            "issuer_id": issuer,
            "decision_date": decision,
            "metric_id": metric,
            "metric_value": float(index + (1 if metric == "roe_after_tax" else 0)),
            "metric_available_at": f"{decision}T12:00:00+08:00",
            "evidence_family_id": family,
        }
        for decision in decisions
        for index, issuer in enumerate(issuers)
        for metric, family in (
            ("roe_after_tax", "earnings_outcomes"),
            ("management_delivery_ratio", "people:management_delivery"),
        )
    ])
    index = pd.date_range("2019-06-28", "2024-07-01", freq="B")
    adjusted = pd.DataFrame(index=index)
    elapsed = np.arange(len(index)) / 252
    for rank, code in enumerate(codes):
        adjusted[code] = 100 * np.exp((0.01 + rank * 0.015) * elapsed)
    return labels, features, adjusted


def test_builds_separate_pit_upside_predictions_without_management_or_market_overlay() -> None:
    labels, features, adjusted = _inputs()
    predictions, report = build_upside_validation(
        labels,
        features,
        adjusted,
        producer_candidate_sha="a" * 64,
        input_artifact_shas={
            "T21_labels": "1" * 64,
            "real_features": "2" * 64,
            "adjusted_total_return": "3" * 64,
        },
    )

    assert report["schema_version"] == "UpsidePotentialValidationReport.v1"
    assert report["publishable"] is False
    assert report["rating_disposition"] == "NO_RATING_NOT_APPLICABLE"
    assert report["prediction_target"] == "12m_adjusted_total_return"
    assert report["benchmark"] == "official_market_total_return_index"
    assert report["secondary_benchmark"] == "same_market_decision_date_median_return"
    assert report["excluded_feature_families"] == [
        "management_delivery",
        "management_continuity",
        "succession_planning",
        "technical",
        "chip",
    ]
    assert report["holdout_observation_count"] == len(predictions)
    assert report["holdout_observation_count"] > 0
    assert set(predictions["star"]) <= {1, 2, 3, 4, 5}
    assert predictions["predicted_p10_return"].le(
        predictions["predicted_p50_return"]
    ).all()
    assert predictions["predicted_p50_return"].le(
        predictions["predicted_p90_return"]
    ).all()
    assert predictions["positive_return_probability"].between(0, 1).all()
    assert predictions["outperform_probability"].between(0, 1).all()
    assert "management_delivery_ratio" not in report["feature_ids"]
    assert report["temporal_windows"]
    assert all(
        date.fromisoformat(window["train_end"])
        < date.fromisoformat(window["holdout_start"])
        for window in report["temporal_windows"]
    )
    schema = json.loads(Path(
        "src/company_quality/lab/contracts/UpsidePotentialValidationReport.schema.json"
    ).read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
