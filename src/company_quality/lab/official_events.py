"""Official material-event normalization and downside-only PIT challenger."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Iterable, Literal, Mapping, Sequence, cast
from zoneinfo import ZoneInfo

import pandas as pd

from company_quality.lab.real_trends import _base_matrix, _holdout_mae
from company_quality.research_snapshot import OfficialMaterialEvent


_TAIPEI = ZoneInfo("Asia/Taipei")
_DOWNSIDE_EVENT_TYPES = (
    "trading_suspension",
    "altered_trading",
    "delisting",
    "regulatory_violation",
    "filing_violation",
    "financial_restatement",
)
_MAJOR_URLS = {
    "TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    "TPEx": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
}
_VIOLATION_URLS = {
    "TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap23_L",
    "TPEx": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap23_O",
}


@dataclass(frozen=True, slots=True)
class OfficialEventCoverage:
    market: str
    available_from: str
    available_to: str
    complete: bool
    source_url: str


def _roc_day(value: object) -> date:
    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) != 7:
        raise ValueError("ROC event date must be YYYMMDD")
    return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))


def _roc_instant(day_value: object, time_value: object) -> datetime:
    day = _roc_day(day_value)
    digits = "".join(character for character in str(time_value) if character.isdigit()).zfill(6)
    if len(digits) != 6:
        raise ValueError("event announcement time must be HHMMSS")
    return datetime(
        day.year,
        day.month,
        day.day,
        int(digits[:2]),
        int(digits[2:4]),
        int(digits[4:6]),
        tzinfo=_TAIPEI,
    )


def normalize_major_announcement_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    market: str,
    generation_id: str,
    issuer_by_security_code: Mapping[str, str],
) -> tuple[tuple[OfficialMaterialEvent, ...], dict[str, object]]:
    """Normalize official TWSE/TPEx daily announcements without severity inference."""
    if market not in _MAJOR_URLS:
        raise ValueError("market must be TWSE or TPEx")
    market_literal = cast(Literal["TWSE", "TPEx"], market)
    code_key = "公司代號" if market == "TWSE" else "SecuritiesCompanyCode"
    title_key = "主旨 " if market == "TWSE" else "主旨"
    source_rows = list(rows)
    events: list[OfficialMaterialEvent] = []
    rejected: dict[str, int] = {}
    for row in source_rows:
        code = str(row.get(code_key, "")).strip()
        issuer_id = issuer_by_security_code.get(code)
        try:
            if not issuer_id:
                raise ValueError("unresolved_issuer")
            title = str(row.get(title_key, "")).strip()
            reason = str(row.get("說明", "")).strip()
            clause = str(row.get("符合條款", "")).strip()
            effective = _roc_day(row.get("事實發生日"))
            available = _roc_instant(row.get("發言日期"), row.get("發言時間"))
            if not title or not reason or not clause:
                raise ValueError("missing_official_event_fields")
        except (TypeError, ValueError) as exc:
            key = str(exc) or "malformed_official_row"
            rejected[key] = rejected.get(key, 0) + 1
            continue
        event_id = (
            f"{market}:{code}:{available.strftime('%Y%m%d%H%M%S')}:{clause}"
        )
        events.append(OfficialMaterialEvent(
            generation_id=generation_id,
            issuer_id=issuer_id,
            security_code=code,
            market=market_literal,
            event_id=event_id,
            event_type="material_announcement",
            title=title,
            effective_date=effective.isoformat(),
            available_at=available.isoformat(),
            official_reason=reason,
            source_authority=market_literal,
            source_url=_MAJOR_URLS[market],
            evidence_id=f"{event_id}:official-row",
            confirmation_status="confirmed",
            downside_candidate_status="display_only",
        ))
    report = {
        "schema_version": "OfficialMaterialEventNormalization.v1",
        "market": market,
        "source_url": _MAJOR_URLS[market],
        "input_row_count": len(source_rows),
        "confirmed_event_count": len(events),
        "rejected_counts": dict(sorted(rejected.items())),
        "text_severity_inference": False,
        "downside_admission": "display_only_pending_independent_validation",
    }
    return tuple(sorted(events, key=lambda item: item.available_at)), report


def normalize_violation_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    market: str,
    generation_id: str,
    issuer_by_security_code: Mapping[str, str],
) -> tuple[tuple[OfficialMaterialEvent, ...], dict[str, object]]:
    """Normalize official exchange violation letters as downside candidates."""
    if market not in _VIOLATION_URLS:
        raise ValueError("market must be TWSE or TPEx")
    market_literal = cast(Literal["TWSE", "TPEx"], market)
    code_key = "股票代號" if market == "TWSE" else "SecuritiesCompanyCode"
    source_rows = list(rows)
    events: list[OfficialMaterialEvent] = []
    rejected: dict[str, int] = {}
    for row in source_rows:
        code = str(row.get(code_key, "")).strip()
        issuer_id = issuer_by_security_code.get(code)
        try:
            if not issuer_id:
                raise ValueError("unresolved_issuer")
            letter_day = _roc_day(row.get("發函日期"))
            reason = str(row.get("違規事由", "")).strip()
            if not reason:
                raise ValueError("missing_official_event_fields")
        except (TypeError, ValueError) as exc:
            key = str(exc) or "malformed_official_row"
            rejected[key] = rejected.get(key, 0) + 1
            continue
        available = datetime(
            letter_day.year,
            letter_day.month,
            letter_day.day,
            23,
            59,
            59,
            tzinfo=_TAIPEI,
        )
        event_id = f"{market}:{code}:{letter_day.isoformat()}:filing-violation"
        events.append(OfficialMaterialEvent(
            generation_id=generation_id,
            issuer_id=issuer_id,
            security_code=code,
            market=market_literal,
            event_id=event_id,
            event_type="filing_violation",
            title="交易所違反資訊申報或重大訊息規定紀錄",
            effective_date=letter_day.isoformat(),
            available_at=available.isoformat(),
            official_reason=reason,
            source_authority=market_literal,
            source_url=_VIOLATION_URLS[market],
            evidence_id=f"{event_id}:official-row",
            confirmation_status="confirmed",
            downside_candidate_status="eligible_for_validation",
        ))
    report = {
        "schema_version": "OfficialViolationEventNormalization.v1",
        "market": market,
        "source_url": _VIOLATION_URLS[market],
        "input_row_count": len(source_rows),
        "confirmed_event_count": len(events),
        "rejected_counts": dict(sorted(rejected.items())),
        "available_time_rule": "official_letter_date_end_of_day_conservative",
        "downside_admission": "eligible_only_after_independent_validation_gain",
        "quality_score_effect": None,
    }
    return tuple(sorted(events, key=lambda item: item.available_at)), report


def _coverage_admits(
    coverage: OfficialEventCoverage | None,
    market: str,
    decision: pd.Timestamp,
) -> bool:
    if coverage is None or coverage.market != market or not coverage.complete:
        return False
    start = pd.Timestamp(coverage.available_from)
    end = pd.Timestamp(coverage.available_to)
    decision_stamp = cast(pd.Timestamp, pd.Timestamp(decision))
    return (
        start <= decision_stamp - pd.DateOffset(months=12)
        and end >= decision_stamp
    )


def validate_downside_event_challenger(
    labels: pd.DataFrame,
    base_features: pd.DataFrame,
    events: Sequence[OfficialMaterialEvent],
    coverage_by_market: Mapping[str, OfficialEventCoverage],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Admit confirmed official event types only after earlier-year MAE gain."""
    required = {
        "issuer_id",
        "security_code",
        "market",
        "decision_date",
        "generation_id",
        "adverse_outcome",
    }
    missing = required - set(labels.columns)
    if missing:
        raise ValueError("event validation labels missing: " + ", ".join(sorted(missing)))
    generations = set(labels["generation_id"].astype(str))
    if len(generations) != 1:
        raise ValueError("event validation requires one generation")
    generation = next(iter(generations))
    for event in events:
        if event.generation_id != generation:
            raise ValueError("event/label generation mismatch")
        if (
            event.downside_candidate_status == "eligible_for_validation"
            and (
                event.confirmation_status != "confirmed"
                or event.event_type not in _DOWNSIDE_EVENT_TYPES
            )
        ):
            raise ValueError("unconfirmed or generic event cannot enter downside validation")

    admitted_labels = labels.copy()
    admitted_labels["decision"] = pd.to_datetime(admitted_labels["decision_date"])
    admitted_labels = admitted_labels.loc[
        [
            _coverage_admits(
                coverage_by_market.get(str(row["market"])),
                str(row["market"]),
                cast(pd.Timestamp, pd.Timestamp(row["decision"])),
            )
            for _, row in admitted_labels.iterrows()
        ]
    ].copy()
    candidate_types = sorted({
        event.event_type
        for event in events
        if event.confirmation_status == "confirmed"
        and event.downside_candidate_status == "eligible_for_validation"
        and event.event_type in _DOWNSIDE_EVENT_TYPES
    })
    if admitted_labels.empty or not candidate_types:
        return pd.DataFrame(), {
            "schema_version": "DownsideOfficialEventAblation.v1",
            "status": "research_only_insufficient_official_history",
            "publishable": False,
            "admitted_event_types": [],
            "rejected_event_types": candidate_types,
            "quality_score_effect": None,
            "faces": None,
            "coverage": [asdict(item) for item in coverage_by_market.values()],
        }

    event_rows: list[dict[str, object]] = []
    for label in admitted_labels.itertuples(index=False):
        decision = cast(pd.Timestamp, pd.Timestamp(label.decision))
        decision_end = decision.tz_localize(_TAIPEI) + pd.Timedelta(
            hours=23, minutes=59, seconds=59
        )
        start = decision_end - pd.DateOffset(months=12)
        for event_type in candidate_types:
            count = sum(
                1
                for event in events
                if event.issuer_id == str(label.issuer_id)
                and event.market == str(label.market)
                and event.event_type == event_type
                and event.confirmation_status == "confirmed"
                and event.downside_candidate_status == "eligible_for_validation"
                and start < pd.Timestamp(event.available_at) <= decision_end
            )
            event_rows.append({
                "issuer_id": str(label.issuer_id),
                "decision_date": str(label.decision_date),
                "metric_id": f"downside__official_event__{event_type}__count_12m",
                "metric_value": float(count),
                "metric_available_at": decision_end.isoformat(),
                "evidence_family_id": f"official_event:{event_type}",
            })
    event_features = pd.DataFrame(event_rows)
    event_matrix = event_features.pivot(
        index=["issuer_id", "decision_date"],
        columns="metric_id",
        values="metric_value",
    ).reset_index()
    event_matrix.columns.name = None
    event_ids = sorted(
        item for item in event_matrix.columns if item not in {"issuer_id", "decision_date"}
    )
    base_matrix, base_ids = _base_matrix(base_features)
    data = admitted_labels.merge(
        base_matrix,
        on=["issuer_id", "decision_date"],
        how="inner",
        validate="one_to_one",
    ).merge(
        event_matrix,
        on=["issuer_id", "decision_date"],
        how="inner",
        validate="one_to_one",
    )
    data["adverse_target"] = data["adverse_outcome"].astype(float)
    dates = [
        cast(pd.Timestamp, pd.Timestamp(item))
        for item in sorted(data["decision"].unique())
    ][1:]
    baseline_mae, used_dates = _holdout_mae(
        data, base_ids, "adverse_target", dates
    )
    if baseline_mae is None:
        return event_features, {
            "schema_version": "DownsideOfficialEventAblation.v1",
            "status": "research_only_insufficient_official_history",
            "publishable": False,
            "admitted_event_types": [],
            "rejected_event_types": candidate_types,
            "quality_score_effect": None,
            "faces": None,
            "coverage": [asdict(item) for item in coverage_by_market.values()],
        }

    comparisons: list[dict[str, object]] = []
    admitted_types: list[str] = []
    for event_type, metric_id in zip(candidate_types, event_ids, strict=True):
        challenger_mae, metric_dates = _holdout_mae(
            data, [*base_ids, metric_id], "adverse_target", dates
        )
        gain = baseline_mae - challenger_mae if challenger_mae is not None else None
        admitted = gain is not None and gain > 1e-12 and metric_dates == used_dates
        if admitted:
            admitted_types.append(event_type)
        comparisons.append({
            "event_type": event_type,
            "metric_id": metric_id,
            "baseline_mean_absolute_error": baseline_mae,
            "challenger_mean_absolute_error": challenger_mae,
            "mean_absolute_error_gain": gain,
            "admitted": admitted,
        })
    report = {
        "schema_version": "DownsideOfficialEventAblation.v1",
        "status": "research_only",
        "publishable": False,
        "holdout_dates": used_dates,
        "admitted_event_types": admitted_types,
        "rejected_event_types": [
            item for item in candidate_types if item not in admitted_types
        ],
        "comparisons": comparisons,
        "quality_score_effect": None,
        "faces": None,
        "coverage": [asdict(item) for item in coverage_by_market.values()],
    }
    return event_features, report


__all__ = [
    "OfficialEventCoverage",
    "normalize_major_announcement_rows",
    "normalize_violation_rows",
    "validate_downside_event_challenger",
]
