"""Formal single-company 12-month empirical probability calibration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from typing import Literal

import pandas as pd


class ProbabilityCalibrationError(RuntimeError):
    pass


Target = Literal["positive_total_return", "outperformed_official_market"]
Status = Literal["formal", "data_insufficient"]
_Q = Decimal("0.000001")
_WILSON_Z_90 = Decimal("1.6448536269514722")


@dataclass(frozen=True, slots=True)
class AnnualReturnObservation:
    decision_date: str
    result_end_date: str
    company_baseline_date: str
    company_result_date: str
    benchmark_baseline_date: str
    benchmark_result_date: str
    actual_total_return: Decimal
    official_benchmark_return: Decimal
    official_excess_return: Decimal
    positive_return: bool
    outperformed_official_market: bool


@dataclass(frozen=True, slots=True)
class EmpiricalProbabilityCalibration:
    target: Target
    successes: int
    trials: int
    point: Decimal | None
    lower: Decimal | None
    upper: Decimal | None
    confidence_level: Decimal | None
    calibration_id: str | None
    method: Literal["season-matched-non-overlapping-wilson-90.v1"] = (
        "season-matched-non-overlapping-wilson-90.v1"
    )


@dataclass(frozen=True, slots=True)
class SingleCompanyProbabilityCalibration:
    issuer_id: str
    security_code: str
    market: Literal["TWSE"]
    season_month: int
    final_oos_start: str
    observations: tuple[AnnualReturnObservation, ...]
    positive_return: EmpiricalProbabilityCalibration
    official_outperformance: EmpiricalProbabilityCalibration
    minimum_observations: int
    status: Status
    failure_reasons: dict[str, str]
    ignored_final_oos_company_points: int
    ignored_final_oos_benchmark_points: int
    company_source_ref: str
    official_benchmark_source_ref: str
    generated_at: str
    generation_id: str
    schema_version: Literal["SingleCompanyProbabilityCalibration.v1"] = (
        "SingleCompanyProbabilityCalibration.v1"
    )
    formula_version: Literal["calendar-month-last-valid-12m-total-return.v1"] = (
        "calendar-month-last-valid-12m-total-return.v1"
    )
    model_version: Literal["empirical-base-rate-no-feature-model.v1"] = (
        "empirical-base-rate-no-feature-model.v1"
    )


def _validate_text(value: str, field: str, maximum: int = 256) -> str:
    text = value.strip()
    if not text or len(text) > maximum:
        raise ProbabilityCalibrationError(f"invalid {field}")
    return text


def _validate_instant(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProbabilityCalibrationError("invalid generated_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProbabilityCalibrationError("generated_at must be timezone-aware")


def _normalise_series(series: pd.Series, field: str) -> pd.Series:
    if not isinstance(series, pd.Series) or series.empty:
        raise ProbabilityCalibrationError(f"{field} series required")
    if series.index.has_duplicates:
        raise ProbabilityCalibrationError(f"duplicate {field} date")
    converted: dict[pd.Timestamp, Decimal] = {}
    for raw_day, raw_value in series.items():
        day = pd.Timestamp(raw_day).normalize()
        if pd.isna(raw_value):
            continue
        try:
            value = Decimal(str(raw_value))
        except Exception as exc:
            raise ProbabilityCalibrationError(f"invalid {field} value") from exc
        if not value.is_finite() or value <= 0:
            raise ProbabilityCalibrationError(f"{field} wealth must be positive")
        converted[day] = value
    if not converted:
        raise ProbabilityCalibrationError(f"{field} series has no valid points")
    return pd.Series(converted, dtype="object", name=field).sort_index()


def _last_point(series: pd.Series, year: int, month: int) -> tuple[pd.Timestamp, Decimal] | None:
    mask = (series.index.year == year) & (series.index.month == month)
    selected = series.loc[mask]
    if selected.empty:
        return None
    day = selected.index[-1]
    return day, Decimal(str(selected.iloc[-1]))


def _return(end: Decimal, start: Decimal) -> Decimal:
    return (end / start - Decimal("1")).quantize(_Q, rounding=ROUND_HALF_UP)


def _calibration_id(
    target: Target, observations: tuple[AnnualReturnObservation, ...]
) -> str:
    labels = [
        {
            "decision_date": item.decision_date,
            "result_end_date": item.result_end_date,
            "outcome": (
                item.positive_return
                if target == "positive_total_return"
                else item.outperformed_official_market
            ),
        }
        for item in observations
    ]
    payload = {
        "target": target,
        "labels": labels,
        "method": "season-matched-non-overlapping-wilson-90.v1",
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"scpc-{target}-{digest[:24]}"


def _wilson(
    target: Target,
    outcomes: tuple[bool, ...],
    observations: tuple[AnnualReturnObservation, ...],
    *,
    minimum_observations: int,
) -> EmpiricalProbabilityCalibration:
    trials = len(outcomes)
    successes = sum(outcomes)
    if trials < minimum_observations:
        return EmpiricalProbabilityCalibration(
            target, successes, trials, None, None, None, None, None
        )
    count = Decimal(trials)
    point = Decimal(successes) / count
    z2 = _WILSON_Z_90 * _WILSON_Z_90
    denominator = Decimal("1") + z2 / count
    center = (point + z2 / (Decimal("2") * count)) / denominator
    radicand = (
        point * (Decimal("1") - point) / count
        + z2 / (Decimal("4") * count * count)
    )
    half = _WILSON_Z_90 * radicand.sqrt() / denominator
    return EmpiricalProbabilityCalibration(
        target=target,
        successes=successes,
        trials=trials,
        point=point.quantize(_Q, rounding=ROUND_HALF_UP),
        lower=max(Decimal("0"), center - half).quantize(_Q, rounding=ROUND_HALF_UP),
        upper=min(Decimal("1"), center + half).quantize(_Q, rounding=ROUND_HALF_UP),
        confidence_level=Decimal("0.90"),
        calibration_id=_calibration_id(target, observations),
    )


def calibrate_single_company_annual_base_rates(
    *,
    issuer_id: str,
    security_code: str,
    market: Literal["TWSE"],
    company_total_return_wealth: pd.Series,
    official_benchmark_total_return: pd.Series,
    season_month: int,
    final_oos_start: date,
    minimum_observations: int,
    generated_at: str,
    generation_id: str,
    company_source_ref: str = "FinLab:etl:adj_close",
    official_benchmark_source_ref: str = (
        "https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U"
    ),
) -> SingleCompanyProbabilityCalibration:
    """Calibrate non-overlapping 12-month historical base rates.

    The function intentionally ignores every input point on or after ``final_oos_start``.
    It estimates a season-matched empirical base rate; it is not a feature model and does
    not blend evidence-derived research judgments into the formal probability.
    """

    _validate_text(issuer_id, "issuer_id", 64)
    _validate_text(security_code, "security_code", 16)
    _validate_text(generation_id, "generation_id", 128)
    _validate_text(company_source_ref, "company_source_ref", 512)
    _validate_text(official_benchmark_source_ref, "official_benchmark_source_ref", 512)
    _validate_instant(generated_at)
    if market != "TWSE":
        raise ProbabilityCalibrationError("unsupported market benchmark")
    if not 1 <= season_month <= 12:
        raise ProbabilityCalibrationError("season_month must be 1..12")
    if minimum_observations < 1:
        raise ProbabilityCalibrationError("minimum_observations must be positive")

    company_all = _normalise_series(company_total_return_wealth, "company")
    benchmark_all = _normalise_series(
        official_benchmark_total_return, "official benchmark"
    )
    cutoff = pd.Timestamp(final_oos_start)
    ignored_company = int((company_all.index >= cutoff).sum())
    ignored_benchmark = int((benchmark_all.index >= cutoff).sum())
    company = company_all.loc[company_all.index < cutoff]
    benchmark = benchmark_all.loc[benchmark_all.index < cutoff]
    if company.empty or benchmark.empty:
        raise ProbabilityCalibrationError("no pre-OOS wealth points")

    first_year = max(int(company.index.year.min()), int(benchmark.index.year.min()))
    last_result_year = min(int(company.index.year.max()), int(benchmark.index.year.max()))
    observations: list[AnnualReturnObservation] = []
    for year in range(first_year, last_result_year):
        company_start = _last_point(company, year, season_month)
        company_end = _last_point(company, year + 1, season_month)
        benchmark_start = _last_point(benchmark, year, season_month)
        benchmark_end = _last_point(benchmark, year + 1, season_month)
        if None in (company_start, company_end, benchmark_start, benchmark_end):
            continue
        assert company_start is not None
        assert company_end is not None
        assert benchmark_start is not None
        assert benchmark_end is not None
        actual = _return(company_end[1], company_start[1])
        official = _return(benchmark_end[1], benchmark_start[1])
        excess = (actual - official).quantize(_Q, rounding=ROUND_HALF_UP)
        decision_day = date(year, season_month, 1)
        result_day = date(year + 1, season_month, 1)
        decision_calendar_end = (
            decision_day + pd.offsets.MonthEnd(1)
        ).date().isoformat()
        result_calendar_end = (result_day + pd.offsets.MonthEnd(1)).date().isoformat()
        observations.append(
            AnnualReturnObservation(
                decision_date=decision_calendar_end,
                result_end_date=result_calendar_end,
                company_baseline_date=company_start[0].date().isoformat(),
                company_result_date=company_end[0].date().isoformat(),
                benchmark_baseline_date=benchmark_start[0].date().isoformat(),
                benchmark_result_date=benchmark_end[0].date().isoformat(),
                actual_total_return=actual,
                official_benchmark_return=official,
                official_excess_return=excess,
                positive_return=actual > 0,
                outperformed_official_market=excess > 0,
            )
        )
    rows = tuple(observations)
    positive = _wilson(
        "positive_total_return",
        tuple(item.positive_return for item in rows),
        rows,
        minimum_observations=minimum_observations,
    )
    outperformance = _wilson(
        "outperformed_official_market",
        tuple(item.outperformed_official_market for item in rows),
        rows,
        minimum_observations=minimum_observations,
    )
    status: Status = (
        "formal" if len(rows) >= minimum_observations else "data_insufficient"
    )
    failures = (
        {}
        if status == "formal"
        else {
            "minimum_observations": (
                f"requires {minimum_observations} non-overlapping labels; got {len(rows)}"
            )
        }
    )
    return SingleCompanyProbabilityCalibration(
        issuer_id=issuer_id,
        security_code=security_code,
        market=market,
        season_month=season_month,
        final_oos_start=final_oos_start.isoformat(),
        observations=rows,
        positive_return=positive,
        official_outperformance=outperformance,
        minimum_observations=minimum_observations,
        status=status,
        failure_reasons=failures,
        ignored_final_oos_company_points=ignored_company,
        ignored_final_oos_benchmark_points=ignored_benchmark,
        company_source_ref=company_source_ref,
        official_benchmark_source_ref=official_benchmark_source_ref,
        generated_at=generated_at,
        generation_id=generation_id,
    )
