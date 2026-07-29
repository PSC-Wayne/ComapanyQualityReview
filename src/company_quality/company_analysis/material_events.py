"""Bounded official MOPS material-event history for one resolved company."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import http.cookiejar
import json
import os
from pathlib import Path
import re
from typing import Literal, Protocol
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from company_quality.company_analysis.contracts import EvidenceCitation

_LIST_URL = "https://mopsov.twse.com.tw/mops/web/t05st01"
_DATA_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01"
_TAIPEI = ZoneInfo("Asia/Taipei")
_RELEVANT_TERMS = (
    "分割",
    "增資",
    "取得",
    "處分",
    "投資",
    "履約爭議",
    "仲裁",
    "減損",
    "資金貸與",
    "背書保證",
)


class MaterialEventError(RuntimeError):
    """Raised when official material-event evidence cannot be validated."""


@dataclass(frozen=True, slots=True)
class MaterialEvent:
    event_id: str
    market: Literal["TWSE", "TPEx"]
    security_code: str
    company_name: str
    roc_year: int
    sequence: str
    title: str
    event_type: Literal[
        "asset_transfer",
        "capital_injection",
        "contract_dispute",
        "financing_support",
        "other",
    ]
    announced_at: str
    effective_at: str | None
    clause: str | None
    description: str
    source_url: str
    content_sha256: str
    artifact_path: Path
    disposition: Literal["display_only"] = "display_only"
    confirmation_status: Literal["official_confirmed"] = "official_confirmed"

    def citation(self) -> EvidenceCitation:
        excerpt = self.description[:2000].strip() or self.title
        return EvidenceCitation(
            evidence_id=f"event:{self.event_id}",
            source_id=self.event_id,
            source_tier="official",
            url=self.source_url,
            content_sha256=self.content_sha256,
            period=self.announced_at[:10],
            available_at=self.announced_at,
            page=None,
            coordinate=None,
            verbatim_excerpt=excerpt,
            source_format="html",
            locator=(
                f"material-event:{self.announced_at}:{self.sequence}"
            ),
        )


@dataclass(frozen=True, slots=True)
class MaterialEventCollection:
    events: tuple[MaterialEvent, ...]
    status: Literal["available", "blocked"]
    coverage: Literal[
        "complete_bounded_company_year_query",
        "blocked_official_source",
    ]
    missing_reason: str | None
    cache_hits: int
    online_fetches: int


@dataclass(frozen=True, slots=True)
class _ListEvent:
    security_code: str
    company_name: str
    roc_date: str
    spoke_time: str
    title: str
    sequence: str


class EventTransport(Protocol):
    def list_year(
        self, *, market: str, security_code: str, roc_year: int
    ) -> bytes: ...

    def detail(
        self,
        *,
        market: str,
        security_code: str,
        roc_year: int,
        spoke_date: str,
        spoke_time: str,
        sequence: str,
    ) -> bytes: ...


class MopsEventTransport:
    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        self.headers = {
            "User-Agent": "CompanyQualityResearch/0.1",
            "Referer": _LIST_URL,
        }
        self._preloaded = False

    def _preload(self) -> None:
        if self._preloaded:
            return
        request = urllib.request.Request(_LIST_URL, headers=self.headers)
        with self.opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise MaterialEventError("MOPS event landing page unavailable")
            response.read()
        self._preloaded = True

    def _post(self, payload: dict[str, str]) -> bytes:
        self._preload()
        request = urllib.request.Request(
            _DATA_URL,
            data=urllib.parse.urlencode(payload).encode(),
            headers=self.headers,
        )
        with self.opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise MaterialEventError("MOPS material-event query unavailable")
            body = response.read()
        if b"captcha" in body.lower() or "驗證碼" in body.decode("utf-8", "ignore"):
            raise MaterialEventError("MOPS material-event security response")
        return body

    def list_year(
        self, *, market: str, security_code: str, roc_year: int
    ) -> bytes:
        return self._post(
            {
                "step": "1",
                "firstin": "ture",
                "off": "1",
                "keyword4": "",
                "code1": "",
                "TYPEK2": "",
                "checkbtn": "",
                "queryName": "co_id",
                "inpuType": "co_id",
                "TYPEK": "sii" if market == "TWSE" else "otc",
                "co_id": security_code,
                "year": str(roc_year),
                "month": "",
                "b_date": "",
                "e_date": "",
            }
        )

    def detail(
        self,
        *,
        market: str,
        security_code: str,
        roc_year: int,
        spoke_date: str,
        spoke_time: str,
        sequence: str,
    ) -> bytes:
        return self._post(
            {
                "firstin": "true",
                "b_date": "",
                "e_date": "",
                "TYPEK": "sii" if market == "TWSE" else "otc",
                "year": str(roc_year),
                "month": "all",
                "type": "",
                "co_id": security_code,
                "spoke_date": spoke_date,
                "spoke_time": spoke_time,
                "seq_no": sequence,
                "MEETING_STEP": "",
                "MODEL": "",
                "ITEM": "",
                "e_month": "all",
                "step": "2",
                "off": "1",
            }
        )


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[list[str], dict[str, str]]] = []
        self._row: list[str] | None = None
        self._attrs: dict[str, str] = {}
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "tr":
            self._row = []
            self._attrs = {}
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "input" and self._row is not None:
            onclick = values.get("onclick", "")
            if "seq_no.value" in onclick:
                for key in ("seq_no", "spoke_time", "spoke_date", "co_id", "TYPEK"):
                    match = re.search(rf"\.{key}\.value='([^']+)'", onclick)
                    if match is not None:
                        self._attrs[key] = match.group(1)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join(unescape("".join(self._cell)).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append((self._row, dict(self._attrs)))
            self._row = None
            self._attrs = {}
            self._cell = None


def _parse_list(
    body: bytes, *, security_code: str, company_name: str, roc_year: int
) -> tuple[_ListEvent, ...]:
    text = body.decode("utf-8", "replace")
    if "查無" in text:
        return ()
    if security_code not in text:
        raise MaterialEventError("material-event response identity mismatch")
    parser = _TableParser()
    parser.feed(text)
    events: list[_ListEvent] = []
    for cells, attrs in parser.rows:
        if len(cells) < 5 or cells[0] != security_code or not attrs:
            continue
        if not cells[2].startswith(f"{roc_year}/"):
            raise MaterialEventError("material-event response period mismatch")
        events.append(
            _ListEvent(
                security_code=cells[0],
                company_name=cells[1],
                roc_date=cells[2],
                spoke_time=attrs["spoke_time"],
                title=cells[4],
                sequence=attrs["seq_no"],
            )
        )
    if events and company_name not in text and not all(event.company_name for event in events):
        raise MaterialEventError("material-event company name unavailable")
    return tuple(events)


def _roc_date(value: str) -> date:
    match = re.fullmatch(r"(\d{2,3})/(\d{2})/(\d{2})", value)
    if match is None:
        raise MaterialEventError("invalid ROC event date")
    year, month, day = map(int, match.groups())
    return date(year + 1911, month, day)


def _announced_at(event: _ListEvent) -> str:
    event_date = _roc_date(event.roc_date)
    raw_time = event.spoke_time
    if not re.fullmatch(r"\d{5,6}", raw_time):
        raise MaterialEventError("invalid material-event time")
    normalized_time = raw_time.zfill(6)
    value = datetime(
        event_date.year,
        event_date.month,
        event_date.day,
        int(normalized_time[:2]),
        int(normalized_time[2:4]),
        int(normalized_time[4:]),
        tzinfo=_TAIPEI,
    )
    return value.isoformat()


def _parse_detail(
    body: bytes,
    *,
    listed: _ListEvent,
    market: Literal["TWSE", "TPEx"],
    security_code: str,
    roc_year: int,
    path: Path,
) -> MaterialEvent:
    text = body.decode("utf-8", "replace")
    parser = _TableParser()
    parser.feed(text)
    title = ""
    clause: str | None = None
    effective_at: str | None = None
    description = ""
    for cells, _ in parser.rows:
        if cells and cells[0] == "主旨" and len(cells) >= 2:
            title = cells[1]
        elif cells and cells[0] == "符合條款":
            clause = cells[1] if len(cells) >= 2 else None
            if "事實發生日" in cells:
                index = cells.index("事實發生日")
                if index + 1 < len(cells):
                    effective_at = _roc_date(cells[index + 1]).isoformat()
        elif cells and cells[0] == "說明" and len(cells) >= 2:
            description = cells[1]
    if listed.title.replace(" ", "") not in title.replace(" ", ""):
        raise MaterialEventError("material-event detail title mismatch")
    if not description:
        raise MaterialEventError("material-event detail description unavailable")
    announced = _announced_at(listed)
    event_type = _event_type(title)
    digest = sha256(body).hexdigest()
    event_id = (
        f"{market}:{security_code}:{announced}:{listed.sequence}:{digest[:12]}"
    )
    return MaterialEvent(
        event_id=event_id,
        market=market,
        security_code=security_code,
        company_name=listed.company_name,
        roc_year=roc_year,
        sequence=listed.sequence,
        title=title,
        event_type=event_type,
        announced_at=announced,
        effective_at=effective_at,
        clause=clause,
        description=description,
        source_url=_LIST_URL,
        content_sha256=digest,
        artifact_path=path,
    )


def _event_type(title: str) -> Literal[
    "asset_transfer", "capital_injection", "contract_dispute", "financing_support", "other"
]:
    if "分割" in title or "取得" in title or "處分" in title:
        return "asset_transfer"
    if "增資" in title or "投資" in title:
        return "capital_injection"
    if "履約爭議" in title or "仲裁" in title:
        return "contract_dispute"
    if "資金貸與" in title or "背書保證" in title:
        return "financing_support"
    return "other"


def _atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, path)


def _cached_raw(directory: Path, prefix: str) -> tuple[bytes, Path] | None:
    candidates = sorted(directory.glob(f"{prefix}-*.html"), reverse=True)
    for path in candidates:
        digest = path.stem.rsplit("-", 1)[-1]
        body = path.read_bytes()
        if len(digest) == 64 and sha256(body).hexdigest() == digest:
            return body, path
    return None


def _save_raw(directory: Path, prefix: str, body: bytes) -> Path:
    digest = sha256(body).hexdigest()
    path = directory / f"{prefix}-{digest}.html"
    if not path.exists():
        _atomic_write(path, body)
    elif sha256(path.read_bytes()).hexdigest() != digest:
        raise MaterialEventError("cached material-event hash mismatch")
    return path


class MaterialEventCollector:
    def __init__(self, transport: EventTransport | None = None) -> None:
        self.transport = transport or MopsEventTransport()

    def collect(
        self,
        *,
        market: Literal["TWSE", "TPEx"],
        security_code: str,
        company_name: str,
        roc_year: int,
        start_date: date,
        end_date: date,
        as_of: str,
        store_root: Path,
    ) -> MaterialEventCollection:
        decision_time = datetime.fromisoformat(as_of)
        if decision_time.tzinfo is None:
            raise MaterialEventError("as_of must be timezone-aware")
        if start_date > end_date:
            raise MaterialEventError("invalid material-event date window")
        directory = store_root / "events" / market / security_code / str(roc_year)
        hits = 0
        fetches = 0
        cached = _cached_raw(directory, "list")
        if cached is None:
            list_body = self.transport.list_year(
                market=market, security_code=security_code, roc_year=roc_year
            )
            list_path = _save_raw(directory, "list", list_body)
            fetches += 1
        else:
            list_body, list_path = cached
            hits += 1
        try:
            listed_events = _parse_list(
                list_body,
                security_code=security_code,
                company_name=company_name,
                roc_year=roc_year,
            )
        except MaterialEventError:
            list_path.unlink(missing_ok=True)
            raise
        admitted: list[MaterialEvent] = []
        for listed in listed_events:
            announced = datetime.fromisoformat(_announced_at(listed))
            event_date = announced.date()
            if not (start_date <= event_date <= end_date):
                continue
            if announced > decision_time:
                continue
            if not any(term in listed.title for term in _RELEVANT_TERMS):
                continue
            prefix = (
                f"detail-{announced.strftime('%Y%m%d-%H%M%S')}-{listed.sequence}"
            )
            cached_detail = _cached_raw(directory, prefix)
            if cached_detail is None:
                detail_body = self.transport.detail(
                    market=market,
                    security_code=security_code,
                    roc_year=roc_year,
                    spoke_date=announced.strftime("%Y%m%d"),
                    spoke_time=listed.spoke_time,
                    sequence=listed.sequence,
                )
                detail_path = _save_raw(directory, prefix, detail_body)
                fetches += 1
            else:
                detail_body, detail_path = cached_detail
                hits += 1
            admitted.append(
                _parse_detail(
                    detail_body,
                    listed=listed,
                    market=market,
                    security_code=security_code,
                    roc_year=roc_year,
                    path=detail_path,
                )
            )
        return MaterialEventCollection(
            events=tuple(sorted(admitted, key=lambda event: event.announced_at)),
            status="available",
            coverage="complete_bounded_company_year_query",
            missing_reason=None,
            cache_hits=hits,
            online_fetches=fetches,
        )


__all__ = [
    "EventTransport",
    "MaterialEvent",
    "MaterialEventCollection",
    "MaterialEventCollector",
    "MaterialEventError",
]
