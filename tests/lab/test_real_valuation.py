from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from company_quality.lab.real_valuation import build_pit_valuation_features


def _wide(path: Path, dates: list[str], values: dict[str, list[float]]) -> None:
    frame = pd.DataFrame({"date": pd.to_datetime(dates), **values})
    if path.suffix == ".feather":
        frame.to_feather(path)
    else:
        frame.to_pickle(path)


def test_builds_pit_upside_only_valuation_and_excludes_financial_fcf(tmp_path: Path) -> None:
    decision = "2021-01-10"
    labels = pd.DataFrame([
        {"issuer_id": "issuer-2330", "security_code": "2330", "market": "TWSE", "decision_date": decision, "generation_id": "g1", "official_industry": "半導體業", "industry_available_at": "2020-01-01"},
        {"issuer_id": "issuer-6488", "security_code": "6488", "market": "TPEx", "decision_date": decision, "generation_id": "g1", "official_industry": "半導體業", "industry_available_at": "2020-01-01"},
        {"issuer_id": "issuer-2881", "security_code": "2881", "market": "TWSE", "decision_date": decision, "generation_id": "g1", "official_industry": "金融保險業", "industry_available_at": "2020-01-01"},
        {"issuer_id": "issuer-9999", "security_code": "9999", "market": "TWSE", "decision_date": decision, "generation_id": "g1"},
    ])
    _wide(
        tmp_path / "price_earning_ratio#本益比.pickle",
        ["2021-01-09", "2021-01-11"],
        {"2330 台積電": [20, 5], "6488 環球晶": [40, 5], "2881 富邦金": [10, 5], "2881 富邦金*": [11, 5]},
    )
    _wide(
        tmp_path / "price_earning_ratio#股價淨值比.feather",
        ["2021-01-09", "2021-01-11"],
        {"2330 台積電": [5, 1], "6488 環球晶": [10, 1], "2881 富邦金": [1.5, 1]},
    )
    _wide(
        tmp_path / "fundamental_features#自由現金流量.feather",
        ["2020-11-14", "2021-01-11"],
        {"2330": [100_000, 9_999_999], "6488": [50_000, 9_999_999], "2881": [-80_000, 9_999_999]},
    )
    revenue_dates = pd.date_range("2020-02-10", periods=12, freq="MS") + pd.Timedelta(days=9)
    _wide(
        tmp_path / "monthly_revenue#當月營收.pickle",
        [item.date().isoformat() for item in revenue_dates],
        {"2330 台積電": [10_000] * 12, "6488 環球晶": [5_000] * 12, "2881 富邦金": [8_000] * 12},
    )
    _wide(
        tmp_path / "etl#market_value.feather",
        ["2021-01-09", "2021-01-11"],
        {"2330": [1_000_000_000, 1], "6488": [1_000_000_000, 1], "2881": [1_000_000_000, 1]},
    )
    pd.DataFrame([
        {"stock_id": "2330", "name": "台積電", "category": "半導體業", "market": "sii"},
        {"stock_id": "6488", "name": "環球晶", "category": "半導體業", "market": "otc"},
        {"stock_id": "2881", "name": "富邦金", "category": "金融保險業", "market": "sii"},
    ]).to_feather(tmp_path / "security_categories.feather")

    features, report = build_pit_valuation_features(tmp_path, labels)

    assert set(features["model_scope"]) == {"upside_only"}
    assert not features["evidence_family_id"].str.startswith(("technical:", "chip:")).any()
    earnings = features.loc[
        (features["security_code"] == "2330")
        & (features["metric_id"] == "earnings_yield")
    ].iloc[0]
    assert earnings.metric_value == pytest.approx(0.05)
    assert earnings.metric_available_at.startswith("2021-01-09")
    relative = features.loc[
        (features["security_code"] == "2330")
        & (features["metric_id"] == "industry_relative_earnings_yield")
    ].iloc[0]
    assert relative.metric_value == pytest.approx(1.0)
    financial_earnings = features.loc[
        (features["security_code"] == "2881")
        & (features["metric_id"] == "earnings_yield")
    ].iloc[0]
    assert pd.isna(financial_earnings.metric_value)
    assert financial_earnings.unavailable_reason == "conflicting_alias_values"
    financial_fcf = features.loc[
        (features["security_code"] == "2881")
        & (features["metric_id"] == "free_cash_flow_yield")
    ].iloc[0]
    assert pd.isna(financial_fcf.metric_value)
    assert financial_fcf.unavailable_reason == "not_applicable_financial_industry"
    missing_industry = features.loc[
        (features["security_code"] == "9999")
        & (features["metric_id"] == "industry_relative_book_yield")
    ].iloc[0]
    assert pd.isna(missing_industry.metric_value)
    assert missing_industry.unavailable_reason == "pit_industry_unavailable"
    assert report["status"] == "research_only"
    assert report["pit_industry_missing_observation_count"] == 1
    assert report["financial_fcf_exclusion_count"] == 1
