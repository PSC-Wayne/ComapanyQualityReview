"""Official governance and insider evidence with conservative checklist mapping.

The exchange OpenAPI endpoints are current source windows.  They are not treated
as historical-zero authority.  R41 uses the holdings/pledge row itself; transfer
feeds remain intent/non-completion context.  R42 uses only a bounded, explicitly
complete MOPS material-event history with event effective dates.  Control-change
and penalty rows remain governance context unless their substance proves an
existing authoritative checklist claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
import re
from typing import Literal, Mapping, Protocol, Sequence, cast
from urllib.request import Request, build_opener
from urllib.request import HTTPCookieProcessor
from http.cookiejar import CookieJar
from zoneinfo import ZoneInfo

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.evidence_producers import (
    EvidenceRole,
    Market,
    MultiSourceEvidence,
    SourceFamily,
)

_TAIPEI = ZoneInfo("Asia/Taipei")
_MOPS_HISTORY_URL = "https://mops.twse.com.tw/mops/api/t05st02"


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    dataset_id: str
    twse_url: str
    tpex_url: str
    event_type: str
    evidence_role: EvidenceRole

    def url(self, market: Market) -> str:
        return self.twse_url if market == "TWSE" else self.tpex_url


ENDPOINTS = (
    EndpointSpec(
        "t187ap11_L",
        "https://openapi.twse.com.tw/v1/opendata/t187ap11_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O",
        "holdings_pledge",
        "substantive",
    ),
    EndpointSpec(
        "t187ap12_L",
        "https://openapi.twse.com.tw/v1/opendata/t187ap12_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O",
        "transfer_intent",
        "discovery",
    ),
    EndpointSpec(
        "t187ap13_L",
        "https://openapi.twse.com.tw/v1/opendata/t187ap13_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap13_O",
        "transfer_non_completion",
        "discovery",
    ),
    EndpointSpec(
        "t187ap22_L",
        "https://openapi.twse.com.tw/v1/opendata/t187ap22_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap22_O",
        "regulatory_penalty",
        "substantive",
    ),
    EndpointSpec(
        "t187ap23_L",
        "https://openapi.twse.com.tw/v1/opendata/t187ap23_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap23_O",
        "disclosure_violation",
        "substantive",
    ),
    EndpointSpec(
        "t187ap24_L",
        "https://openapi.twse.com.tw/v1/opendata/t187ap24_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap24_O",
        "control_change",
        "substantive",
    ),
    EndpointSpec(
        "t187ap33_L",
        "https://openapi.twse.com.tw/v1/opendata/t187ap33_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap33_O",
        "current_leadership",
        "discovery",
    ),
    EndpointSpec(
        "t187ap04_L",
        "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
        "current_material_event",
        "discovery",
    ),
)


class GovernanceTransport(Protocol):
    def fetch(self, url: str) -> bytes: ...


class UrlopenGovernanceTransport:
    """Small credential-free transport for the official OpenAPI windows."""

    def fetch(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "CompanyQualityResearch/0.1"})
        with build_opener().open(request, timeout=45) as response:
            if response.status != 200:
                raise OSError(f"official governance endpoint returned {response.status}")
            return response.read()


class MopsMaterialEventTransport:
    """Session-aware transport for bounded daily MOPS history and detail rows."""

    def __init__(self) -> None:
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        request = Request(
            "https://mops.twse.com.tw/mops/",
            headers={"User-Agent": "CompanyQualityResearch/0.1"},
        )
        with self._opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise OSError("MOPS session preload failed")
            response.read()

    def post(self, api_name: str, payload: Mapping[str, object]) -> bytes:
        request = Request(
            f"https://mops.twse.com.tw/mops/api/{api_name}",
            data=json.dumps(payload).encode(),
            headers={
                "User-Agent": "CompanyQualityResearch/0.1",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self._opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise OSError(f"MOPS {api_name} returned {response.status}")
            return response.read()


@dataclass(frozen=True, slots=True)
class MaterialEventHistory:
    """Pre-materialized bounded MOPS detail records and their coverage assertion."""

    window_start: str
    window_end: str
    complete: bool
    records: tuple[Mapping[str, object], ...]
    source_url: str = _MOPS_HISTORY_URL

    def __post_init__(self) -> None:
        start = date.fromisoformat(self.window_start)
        end = date.fromisoformat(self.window_end)
        if start > end:
            raise ValueError("material-event history window is reversed")
        if not self.source_url.startswith("https://"):
            raise ValueError("material-event history source URL must use HTTPS")


@dataclass(frozen=True, slots=True)
class GovernanceEvent:
    evidence_id: str
    issuer_id: str
    security_code: str
    reported_company_name: str
    market: Market
    dataset_id: str
    event_type: str
    evidence_role: EvidenceRole
    observed_period: str
    effective_date: str | None
    available_at: str
    retrieved_at: str
    source_url: str
    source_locator: str
    content_sha256: str
    verbatim_excerpt: str
    checklist_ids: tuple[str, ...]
    counterevidence: tuple[str, ...]
    fields: tuple[tuple[str, str], ...]

    def field(self, name: str) -> str | None:
        return dict(self.fields).get(name)


@dataclass(frozen=True, slots=True)
class GovernanceEvidenceCollection:
    market: Market
    security_code: str
    as_of: str
    events: tuple[GovernanceEvent, ...]
    history_window_start: str | None
    history_window_end: str | None
    history_source_url: str | None
    history_complete: bool
    unresolved_reasons: tuple[str, ...]
    schema_version: Literal["GovernanceEvidenceCollection.v1"] = (
        "GovernanceEvidenceCollection.v1"
    )


class GovernanceInsiderProducer:
    """Paired TWSE/TPEx producer implementing issue #122's per-item role contract."""

    producer_id = "official.governance-insiders"

    def __init__(
        self,
        *,
        transport: GovernanceTransport,
        material_event_history: MaterialEventHistory | None = None,
        retrieved_at: str | None = None,
    ) -> None:
        self.transport = transport
        self.material_event_history = material_event_history
        self.retrieved_at = retrieved_at
        self.last_collection: GovernanceEvidenceCollection | None = None
        self.source_family: SourceFamily = "twse_openapi"

    def produce(
        self,
        *,
        issuer_id: str,
        security_code: str,
        reported_company_name: str,
        market: Market,
        as_of: str,
    ) -> Sequence[MultiSourceEvidence]:
        decision = _instant(as_of)
        retrieved_at = self.retrieved_at or as_of
        _instant(retrieved_at)
        self.source_family = "twse_openapi" if market == "TWSE" else "tpex_openapi"
        events: list[GovernanceEvent] = []
        reasons: list[str] = []
        for spec in ENDPOINTS:
            url = spec.url(market)
            try:
                body = self.transport.fetch(url)
                payload = json.loads(body)
                if not isinstance(payload, list):
                    raise ValueError("official endpoint did not return an array")
            except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
                reasons.append(f"source_error:{spec.dataset_id}:{type(exc).__name__}")
                continue
            digest = sha256(body).hexdigest()
            for row in payload:
                if not isinstance(row, dict) or _code(row, market, spec.event_type) != security_code:
                    continue
                try:
                    event = _openapi_event(
                        row=row,
                        spec=spec,
                        market=market,
                        issuer_id=issuer_id,
                        security_code=security_code,
                        fallback_name=reported_company_name,
                        retrieved_at=retrieved_at,
                        source_digest=digest,
                    )
                except ValueError as exc:
                    reasons.append(f"malformed:{spec.dataset_id}:{str(exc)}")
                    continue
                if _instant(event.available_at) > decision:
                    reasons.append(f"post_as_of:{event.evidence_id}")
                    continue
                events.append(event)

        history = self.material_event_history
        if history is None:
            reasons.append("mops_material_event_history_unavailable")
        else:
            if date.fromisoformat(history.window_end) > decision.date():
                reasons.append("mops_material_event_history_post_as_of")
            else:
                for record in history.records:
                    if str(record.get("market", "")) != market:
                        continue
                    if str(record.get("security_code", "")) != security_code:
                        continue
                    try:
                        event = _history_event(
                            record,
                            issuer_id=issuer_id,
                            security_code=security_code,
                            fallback_name=reported_company_name,
                            market=market,
                            retrieved_at=retrieved_at,
                            source_url=history.source_url,
                        )
                    except ValueError as exc:
                        reasons.append(f"malformed:mops_material_event:{str(exc)}")
                        continue
                    if _instant(event.available_at) > decision:
                        reasons.append(f"post_as_of:{event.evidence_id}")
                        continue
                    events.append(event)
            if not history.complete:
                reasons.append("mops_material_event_history_incomplete")

        events = list({event.evidence_id: event for event in events}.values())
        events.sort(key=lambda item: (item.available_at, item.evidence_id))
        self.last_collection = GovernanceEvidenceCollection(
            market=market,
            security_code=security_code,
            as_of=as_of,
            events=tuple(events),
            history_window_start=history.window_start if history else None,
            history_window_end=history.window_end if history else None,
            history_source_url=history.source_url if history else None,
            history_complete=bool(history and history.complete),
            unresolved_reasons=tuple(dict.fromkeys(reasons)),
        )
        return tuple(_multi_source(item, as_of, self.source_family) for item in events)


