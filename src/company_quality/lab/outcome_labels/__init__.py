"""Corporate-action adjusted wealth and 12/24/36-month outcome labels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import calendar
import re
from typing import Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from company_quality.lab.cohort import AdverseControlCohort


class OutcomeLabelError(RuntimeError):
    pass


AdverseLabel = Literal[
    "drawdown_over_50", "forced_delisting", "default", "fraud",
    "restatement", "other_material_adverse",
]


@dataclass(frozen=True, slots=True)
class DailyClose:
    effective_on: str
    unadjusted_close: Decimal
    available_at: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorporateAction:
    effective_on: str
    share_multiplier: Decimal
    cash_per_pre_action_share: Decimal
    terminal_cash: bool
    available_at: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuspensionInterval:
    start_on: str
    end_on: str | None
    available_at: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GovernedOutcomeEvent:
    effective_on: str
    adverse_label: AdverseLabel
    official_reason: str
    available_at: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PITWealthInput:
    issuer_id: str
    wealth_series_ref: str
    daily_closes: tuple[DailyClose, ...]
    corporate_actions: tuple[CorporateAction, ...]
    suspension_intervals: tuple[SuspensionInterval, ...]
    unresolved_missing_dates: tuple[str, ...]
    governed_events: tuple[GovernedOutcomeEvent, ...]
    complete_through: str
    evidence_ids: tuple[str, ...]
    price_basis: Literal[
        "unadjusted_close_with_actions", "pre_adjusted_total_return"
    ] = "unadjusted_close_with_actions"
    schema_version: Literal["PITWealthInput.v1"] = "PITWealthInput.v1"


@dataclass(frozen=True, slots=True)
class DrawdownEpisode:
    peak_date: str
    trough_date: str
    recovery_date: str | None
    maximum_drawdown_pct: Decimal
    duration_days: int
    recovered: bool


@dataclass(frozen=True, slots=True)
class WealthPoint:
    effective_on: str
    adjusted_wealth_index: Decimal


@dataclass(frozen=True, slots=True)
class OfficialTotalReturnPoint:
    effective_on: str
    value: Decimal
    available_at: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OfficialMarketTotalReturnInput:
    market: Literal["TWSE", "TPEx"]
    series_ref: str
    points: tuple[OfficialTotalReturnPoint, ...]
    complete_through: str
    evidence_ids: tuple[str, ...]
    schema_version: Literal["OfficialMarketTotalReturnInput.v1"] = (
        "OfficialMarketTotalReturnInput.v1"
    )


@dataclass(frozen=True, slots=True)
class TwelveMonthReturnLabel:
    generation_id: str
    market: Literal["TWSE", "TPEx"] | None
    decision_date: str
    result_end_date: str
    actual_total_return: Decimal | None
    official_benchmark_return: Decimal | None
    official_excess_return: Decimal | None
    same_market_median_return: Decimal | None
    positive_return: bool | None
    outperformed_official_market: bool | None
    company_total_return_source_ref: str
    official_benchmark_source_ref: str | None
    same_market_median_source_ref: str | None
    status: Literal["complete", "blocked_missing_authority"]
    evidence_ids: tuple[str, ...]
    schema_version: Literal["TwelveMonthReturnLabel.v1"] = (
        "TwelveMonthReturnLabel.v1"
    )


@dataclass(frozen=True, slots=True)
class HorizonOutcome:
    horizon_months: Literal[12, 24, 36]
    drawdown_episodes: tuple[DrawdownEpisode, ...]
    adverse_labels: tuple[AdverseLabel, ...]
    censoring_state: Literal[
        "fully_observed", "right_censored", "blocked_missing_authority"
    ]
    label_version: str
    label_coverage: Decimal
    failure_reasons: dict[str, str]


@dataclass(frozen=True, slots=True)
class OutcomeLabelSet:
    issuer_id: str
    decision_time: str
    wealth_series_ref: str
    adjusted_wealth_series: tuple[WealthPoint, ...]
    drawdown_episodes: tuple[DrawdownEpisode, ...]
    adverse_labels: tuple[AdverseLabel, ...]
    horizon_months: Literal[12]
    twelve_month_return: TwelveMonthReturnLabel
    censoring_state: Literal[
        "fully_observed", "right_censored", "blocked_missing_authority"
    ]
    label_version: str
    label_coverage: Decimal
    sensitivity_outcomes: tuple[HorizonOutcome, HorizonOutcome]
    adjustment_evidence_ids: tuple[str, ...]
    failure_reasons: dict[str, str]
    input_producer_shas: dict[str, str]
    available_at: str
    generation_id: str
    producer_candidate_sha: str
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["OutcomeLabelSet.v1"] = "OutcomeLabelSet.v1"
    source_version: Literal[
        "AdverseControlCohort.v1+PITWealthInput.v1+OfficialMarketTotalReturnInput.v1"
    ] = "AdverseControlCohort.v1+PITWealthInput.v1+OfficialMarketTotalReturnInput.v1"
    formula_version: Literal[
        "unadjusted-close-action-cash-total-return.v1",
        "pre-adjusted-total-return-series.v1",
    ] = "unadjusted-close-action-cash-total-return.v1"
    model_version: Literal["deterministic-outcome-labels-no-calibration.v1"] = (
        "deterministic-outcome-labels-no-calibration.v1"
    )


_SHA = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_TAIPEI = ZoneInfo("Asia/Taipei")
_Q = Decimal("0.000001")


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise OutcomeLabelError(f"invalid {field}") from exc


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OutcomeLabelError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise OutcomeLabelError(f"{field} must be timezone-aware")
    return result


def add_calendar_months_clamped(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _drawdowns(points: Sequence[tuple[date, Decimal]]) -> tuple[DrawdownEpisode, ...]:
    if not points:
        return ()
    peak_date, peak = points[0]
    trough_date, trough = points[0]
    in_episode = False
    episodes: list[DrawdownEpisode] = []
    for current_date, wealth in points[1:]:
        if wealth >= peak:
            if in_episode:
                episodes.append(DrawdownEpisode(
                    peak_date=peak_date.isoformat(),
                    trough_date=trough_date.isoformat(),
                    recovery_date=current_date.isoformat(),
                    maximum_drawdown_pct=(
                        (trough / peak - Decimal("1")) * Decimal("100")
                    ).quantize(_Q, rounding=ROUND_HALF_UP),
                    duration_days=(current_date - peak_date).days,
                    recovered=True,
                ))
            if wealth > peak:
                peak = wealth
                peak_date = current_date
            trough = wealth
            trough_date = current_date
            in_episode = False
        else:
            if not in_episode:
                trough = wealth
                trough_date = current_date
                in_episode = True
            elif wealth < trough:
                trough = wealth
                trough_date = current_date
    if in_episode:
        last_date = points[-1][0]
        episodes.append(DrawdownEpisode(
            peak_date=peak_date.isoformat(),
            trough_date=trough_date.isoformat(),
            recovery_date=None,
            maximum_drawdown_pct=(
                (trough / peak - Decimal("1")) * Decimal("100")
            ).quantize(_Q, rounding=ROUND_HALF_UP),
            duration_days=(last_date - peak_date).days,
            recovered=False,
        ))
    if len(episodes) > 128:
        raise OutcomeLabelError("drawdown episode count exceeds contract")
    return tuple(episodes)


def _validate_input(
    cohort: AdverseControlCohort,
    wealth_input: PITWealthInput,
    issuer_id: str,
    decision_time: str,
    producer_shas: Mapping[str, str],
) -> tuple[date, datetime]:
    if cohort.schema_version != "AdverseControlCohort.v1":
        raise OutcomeLabelError("BLOCKED_CONTRACT: T20 schema mismatch")
    if wealth_input.schema_version != "PITWealthInput.v1":
        raise OutcomeLabelError("BLOCKED_CONTRACT: wealth schema mismatch")
    if wealth_input.price_basis == "pre_adjusted_total_return":
        if wealth_input.corporate_actions:
            raise OutcomeLabelError(
                "pre-adjusted total-return input forbids additional corporate actions"
            )
    elif wealth_input.price_basis != "unadjusted_close_with_actions":
        raise OutcomeLabelError("unsupported wealth price basis")
    if issuer_id not in cohort.issuer_ids or wealth_input.issuer_id != issuer_id:
        raise OutcomeLabelError("issuer is not admitted by T20 cohort")
    if not 1 <= len(issuer_id) <= 64:
        raise OutcomeLabelError("issuer_id outside output contract")
    if set(producer_shas) != {"T20", "PITWealthInput"} or any(
        not _SHA.fullmatch(value) for value in producer_shas.values()
    ):
        raise OutcomeLabelError("BLOCKED_CONTRACT: exact input producer SHAs required")
    decision = _instant(decision_time, "decision_time")
    cohort_asof = _instant(cohort.cohort_asof, "cohort_asof")
    if decision > cohort_asof:
        raise OutcomeLabelError("decision_time exceeds cohort PIT boundary")
    decision_date = decision.astimezone(_TAIPEI).date()
    if not wealth_input.wealth_series_ref or len(wealth_input.wealth_series_ref) > 256:
        raise OutcomeLabelError("invalid wealth_series_ref")
    if not wealth_input.evidence_ids:
        raise OutcomeLabelError("wealth input requires evidence")
    return decision_date, cohort_asof


def _horizon(
    wealth_input: PITWealthInput,
    *,
    decision_date: date,
    cohort_asof: datetime,
    horizon_months: Literal[12, 24, 36],
    base_label_version: str,
) -> tuple[
    HorizonOutcome, tuple[str, ...], list[datetime], tuple[WealthPoint, ...]
]:
    end = add_calendar_months_clamped(decision_date, horizon_months)
    complete_through = _day(wealth_input.complete_through, "complete_through")
    if complete_through > cohort_asof.astimezone(_TAIPEI).date():
        raise OutcomeLabelError("complete_through breaches cohort PIT boundary")
    closes: dict[date, DailyClose] = {}
    evidence: list[str] = list(wealth_input.evidence_ids)
    available: list[datetime] = []
    for row in wealth_input.daily_closes:
        day = _day(row.effective_on, "close effective_on")
        if day > complete_through:
            raise OutcomeLabelError("close exceeds complete_through")
        if day in closes:
            raise OutcomeLabelError("duplicate daily close")
        if row.unadjusted_close <= 0 or not row.evidence_ids:
            raise OutcomeLabelError("invalid unadjusted close/evidence")
        stamp = _instant(row.available_at, "close available_at")
        if stamp > cohort_asof:
            raise OutcomeLabelError("close breaches cohort PIT boundary")
        closes[day] = row
        evidence.extend(row.evidence_ids)
        available.append(stamp)
    baselines = [day for day in closes if day <= decision_date]
    if not baselines:
        failure = {"wealth": "missing_baseline_close"}
        return HorizonOutcome(
            horizon_months, (), (), "blocked_missing_authority",
            f"{base_label_version}-h{horizon_months}", Decimal("0"), failure,
        ), tuple(dict.fromkeys(evidence)), available, ()
    baseline_day = max(baselines)
    previous_close = closes[baseline_day].unadjusted_close
    wealth = Decimal("100")
    points: list[tuple[date, Decimal]] = [(baseline_day, wealth)]

    actions: dict[date, list[CorporateAction]] = {}
    terminal_date: date | None = None
    for action in wealth_input.corporate_actions:
        day = _day(action.effective_on, "action effective_on")
        if day > complete_through:
            raise OutcomeLabelError("corporate action exceeds complete_through")
        if action.share_multiplier <= 0 or action.cash_per_pre_action_share < 0:
            raise OutcomeLabelError("invalid corporate action terms")
        if not action.evidence_ids:
            raise OutcomeLabelError("corporate action requires evidence")
        stamp = _instant(action.available_at, "action available_at")
        if stamp > cohort_asof:
            raise OutcomeLabelError("corporate action breaches cohort PIT boundary")
        actions.setdefault(day, []).append(action)
        evidence.extend(action.evidence_ids)
        available.append(stamp)
    if any(len(day_actions) > 1 for day_actions in actions.values()):
        raise OutcomeLabelError("multiple same-day actions require ordered authority")

    for interval in wealth_input.suspension_intervals:
        start = _day(interval.start_on, "suspension start_on")
        finish = (
            _day(interval.end_on, "suspension end_on")
            if interval.end_on is not None else None
        )
        if finish is not None and finish < start:
            raise OutcomeLabelError("suspension ends before it starts")
        if not interval.evidence_ids:
            raise OutcomeLabelError("suspension requires authority evidence")
        stamp = _instant(interval.available_at, "suspension available_at")
        if stamp > cohort_asof:
            raise OutcomeLabelError("suspension breaches cohort PIT boundary")
        evidence.extend(interval.evidence_ids)
        available.append(stamp)

    missing = {
        _day(value, "unresolved_missing_date")
        for value in wealth_input.unresolved_missing_dates
    }
    if len(missing) != len(wealth_input.unresolved_missing_dates):
        raise OutcomeLabelError("duplicate unresolved missing date")
    relevant_missing = sorted(
        day for day in missing if decision_date < day <= end
    )
    failure_reasons: dict[str, str] = {}
    blocked = bool(relevant_missing)
    if blocked:
        failure_reasons["wealth"] = "unresolved_event_price_or_action_authority"

    timeline = sorted(
        day for day in set(closes) | set(actions)
        if baseline_day < day <= end
    )
    for day in timeline:
        day_actions = actions.get(day, [])
        terminal = [action for action in day_actions if action.terminal_cash]
        nonterminal = [action for action in day_actions if not action.terminal_cash]
        if terminal and (nonterminal or len(terminal) != 1):
            raise OutcomeLabelError("ambiguous terminal corporate action")
        if terminal:
            terminal_action = terminal[0]
            if terminal_action.cash_per_pre_action_share <= 0:
                raise OutcomeLabelError("terminal action requires cash consideration")
            wealth *= terminal_action.cash_per_pre_action_share / previous_close
            points.append((day, wealth))
            terminal_date = day
            break
        close = closes.get(day)
        if close is None:
            if day_actions:
                blocked = True
                failure_reasons["wealth"] = "action_date_close_unresolved"
            continue
        multiplier = Decimal("1")
        cash = Decimal("0")
        for action in day_actions:
            multiplier *= action.share_multiplier
            cash += action.cash_per_pre_action_share
        wealth *= (close.unadjusted_close * multiplier + cash) / previous_close
        previous_close = close.unadjusted_close
        points.append((day, wealth))

    episodes = _drawdowns(points)
    labels: list[AdverseLabel] = []
    if any(item.maximum_drawdown_pct < Decimal("-50") for item in episodes):
        labels.append("drawdown_over_50")
    for event in wealth_input.governed_events:
        event_day = _day(event.effective_on, "event effective_on")
        if event_day > cohort_asof.astimezone(_TAIPEI).date():
            raise OutcomeLabelError("outcome event exceeds cohort PIT boundary")
        stamp = _instant(event.available_at, "event available_at")
        if stamp > cohort_asof:
            raise OutcomeLabelError("outcome event breaches cohort PIT boundary")
        if not event.official_reason.strip() or not event.evidence_ids:
            raise OutcomeLabelError("outcome event requires authority evidence/reason")
        evidence.extend(event.evidence_ids)
        available.append(stamp)
        if decision_date < event_day <= end and event.adverse_label not in labels:
            labels.append(event.adverse_label)

    if blocked:
        censoring = "blocked_missing_authority"
        coverage = Decimal("0")
    elif terminal_date is not None or complete_through >= end:
        censoring = "fully_observed"
        coverage = Decimal("1")
    else:
        censoring = "right_censored"
        observed_end = max(
            (day for day, _ in points if day <= complete_through),
            default=decision_date,
        )
        denominator = max((end - decision_date).days, 1)
        coverage = min(
            Decimal("1"),
            Decimal(max((observed_end - decision_date).days, 0)) / Decimal(denominator),
        )
    outcome = HorizonOutcome(
        horizon_months=horizon_months,
        drawdown_episodes=episodes,
        adverse_labels=tuple(labels),
        censoring_state=censoring,
        label_version=f"{base_label_version}-h{horizon_months}",
        label_coverage=coverage,
        failure_reasons=failure_reasons,
    )
    wealth_points = tuple(
        WealthPoint(day.isoformat(), value.quantize(_Q, rounding=ROUND_HALF_UP))
        for day, value in points
    )
    return outcome, tuple(dict.fromkeys(evidence)), available, wealth_points


def _twelve_month_return_label(
    *,
    decision_date: date,
    generation_id: str,
    cohort_asof: datetime,
    headline: HorizonOutcome,
    adjusted_wealth_series: tuple[WealthPoint, ...],
    wealth_series_ref: str,
    market: Literal["TWSE", "TPEx"] | None,
    official: OfficialMarketTotalReturnInput | None,
    same_market_median_return: Decimal | None,
    same_market_median_source_ref: str | None,
    company_evidence_ids: tuple[str, ...],
) -> tuple[TwelveMonthReturnLabel, list[datetime]]:
    end = add_calendar_months_clamped(decision_date, 12)

    def blocked(
        official_ref: str | None = None,
        evidence_ids: tuple[str, ...] = company_evidence_ids,
    ) -> TwelveMonthReturnLabel:
        return TwelveMonthReturnLabel(
            generation_id=generation_id,
            market=market,
            decision_date=decision_date.isoformat(),
            result_end_date=end.isoformat(),
            actual_total_return=None,
            official_benchmark_return=None,
            official_excess_return=None,
            same_market_median_return=None,
            positive_return=None,
            outperformed_official_market=None,
            company_total_return_source_ref=wealth_series_ref,
            official_benchmark_source_ref=official_ref,
            same_market_median_source_ref=None,
            status="blocked_missing_authority",
            evidence_ids=evidence_ids,
        )

    if same_market_median_return is not None and not same_market_median_source_ref:
        raise OutcomeLabelError("same-market median source required")
    if market is None or official is None or headline.censoring_state != "fully_observed":
        return blocked(None if official is None else official.series_ref), []
    if official.schema_version != "OfficialMarketTotalReturnInput.v1":
        raise OutcomeLabelError("BLOCKED_CONTRACT: official benchmark schema mismatch")
    if official.market != market:
        raise OutcomeLabelError("official benchmark market mismatch")
    if not official.series_ref or not official.evidence_ids:
        raise OutcomeLabelError("official benchmark source/evidence required")
    if _day(official.complete_through, "official benchmark complete_through") < end:
        return blocked(official.series_ref), []

    official_points: dict[date, OfficialTotalReturnPoint] = {}
    official_available: list[datetime] = []
    official_evidence = list(official.evidence_ids)
    for point in official.points:
        day = _day(point.effective_on, "official benchmark effective_on")
        if day > end:
            continue
        if day in official_points:
            raise OutcomeLabelError("duplicate official benchmark point")
        if point.value <= 0 or not point.evidence_ids:
            raise OutcomeLabelError("invalid official benchmark point")
        available_at = _instant(point.available_at, "official benchmark available_at")
        if available_at > cohort_asof:
            raise OutcomeLabelError("official benchmark breaches cohort PIT boundary")
        official_points[day] = point
        official_available.append(available_at)
        official_evidence.extend(point.evidence_ids)

    company_points = {
        _day(point.effective_on, "company wealth effective_on"): point.adjusted_wealth_index
        for point in adjusted_wealth_series
    }
    company_start_days = [day for day in company_points if day <= decision_date]
    company_end_days = [day for day in company_points if day <= end]
    official_start_days = [day for day in official_points if day <= decision_date]
    official_end_days = [day for day in official_points if day <= end]
    if not all((company_start_days, company_end_days, official_start_days, official_end_days)):
        evidence = tuple(dict.fromkeys([*company_evidence_ids, *official_evidence]))
        return blocked(official.series_ref, evidence), official_available

    company_start = company_points[max(company_start_days)]
    company_end = company_points[max(company_end_days)]
    official_start = official_points[max(official_start_days)].value
    official_end = official_points[max(official_end_days)].value
    actual = (company_end / company_start - Decimal("1")).quantize(
        _Q, rounding=ROUND_HALF_UP
    )
    benchmark = (official_end / official_start - Decimal("1")).quantize(
        _Q, rounding=ROUND_HALF_UP
    )
    excess = (actual - benchmark).quantize(_Q, rounding=ROUND_HALF_UP)
    median = (
        same_market_median_return.quantize(_Q, rounding=ROUND_HALF_UP)
        if same_market_median_return is not None
        else None
    )
    evidence = tuple(dict.fromkeys([
        *company_evidence_ids,
        *official_evidence,
        *(() if same_market_median_source_ref is None else (same_market_median_source_ref,)),
    ]))
    return TwelveMonthReturnLabel(
        generation_id=generation_id,
        market=market,
        decision_date=decision_date.isoformat(),
        result_end_date=end.isoformat(),
        actual_total_return=actual,
        official_benchmark_return=benchmark,
        official_excess_return=excess,
        same_market_median_return=median,
        positive_return=actual > 0,
        outperformed_official_market=excess > 0,
        company_total_return_source_ref=wealth_series_ref,
        official_benchmark_source_ref=official.series_ref,
        same_market_median_source_ref=same_market_median_source_ref,
        status="complete",
        evidence_ids=evidence,
    ), official_available


def build_outcome_label_set(
    cohort: AdverseControlCohort,
    wealth_input: PITWealthInput,
    *,
    issuer_id: str,
    decision_time: str,
    base_label_version: str,
    producer_shas: Mapping[str, str],
    generation_id: str,
    producer_candidate_sha: str,
    market: Literal["TWSE", "TPEx"] | None = None,
    official_market_total_return: OfficialMarketTotalReturnInput | None = None,
    same_market_median_return: Decimal | None = None,
    same_market_median_source_ref: str | None = None,
) -> OutcomeLabelSet:
    if not _SEMVER.fullmatch(base_label_version):
        raise OutcomeLabelError("base label version must be semver")
    if not generation_id or not _SHA.fullmatch(producer_candidate_sha):
        raise OutcomeLabelError("generation and producer candidate SHA required")
    decision_date, cohort_asof = _validate_input(
        cohort, wealth_input, issuer_id, decision_time, producer_shas
    )
    outcomes: list[HorizonOutcome] = []
    evidence: list[str] = []
    available: list[datetime] = []
    adjusted_wealth_series: tuple[WealthPoint, ...] = ()
    for horizon in (12, 24, 36):
        outcome, outcome_evidence, outcome_available, wealth_points = _horizon(
            wealth_input,
            decision_date=decision_date,
            cohort_asof=cohort_asof,
            horizon_months=horizon,
            base_label_version=base_label_version,
        )
        outcomes.append(outcome)
        evidence.extend(outcome_evidence)
        available.extend(outcome_available)
        if horizon == 36:
            adjusted_wealth_series = wealth_points
    headline = outcomes[0]
    if not evidence or not available or not adjusted_wealth_series:
        raise OutcomeLabelError("no admitted wealth authority")
    adjustment_evidence_ids = tuple(dict.fromkeys(evidence))
    if len(adjustment_evidence_ids) > 10000:
        raise OutcomeLabelError("adjustment evidence exceeds contract")
    twelve_month_return, benchmark_available = _twelve_month_return_label(
        decision_date=decision_date,
        generation_id=generation_id,
        cohort_asof=cohort_asof,
        headline=headline,
        adjusted_wealth_series=adjusted_wealth_series,
        wealth_series_ref=wealth_input.wealth_series_ref,
        market=market,
        official=official_market_total_return,
        same_market_median_return=same_market_median_return,
        same_market_median_source_ref=same_market_median_source_ref,
        company_evidence_ids=adjustment_evidence_ids,
    )
    available.extend(benchmark_available)
    return OutcomeLabelSet(
        issuer_id=issuer_id,
        decision_time=decision_time,
        wealth_series_ref="OutcomeLabelSet.adjusted_wealth_series",
        adjusted_wealth_series=adjusted_wealth_series,
        drawdown_episodes=headline.drawdown_episodes,
        adverse_labels=headline.adverse_labels,
        horizon_months=12,
        twelve_month_return=twelve_month_return,
        censoring_state=headline.censoring_state,
        label_version=headline.label_version,
        label_coverage=headline.label_coverage,
        sensitivity_outcomes=(outcomes[1], outcomes[2]),
        adjustment_evidence_ids=adjustment_evidence_ids,
        failure_reasons=dict(headline.failure_reasons),
        input_producer_shas=dict(sorted(producer_shas.items())),
        available_at=max(available).isoformat(),
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
        formula_version=(
            "pre-adjusted-total-return-series.v1"
            if wealth_input.price_basis == "pre_adjusted_total_return"
            else "unadjusted-close-action-cash-total-return.v1"
        ),
    )


__all__ = [
    "CorporateAction", "DailyClose", "GovernedOutcomeEvent",
    "OfficialMarketTotalReturnInput", "OfficialTotalReturnPoint",
    "OutcomeLabelError", "OutcomeLabelSet", "PITWealthInput", "SuspensionInterval",
    "TwelveMonthReturnLabel", "add_calendar_months_clamped", "build_outcome_label_set",
]
