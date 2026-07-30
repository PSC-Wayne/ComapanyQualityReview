from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from company_quality.company_analysis.probability_calibration import (
    ProbabilityCalibrationError,
    calibrate_single_company_annual_base_rates,
)


def _series(values: dict[str, str], name: str) -> pd.Series:
    return pd.Series(
        {pd.Timestamp(day): Decimal(value) for day, value in values.items()},
        name=name,
        dtype="object",
    ).sort_index()


def _annual_series(*, include_final_oos: bool = False) -> tuple[pd.Series, pd.Series]:
    company: dict[str, str] = {}
    benchmark: dict[str, str] = {}
    company_value = Decimal("100")
    benchmark_value = Decimal("100")
    for year in range(2007, 2026):
        company[f"{year}-07-31"] = str(company_value)
        benchmark[f"{year}-07-31"] = str(benchmark_value)
        company_value *= Decimal("1.10") if year % 3 else Decimal("0.90")
        benchmark_value *= Decimal("1.05") if year % 4 else Decimal("0.95")
    if include_final_oos:
        company["2026-07-31"] = "99999"
        benchmark["2026-07-31"] = "1"
    return _series(company, "company"), _series(benchmark, "benchmark")


def test_calibrates_absolute_and_official_benchmark_probabilities() -> None:
    company, benchmark = _annual_series()

    report = calibrate_single_company_annual_base_rates(
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        company_total_return_wealth=company,
        official_benchmark_total_return=benchmark,
        season_month=7,
        final_oos_start=date(2026, 1, 1),
        minimum_observations=15,
        generated_at="2026-07-29T12:30:00+08:00",
        generation_id="2330-formal-calibration-v1",
    )

    assert report.status == "formal"
    assert len(report.observations) == 18
    assert report.observations[0].decision_date == "2007-07-31"
    assert report.observations[-1].result_end_date == "2025-07-31"
    assert report.positive_return.target == "positive_total_return"
    assert report.official_outperformance.target == "outperformed_official_market"
    assert report.positive_return.trials == 18
    assert report.positive_return.lower < report.positive_return.point < report.positive_return.upper
    assert report.positive_return.calibration_id != report.official_outperformance.calibration_id
    first = report.observations[0]
    assert first.official_excess_return == (
        first.actual_total_return - first.official_benchmark_return
    )
    assert first.positive_return is (first.actual_total_return > 0)
    assert first.outperformed_official_market is (first.official_excess_return > 0)


def test_final_oos_points_do_not_change_pre_oos_calibration() -> None:
    base_company, base_benchmark = _annual_series()
    future_company, future_benchmark = _annual_series(include_final_oos=True)
    kwargs = dict(
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        season_month=7,
        final_oos_start=date(2026, 1, 1),
        minimum_observations=15,
        generated_at="2026-07-29T12:30:00+08:00",
        generation_id="2330-formal-calibration-v1",
    )

    base = calibrate_single_company_annual_base_rates(
        company_total_return_wealth=base_company,
        official_benchmark_total_return=base_benchmark,
        **kwargs,
    )
    with_future = calibrate_single_company_annual_base_rates(
        company_total_return_wealth=future_company,
        official_benchmark_total_return=future_benchmark,
        **kwargs,
    )

    assert with_future.observations == base.observations
    assert with_future.positive_return == base.positive_return
    assert with_future.official_outperformance == base.official_outperformance
    assert with_future.ignored_final_oos_company_points == 1
    assert with_future.ignored_final_oos_benchmark_points == 1


def test_blocks_when_non_overlapping_history_is_too_short() -> None:
    company, benchmark = _annual_series()

    report = calibrate_single_company_annual_base_rates(
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        company_total_return_wealth=company.loc["2015":],
        official_benchmark_total_return=benchmark.loc["2015":],
        season_month=7,
        final_oos_start=date(2026, 1, 1),
        minimum_observations=15,
        generated_at="2026-07-29T12:30:00+08:00",
        generation_id="2330-formal-calibration-v1",
    )

    assert report.status == "data_insufficient"
    assert report.positive_return.point is None
    assert report.official_outperformance.point is None
    assert "minimum_observations" in report.failure_reasons


def test_rejects_invalid_wealth_or_market_contract() -> None:
    company, benchmark = _annual_series()
    company.iloc[0] = Decimal("0")

    with pytest.raises(ProbabilityCalibrationError, match="positive"):
        calibrate_single_company_annual_base_rates(
            issuer_id="22099131",
            security_code="2330",
            market="TWSE",
            company_total_return_wealth=company,
            official_benchmark_total_return=benchmark,
            season_month=7,
            final_oos_start=date(2026, 1, 1),
            minimum_observations=15,
            generated_at="2026-07-29T12:30:00+08:00",
            generation_id="2330-formal-calibration-v1",
        )