def _instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return result


def _roc_date(value: object) -> date:
    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) != 7:
        raise ValueError("invalid ROC date")
    return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))


def _available(value: object) -> str:
    # OpenAPI exposes a date, not an original release time.  Midnight is the
    # earliest defensible availability boundary; callers still reject post-as-of rows.
    day = _roc_date(value)
    return datetime.combine(day, time.min, tzinfo=_TAIPEI).isoformat()


def _code(row: Mapping[str, object], market: Market, event_type: str) -> str:
    if market == "TPEx":
        return str(row.get("SecuritiesCompanyCode") or row.get("公司代號") or "").strip()
    if event_type in {"regulatory_penalty", "disclosure_violation"}:
        return str(row.get("股票代號") or row.get("公司代號") or "").strip()
    return str(row.get("公司代號") or "").strip()


def _name(row: Mapping[str, object], market: Market, fallback: str) -> str:
    return str(row.get("公司名稱") or row.get("CompanyName") or fallback).strip()


def _row_locator(row: Mapping[str, object]) -> str:
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "row_sha256:" + sha256(canonical.encode()).hexdigest()


def _excerpt(row: Mapping[str, object], event_type: str) -> str:
    preferred = {
        "holdings_pledge": ("職稱", "姓名", "目前持股", "設質股數", "設質股數佔持股比例"),
        "transfer_intent": ("申報人身分", "申請人身分", "姓名", "預定轉讓方式及股數-轉讓方式", "預定轉讓總股數-自有持股", "有效轉讓期間"),
        "transfer_non_completion": ("申報人身分", "申請人身分", "姓名", "未轉讓理由"),
        "regulatory_penalty": ("發函日期", "違規事由", "違反法規", "裁處情形"),
        "disclosure_violation": ("發函日期", "違規事由", "裁罰金額(萬)", "裁罰金額"),
        "control_change": ("經營權異動日期", "經營權異動說明"),
        "current_leadership": ("董事長", "Chairman", "總經理", "GeneralManager", "董事長是否兼任總經理"),
        "current_material_event": ("發言日期", "發言時間", "主旨 ", "主旨", "事實發生日", "說明"),
    }[event_type]
    values = [f"{key}={str(row[key]).strip()}" for key in preferred if str(row.get(key, "")).strip()]
    return "；".join(values)[:3900]


