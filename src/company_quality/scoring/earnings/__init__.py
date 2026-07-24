"""Non-publishable earnings quality and capital-efficiency diagnostics."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Sequence

from company_quality.facts.financial import CanonicalFinancialFact, CanonicalFinancialFacts

CycleFlag = Literal[
    "peak_margin",
    "trough_margin",
    "commodity_cycle",
    "construction_lumpiness",
    "none",
]
_ALLOWED_CYCLE_FLAGS = {
    "peak_margin",
    "trough_margin",
    "commodity_cycle",
    "construction_lumpiness",
    "none",
}


class EarningsMetricError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EarningsMetrics:
    roa: Decimal | None
    operating_cash_flow: Decimal | None
    accrual_ratio: Decimal | None
    gross_margin: Decimal | None
    asset_turnover: Decimal | None
    roic: Decimal | None
    free_cash_flow: Decimal | None


@dataclass(frozen=True, slots=True)
class NormalisedMetrics:
    roa_z: Decimal | None = None
    accrual_z: Decimal | None = None
    margin_z: Decimal | None = None
    turnover_z: Decimal | None = None
    roic_z: Decimal | None = None
    fcf_z: Decimal | None = None


@dataclass(frozen=True, slots=True)
class EarningsDiagnostics:
    roe: Decimal | None
    operating_margin: Decimal | None
    revenue_growth_yoy: Decimal | None
    net_income_growth_yoy: Decimal | None


@dataclass(frozen=True, slots=True)
class ForensicDiagnostics:
    piotroski_f_score: Decimal | None = None
    beneish_m_score: Decimal | None = None
    altman_z_score: Decimal | None = None


@dataclass(frozen=True, slots=True)
class EarningsCapitalEfficiencyCandidate:
    metrics: EarningsMetrics
    normalised_metrics: NormalisedMetrics
    diagnostics: EarningsDiagnostics
    forensic_diagnostics: ForensicDiagnostics
    cycle_flags: tuple[CycleFlag, ...]
    evidence_family_ids: tuple[str, ...]
    metric_lineage: dict[str, tuple[str, ...]]
    unavailable_reasons: dict[str, str]
    coverage: Decimal
    candidate_score: Decimal | None
    available_at: str
    publication_status: Literal["NON_PUBLISHABLE_CANDIDATE"] = (
        "NON_PUBLISHABLE_CANDIDATE"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["EarningsCapitalEfficiencyCandidate.v1"] = (
        "EarningsCapitalEfficiencyCandidate.v1"
    )
    source_version: Literal["CanonicalFinancialFacts.v1"] = (
        "CanonicalFinancialFacts.v1"
    )
    formula_version: Literal["single-quarter-earnings-efficiency.v1"] = (
        "single-quarter-earnings-efficiency.v1"
    )
    model_version: Literal["unscored-candidate.v1"] = "unscored-candidate.v1"


def _bundle_period(bundle: CanonicalFinancialFacts) -> date:
    if bundle.schema_version != "CanonicalFinancialFacts.v1":
        raise EarningsMetricError("expected CanonicalFinancialFacts.v1")
    if not bundle.facts:
        raise EarningsMetricError("canonical financial facts are required")
    ends = {fact.period_end for fact in bundle.facts}
    if len(ends) != 1:
        raise EarningsMetricError("one canonical bundle must contain one fiscal period")
    try:
        period = date.fromisoformat(next(iter(ends)))
    except ValueError as exc:
        raise EarningsMetricError("invalid canonical fiscal period") from exc
    if period.month not in (3, 6, 9, 12) or period.day != calendar.monthrange(
        period.year, period.month
    )[1]:
        raise EarningsMetricError("canonical period must be a quarter end")
    return period


def _previous_quarter(period: date) -> date:
    if period.month == 3:
        return date(period.year - 1, 12, 31)
    month = period.month - 3
    return date(period.year, month, calendar.monthrange(period.year, month)[1])


def _previous_year(period: date) -> date:
    return date(
        period.year - 1,
        period.month,
        calendar.monthrange(period.year - 1, period.month)[1],
    )


def _validate_facts(
    bundles: Sequence[CanonicalFinancialFacts],
) -> tuple[dict[date, dict[str, CanonicalFinancialFact]], str]:
    by_period: dict[date, dict[str, CanonicalFinancialFact]] = {}
    coordinates: set[tuple[str, int, int, int]] = set()
    available: list[datetime] = []
    for bundle in bundles:
        period = _bundle_period(bundle)
        if period in by_period:
            raise EarningsMetricError("duplicate canonical financial period")
        concepts: dict[str, CanonicalFinancialFact] = {}
        for fact in bundle.facts:
            if fact.concept_id in concepts:
                raise EarningsMetricError(
                    f"duplicate concept in fiscal period: {fact.concept_id}"
                )
            coordinate_values = (
                fact.source_table_index,
                fact.source_row_index,
                fact.source_column_index,
            )
            if any(value < 0 for value in coordinate_values):
                raise EarningsMetricError("source coordinates must be non-negative")
            coordinate = (fact.source_artifact_sha256, *coordinate_values)
            if coordinate in coordinates:
                raise EarningsMetricError("duplicate canonical source coordinate")
            coordinates.add(coordinate)
            if fact.unit != "TWD_thousands":
                raise EarningsMetricError("unsupported canonical financial unit")
            try:
                timestamp = datetime.fromisoformat(fact.available_at)
            except ValueError as exc:
                raise EarningsMetricError("invalid fact available_at") from exc
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise EarningsMetricError("fact available_at must be timezone-aware")
            available.append(timestamp)
            concepts[fact.concept_id] = fact
        by_period[period] = concepts
    if not by_period:
        raise EarningsMetricError("at least one canonical financial period is required")
    return by_period, max(available).isoformat()


def _value(
    concepts: dict[str, CanonicalFinancialFact] | None,
    concept: str,
) -> Decimal | None:
    if concepts is None or concept not in concepts:
        return None
    return concepts[concept].value


def _ids(*facts: CanonicalFinancialFact | None) -> tuple[str, ...]:
    return tuple(fact.fact_id for fact in facts if fact is not None)


def build_earnings_capital_efficiency_candidate(
    bundles: Sequence[CanonicalFinancialFacts],
    *,
    cycle_flags: tuple[CycleFlag, ...] = ("none",),
) -> EarningsCapitalEfficiencyCandidate:
    if not cycle_flags or len(cycle_flags) > 8 or len(set(cycle_flags)) != len(cycle_flags):
        raise EarningsMetricError("cycle flags must contain 1..8 unique values")
    if any(flag not in _ALLOWED_CYCLE_FLAGS for flag in cycle_flags):
        raise EarningsMetricError("unsupported cycle flag")
    if "none" in cycle_flags and len(cycle_flags) != 1:
        raise EarningsMetricError("cycle flag none is exclusive")

    periods, available_at = _validate_facts(bundles)
    current_period = max(periods)
    current = periods[current_period]
    prior = periods.get(_previous_quarter(current_period))
    prior_year = periods.get(_previous_year(current_period))
    reasons: dict[str, str] = {}
    lineage: dict[str, tuple[str, ...]] = {}

    def current_fact(concept: str) -> CanonicalFinancialFact | None:
        return current.get(concept)

    def prior_fact(concept: str) -> CanonicalFinancialFact | None:
        return None if prior is None else prior.get(concept)

    def prior_year_fact(concept: str) -> CanonicalFinancialFact | None:
        return None if prior_year is None else prior_year.get(concept)

    def average_balance(
        concept: str, metric: str, reason_name: str
    ) -> Decimal | None:
        current_value = _value(current, concept)
        previous_value = _value(prior, concept)
        lineage[metric] = _ids(current_fact(concept), prior_fact(concept))
        if current_value is None:
            reasons[metric] = f"missing_current_{reason_name}"
            return None
        if previous_value is None:
            reasons[metric] = f"missing_immediately_preceding_quarter_{reason_name}"
            return None
        average = (current_value + previous_value) / Decimal(2)
        if average <= 0:
            reasons[metric] = f"nonpositive_average_{reason_name}"
            return None
        return average

    def single_quarter_cash(concept: str, metric: str) -> Decimal | None:
        current_value = _value(current, concept)
        current_source = current_fact(concept)
        if current_value is None:
            suffix = "capex" if concept.endswith("acquisition_of_ppe") else "operating_cash_flow"
            reasons[metric] = f"missing_current_ytd_{suffix}"
            lineage[metric] = _ids(current_source)
            return None
        if current_period.month == 3:
            lineage[metric] = _ids(current_source)
            return current_value
        previous_value = _value(prior, concept)
        previous_source = prior_fact(concept)
        lineage[metric] = _ids(current_source, previous_source)
        if previous_value is None:
            suffix = "capex" if concept.endswith("acquisition_of_ppe") else "operating_cash_flow"
            reasons[metric] = f"missing_prior_ytd_{suffix}"
            return None
        return current_value - previous_value

    net_income = _value(current, "income.net_income")
    revenue = _value(current, "income.revenue")
    gross_profit = _value(current, "income.gross_profit")
    operating_income = _value(current, "income.operating_income")
    avg_assets = average_balance("balance.total_assets", "roa", "assets")
    asset_denominator_reason = reasons.get("roa")
    avg_equity = average_balance("balance.total_equity", "roe", "equity")
    operating_cash_flow = single_quarter_cash(
        "cash_flow.operating_cash_flow", "operating_cash_flow"
    )
    capex = single_quarter_cash("cash_flow.acquisition_of_ppe", "free_cash_flow")

    if net_income is None:
        roa = None
        reasons["roa"] = "missing_current_net_income"
    elif avg_assets is None:
        roa = None
    else:
        roa = net_income * Decimal(4) / avg_assets
        lineage["roa"] = _ids(
            current_fact("income.net_income"),
            current_fact("balance.total_assets"),
            prior_fact("balance.total_assets"),
        )

    if revenue is None:
        gross_margin = None
        reasons["gross_margin"] = "missing_current_revenue"
    elif revenue == 0:
        gross_margin = None
        reasons["gross_margin"] = "revenue_zero"
    elif gross_profit is None:
        gross_margin = None
        reasons["gross_margin"] = "missing_current_gross_profit"
    else:
        gross_margin = gross_profit / revenue
    lineage["gross_margin"] = _ids(
        current_fact("income.gross_profit"), current_fact("income.revenue")
    )

    if revenue is None:
        asset_turnover = None
        reasons["asset_turnover"] = "missing_current_revenue"
    elif avg_assets is None:
        asset_turnover = None
        reasons["asset_turnover"] = (
            asset_denominator_reason or "missing_average_assets"
        )
    else:
        asset_turnover = revenue * Decimal(4) / avg_assets
        lineage["asset_turnover"] = _ids(
            current_fact("income.revenue"),
            current_fact("balance.total_assets"),
            prior_fact("balance.total_assets"),
        )

    if net_income is None:
        accrual_ratio = None
        reasons["accrual_ratio"] = "missing_current_net_income"
    elif operating_cash_flow is None:
        accrual_ratio = None
        reasons["accrual_ratio"] = reasons["operating_cash_flow"]
    elif avg_assets is None:
        accrual_ratio = None
        reasons["accrual_ratio"] = (
            asset_denominator_reason or "missing_average_assets"
        )
    else:
        accrual_ratio = (net_income - operating_cash_flow) * Decimal(4) / avg_assets
        lineage["accrual_ratio"] = _ids(
            current_fact("income.net_income"),
            current_fact("cash_flow.operating_cash_flow"),
            prior_fact("cash_flow.operating_cash_flow"),
            current_fact("balance.total_assets"),
            prior_fact("balance.total_assets"),
        )

    if operating_cash_flow is None:
        free_cash_flow = None
        reasons["free_cash_flow"] = reasons["operating_cash_flow"]
    elif capex is None:
        free_cash_flow = None
    else:
        free_cash_flow = operating_cash_flow + capex
        lineage["free_cash_flow"] = tuple(dict.fromkeys(
            (*lineage.get("operating_cash_flow", ()), *lineage.get("free_cash_flow", ()))
        ))

    reasons["roic"] = "missing_nopat_and_invested_capital_authority"
    roic = None

    if net_income is None:
        roe = None
        reasons["roe"] = "missing_current_net_income"
    elif avg_equity is None:
        roe = None
    else:
        roe = net_income * Decimal(4) / avg_equity
        lineage["roe"] = _ids(
            current_fact("income.net_income"),
            current_fact("balance.total_equity"),
            prior_fact("balance.total_equity"),
        )

    if revenue is None:
        operating_margin = None
        reasons["operating_margin"] = "missing_current_revenue"
    elif revenue == 0:
        operating_margin = None
        reasons["operating_margin"] = "revenue_zero"
    elif operating_income is None:
        operating_margin = None
        reasons["operating_margin"] = "missing_current_operating_income"
    else:
        operating_margin = operating_income / revenue
    lineage["operating_margin"] = _ids(
        current_fact("income.operating_income"), current_fact("income.revenue")
    )

    def growth(concept: str, metric: str) -> Decimal | None:
        current_value = _value(current, concept)
        previous_value = _value(prior_year, concept)
        lineage[metric] = _ids(current_fact(concept), prior_year_fact(concept))
        if current_value is None:
            reasons[metric] = f"missing_current_{concept.split('.')[-1]}"
            return None
        if previous_value is None:
            reasons[metric] = f"missing_prior_year_{concept.split('.')[-1]}"
            return None
        if previous_value == 0:
            reasons[metric] = "prior_year_value_zero"
            return None
        return (current_value - previous_value) / abs(previous_value)

    revenue_growth = growth("income.revenue", "revenue_growth_yoy")
    net_income_growth = growth("income.net_income", "net_income_growth_yoy")

    for metric in (
        "roa_z", "accrual_z", "margin_z", "turnover_z", "roic_z", "fcf_z"
    ):
        reasons[metric] = "comparable_normalisation_not_calibrated"
    for metric in ("piotroski_f_score", "beneish_m_score", "altman_z_score"):
        reasons[metric] = "insufficient_model_specific_authority"
    reasons["candidate_score"] = "normalisation_and_subweights_not_calibrated"

    metrics = EarningsMetrics(
        roa=roa,
        operating_cash_flow=operating_cash_flow,
        accrual_ratio=accrual_ratio,
        gross_margin=gross_margin,
        asset_turnover=asset_turnover,
        roic=roic,
        free_cash_flow=free_cash_flow,
    )
    available_core = sum(value is not None for value in (
        metrics.roa,
        metrics.operating_cash_flow,
        metrics.accrual_ratio,
        metrics.gross_margin,
        metrics.asset_turnover,
        metrics.roic,
        metrics.free_cash_flow,
    ))
    return EarningsCapitalEfficiencyCandidate(
        metrics=metrics,
        normalised_metrics=NormalisedMetrics(),
        diagnostics=EarningsDiagnostics(
            roe=roe,
            operating_margin=operating_margin,
            revenue_growth_yoy=revenue_growth,
            net_income_growth_yoy=net_income_growth,
        ),
        forensic_diagnostics=ForensicDiagnostics(),
        cycle_flags=cycle_flags,
        evidence_family_ids=(
            "earnings_outcomes",
            "cash_conversion",
            "capital_efficiency",
        ),
        metric_lineage=lineage,
        unavailable_reasons=reasons,
        coverage=Decimal(available_core) / Decimal(7),
        candidate_score=None,
        available_at=available_at,
    )
