"""General official TPEx value-chain discovery, current ingestion, and PIT availability.

The official index is the chain registry.  Current pages are never substituted for
historical evidence: callers must inspect the archive matrix before historical use.
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
from typing import Iterable, Literal, Mapping, Sequence
from urllib.parse import parse_qs, quote, urljoin, urlparse
from uuid import uuid4

from company_quality.sources.tpex_f000 import (
    ByteTransport,
    F000Membership,
    F000Node,
    F000SourceError,
    UrlLibTransport,
    parse_chain_snapshot,
)

INDEX_URL = "https://ic.tpex.org.tw/"
WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
ArchiveState = Literal["CURRENT_ONLY", "FRESH_PIT", "STALE", "UNAVAILABLE"]
_STALE_AFTER_DAYS = 365

# General names preserve the accepted F000 wire shape without copying its parser.
ValueChainNode = F000Node
ValueChainMembership = F000Membership


@dataclass(frozen=True, slots=True)
class ValueChain:
    chain_code: str
    chain_name: str
    source_url: str
    page_url: str


@dataclass(frozen=True, slots=True)
class CurrentValueChains:
    chains: tuple[ValueChain, ...]
    nodes: tuple[ValueChainNode, ...]
    memberships: tuple[ValueChainMembership, ...]
    report: dict[str, object]


@dataclass(frozen=True, slots=True)
class ArchiveCaptureIndex:
    chain_code: str
    snapshot_at: datetime
    replay_url: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z0-9]{4}", self.chain_code):
            raise ValueError("chain_code must be four uppercase alphanumeric characters")
        if self.snapshot_at.tzinfo is None:
            raise ValueError("snapshot_at must be timezone-aware")
        parsed = urlparse(self.replay_url)
        if parsed.scheme != "https" or parsed.hostname != "web.archive.org":
            raise ValueError("replay_url must be an HTTPS Wayback replay")


@dataclass(frozen=True, slots=True)
class ArchiveDiscoveryResult:
    captures: tuple[ArchiveCaptureIndex, ...]
    report: dict[str, object]


@dataclass(frozen=True, slots=True)
class ArchiveAvailability:
    chain_code: str
    chain_name: str
    decision_date: str
    decision_year: int
    state: ArchiveState
    snapshot_at: str | None
    snapshot_age_days: int | None
    replay_url: str | None
    historical_membership_allowed: bool
    current_fill_used: bool


@dataclass(frozen=True, slots=True)
class ArchiveAvailabilityMatrix:
    rows: tuple[ArchiveAvailability, ...]
    report: dict[str, object]


class _IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if "introduce.php" in href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._parts).split())))
            self._href = None
            self._parts = []


def _official_index_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "ic.tpex.org.tw"
        or parsed.path.rstrip("/") != ""
        or parsed.query
    ):
        raise F000SourceError("source is not the official TPEx value-chain index")


def _official_archived_chain_url(url: str, expected_code: str) -> None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if (
        parsed.scheme not in {"http", "https"}
        or (parsed.hostname or "").lower() != "ic.tpex.org.tw"
        or parsed.port not in {None, 80, 443}
        or parsed.path != "/introduce.php"
        or query != {"ic": [expected_code]}
    ):
        raise F000SourceError("Wayback CDX capture authority is unexpected")


def discover_chains(body: bytes, *, source_url: str = INDEX_URL) -> tuple[ValueChain, ...]:
    """Discover chain codes/names in official index order, removing exact repeats."""
    _official_index_url(source_url)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise F000SourceError("official TPEx value-chain index must be UTF-8") from exc
    parser = _IndexParser()
    parser.feed(text)
    result: list[ValueChain] = []
    seen: dict[str, str] = {}
    for href, name in parser.links:
        page_url = urljoin(source_url, href)
        parsed = urlparse(page_url)
        query = parse_qs(parsed.query)
        code = (query.get("ic") or [""])[0].strip().upper()
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower() != "ic.tpex.org.tw"
            or parsed.path != "/introduce.php"
            or not re.fullmatch(r"[A-Z0-9]{4}", code)
            or not name
        ):
            continue
        canonical = f"https://ic.tpex.org.tw/introduce.php?ic={code}"
        prior = seen.get(code)
        if prior is not None:
            if prior != name:
                raise F000SourceError(f"official TPEx index has conflicting names for {code}")
            continue
        seen[code] = name
        result.append(ValueChain(code, name, source_url, canonical))
    if not result:
        raise F000SourceError("official TPEx index contains no parseable chains")
    return tuple(result)


def collect_current_value_chains(
    *,
    retrieved_at: datetime,
    transport: ByteTransport | None = None,
    issuer_by_security_code: Mapping[str, str] | None = None,
) -> CurrentValueChains:
    """Discover the live registry and materialize all parseable current chain pages."""
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    client = transport or UrlLibTransport()
    chains = discover_chains(client.get(INDEX_URL), source_url=INDEX_URL)
    nodes: list[ValueChainNode] = []
    memberships: list[ValueChainMembership] = []
    parsed_chains: list[ValueChain] = []
    exceptions: list[dict[str, str]] = []
    for chain in chains:
        try:
            parsed = parse_chain_snapshot(
                client.get(chain.page_url),
                chain_code=chain.chain_code,
                snapshot_at=retrieved_at,
                source_url=chain.page_url,
                replay_url=None,
                issuer_by_security_code=issuer_by_security_code,
            )
        except Exception as exc:
            exceptions.append({
                "chain_code": chain.chain_code,
                "chain_name": chain.chain_name,
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
            continue
        parsed_chains.append(chain)
        nodes.extend(parsed.nodes)
        memberships.extend(parsed.memberships)
    securities = {row.security_code for row in memberships}
    resolved = {row.security_code for row in memberships if row.identity_status == "resolved"}
    report: dict[str, object] = {
        "schema_version": "TPExCurrentValueChainsReport.v1",
        "source_url": INDEX_URL,
        "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "discovered_chain_count": len(chains),
        "parsed_chain_count": len(parsed_chains),
        "parser_exception_count": len(exceptions),
        "parser_exceptions": exceptions,
        "node_count": len(nodes),
        "deduplicated_membership_count": len(memberships),
        "unique_security_count": len(securities),
        "resolved_unique_security_count": len(resolved),
        "issuer_coverage": len(resolved) / len(securities) if securities else 0.0,
        "market_is_not_route_key": True,
        "historical_membership_enabled": False,
    }
    return CurrentValueChains(
        tuple(parsed_chains), tuple(nodes), tuple(memberships), report
    )


def _decision_day(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise F000SourceError(f"invalid decision date: {value}") from exc
    if parsed.isoformat() != value:
        raise F000SourceError(f"invalid decision date: {value}")
    return parsed


def discover_archive_capture_index(
    *,
    chains: Sequence[ValueChain],
    transport: ByteTransport | None = None,
) -> ArchiveDiscoveryResult:
    """Discover Wayback timestamps for each official chain without downloading pages."""
    client = transport or UrlLibTransport()
    captures: list[ArchiveCaptureIndex] = []
    exceptions: list[dict[str, str]] = []
    for chain in chains:
        query = (
            f"{WAYBACK_CDX_URL}?url={quote(chain.page_url, safe='')}"
            "&output=json&filter=statuscode:200&filter=mimetype:text/html"
            "&fl=timestamp,original&collapse=digest"
        )
        try:
            rows = json.loads(client.get(query))
            if not isinstance(rows, list) or not rows or rows[0] != ["timestamp", "original"]:
                raise F000SourceError("Wayback CDX response has unexpected columns")
            for row in rows[1:]:
                if not isinstance(row, list) or len(row) != 2 or not re.fullmatch(r"\d{14}", str(row[0])):
                    raise F000SourceError("Wayback CDX capture row is malformed")
                original = str(row[1])
                _official_archived_chain_url(original, chain.chain_code)
                stamp = datetime.strptime(str(row[0]), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                captures.append(ArchiveCaptureIndex(
                    chain.chain_code,
                    stamp,
                    f"https://web.archive.org/web/{row[0]}id_/{original}",
                ))
        except Exception as exc:
            exceptions.append({
                "chain_code": chain.chain_code,
                "chain_name": chain.chain_name,
                "error_type": type(exc).__name__,
                "message": str(exc),
            })
    unique = {
        (row.chain_code, row.snapshot_at, row.replay_url): row for row in captures
    }
    ordered = tuple(sorted(unique.values(), key=lambda row: (row.chain_code, row.snapshot_at, row.replay_url)))
    return ArchiveDiscoveryResult(ordered, {
        "schema_version": "TPExArchiveDiscoveryReport.v1",
        "chain_count": len(chains),
        "capture_count": len(ordered),
        "exception_count": len(exceptions),
        "exceptions": exceptions,
    })


def produce_archive_availability_matrix(
    *,
    chains: Sequence[ValueChain],
    decision_dates: Iterable[str],
    captures: Sequence[ArchiveCaptureIndex],
    current_snapshot_at: datetime,
) -> ArchiveAvailabilityMatrix:
    """Classify each chain/date without ever treating current data as historical."""
    if current_snapshot_at.tzinfo is None:
        raise ValueError("current_snapshot_at must be timezone-aware")
    decisions = sorted(set(decision_dates))
    known = {chain.chain_code for chain in chains}
    unknown = sorted({capture.chain_code for capture in captures} - known)
    if unknown:
        raise F000SourceError(f"archive captures reference unknown chains: {', '.join(unknown)}")
    captures_by_chain: dict[str, list[ArchiveCaptureIndex]] = {code: [] for code in known}
    for capture in captures:
        captures_by_chain[capture.chain_code].append(capture)
    for values in captures_by_chain.values():
        values.sort(key=lambda row: row.snapshot_at)

    rows: list[ArchiveAvailability] = []
    current_day = current_snapshot_at.astimezone(timezone.utc).date()
    for chain in chains:
        for decision_value in decisions:
            decision = _decision_day(decision_value)
            if decision >= current_day:
                rows.append(ArchiveAvailability(
                    chain.chain_code, chain.chain_name, decision_value, decision.year,
                    "CURRENT_ONLY", current_snapshot_at.astimezone(timezone.utc).isoformat(),
                    0 if decision == current_day else None, None, False, False,
                ))
                continue
            cutoff = datetime.combine(decision, time.max, tzinfo=timezone.utc)
            eligible = [
                capture for capture in captures_by_chain[chain.chain_code]
                if capture.snapshot_at.astimezone(timezone.utc) <= cutoff
            ]
            if not eligible:
                rows.append(ArchiveAvailability(
                    chain.chain_code, chain.chain_name, decision_value, decision.year,
                    "UNAVAILABLE", None, None, None, False, False,
                ))
                continue
            capture = eligible[-1]
            age = (decision - capture.snapshot_at.astimezone(timezone.utc).date()).days
            state: ArchiveState = "FRESH_PIT" if age <= _STALE_AFTER_DAYS else "STALE"
            rows.append(ArchiveAvailability(
                chain.chain_code, chain.chain_name, decision_value, decision.year,
                state, capture.snapshot_at.astimezone(timezone.utc).isoformat(), age,
                capture.replay_url, state == "FRESH_PIT", False,
            ))
    state_counts = {state: sum(row.state == state for row in rows) for state in (
        "CURRENT_ONLY", "FRESH_PIT", "STALE", "UNAVAILABLE"
    )}
    report: dict[str, object] = {
        "schema_version": "TPExArchiveAvailabilityMatrix.v1",
        "chain_count": len(chains),
        "decision_date_count": len(decisions),
        "row_count": len(rows),
        "state_counts": state_counts,
        "freshness_days": _STALE_AFTER_DAYS,
        "current_fill_used": False,
        "historical_membership_allowed_states": ["FRESH_PIT"],
    }
    return ArchiveAvailabilityMatrix(tuple(rows), report)


def materialize_value_chains(
    output_path: Path,
    *,
    current: CurrentValueChains,
    archive_availability: ArchiveAvailabilityMatrix,
) -> str:
    """Atomically write deterministic current data plus the mandatory archive matrix."""
    payload = {
        "schema_version": "TPExValueChainMaterialization.v1",
        "current": {
            "chains": [asdict(row) for row in current.chains],
            "nodes": [asdict(row) for row in current.nodes],
            "memberships": [asdict(row) for row in current.memberships],
            "report": current.report,
        },
        "archive_availability": {
            "rows": [asdict(row) for row in archive_availability.rows],
            "report": archive_availability.report,
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
    "INDEX_URL", "WAYBACK_CDX_URL", "ArchiveAvailability", "ArchiveAvailabilityMatrix",
    "ArchiveCaptureIndex", "ArchiveDiscoveryResult", "ArchiveState", "CurrentValueChains", "ValueChain",
    "ValueChainMembership", "ValueChainNode", "collect_current_value_chains",
    "discover_archive_capture_index", "discover_chains", "materialize_value_chains",
    "produce_archive_availability_matrix",
]