def _openapi_event(
    *,
    row: Mapping[str, object],
    spec: EndpointSpec,
    market: Market,
    issuer_id: str,
    security_code: str,
    fallback_name: str,
    retrieved_at: str,
    source_digest: str,
) -> GovernanceEvent:
    output = row.get("出表日期") if market == "TWSE" else row.get("Date", row.get("出表日期"))
    available_at = _available(output)
    observed = str(
        row.get("資料年月")
        or row.get("經營權異動日期")
        or row.get("發函日期")
        or row.get("事實發生日")
        or output
    ).strip()
    if not observed:
        raise ValueError("missing observed period")
    locator = _row_locator(row)
    evidence_id = f"{market}:{security_code}:{spec.dataset_id}:{observed}:{locator.split(':', 1)[1][:16]}"
    fields = tuple((str(key), str(value).strip()) for key, value in row.items())
    effective: str | None = None
    for key in ("經營權異動日期", "事實發生日", "發函日期"):
        if str(row.get(key, "")).strip():
            effective = _roc_date(row[key]).isoformat()
            break
    counter = (
        ("本列只是預定轉讓申報，不證明已完成轉讓或已執行出售。",)
        if spec.event_type == "transfer_intent"
        else ("目前來源窗口不完整，不能以未命中推論歷史上沒有事件。",)
    )
    return GovernanceEvent(
        evidence_id=evidence_id,
        issuer_id=issuer_id,
        security_code=security_code,
        reported_company_name=_name(row, market, fallback_name),
        market=market,
        dataset_id=(spec.dataset_id if market == "TWSE" else f"mopsfin_{spec.dataset_id[:-2]}_O"),
        event_type=spec.event_type,
        evidence_role=spec.evidence_role,
        observed_period=observed,
        effective_date=effective,
        available_at=available_at,
        retrieved_at=retrieved_at,
        source_url=spec.url(market),
        source_locator=locator,
        content_sha256=source_digest,
        verbatim_excerpt=_excerpt(row, spec.event_type),
        checklist_ids=("R41",) if spec.event_type == "holdings_pledge" else (),
        counterevidence=counter,
        fields=fields,
    )


