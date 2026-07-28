from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker

from company_quality.lab.official_benchmarks import TWSE_TOTAL_RETURN_URL
from company_quality.lab.real_pre_oos_candidates import build_pre_oos_candidates
from company_quality.lab.real_upside import (
    build_upside_validation,
    to_research_upside_core_result,
)
from company_quality.research_snapshot import (
    DownsideCoreResult,
    QualityCoreResult,
    build_company_research_snapshot,
)


def _inputs():
    issuers = [f"issuer-{i:02d}" for i in range(12)]
    codes = [f"{1000 + i}" for i in range(12)]
    decisions = ["2020-06-30", "2021-06-30", "2022-06-30", "2023-06-30"]
    labels = pd.DataFrame([
        {
            "issuer_id": "issuer-shared" if rank < 2 else issuer,
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
            "official_benchmark_source_ref": TWSE_TOTAL_RETURN_URL,
            "generation_id": "generation-upside-test",
        }
        for decision in decisions
        for rank, (issuer, code) in enumerate(zip(issuers, codes, strict=True))
    ])
    features = pd.DataFrame([
        {
            "issuer_id": "issuer-shared" if index < 2 else issuer,
            "security_code": code,
            "market": "TWSE",
            "decision_date": decision,
            "metric_id": metric,
            "metric_value": float(index % 2) if metric == "roe_after_tax" else float(index),
            "metric_available_at": f"{decision}T12:00:00+08:00",
            "evidence_family_id": family,
        }
        for decision in decisions
        for index, (issuer, code) in enumerate(zip(issuers, codes, strict=True))
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
    valuation = pd.DataFrame([
        {
            "issuer_id": "issuer-shared" if rank < 2 else issuer,
            "security_code": code,
            "market": "TWSE",
            "decision_date": decision,
            "metric_id": metric,
            "metric_value": rank * 0.015 if metric == "earnings_yield" else 1.0,
            "metric_available_at": f"{decision}T12:00:00+08:00",
            "evidence_family_id": f"valuation:{metric}",
            "model_scope": "upside_only",
        }
        for decision in decisions
        for rank, (issuer, code) in enumerate(zip(issuers, codes, strict=True))
        for metric in ("earnings_yield", "book_yield")
    ])
    return labels, features, adjusted, valuation


def test_builds_separate_pit_upside_predictions_without_management_or_market_overlay() -> None:
    labels, features, adjusted, valuation = _inputs()
    predictions, report = build_upside_validation(
        labels,
        features,
        adjusted,
        valuation_features=valuation,
        producer_candidate_sha="a" * 64,
        input_artifact_shas={
            "T21_labels": "1" * 64,
            "real_features": "2" * 64,
            "adjusted_total_return": "3" * 64,
            "valuation_features": "4" * 64,
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
    assert predictions["star"].isna().all()
    challenger = report["valuation_challenger"]
    assert challenger["status"] == "research_only"
    assert "earnings_yield" in challenger["admitted_metric_ids"]
    assert "book_yield" in challenger["rejected_metric_ids"]
    assert set(challenger["earlier_holdout_dates"]) == set(
        predictions["decision_date"]
    )
    assert predictions["predicted_p10_return"].le(
        predictions["predicted_p50_return"]
    ).all()
    assert predictions["predicted_p50_return"].le(
        predictions["predicted_p90_return"]
    ).all()
    assert predictions["positive_return_probability"].between(0, 1).all()
    assert predictions["outperform_probability"].between(0, 1).all()
    shared = predictions.loc[predictions["issuer_id"].eq("issuer-shared")]
    assert set(shared["security_code"]) == {"1000", "1001"}
    assert "management_delivery_ratio" not in report["feature_ids"]
    assert {
        column.removeprefix("linear_feature_")
        for column in predictions
        if column.startswith("linear_feature_")
    } == set(cast(list[str], report["feature_ids"]))
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

    prediction = predictions.iloc[0]
    upside = to_research_upside_core_result(prediction, report)
    snapshot = build_company_research_snapshot(
        issuer_id=str(prediction["issuer_id"]),
        security_code=str(prediction["security_code"]),
        market="TWSE",
        generated_at="2026-07-27T12:00:00+00:00",
        input_source_versions={"upside": str(report["source_version"])},
        quality=QualityCoreResult(
            generation_id=upside.generation_id,
            status="research_only",
            score=None,
            confidence=None,
            model_version="quality-test.v1",
            data_as_of=upside.data_as_of,
        ),
        upside=upside,
        downside=DownsideCoreResult(
            generation_id=upside.generation_id,
            status="research_only",
            risk_score=None,
            faces=None,
            confidence=None,
            model_version="downside-test.v1",
            data_as_of=upside.data_as_of,
        ),
    )
    assert snapshot.upside.positive_return_probability is not None
    assert snapshot.upside.p10_return is not None
    assert snapshot.upside.p90_return is not None
    assert snapshot.upside.stars is None


def test_builds_two_same_observation_pre_oos_candidates_with_linear_features() -> None:
    labels, features, adjusted, valuation = _inputs()

    rows, report = build_pre_oos_candidates(
        labels,
        features,
        adjusted,
        valuation,
        producer_candidate_sha="a" * 64,
        input_artifact_shas={
            "T21_labels": "1" * 64,
            "real_features": "2" * 64,
            "adjusted_total_return": "3" * 64,
            "valuation_features": "4" * 64,
        },
        ridge_penalties=(10.0, 100.0),
    )

    assert report["candidate_count"] == 2
    assert set(rows["candidate_id"]) == {"ridge_penalty_10", "ridge_penalty_100"}
    assert any(column.startswith("linear_feature_") for column in rows)
    assert (pd.to_datetime(rows["trained_through"]) < pd.to_datetime(
        rows["decision_date"]
    )).all()
    counts = rows.groupby("candidate_id").size()
    assert counts.nunique() == 1
    model_versions = {
        str(item["model_version"])
        for item in cast(list[dict[str, object]], report["candidates"])
    }
    assert model_versions == {
        "train_only_ridge_residual_distribution.penalty_10.v1",
        "train_only_ridge_residual_distribution.penalty_100.v1",
    }
