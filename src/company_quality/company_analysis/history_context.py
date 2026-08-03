"""PIT historical, seasonality, business-model and guidance-hit context.

This module consumes already materialised, source-bound observations.  It does
not fetch, duplicate canonical financial facts, or turn a latest snapshot into
history.  Each axis reports coverage independently so one gap cannot erase a
completed axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from typing import Iterable, Literal, Sequence

ContextStatus = Literal["full", "partial", "unresolved"]
ContextAxis = Literal[
    "five_year_annual_audited",
    "twelve_quarters",
    "monthly_seasonality",
    "official_business_model",
    "guidance_hits",
]
BusinessAxis = Literal["business_model", "products_services", "customers", "end_markets"]
SourceKind = Literal[
    "official_historical_filing",
    "official_monthly_filing",
    "issuer_primary_filing",
    "current_snapshot",
]


class HistoryContextError(ValueError):
    """Raised for malformed or semantically unsafe context input."""


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise HistoryContextError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise HistoryContextError(f"{field} must be timezone-aware")
    return result


@dataclass(frozen=True, slots=True)
class HistoricalObservation:
    observation_id: str
    frequency: Literal["annual", "quarterly", "monthly"]
    period: str
    available_at: str
    evidence_id: str
    source_url: str
    source_kind: SourceKind
    period_basis: Literal["annual", "single_quarter", "single_month"]
    assurance: Literal["audit", "review", "unaudited"]
    value: Decimal | None = None
    yoy_percent: Decimal | None = None

    def __post_init__(self) -> None:
        if not all((self.observation_id, self.period, self.evidence_id, self.source_url)):
            raise HistoryContextError("historical observation requires identity and source")
        _instant(self.available_at, "available_at")
        expected = {
            "annual": "annual", "quarterly": "single_quarter", "monthly": "single_month"
        }[self.frequency]
        if self.period_basis != expected:
            raise HistoryContextError("frequency and period_basis mismatch")
        if self.frequency == "annual" and self.assurance != "audit":
            raise HistoryContextError("annual context requires audited filings")
        if self.frequency == "monthly" and self.value is None:
            raise HistoryContextError("monthly seasonality requires a revenue value")


@dataclass(frozen=True, slots=True)
class BusinessModelClaim:
    claim_id: str
    axis: BusinessAxis
    statement: str
    period: str
    available_at: str
    evidence_id: str
    source_url: str
    source_kind: SourceKind = "issuer_primary_filing"

    def __post_init__(self) -> None:
        if not all((self.claim_id, self.statement, self.period, self.evidence_id, self.source_url)):
            raise HistoryContextError("business claim requires statement, period and source")
        _instant(self.available_at, "business available_at")


@dataclass(frozen=True, slots=True)
class GuidanceRevision:
    guidance_id: str
    target_period: str
    metric_id: str
    period_basis: Literal["single_quarter", "annual", "single_month"]
    low: Decimal
    high: Decimal
    unit: str
    available_at: str
    evidence_id: str
    source_url: str
    source_kind: SourceKind = "issuer_primary_filing"
    revision_of: str | None = None

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise HistoryContextError("guidance low cannot exceed high")
        if not all((self.guidance_id, self.target_period, self.metric_id, self.unit, self.evidence_id, self.source_url)):
            raise HistoryContextError("guidance requires target, metric and original filing")
        _instant(self.available_at, "guidance available_at")
        if self.revision_of == self.guidance_id:
            raise HistoryContextError("guidance cannot revise itself")


@dataclass(frozen=True, slots=True)
class GuidanceActual:
    actual_id: str
    target_period: str
    metric_id: str
    period_basis: Literal["single_quarter", "annual", "single_month"]
    value: Decimal
    unit: str
    available_at: str
    evidence_id: str
    source_url: str
    source_kind: SourceKind = "official_historical_filing"

    def __post_init__(self) -> None:
        if not all((self.actual_id, self.target_period, self.metric_id, self.unit, self.evidence_id, self.source_url)):
            raise HistoryContextError("actual requires period, metric and filing")
        _instant(self.available_at, "actual available_at")


@dataclass(frozen=True, slots=True)
class AxisCoverage:
    axis: ContextAxis
    status: ContextStatus
    observed: int
    required: int
    periods: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    unresolved_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MonthlySeasonality:
    calendar_month: int
    observation_count: int
    average_revenue_index: Decimal
    median_yoy_percent: Decimal | None


@dataclass(frozen=True, slots=True)
class RevenueTurningPoint:
    period: str
    kind: Literal["acceleration", "deceleration"]
    prior_three_month_yoy: Decimal
    current_three_month_yoy: Decimal
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GuidanceHitRecord:
    guidance_id: str
    revision_of: str | None
    target_period: str
    metric_id: str
    period_basis: str
    guidance_low: Decimal
    guidance_high: Decimal
    actual_value: Decimal | None
    hit: bool | None
    guidance_available_at: str
    actual_available_at: str | None
    guidance_evidence_id: str
    actual_evidence_id: str | None
    guidance_source_url: str
    actual_source_url: str | None


@dataclass(frozen=True, slots=True)
class HistoricalContextAssessment:
    issuer_id: str
    as_of: str
    status: ContextStatus
    coverage: tuple[AxisCoverage, ...]
    seasonality: tuple[MonthlySeasonality, ...]
    turning_points: tuple[RevenueTurningPoint, ...]
    business_claims: tuple[BusinessModelClaim, ...]
    guidance_hits: tuple[GuidanceHitRecord, ...]
    schema_version: Literal["HistoricalContextAssessment.v1"] = "HistoricalContextAssessment.v1"

    def __post_init__(self) -> None:
        if not self.issuer_id:
            raise HistoryContextError("context requires issuer_id")
        expected = {
            "five_year_annual_audited", "twelve_quarters", "monthly_seasonality",
            "official_business_model", "guidance_hits",
        }
        if {item.axis for item in self.coverage} != expected:
            raise HistoryContextError("context must declare every independent axis")

    @property
    def by_axis(self) -> dict[str, AxisCoverage]:
        return {item.axis: item for item in self.coverage}


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _coverage(
    axis: ContextAxis, observed: int, required: int, periods: Iterable[str],
    evidence_ids: Iterable[str], reason: str,
) -> AxisCoverage:
    status: ContextStatus = "full" if observed >= required else "partial" if observed else "unresolved"
    return AxisCoverage(
        axis, status, observed, required, tuple(periods), _unique(evidence_ids),
        None if status == "full" else reason,
    )


def _month_number(period: str) -> int:
    try:
        month = int(period.rsplit("-", 1)[1])
    except (IndexError, ValueError) as exc:
        raise HistoryContextError(f"invalid monthly period: {period}") from exc
    if not 1 <= month <= 12:
        raise HistoryContextError(f"invalid monthly period: {period}")
    return month


def _seasonality(monthly: Sequence[HistoricalObservation]) -> tuple[MonthlySeasonality, ...]:
    if len(monthly) < 36:
        return ()
    overall = sum((item.value or Decimal(0) for item in monthly), Decimal(0)) / Decimal(len(monthly))
    if overall == 0:
        return ()
    rows: list[MonthlySeasonality] = []
    for month in range(1, 13):
        samples = [item for item in monthly if _month_number(item.period) == month]
        if not samples:
            continue
        average = sum((item.value or Decimal(0) for item in samples), Decimal(0)) / Decimal(len(samples))
        yoy = [item.yoy_percent for item in samples if item.yoy_percent is not None]
        rows.append(MonthlySeasonality(
            month, len(samples), (average / overall).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            Decimal(str(median(yoy))) if yoy else None,
        ))
    return tuple(rows)


def _turning_points(monthly: Sequence[HistoricalObservation]) -> tuple[RevenueTurningPoint, ...]:
    usable = [item for item in monthly if item.yoy_percent is not None]
    if len(usable) < 6:
        return ()
    rolling: list[tuple[HistoricalObservation, Decimal, tuple[str, ...]]] = []
    for index in range(2, len(usable)):
        window = usable[index - 2:index + 1]
        value = sum((item.yoy_percent or Decimal(0) for item in window), Decimal(0)) / Decimal(3)
        rolling.append((usable[index], value, tuple(item.evidence_id for item in window)))
    points: list[RevenueTurningPoint] = []
    for index in range(1, len(rolling)):
        previous_change = rolling[index - 1][1] - (rolling[index - 2][1] if index >= 2 else rolling[index - 1][1])
        current_change = rolling[index][1] - rolling[index - 1][1]
        if previous_change == 0 or current_change == 0 or (previous_change > 0) == (current_change > 0):
            continue
        item, current, evidence = rolling[index]
        points.append(RevenueTurningPoint(
            item.period, "acceleration" if current_change > 0 else "deceleration",
            rolling[index - 1][1].quantize(Decimal("0.0001")),
            current.quantize(Decimal("0.0001")), _unique((*rolling[index - 1][2], *evidence)),
        ))
    return tuple(points)


def build_historical_context(
    *,
    issuer_id: str,
    as_of: str,
    observations: Sequence[HistoricalObservation],
    business_claims: Sequence[BusinessModelClaim] = (),
    guidance: Sequence[GuidanceRevision] = (),
    actuals: Sequence[GuidanceActual] = (),
) -> HistoricalContextAssessment:
    """Build deterministic context using only evidence available at ``as_of``."""

    if not issuer_id:
        raise HistoryContextError("context requires issuer_id")
    cutoff = _instant(as_of, "as_of")
    eligible_observations = tuple(sorted(
        (item for item in observations if _instant(item.available_at, "available_at") <= cutoff and item.source_kind != "current_snapshot"),
        key=lambda item: (item.frequency, item.period, _instant(item.available_at, "available_at"), item.observation_id),
    ))
    # A corrected filing available by the decision time supersedes an earlier
    # version for calculation, while its evidence ID remains explicit.  This
    # prevents duplicate period rows from biasing seasonality or coverage.
    latest_by_period = {
        (item.frequency, item.period): item for item in eligible_observations
    }
    admitted_observations = tuple(sorted(
        latest_by_period.values(), key=lambda item: (item.period, item.observation_id)
    ))
    admitted_business = tuple(sorted(
        (item for item in business_claims if _instant(item.available_at, "available_at") <= cutoff and item.source_kind == "issuer_primary_filing"),
        key=lambda item: (item.axis, item.period, item.claim_id),
    ))
    admitted_guidance = tuple(sorted(
        (item for item in guidance if _instant(item.available_at, "available_at") <= cutoff and item.source_kind == "issuer_primary_filing"),
        key=lambda item: (item.target_period, item.metric_id, item.available_at, item.guidance_id),
    ))
    admitted_actuals = tuple(
        item for item in actuals
        if _instant(item.available_at, "available_at") <= cutoff and item.source_kind != "current_snapshot"
    )

    annual = tuple(item for item in admitted_observations if item.frequency == "annual" and item.source_kind == "official_historical_filing")
    quarterly = tuple(item for item in admitted_observations if item.frequency == "quarterly" and item.source_kind == "official_historical_filing")
    monthly = tuple(
        item for item in admitted_observations
        if item.frequency == "monthly" and item.source_kind == "official_monthly_filing"
    )[-60:]
    axes_present = {item.axis for item in admitted_business}

    if len({item.guidance_id for item in admitted_guidance}) != len(admitted_guidance):
        raise HistoryContextError("duplicate guidance_id")
    actual_index: dict[tuple[str, str, str, str], GuidanceActual] = {}
    for item in admitted_actuals:
        key = (item.target_period, item.metric_id, item.period_basis, item.unit)
        if key in actual_index:
            raise HistoryContextError("duplicate guidance actual coordinate")
        actual_index[key] = item
    hit_rows: list[GuidanceHitRecord] = []
    for item in admitted_guidance:
        actual = actual_index.get((item.target_period, item.metric_id, item.period_basis, item.unit))
        hit_rows.append(GuidanceHitRecord(
            guidance_id=item.guidance_id, revision_of=item.revision_of,
            target_period=item.target_period, metric_id=item.metric_id,
            period_basis=item.period_basis, guidance_low=item.low, guidance_high=item.high,
            actual_value=actual.value if actual else None,
            hit=item.low <= actual.value <= item.high if actual else None,
            guidance_available_at=item.available_at,
            actual_available_at=actual.available_at if actual else None,
            guidance_evidence_id=item.evidence_id,
            actual_evidence_id=actual.evidence_id if actual else None,
            guidance_source_url=item.source_url,
            actual_source_url=actual.source_url if actual else None,
        ))
    completed_periods = {item.target_period for item in hit_rows if item.actual_value is not None}
    guidance_evidence = _unique(
        evidence for item in hit_rows
        for evidence in (item.guidance_evidence_id, item.actual_evidence_id or "")
    )

    coverage = (
        _coverage("five_year_annual_audited", len({x.period for x in annual}), 5,
                  (x.period for x in annual), (x.evidence_id for x in annual),
                  "至少需要5個不同年度的官方查核申報；current/latest snapshot不可代替歷史。"),
        _coverage("twelve_quarters", len({x.period for x in quarterly}), 12,
                  (x.period for x in quarterly), (x.evidence_id for x in quarterly),
                  "至少需要12個不同季度的官方歷史申報。"),
        _coverage("monthly_seasonality", len({x.period for x in monthly}), 36,
                  (x.period for x in monthly), (x.evidence_id for x in monthly),
                  "至少需要36個有發布時間的月營收觀察；目標為36至60個月。"),
        _coverage("official_business_model", len(axes_present), 4,
                  (x.period for x in admitted_business), (x.evidence_id for x in admitted_business),
                  "官方商業模式、產品／服務、客戶與終端市場必須逐軸取得。"),
        _coverage("guidance_hits", len(completed_periods), 2,
                  sorted(completed_periods), guidance_evidence,
                  "至少需要2個目標期間的正式guidance對Actual，並保留修正與原始申報。"),
    )
    status: ContextStatus = (
        "full" if all(item.status == "full" for item in coverage)
        else "unresolved" if all(item.status == "unresolved" for item in coverage)
        else "partial"
    )
    return HistoricalContextAssessment(
        issuer_id=issuer_id, as_of=as_of, status=status, coverage=coverage,
        seasonality=_seasonality(monthly), turning_points=_turning_points(monthly),
        business_claims=admitted_business, guidance_hits=tuple(hit_rows),
    )


def build_bundle_history_context(bundle: object) -> HistoricalContextAssessment:
    """Minimal shared hook for existing bundle history; qualitative axes stay honest gaps."""

    observations: list[HistoricalObservation] = []
    for period in getattr(bundle, "periods", ()):
        financial = getattr(period, "financial", None)
        if financial is None:
            continue
        artifacts = tuple(getattr(financial, "artifacts", ()))
        if not artifacts:
            continue
        evidence = artifacts[0]
        audit = getattr(period, "audit", None)
        if getattr(period, "is_annual", False) and audit is not None and getattr(audit, "pdf_path", None) is not None:
            observations.append(HistoricalObservation(
                f"annual:{period.period}", "annual", period.period,
                audit.available_at, audit.evidence_ids[0], audit.pdf_source_url,
                "official_historical_filing", "annual", "audit",
            ))
        observations.append(HistoricalObservation(
            f"quarter:{period.period}", "quarterly", period.period,
            evidence.available_at, evidence.artifact_id, evidence.official_url,
            "official_historical_filing", "single_quarter", "review",
        ))
    for item in getattr(bundle, "monthly_revenue", ()):
        observations.append(HistoricalObservation(
            f"month:{item.month}", "monthly", item.month, item.available_at,
            item.artifact_id, item.official_url, "official_monthly_filing",
            "single_month", "unaudited", item.revenue_thousand_twd, item.yoy_percent,
        ))
    return build_historical_context(
        issuer_id=getattr(getattr(bundle, "identity"), "issuer_id"),
        as_of=getattr(getattr(bundle, "request"), "as_of"), observations=observations
    )


__all__ = [
    "AxisCoverage", "BusinessModelClaim", "GuidanceActual", "GuidanceHitRecord",
    "GuidanceRevision", "HistoricalContextAssessment", "HistoricalObservation",
    "HistoryContextError", "MonthlySeasonality", "RevenueTurningPoint",
    "build_bundle_history_context", "build_historical_context",
]