_KEY_ROLE_PATTERN = re.compile(
    r"(財務主管|會計主管|稽核主管|內部稽核主管|總經理|執行長).{0,12}(異動|辭任|解任|離職|接任|新任)"
    r"|(異動|辭任|解任|離職|接任|新任).{0,12}(財務主管|會計主管|稽核主管|內部稽核主管|總經理|執行長)"
)


def _history_event(
    record: Mapping[str, object],
    *,
    issuer_id: str,
    security_code: str,
    fallback_name: str,
    market: Market,
    retrieved_at: str,
    source_url: str,
) -> GovernanceEvent:
    announced = str(record.get("announced_at", ""))
    effective = str(record.get("effective_date", ""))
    subject = str(record.get("subject", "")).strip()
    detail = str(record.get("detail", "")).strip()
    locator = str(record.get("source_locator", "")).strip()
    _instant(announced)
    date.fromisoformat(effective)
    if not subject or not detail or not locator:
        raise ValueError("MOPS detail lacks subject, effective date, detail, or locator")
    role_change = bool(_KEY_ROLE_PATTERN.search(subject + " " + detail))
    canonical = json.dumps(dict(record), ensure_ascii=False, sort_keys=True, default=str)
    digest = sha256(canonical.encode()).hexdigest()
    evidence_id = f"MOPS:{market}:{security_code}:{announced}:{sha256(locator.encode()).hexdigest()[:16]}"
    return GovernanceEvent(
        evidence_id=evidence_id,
        issuer_id=issuer_id,
        security_code=security_code,
        reported_company_name=str(record.get("company_name") or fallback_name),
        market=market,
        dataset_id="mops:t05st02:detail",
        event_type="key_role_change" if role_change else "material_event_context",
        evidence_role="substantive" if role_change else "discovery",
        observed_period=effective,
        effective_date=effective,
        available_at=announced,
        retrieved_at=retrieved_at,
        source_url=source_url,
        source_locator=locator,
        content_sha256=digest,
        verbatim_excerpt=f"{subject}；{detail}"[:3900],
        checklist_ids=("R42",) if role_change else (),
        counterevidence=("異動原因與財報延遲、重編、內控缺失仍須另行交叉查核。",),
        fields=(("subject", subject), ("detail", detail)),
    )


