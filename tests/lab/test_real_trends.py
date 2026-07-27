from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from company_quality.lab.real_trends import (
    build_pit_trend_features,
    validate_three_model_trends,
)


def _wide(path: Path, dates: list[str], values: dict[str, list[float]]) -> None:
    frame = pd.DataFrame({"date": pd.to_datetime(dates), **values})
    if path.suffix == ".feather":
        frame.to_feather(path)
    else:
        frame.to_pickle(path)


def test_builds_pit_shared_facts_and_distinct_three_model_transforms(
    tmp_path: Path,
) -> None:
    decision = "2021-01-10"
    labels = pd.DataFrame([{
        "issuer_id": "issuer-2330",
        "security_code": "2330",
        "market": "TWSE",
        "decision_date": decision,
        "generation_id": "g1",
        "official_industry": "半導體業",
        "industry_available_at": "2020-01-01",
    }])
    quarterly_dates = [
        "2019-03-31", "2019-06-30", "2019-09-30", "2019-12-31",
        "2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31",
        "2021-03-31",
    ]
    paths = {
        "營業毛利率": [1, 2, 3, 4, 5, 6, 7, 8, 999],
        "營業利益率": [2, 3, 4, 5, 6, 7, 8, 9, 999],
        "ROE稅後": [3, 4, 5, 6, 7, 8, 9, 10, 999],
        "自由現金流量": [100, 110, 120, 130, 150, 170, 190, 210, 999999],
        "負債比率": [50, 49, 48, 47, 46, 45, 44, 43, 1],
        "流動比率": [100, 105, 110, 115, 120, 125, 130, 135, 999],
    }
    for name, values in paths.items():
        _wide(
            tmp_path / f"fundamental_features#{name}.feather",
            quarterly_dates,
            {"2330 台積電": values},
        )
    revenue_dates = pd.date_range("2019-07-01", periods=20, freq="MS") + pd.Timedelta(days=9)
    revenue_values = [100.0] * 12 + [110, 112, 114, 120, 130, 140, 150, 9999]
    _wide(
        tmp_path / "monthly_revenue#當月營收.pickle",
        [item.date().isoformat() for item in revenue_dates],
        {"2330 台積電": revenue_values},
    )

    features, report = build_pit_trend_features(tmp_path, labels)

    raw = features.loc[features["model_scope"] == "shared_raw"]
    assert set(raw["metric_id"]) == {
        "revenue_acceleration",
        "gross_margin_trend",
        "operating_margin_trend",
        "roe_trend",
        "cash_flow_conversion_trend",
        "free_cash_flow_trend",
        "debt_ratio_improvement",
        "liquidity_improvement",
    }
    gross = raw.loc[raw["metric_id"] == "gross_margin_trend"].iloc[0]
    assert gross.metric_value == pytest.approx(4.0)
    assert gross.metric_available_at.startswith("2020-12-31")
    conversion = raw.loc[raw["metric_id"] == "cash_flow_conversion_trend"].iloc[0]
    assert pd.isna(conversion.metric_value)
    assert conversion.unavailable_reason == "missing_operating_cash_flow_or_net_income_authority"
    upside = features.loc[
        (features["model_scope"] == "upside_only")
        & (features["metric_id"] == "upside__gross_margin_trend__trend")
    ].iloc[0]
    downside = features.loc[
        (features["model_scope"] == "downside_only")
        & (features["metric_id"] == "downside__gross_margin_trend__deterioration")
    ].iloc[0]
    assert upside.metric_value == pytest.approx(4.0)
    assert downside.metric_value == pytest.approx(0.0)
    assert report["model_scopes"] == ["quality_only", "upside_only", "downside_only"]
    assert "management_delivery" in report["excluded_feature_families"]


def _validation_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = ["2020-06-30", "2021-06-30", "2022-06-30", "2023-06-30"]
    labels: list[dict[str, object]] = []
    base: list[dict[str, object]] = []
    trends: list[dict[str, object]] = []
    for decision in dates:
        for index in range(12):
            issuer = f"issuer-{index:02d}"
            rank = index / 11
            labels.append({
                "issuer_id": issuer,
                "security_code": f"{1000 + index}",
                "market": "TWSE",
                "decision_date": decision,
                "generation_id": "g1",
                "adverse_outcome": index >= 8,
                "actual_total_return": rank,
            })
            base.append({
                "issuer_id": issuer,
                "decision_date": decision,
                "metric_id": "base_noise",
                "metric_value": float(index % 2),
                "metric_available_at": f"{decision}T12:00:00",
                "evidence_family_id": "earnings_outcomes",
            })
            signals = {
                "quality_only": 1.0 - rank,
                "upside_only": rank,
                "downside_only": rank,
            }
            for scope, signal in signals.items():
                prefix = scope.removesuffix("_only")
                suffix = "deterioration" if scope == "downside_only" else "trend"
                metrics = {
                    f"{prefix}__signal__{suffix}": signal,
                    f"{prefix}__constant__{suffix}": 1.0,
                    f"{prefix}__sparse_a__{suffix}": rank if index < 3 else None,
                    f"{prefix}__sparse_b__{suffix}": rank if index < 3 else None,
                    f"{prefix}__sparse_c__{suffix}": rank if index < 3 else None,
                }
                for metric_id, value in metrics.items():
                    trends.append({
                        "issuer_id": issuer,
                        "decision_date": decision,
                        "model_scope": scope,
                        "metric_id": metric_id,
                        "metric_value": value,
                        "metric_available_at": f"{decision}T12:00:00" if value is not None else None,
                        "evidence_family_id": f"financial_trend:{prefix}",
                    })
    return pd.DataFrame(labels), pd.DataFrame(base), pd.DataFrame(trends)


def test_three_models_ablate_independently_and_missingness_suppresses() -> None:
    labels, base, trends = _validation_inputs()

    predictions, report = validate_three_model_trends(labels, base, trends)

    models = {item["model_scope"]: item for item in report["models"]}
    assert set(models) == {"quality_only", "upside_only", "downside_only"}
    for scope, model in models.items():
        prefix = scope.removesuffix("_only")
        suffix = "deterioration" if scope == "downside_only" else "trend"
        assert f"{prefix}__signal__{suffix}" in model["admitted_metric_ids"]
        assert f"{prefix}__constant__{suffix}" in model["rejected_metric_ids"]
        assert model["suppressed_observation_count"] >= 1
    assert report["training_imputation"] == (
        "per_window_training_median_with_missing_indicator"
    )
    assert predictions.loc[
        predictions["result_status"] == "data_insufficient", "predicted_target"
    ].isna().all()
    metric_sets = [
        set(item["admitted_metric_ids"]) | set(item["rejected_metric_ids"])
        for item in models.values()
    ]
    assert metric_sets[0].isdisjoint(metric_sets[1])
    assert metric_sets[0].isdisjoint(metric_sets[2])
    assert metric_sets[1].isdisjoint(metric_sets[2])
