"""Five-calendar-year, single-market survivorship-free adverse/control cohort."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Callable, Literal, Mapping, Sequence
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class CohortError(RuntimeError):
    pass


Market = Literal["TWSE", "TPEx"]
EventClass = Literal[
    "delisting", "default", "fraud", "restatement", "drawdown", "other_adverse"
]
DelistingKind = Literal[
    "forced_redemption", "maturity", "bankruptcy", "other_delisting"
]


@dataclass(frozen=True, slots=True)
class OfficialUniverseMember:
    issuer_id: str
    security_code: str
    company_name: str
    market: Market
    listed_on: str
    delisted_on: str | None
    evidence_ids: tuple[str, ...]
    available_at: str


@dataclass(frozen=True, slots=True)
class GovernedEventLabel:
    issuer_id: str
    event_code: str
    event_class: EventClass
    adverse: bool
    effective_on: str
    official_reason: str
    authoritative_source_type: str
    delisting_kind: DelistingKind | None
    evidence_ids: tuple[str, ...]
    available_at: str


@dataclass(frozen=True, slots=True)
class EventTaxonomyEntry:
    event_code: str
    event_class: EventClass
    authoritative_source_type: str


@dataclass(frozen=True, slots=True)
class DelistingStates:
    forced_redemption: Literal["confirmed", "not_confirmed", "unknown"]
    maturity: Literal["confirmed", "not_confirmed", "unknown"]
    bankruptcy: Literal["confirmed", "not_confirmed", "unknown"]
    other_delisting: Literal["confirmed", "not_confirmed", "unknown"]


@dataclass(frozen=True, slots=True)
class CensoringRules:
    right_censor_at: str
    min_followup_days: int
    suspension_policy: Literal["right_censor_until_official_resume_or_delisting"]
    missing_price_policy: Literal[
        "confirmed_delisting_zero_contribution", "block_unconfirmed"
    ]


@dataclass(frozen=True, slots=True)
class CohortMember:
    issuer_id: str
    security_code: str
    company_name: str
    market: Market
    listed_on: str
    delisted_on: str | None
    disposition: Literal["adverse", "control", "right_censored"]
    event_codes: tuple[str, ...]
    official_reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdverseControlCohort:
    market: Market
    issuer_ids: tuple[str, ...]
    control_ids: tuple[str, ...]
    members: tuple[CohortMember, ...]
    event_taxonomy: tuple[EventTaxonomyEntry, ...]
    delisting_states: DelistingStates
    censoring_rules: CensoringRules
    cohort_asof: str
    window_start_inclusive: str
    window_end_exclusive: str
    lookback_calendar_years: Literal[5]
    window_boundary_policy: Literal["asia_taipei_calendar_year_half_open_v1"]
    universe_policy: Literal["all_securities_listed_at_any_instant_during_window"]
    delisted_included: Literal[True]
    eligibility_version: str
    evidence_ids: tuple[str, ...]
    failure_reasons: dict[str, str]
    input_producer_shas: dict[str, str]
    cohort_coverage: Decimal
    available_at: str
    generation_id: str
    producer_candidate_sha: str
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["AdverseControlCohort.v1"] = "AdverseControlCohort.v1"
    source_version: Literal[
        "AdmittedFactSet.v1+OfficialFinancialArtifacts.v1+AuditFilingInventory.v1+OfficialExchangeUniverse.v1"
    ] = "AdmittedFactSet.v1+OfficialFinancialArtifacts.v1+AuditFilingInventory.v1+OfficialExchangeUniverse.v1"
    formula_version: Literal["single-market-five-calendar-year-half-open.v1"] = (
        "single-market-five-calendar-year-half-open.v1"
    )
    model_version: Literal["no-calibration-natural-controls.v1"] = (
        "no-calibration-natural-controls.v1"
    )


_SHA = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_TAIPEI = ZoneInfo("Asia/Taipei")


def add_calendar_years_clamped(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        if value.month == 2 and value.day == 29:
            return value.replace(year=value.year + years, day=28)
        raise


def five_year_window(cohort_asof: str) -> tuple[date, date]:
    try:
        instant = datetime.fromisoformat(cohort_asof)
    except ValueError as exc:
        raise CohortError("invalid cohort_asof") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise CohortError("cohort_asof must be timezone-aware")
    end = instant.astimezone(_TAIPEI).date() + timedelta(days=1)
    return add_calendar_years_clamped(end, -5), end


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CohortError(f"invalid {field}") from exc


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CohortError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CohortError(f"{field} must be timezone-aware")
    return result


def _taxonomy() -> tuple[EventTaxonomyEntry, ...]:
    return (
        EventTaxonomyEntry("official_delisting", "delisting", "exchange_delisting_registry"),
        EventTaxonomyEntry("official_default", "default", "official_material_event"),
        EventTaxonomyEntry("confirmed_fraud", "fraud", "competent_authority_decision"),
        EventTaxonomyEntry("official_restatement", "restatement", "official_financial_filing"),
        EventTaxonomyEntry(
            "wealth_drawdown_gt_50", "drawdown",
            "official_price_and_corporate_action_ledger",
        ),
        EventTaxonomyEntry(
            "other_governed_adverse", "other_adverse", "governed_official_event"
        ),
    )


def build_adverse_control_cohort(
    members: Sequence[OfficialUniverseMember],
    event_labels: Sequence[GovernedEventLabel],
    *,
    market: Market,
    cohort_asof: str,
    min_followup_days: int,
    eligibility_version: str,
    producer_shas: Mapping[str, str],
    generation_id: str,
    producer_candidate_sha: str,
) -> AdverseControlCohort:
    if market not in {"TWSE", "TPEx"}:
        raise CohortError("market must be TWSE or TPEx")
    if not 0 <= min_followup_days <= 4294967295:
        raise CohortError("min_followup_days outside uint32")
    if not _SEMVER.fullmatch(eligibility_version):
        raise CohortError("eligibility_version must be semver")
    required_shas = {"T03", "T04", "T06"}
    if set(producer_shas) != required_shas or any(
        not _SHA.fullmatch(value) for value in producer_shas.values()
    ):
        raise CohortError("BLOCKED_CONTRACT: exact T03/T04/T06 SHAs required")
    if not generation_id or not _SHA.fullmatch(producer_candidate_sha):
        raise CohortError("generation and producer candidate SHA required")

    start, end = five_year_window(cohort_asof)
    censor_instant = _instant(cohort_asof, "cohort_asof")
    if not members:
        raise CohortError("official universe is empty")
    by_issuer: dict[str, OfficialUniverseMember] = {}
    for item in members:
        if item.market != market:
            raise CohortError("cross-market member in single-market cohort")
        if not item.issuer_id or len(item.issuer_id) > 4096 or not item.evidence_ids:
            raise CohortError("invalid universe member identity/evidence")
        listed = _day(item.listed_on, "listed_on")
        delisted = _day(item.delisted_on, "delisted_on") if item.delisted_on else None
        if delisted is not None and delisted < listed:
            raise CohortError("delisting precedes listing")
        if item.issuer_id in by_issuer:
            raise CohortError("duplicate issuer membership")
        if _instant(item.available_at, "member available_at") > censor_instant:
            raise CohortError("member evidence breaches PIT boundary")
        by_issuer[item.issuer_id] = item

    labels_by_issuer: dict[str, list[GovernedEventLabel]] = {}
    for label in event_labels:
        if label.issuer_id not in by_issuer:
            raise CohortError("event label references unknown issuer")
        if not label.evidence_ids or not label.official_reason.strip():
            raise CohortError("event labels require official reason/evidence")
        if not 1 <= len(label.event_code) <= 64:
            raise CohortError("event code outside contract")
        _day(label.effective_on, "event effective_on")
        if _instant(label.available_at, "label available_at") > censor_instant:
            raise CohortError("event label breaches PIT boundary")
        labels_by_issuer.setdefault(label.issuer_id, []).append(label)

    output: list[CohortMember] = []
    failures: dict[str, str] = {}
    all_evidence: list[str] = []
    available_values: list[datetime] = []
    unresolved_delisting = False
    kind_hits: set[str] = set()
    eligible_count = 0
    for issuer_id in sorted(by_issuer):
        item = by_issuer[issuer_id]
        listed = _day(item.listed_on, "listed_on")
        delisted = _day(item.delisted_on, "delisted_on") if item.delisted_on else None
        overlaps = listed < end and (delisted is None or delisted >= start)
        if not overlaps:
            continue
        eligible_count += 1
        labels = sorted(
            (
                label for label in labels_by_issuer.get(issuer_id, [])
                if start <= _day(label.effective_on, "event effective_on") < end
            ),
            key=lambda label: (label.effective_on, label.event_code),
        )
        if len({label.event_code for label in labels}) != len(labels):
            raise CohortError("duplicate event code for issuer")
        if delisted is not None and start <= delisted < end and not labels:
            failures[issuer_id] = "unresolved_delisting_event_label"
            unresolved_delisting = True
            continue
        if any(label.delisting_kind for label in labels):
            kind_hits.update(
                label.delisting_kind for label in labels if label.delisting_kind
            )
        observed_end = min(delisted, end) if delisted is not None else end
        followup_days = (observed_end - max(listed, start)).days
        adverse = any(label.adverse for label in labels)
        disposition: Literal["adverse", "control", "right_censored"]
        if adverse:
            disposition = "adverse"
        elif followup_days < min_followup_days:
            disposition = "right_censored"
        else:
            disposition = "control"
        evidence = tuple(dict.fromkeys((
            *item.evidence_ids,
            *(value for label in labels for value in label.evidence_ids),
        )))
        output.append(CohortMember(
            issuer_id=issuer_id,
            security_code=item.security_code,
            company_name=item.company_name,
            market=market,
            listed_on=item.listed_on,
            delisted_on=item.delisted_on,
            disposition=disposition,
            event_codes=tuple(label.event_code for label in labels),
            official_reasons=tuple(label.official_reason for label in labels),
            evidence_ids=evidence,
        ))
        all_evidence.extend(evidence)
        available_values.append(_instant(item.available_at, "member available_at"))
        available_values.extend(
            _instant(label.available_at, "label available_at") for label in labels
        )

    if not output or eligible_count == 0:
        raise CohortError("no admitted cohort members")
    evidence_ids = tuple(dict.fromkeys(all_evidence))
    if not evidence_ids or len(evidence_ids) > 10000:
        raise CohortError("cohort evidence count must be 1..10000")
    if any(len(value) > 4096 for value in evidence_ids):
        raise CohortError("cohort evidence ID too long")

    def state(kind: str) -> Literal["confirmed", "not_confirmed", "unknown"]:
        if kind in kind_hits:
            return "confirmed"
        return "unknown" if unresolved_delisting else "not_confirmed"

    output.sort(key=lambda item: item.issuer_id)
    controls = tuple(item.issuer_id for item in output if item.disposition == "control")
    if not controls:
        raise CohortError("cohort contract requires at least one control")
    coverage = Decimal(len(output)) / Decimal(eligible_count)
    return AdverseControlCohort(
        market=market,
        issuer_ids=tuple(item.issuer_id for item in output),
        control_ids=controls,
        members=tuple(output),
        event_taxonomy=_taxonomy(),
        delisting_states=DelistingStates(
            state("forced_redemption"), state("maturity"),
            state("bankruptcy"), state("other_delisting"),
        ),
        censoring_rules=CensoringRules(
            right_censor_at=cohort_asof,
            min_followup_days=min_followup_days,
            suspension_policy="right_censor_until_official_resume_or_delisting",
            missing_price_policy="block_unconfirmed",
        ),
        cohort_asof=cohort_asof,
        window_start_inclusive=start.isoformat(),
        window_end_exclusive=end.isoformat(),
        lookback_calendar_years=5,
        window_boundary_policy="asia_taipei_calendar_year_half_open_v1",
        universe_policy="all_securities_listed_at_any_instant_during_window",
        delisted_included=True,
        eligibility_version=eligibility_version,
        evidence_ids=evidence_ids,
        failure_reasons=failures,
        input_producer_shas=dict(sorted(producer_shas.items())),
        cohort_coverage=coverage,
        available_at=max(available_values).isoformat(),
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
    )


TWSE_DELISTED_URL = "https://www.twse.com.tw/rwd/zh/company/suspendListing?response=json"
TPEX_DELISTED_URL = "https://www.tpex.org.tw/www/zh-tw/company/deListed"
TWSE_IDENTITY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_IDENTITY_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"


def fetch_json(url: str) -> tuple[object, bytes]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
        if response.status != 200:
            raise CohortError(f"official source HTTP {response.status}")
    try:
        return json.loads(body), body
    except json.JSONDecodeError as exc:
        raise CohortError("official source returned non-JSON") from exc


def probe_twse_delisted(
    fetcher: Callable[[str], tuple[object, bytes]] = fetch_json,
) -> dict[str, object]:
    payload, body = fetcher(TWSE_DELISTED_URL)
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise CohortError("TWSE delisted source status invalid")
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows or any(
        not isinstance(row, list) or len(row) < 3 for row in rows
    ):
        raise CohortError("TWSE delisted source rows invalid")
    return {
        "source_url": TWSE_DELISTED_URL,
        "source_sha256": sha256(body).hexdigest(),
        "row_count": len(rows),
        "fields": ("終止上市日期", "公司名稱", "公司代號"),
    }


def probe_tpex_delisted_year(
    year: int,
    fetcher: Callable[[str], tuple[object, bytes]] = fetch_json,
) -> dict[str, object]:
    if not 2000 <= year <= 9999:
        raise CohortError("invalid TPEx query year")
    url = (
        f"{TPEX_DELISTED_URL}?response=json&date={year}&reason=ALL"
        "&paging-offset=0&paging-size=1000"
    )
    payload, body = fetcher(url)
    if not isinstance(payload, dict) or payload.get("stat") != "ok":
        raise CohortError("TPEx delisted source status invalid")
    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) != 1:
        raise CohortError("TPEx delisted tables invalid")
    table = tables[0]
    fields = table.get("fields") if isinstance(table, dict) else None
    expected = ["股票代號", "公司名稱", "終止上櫃日期", "終止上櫃原因", "公司資料網址"]
    data = table.get("data") if isinstance(table, dict) else None
    if fields != expected or not isinstance(data, list):
        raise CohortError("TPEx delisted schema invalid")
    return {
        "source_url": url,
        "source_sha256": sha256(body).hexdigest(),
        "row_count": len(data),
        "fields": tuple(expected),
    }


def probe_market_identity(
    market: Market,
    fetcher: Callable[[str], tuple[object, bytes]] = fetch_json,
) -> dict[str, object]:
    if market == "TWSE":
        url = TWSE_IDENTITY_URL
        required = ("公司代號", "公司名稱", "營利事業統一編號", "上市日期")
    elif market == "TPEx":
        url = TPEX_IDENTITY_URL
        required = (
            "SecuritiesCompanyCode", "CompanyName", "UnifiedBusinessNo.",
            "DateOfListing",
        )
    else:
        raise CohortError("market must be TWSE or TPEx")
    payload, body = fetcher(url)
    if not isinstance(payload, list) or not payload:
        raise CohortError("official identity source is empty")
    if any(
        not isinstance(row, dict)
        or any(
            not isinstance(row.get(field), str) or not row[field]
            for field in required
        )
        for row in payload
    ):
        raise CohortError("official identity source schema invalid")
    return {
        "source_url": url,
        "source_sha256": sha256(body).hexdigest(),
        "row_count": len(payload),
        "required_fields": required,
    }


__all__ = [
    "AdverseControlCohort", "CohortError", "GovernedEventLabel",
    "OfficialUniverseMember", "add_calendar_years_clamped",
    "build_adverse_control_cohort", "five_year_window",
    "probe_market_identity", "probe_tpex_delisted_year", "probe_twse_delisted",
]