def _multi_source(
    event: GovernanceEvent, as_of: str, source_family: SourceFamily
) -> MultiSourceEvidence:
    return MultiSourceEvidence(
        evidence_id=event.evidence_id,
        evidence_handle=f"sha256:{event.content_sha256}",
        issuer_id=event.issuer_id,
        security_code=event.security_code,
        reported_company_name=event.reported_company_name,
        dataset_id=event.dataset_id,
        source_locator=event.source_locator,
        source_url=event.source_url,
        source_family=("mops" if event.dataset_id.startswith("mops:") else source_family),
        market=event.market,
        observed_period=event.observed_period,
        retrieved_at=event.retrieved_at,
        available_at=event.available_at,
        as_of=as_of,
        evidence_role=event.evidence_role,
        is_summary_only=False,
    )


def _check(
    original: ChecklistCheckResult,
    *,
    applicability: Literal["triggered", "not_triggered", "unresolved"],
    status: Literal["evaluated", "unresolved"],
    events: Sequence[GovernanceEvent],
    observations: tuple[str, ...],
    counterevidence: tuple[str, ...],
    reason: str | None = None,
) -> ChecklistCheckResult:
    latest = max(events, key=lambda item: item.available_at) if events else None
    return ChecklistCheckResult(
        check_id=original.check_id,
        domain="risk",
        applicability=applicability,
        status=status,
        first_detectable_at=latest.available_at if latest else None,
        financial_period=latest.effective_date or latest.observed_period if latest else None,
        observations=observations,
        evidence_ids=tuple(event.evidence_id for event in events),
        supporting_evidence=("已取得具列身分、期間與列定位的官方來源。",) if events else (),
        counterevidence=counterevidence,
        inference_chain=(
            "官方身分綁定 → 來源列與月份／事件日 → 權威R題條件",
        ) if events else (),
        mechanism=(
            "內部人持股、質押或關鍵職務反覆異動可能放大治理、強制處分及財報控制風險。"
        ),
        leading_warnings=("持股變化", "質押比例", "關鍵職務異動", "財報延遲／重編／內控缺失"),
        buffers=counterevidence,
        monitoring_metrics=("每月董監持股與質押", "五年MOPS關鍵職務異動", "財報延遲與重編"),
        monitoring_date=None,
        invalidation_or_resolution_conditions=("新月份或新重大訊息改變目前證據。",),
        severity="medium" if applicability == "triggered" else "low" if status == "evaluated" else "not_applicable",
        confidence="high" if status == "evaluated" and events else "medium" if status == "evaluated" else "low",
        unresolved_reasons=(reason,) if reason else (),
    )


