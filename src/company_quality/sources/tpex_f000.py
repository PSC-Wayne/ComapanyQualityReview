"""Official TPEx F000 value-chain current and historical PIT source pipeline.

Historical rows are built exclusively from Wayback captures of the official TPEx
page whose capture timestamp is no later than the decision date.  Old captures
remain visible for audit, but are never admitted as fresh memberships.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from typing import Iterable, Literal, Mapping, Protocol, Sequence
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


CURRENT_F000_URL = "https://ic.tpex.org.tw/introduce.php?ic=F000"
WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
_CHAIN_CODE = "F000"
_STALE_AFTER_DAYS = 365
_MARKET_BY_GROUP = {
    "本國上市公司": "TWSE",
    "本國上櫃公司": "TPEx",
    "外國上市公司": "TWSE",
    "外國上櫃公司": "TPEx",
    "本國興櫃公司": "Emerging",
    "創櫃公司": "GoIncubation",
}
SecurityMarket = Literal["TWSE", "TPEx", "Emerging", "GoIncubation"]
IssuerOrigin = Literal["domestic", "foreign"]
DecisionStatus = Literal["AVAILABLE", "STALE_AUDIT_ONLY", "NO_PRE_DECISION_SNAPSHOT"]


class F000SourceError(RuntimeError):
    """Raised when an input cannot be proven to be an official F000 snapshot."""


class ByteTransport(Protocol):
    def get(self, url: str) -> bytes: ...


class UrlLibTransport:
    """Small credential-free HTTP transport for official and archive pages."""

    def __init__(self, *, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def get(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "CompanyQualityResearch/TPEx-F000"})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read()


@dataclass(frozen=True, slots=True)
class SnapshotCapture:
    snapshot_at: datetime
    source_url: str
    replay_url: str
    body: bytes

    def __post_init__(self) -> None:
        if self.snapshot_at.tzinfo is None:
            raise ValueError("snapshot_at must be timezone-aware")
        _validate_official_url(self.source_url)
        _validate_replay_url(self.replay_url)


@dataclass(frozen=True, slots=True)
class F000Node:
    chain_code: str
    chain_name: str
    stage: str
    node_code: str
    node_name: str
    snapshot_at: str
    source_url: str
    replay_url: str | None


@dataclass(frozen=True, slots=True)
class F000Membership:
    chain_code: str
    chain_name: str
    stage: str
    node_code: str
    node_name: str
    company_group: str
    security_code: str
    security_name: str
    security_market: SecurityMarket
    issuer_origin: IssuerOrigin
    issuer_id: str | None
    identity_status: Literal["resolved", "unresolved"]
    snapshot_at: str
    source_url: str
    replay_url: str | None


@dataclass(frozen=True, slots=True)
class ParsedF000Snapshot:
    nodes: tuple[F000Node, ...]
    memberships: tuple[F000Membership, ...]
    report: dict[str, object]


@dataclass(frozen=True, slots=True)
class PITDecision:
    decision_date: str
    snapshot_at: str | None
    snapshot_age_days: int | None
    status: DecisionStatus
    fresh_within_365d: bool | None
    membership_count: int | None
    unique_security_count: int | None
    issuer_coverage: float | None
    replay_url: str | None


@dataclass(frozen=True, slots=True)
class PITMembership:
    decision_date: str
    snapshot_age_days: int
    fresh_within_365d: bool
    chain_code: str
    chain_name: str
    stage: str
    node_code: str
    node_name: str
    company_group: str
    security_code: str
    security_name: str
    security_market: SecurityMarket
    issuer_origin: IssuerOrigin
    issuer_id: str | None
    identity_status: Literal["resolved", "unresolved"]
    snapshot_at: str
    source_url: str
    replay_url: str


@dataclass(frozen=True, slots=True)
class HistoricalPITResult:
    decisions: tuple[PITDecision, ...]
    memberships: tuple[PITMembership, ...]
    report: dict[str, object]


class _F000HTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chain_name_parts: list[str] = []
        self.nodes: list[tuple[str, str, str]] = []
        self.memberships: list[tuple[str, str, str, str]] = []
        self.exclusions: dict[str, int] = {}
        self._capture: str | None = None
        self._capture_parts: list[str] = []
        self._node_code: str | None = None
        self._stage: str | None = None
        self._company_node: str | None = None
        self._company_depth = 0
        self._company_group: str | None = None
        self._link_href: str | None = None

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attrs}

    def _begin_capture(self, kind: str) -> None:
        self._capture = kind
        self._capture_parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        if self._company_node is not None and tag == "div":
            self._company_depth += 1
        if tag == "div":
            element_id = values.get("id", "")
            if element_id.startswith("companyList_"):
                self._company_node = element_id.removeprefix("companyList_").upper()
                self._company_depth = 1
                self._company_group = None
            elif element_id.startswith("ic_link_"):
                self._node_code = element_id.removeprefix("ic_link_").upper()
                self._begin_capture("node")
            elif "chain-title-panel" in values.get("class", "").split():
                self._begin_capture("stage")
        elif tag == "h3" and self._company_node is None:
            self._begin_capture("chain_name")
        elif tag == "b" and self._company_node is not None:
            self._begin_capture("group")
        elif tag == "a" and self._company_node is not None:
            self._link_href = values.get("href", "")
            self._begin_capture("company")

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        text = " ".join("".join(self._capture_parts).split())
        if tag == "h3" and self._capture == "chain_name":
            self.chain_name_parts.append(text)
            self._capture = None
        elif tag == "b" and self._capture == "group":
            self._company_group = text
            self._capture = None
        elif tag == "a" and self._capture == "company":
            self._record_company(text)
            self._capture = None
            self._link_href = None
        elif tag == "div" and self._capture == "stage":
            self._stage = text
            self._capture = None
        elif tag == "div" and self._capture == "node":
            if self._node_code is not None:
                self.nodes.append((self._stage or "", self._node_code, text))
            self._node_code = None
            self._capture = None

        if tag == "div" and self._company_node is not None:
            self._company_depth -= 1
            if self._company_depth == 0:
                self._company_node = None
                self._company_group = None

    def _record_company(self, name: str) -> None:
        group = self._company_group or ""
        group_kind = _group_kind(group)
        if group_kind is None:
            reason = "unlisted_foreign_company" if "外國" in group else "unsupported_company_group"
            self.exclusions[reason] = self.exclusions.get(reason, 0) + 1
            return
        query = parse_qs(urlparse(self._link_href or "").query)
        code = (query.get("stk_code") or [""])[0].strip()
        if not re.fullmatch(r"[0-9A-Z]{4,8}", code) or not name or self._company_node is None:
            self.exclusions["malformed_domestic_membership"] = (
                self.exclusions.get("malformed_domestic_membership", 0) + 1
            )
            return
        self.memberships.append((self._company_node, group, code, name))


def _group_kind(group: str) -> SecurityMarket | None:
    normalized = re.sub(r"\s*\(.*?\)\s*$", "", group).strip()
    return _MARKET_BY_GROUP.get(normalized)  # type: ignore[return-value]


def _iso_utc(value: datetime | str) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise F000SourceError("snapshot timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def _validate_official_url(url: str) -> None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if (
        parsed.scheme not in {"http", "https"}
        or (parsed.hostname or "").lower() != "ic.tpex.org.tw"
        or parsed.path.rstrip("/") != "/introduce.php"
        or query.get("ic") != [_CHAIN_CODE]
    ):
        raise F000SourceError("source is not the official TPEx F000 page")


def _validate_replay_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "web.archive.org":
        raise F000SourceError("historical source is not a Wayback replay")
    match = re.match(r"^/web/\d{14}(?:id_)?/(https?://.+)$", parsed.path + ("?" + parsed.query if parsed.query else ""))
    if not match:
        raise F000SourceError("historical Wayback replay URL is malformed")
    _validate_official_url(match.group(1))


def parse_f000_snapshot(
    body: bytes,
    *,
    snapshot_at: datetime | str,
    source_url: str,
    replay_url: str | None,
    issuer_by_security_code: Mapping[str, str] | None = None,
) -> ParsedF000Snapshot:
    """Parse one official page capture without executing scripts or using a private API."""
    _validate_official_url(source_url)
    if replay_url is not None:
        _validate_replay_url(replay_url)
    snapshot_iso = _iso_utc(snapshot_at)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise F000SourceError("official TPEx F000 page must be UTF-8") from exc
    parser = _F000HTMLParser()
    parser.feed(text)
    chain_headers = [
        value.removesuffix("產業鏈簡介").strip()
        for value in parser.chain_name_parts
        if value.endswith("產業鏈簡介")
    ]
    if not chain_headers:
        raise F000SourceError("official TPEx F000 chain heading is missing")
    chain_name = chain_headers[0]

    raw_nodes: dict[str, tuple[str, str]] = {}
    for stage, code, name in parser.nodes:
        if stage not in {"上游", "中游", "下游"} or not re.fullmatch(r"F[A-Z0-9]{3}", code) or not name:
            raise F000SourceError("official TPEx F000 node is malformed")
        value = (stage, name)
        if code in raw_nodes and raw_nodes[code] != value:
            raise F000SourceError("official TPEx F000 node code is conflicting")
        raw_nodes[code] = value
    if not raw_nodes:
        raise F000SourceError("official TPEx F000 page contains no nodes")

    nodes = tuple(
        F000Node(
            chain_code=_CHAIN_CODE,
            chain_name=chain_name,
            stage=stage,
            node_code=code,
            node_name=name,
            snapshot_at=snapshot_iso,
            source_url=source_url,
            replay_url=replay_url,
        )
        for code, (stage, name) in sorted(raw_nodes.items(), key=lambda item: parser.nodes.index((item[1][0], item[0], item[1][1])))
    )
    issuers = issuer_by_security_code or {}
    unique: dict[tuple[str, str, str], F000Membership] = {}
    for node_code, group, code, name in parser.memberships:
        node = raw_nodes.get(node_code)
        if node is None:
            raise F000SourceError("membership references an unknown F000 node")
        market = _group_kind(group)
        if market is None:
            continue
        issuer_id = str(issuers.get(code, "")).strip() or None
        row = F000Membership(
            chain_code=_CHAIN_CODE,
            chain_name=chain_name,
            stage=node[0],
            node_code=node_code,
            node_name=node[1],
            company_group=group,
            security_code=code,
            security_name=name,
            security_market=market,
            issuer_origin="foreign" if group.startswith("外國") else "domestic",
            issuer_id=issuer_id,
            identity_status="resolved" if issuer_id else "unresolved",
            snapshot_at=snapshot_iso,
            source_url=source_url,
            replay_url=replay_url,
        )
        key = (node_code, group, code)
        prior = unique.get(key)
        if prior is not None and prior.security_name != name:
            raise F000SourceError("duplicate F000 membership has conflicting company names")
        unique[key] = row
    memberships = tuple(sorted(unique.values(), key=lambda row: (row.node_code, row.security_market, row.security_code)))
    security_codes = {row.security_code for row in memberships}
    resolved_codes = {row.security_code for row in memberships if row.identity_status == "resolved"}
    report: dict[str, object] = {
        "schema_version": "TPExF000SnapshotReport.v1",
        "source_kind": "wayback_official_replay" if replay_url else "current_official_page",
        "chain_code": _CHAIN_CODE,
        "chain_name": chain_name,
        "snapshot_at": snapshot_iso,
        "source_url": source_url,
        "replay_url": replay_url,
        "node_count": len(nodes),
        "deduplicated_membership_count": len(memberships),
        "unique_security_count": len(security_codes),
        "resolved_unique_security_count": len(resolved_codes),
        "issuer_coverage": len(resolved_codes) / len(security_codes) if security_codes else 0.0,
        "exclusion_counts": dict(sorted(parser.exclusions.items())),
        "market_is_not_route_key": True,
    }
    return ParsedF000Snapshot(nodes, memberships, report)


def _decision_day(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise F000SourceError(f"invalid decision date: {value}") from exc
    if parsed.isoformat() != value:
        raise F000SourceError(f"invalid decision date: {value}")
    return parsed


def build_historical_pit(
    *,
    decision_dates: Iterable[str],
    captures: Sequence[SnapshotCapture],
    issuer_by_security_code: Mapping[str, str] | None = None,
) -> HistoricalPITResult:
    """Select the latest capture at/before each decision date; never use current data."""
    ordered_captures = sorted(captures, key=lambda item: item.snapshot_at)
    decisions: list[PITDecision] = []
    memberships: list[PITMembership] = []
    missing: list[str] = []
    stale: list[str] = []
    parsed_by_replay: dict[str, ParsedF000Snapshot] = {}
    exclusion_counts: dict[str, int] = {}
    for decision_value in sorted(set(decision_dates)):
        decision = _decision_day(decision_value)
        cutoff = datetime.combine(decision, time.max, tzinfo=timezone.utc)
        eligible = [item for item in ordered_captures if item.snapshot_at.astimezone(timezone.utc) <= cutoff]
        if not eligible:
            missing.append(decision_value)
            decisions.append(PITDecision(decision_value, None, None, "NO_PRE_DECISION_SNAPSHOT", None, None, None, None, None))
            continue
        capture = eligible[-1]
        age = (decision - capture.snapshot_at.astimezone(timezone.utc).date()).days
        if age < 0:
            raise F000SourceError("post-decision snapshot cannot enter historical PIT")
        fresh = age <= _STALE_AFTER_DAYS
        status: DecisionStatus = "AVAILABLE" if fresh else "STALE_AUDIT_ONLY"
        if not fresh:
            stale.append(decision_value)
        parsed = parsed_by_replay.get(capture.replay_url)
        if parsed is None:
            parsed = parse_f000_snapshot(
                capture.body,
                snapshot_at=capture.snapshot_at,
                source_url=capture.source_url,
                replay_url=capture.replay_url,
                issuer_by_security_code=issuer_by_security_code,
            )
            parsed_by_replay[capture.replay_url] = parsed
        for row in parsed.memberships:
            assert row.replay_url is not None
            memberships.append(PITMembership(
                decision_date=decision_value,
                snapshot_age_days=age,
                fresh_within_365d=fresh,
                chain_code=row.chain_code,
                chain_name=row.chain_name,
                stage=row.stage,
                node_code=row.node_code,
                node_name=row.node_name,
                company_group=row.company_group,
                security_code=row.security_code,
                security_name=row.security_name,
                security_market=row.security_market,
                issuer_origin=row.issuer_origin,
                issuer_id=row.issuer_id,
                identity_status=row.identity_status,
                snapshot_at=row.snapshot_at,
                source_url=row.source_url,
                replay_url=row.replay_url,
            ))
        parsed_exclusions = parsed.report["exclusion_counts"]
        if not isinstance(parsed_exclusions, dict):
            raise F000SourceError("snapshot exclusion report is malformed")
        for reason, count in parsed_exclusions.items():
            exclusion_counts[str(reason)] = exclusion_counts.get(str(reason), 0) + int(str(count))
        unique_security_count = len({row.security_code for row in parsed.memberships})
        resolved_security_count = len({
            row.security_code
            for row in parsed.memberships
            if row.identity_status == "resolved"
        })
        decisions.append(PITDecision(
            decision_date=decision_value,
            snapshot_at=_iso_utc(capture.snapshot_at),
            snapshot_age_days=age,
            status=status,
            fresh_within_365d=fresh,
            membership_count=len(parsed.memberships),
            unique_security_count=unique_security_count,
            issuer_coverage=(
                resolved_security_count / unique_security_count
                if unique_security_count else 0.0
            ),
            replay_url=capture.replay_url,
        ))
    fresh_count = sum(row.fresh_within_365d for row in memberships)
    unique_security_codes = {row.security_code for row in memberships}
    resolved_security_codes = {
        row.security_code for row in memberships if row.identity_status == "resolved"
    }
    report: dict[str, object] = {
        "schema_version": "TPExF000HistoricalPITReport.v1",
        "historical_source": "Wayback replay of official TPEx pages",
        "decision_date_count": len(decisions),
        "missing_decision_dates": missing,
        "stale_audit_only_decision_dates": stale,
        "deduplicated_membership_count": len(memberships),
        "fresh_membership_count": fresh_count,
        "audit_only_membership_count": len(memberships) - fresh_count,
        "unique_security_count": len({row.security_code for row in memberships}),
        "resolved_unique_security_count": len({row.security_code for row in memberships if row.identity_status == "resolved"}),
        "current_fill_used": False,
        "market_is_not_route_key": True,
    }
    return HistoricalPITResult(tuple(decisions), tuple(memberships), report)


def collect_current_f000(
    *,
    retrieved_at: datetime,
    transport: ByteTransport | None = None,
    issuer_by_security_code: Mapping[str, str] | None = None,
) -> ParsedF000Snapshot:
    """Download and parse the live official page, with acquisition time supplied by caller."""
    client = transport or UrlLibTransport()
    body = client.get(CURRENT_F000_URL)
    return parse_f000_snapshot(
        body,
        snapshot_at=retrieved_at,
        source_url=CURRENT_F000_URL,
        replay_url=None,
        issuer_by_security_code=issuer_by_security_code,
    )


def discover_wayback_captures(
    *,
    decision_dates: Iterable[str],
    transport: ByteTransport | None = None,
) -> tuple[SnapshotCapture, ...]:
    """Discover and download only captures selected by conservative PIT cutoffs."""
    client = transport or UrlLibTransport()
    query = (
        f"{WAYBACK_CDX_URL}?url={quote(CURRENT_F000_URL, safe='')}"
        "&output=json&filter=statuscode:200&filter=mimetype:text/html"
        "&fl=timestamp,original&collapse=digest"
    )
    try:
        rows = json.loads(client.get(query))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise F000SourceError("Wayback CDX response is not valid JSON") from exc
    if not isinstance(rows, list) or not rows or rows[0] != ["timestamp", "original"]:
        raise F000SourceError("Wayback CDX response has unexpected columns")
    indexed: list[tuple[datetime, str]] = []
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) != 2 or not re.fullmatch(r"\d{14}", str(row[0])):
            raise F000SourceError("Wayback CDX capture row is malformed")
        _validate_official_url(str(row[1]))
        stamp = datetime.strptime(str(row[0]), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        indexed.append((stamp, str(row[1])))
    selected: dict[datetime, str] = {}
    for value in sorted(set(decision_dates)):
        cutoff = datetime.combine(_decision_day(value), time.max, tzinfo=timezone.utc)
        eligible = [item for item in indexed if item[0] <= cutoff]
        if eligible:
            selected[max(eligible, key=lambda item: item[0])[0]] = max(eligible, key=lambda item: item[0])[1]
    captures = []
    for stamp, original in sorted(selected.items()):
        timestamp = stamp.strftime("%Y%m%d%H%M%S")
        replay = f"https://web.archive.org/web/{timestamp}id_/{original}"
        captures.append(SnapshotCapture(stamp, original, replay, client.get(replay)))
    return tuple(captures)


def materialize_f000(
    output_path: Path,
    *,
    current: ParsedF000Snapshot,
    historical: HistoricalPITResult,
) -> str:
    """Atomically write one deterministic JSON artifact and return its SHA-256."""
    payload = {
        "schema_version": "TPExF000Materialization.v1",
        "current": {
            "nodes": [asdict(row) for row in current.nodes],
            "memberships": [asdict(row) for row in current.memberships],
            "report": current.report,
        },
        "historical": {
            "decisions": [asdict(row) for row in historical.decisions],
            "memberships": [asdict(row) for row in historical.memberships],
            "report": historical.report,
        },
    }
    body = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
        directory_fd = os.open(output_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256(body).hexdigest()


__all__ = [
    "CURRENT_F000_URL",
    "F000Membership",
    "F000Node",
    "F000SourceError",
    "HistoricalPITResult",
    "PITDecision",
    "PITMembership",
    "ParsedF000Snapshot",
    "SnapshotCapture",
    "UrlLibTransport",
    "build_historical_pit",
    "collect_current_f000",
    "discover_wayback_captures",
    "materialize_f000",
    "parse_f000_snapshot",
]
