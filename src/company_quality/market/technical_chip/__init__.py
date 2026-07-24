"""Deterministic, point-in-time technical and chip-market overlay."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal, Mapping, Sequence, cast
from zoneinfo import ZoneInfo

from company_quality.pit import AdmittedFactSet, FactAdmission

_TWSE_DAILY_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_TAIPEI = ZoneInfo("Asia/Taipei")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RELEVANT_TYPES = {
    "market.daily_bar",
    "market.cash_distribution",
    "market.capital_action",
    "chip.foreign_net",
    "chip.dealer_net",
    "chip.investment_trust_net",
    "chip.margin_balance",
    "chip.insider_holding_change",
    "chip.pledge_change",
    "chip.tdcc_band",
    "chip.tdcc_distribution_complete",
}
_PERSON_TYPES = {
    "director", "supervisor", "manager", "major_shareholder", "other_insider"
}
_STATES = {"present", "missing", "not_applicable"}
PersonType = Literal[
    "director", "supervisor", "manager", "major_shareholder", "other_insider"
]
EvidenceState = Literal["present", "missing", "not_applicable"]


class TechnicalChipError(RuntimeError):
    """Raised when the overlay cannot be produced without guessing."""


@dataclass(frozen=True, slots=True)
class MarketAuthority:
    source_id: str
    authority_type: Literal["official"]
    url: str
    content_sha256: str
    available_at: str
    retrieved_at: str


@dataclass(frozen=True, slots=True)
class AuthorityRecord:
    source_id: str
    authority_type: Literal["official"]
    url: str
    content_sha256: str
    available_at: str
    retrieved_at: str
    used: bool


@dataclass(frozen=True, slots=True)
class TechnicalSignals:
    return_1m: Decimal | None
    return_2m: Decimal | None
    ma20_gap: Decimal | None
    ma60_gap: Decimal | None
    volatility_20d: Decimal | None


@dataclass(frozen=True, slots=True)
class PriceBar:
    date: str
    adjusted_open: Decimal
    adjusted_high: Decimal
    adjusted_low: Decimal
    adjusted_close: Decimal
    volume: Decimal
    evidence_id: str


@dataclass(frozen=True, slots=True)
class ChipSignals:
    foreign_net_20d: Decimal | None
    dealer_net_20d: Decimal | None
    investment_trust_net_20d: Decimal | None
    margin_balance_change: Decimal | None


@dataclass(frozen=True, slots=True)
class InsiderHoldingChange:
    person_type: Literal[
        "director", "supervisor", "manager", "major_shareholder", "other_insider"
    ]
    as_of: str
    holding_change_shares: int
    holding_change_pct: Decimal | None
    state: Literal["present", "missing", "not_applicable"]
    reason: str | None
    evidence_id: str | None


@dataclass(frozen=True, slots=True)
class PledgeChange:
    person_type: Literal[
        "director", "supervisor", "manager", "major_shareholder", "other_insider"
    ]
    as_of: str
    pledged_share_change: int
    pledged_ratio_change_pct: Decimal | None
    state: Literal["present", "missing", "not_applicable"]
    reason: str | None
    evidence_id: str | None


@dataclass(frozen=True, slots=True)
class TdccBand:
    band: str
    holder_count: int
    share_count: int
    share_pct: Decimal
    previous_as_of: str | None
    previous_share_pct: Decimal | None
    change_pct_points: Decimal | None
    evidence_id: str


@dataclass(frozen=True, slots=True)
class TdccHeadlineRatios:
    gte_400_lots_share_pct: Decimal | None
    gte_1000_lots_share_pct: Decimal | None
    denominator_outstanding_shares: int | None
    ratio_state: Literal["present", "missing", "not_applicable"]
    reason: str | None
    evidence_id: str | None


@dataclass(frozen=True, slots=True)
class CapitalEventAdjustment:
    applied: bool
    rule_version: Literal["1.0.0"]
    corporate_action_ids: tuple[str, ...]
    pre_event_denominator: int | None
    post_event_denominator: int | None
    adjustment_factor: Decimal | None


@dataclass(frozen=True, slots=True)
class TechnicalChipOverlay:
    window_start: str
    window_end: str
    price_series_ref: str
    price_series: tuple[PriceBar, ...]
    technical_signals: TechnicalSignals
    chip_signals: ChipSignals
    insider_holding_changes: tuple[InsiderHoldingChange, ...]
    pledge_changes: tuple[PledgeChange, ...]
    tdcc_as_of: str
    tdcc_state: Literal["present", "missing", "not_applicable"]
    tdcc_state_reason: str | None
    tdcc_bands: tuple[TdccBand, ...]
    tdcc_headline_ratios: TdccHeadlineRatios
    capital_event_adjustment: CapitalEventAdjustment
    warmup_state: Literal["ready", "insufficient_history", "unavailable"]
    available_at: str | None
    overlay_coverage: Decimal
    independent_from_ratings: Literal[True]
    authority_records: tuple[AuthorityRecord, ...]
    metric_lineage: dict[str, tuple[str, ...]]
    failure_reasons: dict[str, str]
    coverage: Decimal
    confidence: Decimal
    candidate_technical_score: None
    candidate_chip_score: None
    generation_id: str
    producer_candidate_sha: str
    rating_independence: Literal["INDEPENDENT_NO_HEADLINE_EFFECT"] = (
        "INDEPENDENT_NO_HEADLINE_EFFECT"
    )
    publication_status: Literal["NON_PUBLISHABLE_CANDIDATE"] = (
        "NON_PUBLISHABLE_CANDIDATE"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["TechnicalChipOverlay.v1"] = "TechnicalChipOverlay.v1"
    source_version: Literal["AdmittedFactSet.v1+official-market-authority.v1"] = (
        "AdmittedFactSet.v1+official-market-authority.v1"
    )
    formula_version: Literal["technical-chip-total-return.v1"] = (
        "technical-chip-total-return.v1"
    )
    model_version: Literal["technical-chip-deterministic-1.0.0"] = (
        "technical-chip-deterministic-1.0.0"
    )


@dataclass(frozen=True, slots=True)
class _Bar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    evidence_id: str


def _instant(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise TechnicalChipError(f"invalid {field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise TechnicalChipError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TechnicalChipError(f"{field} must be timezone-aware")
    return parsed


def _day(value: object, field: str) -> date:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise TechnicalChipError(f"invalid {field}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TechnicalChipError(f"invalid {field}") from exc


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise TechnicalChipError(f"invalid {field}")
    return value.strip()


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise TechnicalChipError(f"invalid {field}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TechnicalChipError(f"invalid {field}") from exc
    if not result.is_finite():
        raise TechnicalChipError(f"invalid {field}")
    return result


def _optional_decimal(value: object, field: str) -> Decimal | None:
    return None if value is None else _decimal(value, field)


def _integer(value: object, field: str, *, nonnegative: bool = False) -> int:
    if isinstance(value, bool):
        raise TechnicalChipError(f"invalid {field}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise TechnicalChipError(f"invalid {field}") from exc
    if str(result) != str(value).strip() and not isinstance(value, int):
        raise TechnicalChipError(f"invalid {field}")
    if nonnegative and result < 0:
        raise TechnicalChipError(f"invalid {field}")
    if not -(2**63) <= result < 2**63:
        raise TechnicalChipError(f"invalid {field}")
    return result


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TechnicalChipError(f"invalid {field}")
    return value


def _fingerprint(value: object) -> str:
    def normalize(item: object) -> object:
        if isinstance(item, Mapping):
            return {str(k): normalize(v) for k, v in sorted(item.items(), key=lambda pair: str(pair[0]))}
        if isinstance(item, (list, tuple)):
            return [normalize(v) for v in item]
        if isinstance(item, Decimal):
            return str(item)
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        return repr(item)
    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_authorities(
    authorities: Sequence[MarketAuthority], decision: datetime
) -> dict[str, MarketAuthority]:
    by_id: dict[str, MarketAuthority] = {}
    for authority in authorities:
        source_id = _text(authority.source_id, "authority source_id", 128)
        if authority.authority_type != "official":
            raise TechnicalChipError("market authority must be official")
        _text(authority.url, "authority url", 4096)
        if _SHA256.fullmatch(authority.content_sha256) is None:
            raise TechnicalChipError("invalid authority content_sha256")
        available = _instant(authority.available_at, "authority available_at")
        retrieved = _instant(authority.retrieved_at, "authority retrieved_at")
        if retrieved < available:
            raise TechnicalChipError("authority retrieved before it was available")
        if available > decision:
            continue
        previous = by_id.get(source_id)
        if previous is not None and previous != authority:
            raise TechnicalChipError("conflicting authority records for source_id")
        by_id[source_id] = authority
    return by_id


def _admitted_relevant(admitted: AdmittedFactSet, decision: datetime) -> tuple[FactAdmission, ...]:
    facts: list[FactAdmission] = []
    for fact in admitted.facts:
        if fact.fact_type not in _RELEVANT_TYPES:
            continue
        if fact.disposition == "blocked_conflict":
            raise TechnicalChipError(f"unresolved conflict: {fact.fact_id}")
        if fact.disposition != "admitted":
            continue
        available = _instant(fact.available_at, f"{fact.fact_id} available_at")
        if available > decision:
            continue
        facts.append(fact)
    return tuple(facts)


def _bind_fact(fact: FactAdmission, authorities: Mapping[str, MarketAuthority]) -> None:
    if fact.source_id is None or fact.source_id not in authorities:
        raise TechnicalChipError(f"used fact has no PIT official authority: {fact.fact_id}")


def _unique_by_key(
    facts: Sequence[FactAdmission], fact_type: str, key_name: str
) -> dict[str, FactAdmission]:
    result: dict[str, FactAdmission] = {}
    for fact in facts:
        if fact.fact_type != fact_type:
            continue
        value = _mapping(fact.value, fact.fact_id)
        key_value = value.get(key_name)
        key = key_value if isinstance(key_value, str) else ""
        if not key:
            raise TechnicalChipError(f"invalid {fact_type} {key_name}")
        previous = result.get(key)
        if previous is not None and _fingerprint(previous.value) != _fingerprint(fact.value):
            raise TechnicalChipError(f"conflicting {fact_type} facts for {key}")
        if previous is None or fact.fact_id < previous.fact_id:
            result[key] = fact
    return result


def _bars(facts: Sequence[FactAdmission]) -> list[_Bar]:
    selected = _unique_by_key(facts, "market.daily_bar", "date")
    bars: list[_Bar] = []
    for key, fact in selected.items():
        value = _mapping(fact.value, fact.fact_id)
        prices = [_decimal(value.get(name), f"{fact.fact_id} {name}") for name in ("open", "high", "low", "close")]
        volume = _decimal(value.get("volume"), f"{fact.fact_id} volume")
        if any(price <= 0 for price in prices) or volume < 0:
            raise TechnicalChipError("daily bars require positive prices and nonnegative volume")
        if prices[1] < max(prices[0], prices[2], prices[3]) or prices[2] > min(prices[0], prices[1], prices[3]):
            raise TechnicalChipError("daily bar OHLC invariant failed")
        bars.append(_Bar(_day(key, f"{fact.fact_id} date"), *prices, volume, fact.fact_id))
    bars.sort(key=lambda bar: bar.day)
    return bars


def _events(
    facts: Sequence[FactAdmission], bars: Sequence[_Bar]
) -> tuple[list[_Bar], CapitalEventAdjustment, tuple[str, ...]]:
    adjusted = list(bars)
    event_rows: list[tuple[date, str, Decimal, bool, int | None, int | None, str]] = []
    for fact in facts:
        if fact.fact_type not in {"market.cash_distribution", "market.capital_action"}:
            continue
        value = _mapping(fact.value, fact.fact_id)
        ex_date = _day(value.get("ex_date"), f"{fact.fact_id} ex_date")
        event_id = _text(value.get("event_id"), f"{fact.fact_id} event_id", 128)
        # Future and out-of-series events cannot alter the observed series.
        if not bars or ex_date > bars[-1].day or ex_date <= bars[0].day:
            continue
        if fact.fact_type == "market.cash_distribution":
            cash = _decimal(value.get("cash_per_share"), f"{fact.fact_id} cash_per_share")
            if cash < 0:
                raise TechnicalChipError("cash distribution cannot be negative")
            prior = [bar for bar in bars if bar.day < ex_date]
            if not prior:
                raise TechnicalChipError("cash distribution has no prior raw close")
            prior_close = prior[-1].close
            factor = (prior_close - cash) / prior_close
            if factor <= 0:
                raise TechnicalChipError("cash distribution creates nonpositive adjustment factor")
            event_rows.append((ex_date, event_id, factor, False, None, None, fact.fact_id))
        else:
            factor = _decimal(value.get("adjustment_factor"), f"{fact.fact_id} adjustment_factor")
            if factor <= 0:
                raise TechnicalChipError("capital adjustment factor must be positive")
            pre = _integer(value.get("pre_event_denominator"), f"{fact.fact_id} pre_event_denominator", nonnegative=True)
            post = _integer(value.get("post_event_denominator"), f"{fact.fact_id} post_event_denominator", nonnegative=True)
            if pre == 0 or post == 0:
                raise TechnicalChipError("capital event denominators must be nonzero")
            with localcontext() as context:
                context.prec = 40
                expected_factor = Decimal(pre) / Decimal(post)
            if factor != expected_factor:
                raise TechnicalChipError(
                    "capital adjustment factor must equal pre/post denominator"
                )
            event_rows.append((ex_date, event_id, factor, True, pre, post, fact.fact_id))
    identities: dict[str, tuple[object, ...]] = {}
    for event in event_rows:
        identity = event[1]
        signature = event[:6]
        if identity in identities and identities[identity] != signature:
            raise TechnicalChipError("conflicting market event_id")
        identities[identity] = signature
    event_rows = sorted({event[1]: event for event in event_rows}.values(), key=lambda item: (item[0], item[1]))
    total_factor = Decimal("1")
    corporate = [event for event in event_rows if event[3]]
    for ex_date, _, factor, volume_adjust, _, _, _ in event_rows:
        total_factor *= factor
        changed: list[_Bar] = []
        for bar in adjusted:
            if bar.day < ex_date:
                changed.append(_Bar(
                    bar.day, bar.open * factor, bar.high * factor,
                    bar.low * factor, bar.close * factor,
                    bar.volume / factor if volume_adjust else bar.volume,
                    bar.evidence_id,
                ))
            else:
                changed.append(bar)
        adjusted = changed
    metadata = CapitalEventAdjustment(
        applied=bool(event_rows), rule_version="1.0.0",
        corporate_action_ids=tuple(event[1] for event in event_rows),
        pre_event_denominator=corporate[0][4] if corporate else None,
        post_event_denominator=corporate[-1][5] if corporate else None,
        adjustment_factor=total_factor if event_rows else None,
    )
    return adjusted, metadata, tuple(event[6] for event in event_rows)


def _technical(bars: Sequence[_Bar]) -> TechnicalSignals:
    if len(bars) < 61:
        return TechnicalSignals(None, None, None, None, None)
    with localcontext() as context:
        context.prec = 40
        closes = [bar.close for bar in bars]
        latest = closes[-1]
        returns = [
            closes[index] / closes[index - 1] - 1
            for index in range(1, len(closes))
        ]
        sample = returns[-20:]
        mean = sum(sample, Decimal("0")) / Decimal(20)
        variance = sum((item - mean) ** 2 for item in sample) / Decimal(19)
        volatility = variance.sqrt()
        ma20 = sum(closes[-20:], Decimal("0")) / Decimal(20)
        ma60 = sum(closes[-60:], Decimal("0")) / Decimal(60)
        return TechnicalSignals(
            latest / closes[-22] - 1,
            latest / closes[-43] - 1,
            latest / ma20 - 1,
            latest / ma60 - 1,
            volatility,
        )


def _dated_values(
    facts: Sequence[FactAdmission], fact_type: str
) -> dict[date, tuple[Decimal, str]]:
    selected = _unique_by_key(facts, fact_type, "date")
    result: dict[date, tuple[Decimal, str]] = {}
    for key, fact in selected.items():
        value = _mapping(fact.value, fact.fact_id)
        result[_day(key, f"{fact.fact_id} date")] = (
            _decimal(value.get("value"), f"{fact.fact_id} value"), fact.fact_id
        )
    return result


def _chip_signals(
    facts: Sequence[FactAdmission], bars: Sequence[_Bar], lineage: dict[str, tuple[str, ...]],
    reasons: dict[str, str],
) -> ChipSignals:
    names = {
        "chip.foreign_net": "foreign_net_20d",
        "chip.dealer_net": "dealer_net_20d",
        "chip.investment_trust_net": "investment_trust_net_20d",
    }
    values: dict[str, Decimal | None] = {}
    target20 = tuple(bar.day for bar in bars[-20:]) if len(bars) >= 20 else ()
    for fact_type, output in names.items():
        series = _dated_values(facts, fact_type)
        if target20 and all(day in series for day in target20):
            values[output] = sum((series[day][0] for day in target20), Decimal("0"))
            lineage[output] = tuple(series[day][1] for day in target20)
        else:
            values[output] = None
            lineage[output] = ()
            reasons[output] = "missing_complete_20_session_series"
    margin = _dated_values(facts, "chip.margin_balance")
    target21 = tuple(bar.day for bar in bars[-21:]) if len(bars) >= 21 else ()
    if target21 and all(day in margin for day in target21):
        values["margin_balance_change"] = margin[target21[-1]][0] - margin[target21[0]][0]
        lineage["margin_balance_change"] = tuple(margin[day][1] for day in target21)
    else:
        values["margin_balance_change"] = None
        lineage["margin_balance_change"] = ()
        reasons["margin_balance_change"] = "missing_complete_21_session_margin_series"
    return ChipSignals(**values)


def _changes(
    facts: Sequence[FactAdmission], fact_type: str, decision_day: date
) -> tuple[InsiderHoldingChange, ...] | tuple[PledgeChange, ...]:
    selected: dict[tuple[str, str], tuple[str, InsiderHoldingChange | PledgeChange]] = {}
    seen: dict[tuple[str, str], str] = {}
    for fact in facts:
        if fact.fact_type != fact_type:
            continue
        value = _mapping(fact.value, fact.fact_id)
        raw_person = value.get("person_type")
        if raw_person not in _PERSON_TYPES:
            raise TechnicalChipError(f"invalid {fact_type} person_type")
        person = cast(PersonType, raw_person)
        as_of_day = _day(value.get("as_of"), f"{fact.fact_id} as_of")
        if as_of_day > decision_day:
            continue
        as_of = as_of_day.isoformat()
        raw_state = value.get("state")
        if raw_state not in _STATES:
            raise TechnicalChipError(f"invalid {fact_type} state")
        state = cast(EvidenceState, raw_state)
        reason_value = value.get("reason")
        reason = None if reason_value is None else _text(reason_value, f"{fact.fact_id} reason", 512)
        if state == "present" and reason is not None:
            raise TechnicalChipError("present change record cannot have a missing/N/A reason")
        if state != "present" and reason is None:
            raise TechnicalChipError("missing/N/A change record requires a reason")
        key = (person, as_of)
        signature = _fingerprint(value)
        if key in seen and seen[key] != signature:
            raise TechnicalChipError(f"conflicting {fact_type} records")
        seen[key] = signature
        raw_evidence = value.get("evidence_id")
        if state == "present":
            evidence = _text(raw_evidence, f"{fact.fact_id} evidence_id", 128)
        else:
            if raw_evidence is not None:
                raise TechnicalChipError(
                    "missing/N/A change record cannot carry evidence_id"
                )
            evidence = None
        if fact_type == "chip.insider_holding_change":
            pct = _optional_decimal(value.get("holding_change_pct"), f"{fact.fact_id} holding_change_pct")
            if pct is not None and not Decimal("-100") <= pct <= Decimal("100"):
                raise TechnicalChipError("holding_change_pct outside -100..100")
            item = InsiderHoldingChange(
                person, as_of,
                _integer(value.get("holding_change_shares"), f"{fact.fact_id} holding_change_shares"),
                pct, state, reason, evidence,
            )
        else:
            pct = _optional_decimal(value.get("pledged_ratio_change_pct"), f"{fact.fact_id} pledged_ratio_change_pct")
            if pct is not None and not Decimal("-100") <= pct <= Decimal("100"):
                raise TechnicalChipError("pledged_ratio_change_pct outside -100..100")
            item = PledgeChange(
                person, as_of,
                _integer(value.get("pledged_share_change"), f"{fact.fact_id} pledged_share_change"),
                pct, state, reason, evidence,
            )
        current = selected.get(key)
        if current is None or fact.fact_id < current[0]:
            selected[key] = (fact.fact_id, item)
    result = [item for _, item in selected.values()]
    result.sort(key=lambda item: (item.as_of, item.person_type, item.evidence_id or ""))
    if len(result) > 256:
        raise TechnicalChipError(f"{fact_type} exceeds 256 records")
    return tuple(result)  # type: ignore[return-value]


def _tdcc(
    facts: Sequence[FactAdmission], decision_day: date,
) -> tuple[str, str, str | None, tuple[TdccBand, ...], TdccHeadlineRatios, tuple[str, ...]]:
    markers = _unique_by_key(facts, "chip.tdcc_distribution_complete", "as_of")
    fallback = max((_day(_mapping(f.value, f.fact_id).get("as_of"), "tdcc as_of") for f in facts if f.fact_type == "chip.tdcc_band"), default=None)
    if not markers:
        as_of = fallback.isoformat() if fallback else decision_day.isoformat()
        return as_of, "missing", "complete_distribution_marker_missing", (), TdccHeadlineRatios(None, None, None, "missing", "complete_distribution_marker_missing", None), ()
    marker_dates = sorted(
        (_day(key, "tdcc complete as_of"), fact)
        for key, fact in markers.items()
        if _day(key, "tdcc complete as_of") <= decision_day
    )
    if not marker_dates:
        as_of = fallback.isoformat() if fallback and fallback <= decision_day else decision_day.isoformat()
        reason = "complete_distribution_unavailable_as_of_decision"
        return as_of, "missing", reason, (), TdccHeadlineRatios(
            None, None, None, "missing", reason, None
        ), ()
    latest_day, latest_marker = marker_dates[-1]
    marker_value = _mapping(latest_marker.value, latest_marker.fact_id)
    marker_state = marker_value.get("state", "present")
    if marker_state not in _STATES:
        raise TechnicalChipError("invalid TDCC complete-marker state")
    if marker_state == "present" and marker_value.get("complete") is not True:
        raise TechnicalChipError("TDCC present marker must declare complete=true")
    if marker_state != "present":
        marker_reason = _text(marker_value.get("reason"), "TDCC state reason", 512)
        state = cast(Literal["missing", "not_applicable"], marker_state)
        return latest_day.isoformat(), state, marker_reason, (), TdccHeadlineRatios(
            None, None, None, state, marker_reason, None
        ), (latest_marker.fact_id,)
    bands_by_date: dict[date, list[tuple[FactAdmission, Mapping[str, object]]]] = {}
    for fact in facts:
        if fact.fact_type == "chip.tdcc_band":
            value = _mapping(fact.value, fact.fact_id)
            bands_by_date.setdefault(_day(value.get("as_of"), f"{fact.fact_id} as_of"), []).append((fact, value))
    latest_rows = bands_by_date.get(latest_day, [])
    if not latest_rows:
        reason = "complete_marker_has_no_bands"
        return latest_day.isoformat(), "missing", reason, (), TdccHeadlineRatios(None, None, None, "missing", reason, latest_marker.fact_id), (latest_marker.fact_id,)
    if len(latest_rows) > 32:
        raise TechnicalChipError("TDCC complete distribution exceeds 32 bands")
    declared_band_count = _integer(
        marker_value.get("band_count"),
        f"{latest_marker.fact_id} band_count",
        nonnegative=True,
    )
    if declared_band_count != len(latest_rows):
        raise TechnicalChipError(
            "TDCC complete marker band_count does not match distribution"
        )
    labels: dict[str, tuple[FactAdmission, Mapping[str, object]]] = {}
    denominators: set[int] = set()
    for fact, value in latest_rows:
        label = _text(value.get("band"), f"{fact.fact_id} band", 32)
        if label in labels:
            raise TechnicalChipError("duplicate TDCC band in complete distribution")
        labels[label] = (fact, value)
        denominator = _integer(value.get("outstanding_shares"), f"{fact.fact_id} outstanding_shares", nonnegative=True)
        if denominator == 0:
            raise TechnicalChipError("TDCC denominator must be nonzero")
        denominators.add(denominator)
    if len(denominators) != 1:
        raise TechnicalChipError("TDCC complete bands have inconsistent denominators")
    denominator = next(iter(denominators))
    if sum(
        _integer(
            value.get("share_count"), f"{fact.fact_id} share_count",
            nonnegative=True,
        )
        for fact, value in latest_rows
    ) != denominator:
        raise TechnicalChipError("TDCC complete bands must sum to denominator")
    prior_complete_dates = [
        marker_day
        for marker_day, marker in marker_dates[:-1]
        if (
            _mapping(marker.value, marker.fact_id).get("state", "present") == "present"
            and _mapping(marker.value, marker.fact_id).get("complete") is True
        )
    ]
    previous_day = prior_complete_dates[-1] if prior_complete_dates else None
    previous_rows = bands_by_date.get(previous_day, []) if previous_day else []
    previous: dict[str, tuple[int, Decimal, str]] = {}
    previous_denominators: set[int] = set()
    for fact, value in previous_rows:
        label = _text(value.get("band"), f"{fact.fact_id} band", 32)
        if label in previous:
            raise TechnicalChipError("duplicate previous TDCC band")
        shares = _integer(value.get("share_count"), f"{fact.fact_id} share_count", nonnegative=True)
        den = _integer(value.get("outstanding_shares"), f"{fact.fact_id} outstanding_shares", nonnegative=True)
        if den == 0:
            raise TechnicalChipError("previous TDCC denominator must be nonzero")
        previous_denominators.add(den)
        previous[label] = (shares, Decimal(shares) * 100 / Decimal(den), fact.fact_id)
    if len(previous_denominators) > 1:
        raise TechnicalChipError("previous TDCC bands have inconsistent denominators")
    if previous_rows and sum(
        _integer(
            value.get("share_count"), f"{fact.fact_id} share_count",
            nonnegative=True,
        )
        for fact, value in previous_rows
    ) != next(iter(previous_denominators)):
        raise TechnicalChipError(
            "previous complete TDCC bands must sum to denominator"
        )
    comparable = True
    compare_reason: str | None = (
        "previous_complete_distribution_unavailable"
        if previous_day is None or not previous_rows else None
    )
    comparison_action_ids: tuple[str, ...] = ()
    if previous_day and previous_denominators and next(iter(previous_denominators)) != denominator:
        previous_denominator = next(iter(previous_denominators))
        matching_actions = []
        for action in facts:
            if action.fact_type != "market.capital_action":
                continue
            action_value = _mapping(action.value, action.fact_id)
            action_day = _day(action_value.get("ex_date"), f"{action.fact_id} ex_date")
            if not previous_day < action_day <= latest_day:
                continue
            pre = _integer(action_value.get("pre_event_denominator"), f"{action.fact_id} pre_event_denominator", nonnegative=True)
            post = _integer(action_value.get("post_event_denominator"), f"{action.fact_id} post_event_denominator", nonnegative=True)
            factor = _decimal(action_value.get("adjustment_factor"), f"{action.fact_id} adjustment_factor")
            with localcontext() as context:
                context.prec = 40
                expected_factor = Decimal(pre) / Decimal(post)
            if (
                pre == previous_denominator
                and post == denominator
                and factor == expected_factor
            ):
                matching_actions.append(action)
        comparable = len(matching_actions) == 1
        if comparable:
            comparison_action_ids = (matching_actions[0].fact_id,)
        if not comparable:
            compare_reason = "cross_capital_event_missing_adjustment"
    output: list[TdccBand] = []
    gte400 = 0
    gte1000 = 0
    used = [latest_marker.fact_id, *comparison_action_ids]
    ordered_labels = sorted(
        labels,
        key=lambda label: _integer(
            labels[label][1].get("min_lots"),
            f"{labels[label][0].fact_id} min_lots",
            nonnegative=True,
        ),
    )
    for label in ordered_labels:
        fact, value = labels[label]
        holders = _integer(value.get("holder_count"), f"{fact.fact_id} holder_count", nonnegative=True)
        shares = _integer(value.get("share_count"), f"{fact.fact_id} share_count", nonnegative=True)
        min_lots = _integer(value.get("min_lots"), f"{fact.fact_id} min_lots", nonnegative=True)
        max_raw = value.get("max_lots")
        if max_raw is not None:
            maximum = _integer(max_raw, f"{fact.fact_id} max_lots", nonnegative=True)
            if maximum < min_lots:
                raise TechnicalChipError("TDCC max_lots is below min_lots")
        pct = Decimal(shares) * 100 / Decimal(denominator)
        if pct > 100:
            raise TechnicalChipError("TDCC band share_pct exceeds 100")
        prior = previous.get(label) if comparable else None
        if previous_day is not None and comparable and prior is None and compare_reason is None:
            compare_reason = "previous_same_band_unavailable"
        previous_pct = prior[1] if prior else None
        output.append(TdccBand(
            label, holders, shares, pct,
            previous_day.isoformat() if prior and previous_day else None,
            previous_pct, pct - previous_pct if previous_pct is not None else None,
            _text(value.get("evidence_id"), f"{fact.fact_id} evidence_id", 128),
        ))
        if min_lots >= 400:
            gte400 += shares
        if min_lots >= 1000:
            gte1000 += shares
        used.append(fact.fact_id)
        if prior:
            used.append(prior[2])
    ratios = TdccHeadlineRatios(
        Decimal(gte400) * 100 / Decimal(denominator),
        Decimal(gte1000) * 100 / Decimal(denominator),
        denominator, "present", None,
        _text(
            marker_value.get("evidence_id"),
            f"{latest_marker.fact_id} evidence_id",
            128,
        ),
    )
    return latest_day.isoformat(), "present", compare_reason, tuple(output), ratios, tuple(sorted(set(used)))


def _series_ref(bars: Sequence[_Bar]) -> str:
    if not bars:
        return "technical-chip:adjusted-ohlcv:unavailable"
    return (
        f"technical-chip:adjusted-ohlcv:{bars[0].day.isoformat()}"
        f":{bars[-1].day.isoformat()}:{len(bars)}"
    )


def probe_twse_daily_authority() -> tuple[MarketAuthority, int]:
    """Read the official TWSE daily endpoint and return its raw authority and row count."""
    request = urllib.request.Request(
        _TWSE_DAILY_URL, headers={"User-Agent": "CompanyQualityResearch/0.1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except Exception as exc:
        raise TechnicalChipError("TWSE daily authority probe failed") from exc
    try:
        rows = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TechnicalChipError("TWSE daily authority returned invalid JSON") from exc
    if not isinstance(rows, list) or not rows or any(not isinstance(row, Mapping) for row in rows):
        raise TechnicalChipError("TWSE daily authority returned no valid rows")
    retrieved = datetime.now(_TAIPEI).isoformat(timespec="seconds")
    authority = MarketAuthority(
        source_id="twse:STOCK_DAY_ALL", authority_type="official", url=_TWSE_DAILY_URL,
        content_sha256=hashlib.sha256(body).hexdigest(),
        available_at=retrieved, retrieved_at=retrieved,
    )
    return authority, len(rows)


def build_technical_chip_overlay(
    admitted: AdmittedFactSet,
    authorities: Sequence[MarketAuthority],
    *,
    generation_id: str,
    producer_candidate_sha: str,
) -> TechnicalChipOverlay:
    """Build an independent overlay solely from PIT-admitted, authority-bound facts."""
    if admitted.schema_version != "AdmittedFactSet.v1":
        raise TechnicalChipError("expected AdmittedFactSet.v1")
    if admitted.rating_disposition != "NO_RATING_NOT_APPLICABLE":
        raise TechnicalChipError("invalid AdmittedFactSet rating disposition")
    generation_id = _text(generation_id, "generation_id", 128)
    if _GIT_SHA.fullmatch(producer_candidate_sha) is None:
        raise TechnicalChipError("invalid producer_candidate_sha")
    decision = _instant(admitted.decision_time, "decision_time")
    authority_by_id = _validate_authorities(authorities, decision)
    if not authority_by_id:
        raise TechnicalChipError("at least one PIT official authority is required")
    facts = _admitted_relevant(admitted, decision)
    decision_date = decision.astimezone(_TAIPEI).date()
    bars_raw = [bar for bar in _bars(facts) if bar.day <= decision_date]
    bars_adjusted, capital, event_ids = _events(facts, bars_raw)

    lineage: dict[str, tuple[str, ...]] = {}
    reasons: dict[str, str] = {}
    for fact in admitted.facts:
        if fact.fact_type in _RELEVANT_TYPES and fact.disposition != "admitted":
            reasons[f"excluded:{fact.fact_id}"] = fact.failure_reason or fact.disposition
    technical = _technical(bars_adjusted)
    technical_ids = tuple(bar.evidence_id for bar in bars_adjusted)
    lineage["price_series"] = technical_ids + event_ids
    for name in ("return_1m", "return_2m", "ma20_gap", "ma60_gap", "volatility_20d"):
        value = getattr(technical, name)
        lineage[name] = technical_ids + event_ids if value is not None else ()
        if value is None:
            reasons[name] = "requires_at_least_61_valid_trading_bars"
    chip = _chip_signals(facts, bars_raw, lineage, reasons)
    insider = _changes(facts, "chip.insider_holding_change", decision_date)
    pledge = _changes(facts, "chip.pledge_change", decision_date)
    tdcc_as_of, tdcc_state, tdcc_reason, tdcc_bands, tdcc_ratios, tdcc_ids = _tdcc(
        facts, decision_date
    )
    lineage["insider_holding_changes"] = tuple(
        fact.fact_id for fact in facts
        if fact.fact_type == "chip.insider_holding_change"
    )
    lineage["pledge_changes"] = tuple(
        fact.fact_id for fact in facts
        if fact.fact_type == "chip.pledge_change"
    )
    lineage["tdcc_bands"] = tdcc_ids
    lineage["tdcc_headline_ratios"] = tdcc_ids
    lineage["capital_event_adjustment"] = event_ids
    if not insider:
        reasons["insider_holding_changes"] = "missing_verified_insider_change_facts"
    if not pledge:
        reasons["pledge_changes"] = "missing_verified_pledge_change_facts"
    if tdcc_reason:
        reasons["tdcc"] = tdcc_reason

    used_ids = {evidence for values in lineage.values() for evidence in values}
    # Missing/N/A change rows remain displayed with null evidence_id by contract,
    # but their admitted source facts are still consumed and must be authority-bound.
    used_ids.update(
        fact.fact_id for fact in facts
        if fact.fact_type in {"chip.insider_holding_change", "chip.pledge_change"}
    )
    used_facts = [fact for fact in facts if fact.fact_id in used_ids]
    for fact in used_facts:
        _bind_fact(fact, authority_by_id)
    used_sources = {fact.source_id for fact in used_facts}
    authority_records = tuple(
        AuthorityRecord(
            authority.source_id, authority.authority_type, authority.url,
            authority.content_sha256, authority.available_at, authority.retrieved_at,
            source_id in used_sources,
        )
        for source_id, authority in sorted(authority_by_id.items())
    )
    available_times = [_instant(fact.available_at, "fact available_at") for fact in used_facts]
    available_times.extend(
        _instant(authority_by_id[source].available_at, "authority available_at")
        for source in used_sources if source is not None
    )
    available_at = max(available_times).isoformat() if available_times else None

    metric_values = [
        technical.return_1m, technical.return_2m, technical.ma20_gap,
        technical.ma60_gap, technical.volatility_20d,
        chip.foreign_net_20d, chip.dealer_net_20d,
        chip.investment_trust_net_20d, chip.margin_balance_change,
    ]
    covered = sum(value is not None for value in metric_values)
    covered += int(bool(insider)) + int(bool(pledge)) + int(tdcc_state == "present")
    coverage = Decimal(covered) / Decimal(12)
    display = bars_adjusted[-42:]
    price_series = tuple(
        PriceBar(
            bar.day.isoformat(), bar.open, bar.high, bar.low, bar.close,
            bar.volume, bar.evidence_id,
        )
        for bar in display
    )
    decision_day = decision.astimezone(_TAIPEI).date().isoformat()
    window_start = display[0].day.isoformat() if display else decision_day
    window_end = display[-1].day.isoformat() if display else decision_day
    if len(bars_adjusted) >= 61:
        warmup: Literal["ready", "insufficient_history", "unavailable"] = "ready"
    elif bars_adjusted:
        warmup = "insufficient_history"
    else:
        warmup = "unavailable"
        reasons["price_series"] = "no_valid_authority_bound_daily_bars"
    reasons["candidate_technical_score"] = "no_rating_not_applicable"
    reasons["candidate_chip_score"] = "no_rating_not_applicable"

    return TechnicalChipOverlay(
        window_start=window_start, window_end=window_end,
        price_series_ref=_series_ref(display), price_series=price_series,
        technical_signals=technical,
        chip_signals=chip, insider_holding_changes=insider,
        pledge_changes=pledge, tdcc_as_of=tdcc_as_of,
        tdcc_state=tdcc_state, tdcc_state_reason=tdcc_reason,
        tdcc_bands=tdcc_bands, tdcc_headline_ratios=tdcc_ratios,
        capital_event_adjustment=capital, warmup_state=warmup,
        available_at=available_at, overlay_coverage=coverage,
        independent_from_ratings=True, authority_records=authority_records,
        metric_lineage=lineage, failure_reasons=dict(sorted(reasons.items())),
        coverage=coverage, confidence=coverage,
        candidate_technical_score=None, candidate_chip_score=None,
        generation_id=generation_id, producer_candidate_sha=producer_candidate_sha,
    )


__all__ = [
    "MarketAuthority", "TechnicalChipError", "TechnicalChipOverlay",
    "build_technical_chip_overlay", "probe_twse_daily_authority",
]