def apply_governance_checks(
    checks: tuple[ChecklistCheckResult, ...],
    collection: GovernanceEvidenceCollection,
) -> tuple[ChecklistCheckResult, ...]:
    """Update only R41/R42; unrelated governance context receives no synthetic row."""

    rows = {item.check_id: item for item in checks}
    holdings = [item for item in collection.events if item.event_type == "holdings_pledge"]
    periods = sorted({item.observed_period for item in holdings})
    by_person: dict[tuple[str, str], list[GovernanceEvent]] = {}
    for event in holdings:
        by_person.setdefault((event.field("職稱") or "", event.field("姓名") or ""), []).append(event)
    declines: list[tuple[GovernanceEvent, GovernanceEvent]] = []
    for person_rows in by_person.values():
        person_rows.sort(key=lambda item: item.observed_period)
        for prior, current in zip(person_rows, person_rows[1:]):
            try:
                if int(current.field("目前持股") or "") < int(prior.field("目前持股") or ""):
                    declines.append((prior, current))
            except ValueError:
                continue
    pledge_positive = [
        item for item in holdings
        if _integer(item.field("設質股數")) > 0
        or _percent_number(item.field("設質股數佔持股比例")) > 0
    ]
    if declines:
        selected = tuple(dict.fromkeys(event for pair in declines for event in pair))
        observations = tuple(
            f"{current.field('職稱')} {current.field('姓名')}：{prior.observed_period}持股{prior.field('目前持股')} → "
            f"{current.observed_period}持股{current.field('目前持股')}；來源：{current.source_url}。"
            for prior, current in declines
        )
        rows["R41"] = _check(
            rows["R41"], applicability="triggered", status="evaluated",
            events=selected, observations=observations,
            counterevidence=("R41只作治理風險，不直接推論基本面造假。",),
        )
    elif len(periods) >= 2 and not pledge_positive:
        rows["R41"] = _check(
            rows["R41"], applicability="not_triggered", status="evaluated",
            events=holdings,
            observations=(
                f"已比較{periods[0]}至{periods[-1]}同身分持股列，未見持股下降且揭露質押股數為零；"
                f"來源：{holdings[-1].source_url}。",
            ),
            counterevidence=("本判定只涵蓋已取得月份與列，不代表更早歷史沒有事件。",),
        )
    elif holdings:
        observations = tuple(
            f"{item.verbatim_excerpt}；來源：{item.source_url}"
            for item in holdings[:3]
        )
        reason = (
            "已揭露質押，但權威清單未定義『高質押』門檻，不能任意升級為已評估。"
            if pledge_positive
            else "目前只有單一月份持股／質押快照，不能判定持股下降或歷史上沒有高質押。"
        )
        rows["R41"] = _check(
            rows["R41"], applicability="unresolved", status="unresolved",
            events=holdings, observations=observations,
            counterevidence=("轉讓申報只代表意向，不作已出售反證。",), reason=reason,
        )

    role_changes = [item for item in collection.events if item.event_type == "key_role_change"]
    if collection.history_complete and len(role_changes) >= 2:
        rows["R42"] = _check(
            rows["R42"], applicability="triggered", status="evaluated",
            events=role_changes,
            observations=tuple(
                f"生效日{item.effective_date}；公告{item.available_at}；{item.verbatim_excerpt}；"
                f"來源：{item.source_url}"
                for item in role_changes
            ),
            counterevidence=tuple(item.counterevidence[0] for item in role_changes),
        )
    elif collection.history_complete and not role_changes:
        rows["R42"] = _check(
            rows["R42"], applicability="not_triggered", status="evaluated",
            events=(),
            observations=(
                f"已完整查詢MOPS重大訊息窗口{collection.history_window_start}至{collection.history_window_end}，"
                "未命中關鍵職務異動；本結論只限該完整窗口；"
                f"來源：{collection.history_source_url}。",
            ),
            counterevidence=("窗口外或後續事件仍可能改變判定。",),
        )
    elif len(role_changes) == 1:
        rows["R42"] = _check(
            rows["R42"], applicability="unresolved", status="unresolved",
            events=role_changes,
            observations=(
                f"{role_changes[0].verbatim_excerpt}；來源：{role_changes[0].source_url}",
            ),
            counterevidence=role_changes[0].counterevidence,
            reason="只取得一次關鍵職務異動，或歷史窗口不完整，尚不能判定『頻繁異動』。",
        )
    else:
        rows["R42"] = _check(
            rows["R42"], applicability="unresolved", status="unresolved",
            events=(), observations=(), counterevidence=(),
            reason="MOPS重大訊息歷史窗口不完整；目前feed未命中不能證明沒有異動。",
        )
    return tuple(rows[item.check_id] for item in checks)


def _integer(value: str | None) -> int:
    try:
        return int((value or "0").replace(",", ""))
    except ValueError:
        return 0


def _percent_number(value: str | None) -> float:
    try:
        return float((value or "0").replace("%", ""))
    except ValueError:
        return 0.0


__all__ = [
    "ENDPOINTS",
    "GovernanceEvidenceCollection",
    "GovernanceEvent",
    "GovernanceInsiderProducer",
    "GovernanceTransport",
    "MaterialEventHistory",
    "apply_governance_checks",
]
