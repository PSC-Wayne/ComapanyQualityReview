"""Safe, bounded acquisition of official MOPS F04 annual reports.

A valid listing is the only response allowed to establish document absence.  Security
pages, malformed HTML, identity mismatches, transient-link failures, invalid PDFs,
and transport errors instead produce ``SOURCE_UNAVAILABLE`` after bounded retries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from html import unescape
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import threading
import time as time_module
from typing import Callable, Protocol
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4


_LISTING_URL = "https://doc.twse.com.tw/server-java/t57sb01"
_OFFICIAL_HOST = "doc.twse.com.tw"
_TAIPEI = timezone(timedelta(hours=8))
_SECURITY_MARKERS = (
    "request rejected",
    "support id",
    "access denied",
    "captcha",
    "驗證碼",
    "安全驗證",
    "service unavailable",
)


class AnnualReportSourceState(StrEnum):
    AVAILABLE = "AVAILABLE"
    DOCUMENT_NOT_LISTED = "DOCUMENT_NOT_LISTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class AnnualReportDocument:
    security_code: str
    report_year: int
    filename: str
    available_at: str
    listing_url: str


@dataclass(frozen=True, slots=True)
class AnnualReportProbe:
    security_code: str
    report_year: int
    decision_date: str
    state: AnnualReportSourceState
    listing_url: str
    request_count: int
    detail: str
    document: AnnualReportDocument | None = None
    pdf_url: str | None = None
    pdf_path: Path | None = None
    failure_kind: str | None = None


class MopsTransportProtocol(Protocol):
    def request(self, method: str, url: str, data: bytes | None = None) -> bytes: ...


class UrlLibMopsTransport:
    """Minimal stdlib transport; policy (throttle/retry) lives in the acquirer."""

    def __init__(self, *, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds
        self.opener = urllib.request.build_opener()

    def request(self, method: str, url: str, data: bytes | None = None) -> bytes:
        headers = {
            "User-Agent": "CompanyQualityResearch/0.1 MOPS-F04",
            "Referer": _LISTING_URL,
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(
            url, data=data, headers=headers, method=method.upper()
        )
        with self.opener.open(request, timeout=self.timeout_seconds) as response:
            return response.read()


class _ResponseFailure(RuntimeError):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        for name in ("href", "src", "content"):
            if values.get(name):
                self.links.append(values[name])


def _decode_html(body: bytes) -> str:
    for encoding in ("utf-8", "big5"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise _ResponseFailure("malformed_response", "unsupported MOPS response encoding")


def _security_response(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _SECURITY_MARKERS)


def _listing_url(security_code: str, report_year: int) -> str:
    query = urllib.parse.urlencode(
        {
            "step": "1",
            "colorchg": "1",
            "kind": "F",
            "co_id": security_code,
            "year": str(report_year - 1910),
            "seamon": "",
            "mtype": "F",
        }
    )
    return f"{_LISTING_URL}?{query}"


def _parse_available_at(row: str) -> datetime:
    match = re.search(
        r"(?<!\d)(\d{3})[/-](\d{1,2})[/-](\d{1,2})\s+"
        r"(\d{1,2}):(\d{2}):(\d{2})(?!\d)",
        unescape(row),
    )
    if match is None:
        raise _ResponseFailure(
            "malformed_response", "F04 listing row has no official upload timestamp"
        )
    roc_year, month, day, hour, minute, second = map(int, match.groups())
    try:
        return datetime(
            roc_year + 1911,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=_TAIPEI,
        )
    except ValueError as exc:
        raise _ResponseFailure(
            "malformed_response", "F04 listing row has an invalid upload timestamp"
        ) from exc


def _parse_listing(
    body: bytes, *, security_code: str, listing_url: str
) -> tuple[AnnualReportDocument, ...]:
    text = _decode_html(body)
    if _security_response(text):
        raise _ResponseFailure("security_response", "MOPS returned a security page")
    lowered = text.lower()
    valid_shell = (
        "公開資訊觀測站" in text
        and "t57sb01" in lowered
        and "<table" in lowered
        and "公司代號" in text
        and ("檔案名稱" in text or "查無" in text)
    )
    if not valid_shell:
        raise _ResponseFailure(
            "malformed_response", "response is not a recognized MOPS F04 listing"
        )

    hidden_codes = re.findall(
        r"<input\b[^>]*\bname\s*=\s*['\"]?co_id['\"]?[^>]*\bvalue\s*=\s*['\"]([^'\"]+)",
        text,
        flags=re.IGNORECASE,
    )
    if hidden_codes and security_code not in {value.strip() for value in hidden_codes}:
        raise _ResponseFailure(
            "malformed_response", "MOPS listing security identity mismatch"
        )

    documents: dict[tuple[str, str], AnnualReportDocument] = {}
    all_f04_codes: set[str] = set()
    for row in re.findall(
        r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.IGNORECASE | re.DOTALL
    ):
        filenames = re.findall(
            r"(?<![0-9A-Za-z_])(\d{4}_([0-9A-Za-z]{4,8})_\d{8}F04\.pdf)(?![0-9A-Za-z_.])",
            unescape(row),
            flags=re.IGNORECASE,
        )
        if not filenames:
            continue
        available = _parse_available_at(row)
        for filename, code in filenames:
            all_f04_codes.add(code)
            if code != security_code:
                continue
            normalized = filename[:-7] + "F04.pdf"
            document = AnnualReportDocument(
                security_code=security_code,
                report_year=int(normalized[:4]),
                filename=normalized,
                available_at=available.isoformat(),
                listing_url=listing_url,
            )
            documents[(normalized, document.available_at)] = document
    if all_f04_codes and security_code not in all_f04_codes:
        raise _ResponseFailure(
            "malformed_response", "MOPS listing rows belong to another security"
        )
    return tuple(
        sorted(documents.values(), key=lambda item: (item.available_at, item.filename))
    )


def _parse_pdf_url(body: bytes, filename: str) -> str:
    text = _decode_html(body)
    if _security_response(text):
        raise _ResponseFailure("security_response", "MOPS step-9 returned a security page")
    parser = _LinkParser()
    parser.feed(text)
    candidates = list(parser.links)
    candidates.extend(
        re.findall(r"https?://[^\s'\"<>]+", unescape(text), flags=re.IGNORECASE)
    )
    for candidate in candidates:
        # Meta-refresh content can be "0; URL=/pdf/...".
        match = re.search(r"(?:url\s*=\s*)?([^;\s]+\.pdf(?:\?[^\s]*)?)", candidate, re.I)
        raw = match.group(1) if match else candidate
        url = urllib.parse.urljoin(_LISTING_URL, raw)
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() == _OFFICIAL_HOST
            and parsed.path.startswith("/pdf/")
            and Path(urllib.parse.unquote(parsed.path)).name == filename
        ):
            return url
    raise _ResponseFailure(
        "malformed_response", "MOPS step-9 response has no matching official PDF link"
    )


def _validate_pdf(body: bytes) -> bytes:
    if body.startswith(b"%PDF-"):
        return body
    text = body.decode("utf-8", "ignore")
    if _security_response(text):
        raise _ResponseFailure("security_response", "MOPS PDF request returned a security page")
    raise _ResponseFailure("malformed_response", "MOPS PDF response is not a PDF")


def _is_inside_git_worktree(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in (path, *path.parents))


class MopsAnnualReportAcquirer:
    """Deduplicated, globally throttled official MOPS annual-report acquisition."""

    def __init__(
        self,
        *,
        transport: MopsTransportProtocol | None = None,
        cache_root: Path | None = None,
        clock: Callable[[], float] = time_module.monotonic,
        sleeper: Callable[[float], None] = time_module.sleep,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        root = (
            cache_root
            or Path(
                os.environ.get(
                    "CQR_MOPS_CACHE",
                    Path.home() / ".cache" / "company-quality" / "mops-annual-reports",
                )
            )
        ).expanduser().resolve()
        if _is_inside_git_worktree(root):
            raise ValueError("MOPS cache must be outside a Git worktree")
        self.transport = transport or UrlLibMopsTransport()
        self.cache_root = root
        self.clock = clock
        self.sleeper = sleeper
        self.max_attempts = max_attempts
        self._last_request_at: float | None = None
        self._request_total = 0
        self._results: dict[tuple[str, int], AnnualReportProbe] = {}
        self._probe_log: list[AnnualReportProbe] = []
        self._lock = threading.RLock()

    @property
    def probes(self) -> tuple[AnnualReportProbe, ...]:
        with self._lock:
            return tuple(self._probe_log)

    def _request(self, method: str, url: str, data: bytes | None = None) -> bytes:
        if self._last_request_at is not None:
            remaining = 1.0 - (self.clock() - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
        self._last_request_at = self.clock()
        self._request_total += 1
        return self.transport.request(method, url, data)

    def _bounded(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None,
        parse: Callable[[bytes], object],
    ) -> tuple[object | None, _ResponseFailure | None]:
        last: _ResponseFailure | None = None
        for attempt in range(self.max_attempts):
            try:
                return parse(self._request(method, url, data)), None
            except (urllib.error.URLError, OSError) as exc:
                last = _ResponseFailure("transport_error", f"MOPS transport failed: {exc}")
            except _ResponseFailure as exc:
                last = exc
            if attempt + 1 < self.max_attempts:
                self.sleeper(float(2**attempt))
        return None, last

    def _record(self, result: AnnualReportProbe) -> AnnualReportProbe:
        key = (result.security_code, result.report_year)
        self._results[key] = result
        self._probe_log.append(result)
        return result

    def acquire(
        self, security_code: str, report_year: int, decision_date: str
    ) -> AnnualReportProbe:
        """Acquire one security/report-year once, recording exactly one final state."""
        if not re.fullmatch(r"[0-9A-Za-z]{4,8}", security_code):
            raise ValueError("invalid security_code")
        if report_year <= 1910 or report_year > 9999:
            raise ValueError("invalid report_year")
        try:
            decision = date.fromisoformat(decision_date)
        except ValueError as exc:
            raise ValueError("invalid decision_date") from exc
        if decision.isoformat() != decision_date:
            raise ValueError("invalid decision_date")

        key = (security_code, report_year)
        with self._lock:
            prior = self._results.get(key)
            if prior is not None:
                return prior
            start_count = self._request_total
            listing_url = _listing_url(security_code, report_year)
            parsed, failure = self._bounded(
                "GET",
                listing_url,
                data=None,
                parse=lambda body: _parse_listing(
                    body, security_code=security_code, listing_url=listing_url
                ),
            )
            if failure is not None:
                return self._record(
                    AnnualReportProbe(
                        security_code,
                        report_year,
                        decision_date,
                        AnnualReportSourceState.SOURCE_UNAVAILABLE,
                        listing_url,
                        self._request_total - start_count,
                        failure.detail,
                        failure_kind=failure.kind,
                    )
                )
            assert isinstance(parsed, tuple)
            cutoff = datetime.combine(decision, time.max, tzinfo=_TAIPEI)
            eligible = [
                item
                for item in parsed
                if item.report_year == report_year
                and datetime.fromisoformat(item.available_at) <= cutoff
            ]
            if not eligible:
                target_listed = any(item.report_year == report_year for item in parsed)
                detail = (
                    "target F04 was listed only after the pre-decision cutoff"
                    if target_listed
                    else "valid MOPS listing contains no target F04"
                )
                return self._record(
                    AnnualReportProbe(
                        security_code,
                        report_year,
                        decision_date,
                        AnnualReportSourceState.DOCUMENT_NOT_LISTED,
                        listing_url,
                        self._request_total - start_count,
                        detail,
                    )
                )
            document = max(eligible, key=lambda item: (item.available_at, item.filename))
            step9_data = urllib.parse.urlencode(
                {
                    "step": "9",
                    "kind": "F",
                    "co_id": security_code,
                    "filename": document.filename,
                }
            ).encode()
            parsed_url, failure = self._bounded(
                "POST",
                _LISTING_URL,
                data=step9_data,
                parse=lambda body: _parse_pdf_url(body, document.filename),
            )
            if failure is not None:
                return self._record(
                    AnnualReportProbe(
                        security_code,
                        report_year,
                        decision_date,
                        AnnualReportSourceState.SOURCE_UNAVAILABLE,
                        listing_url,
                        self._request_total - start_count,
                        failure.detail,
                        document=document,
                        failure_kind=failure.kind,
                    )
                )
            assert isinstance(parsed_url, str)
            pdf, failure = self._bounded(
                "GET", parsed_url, data=None, parse=_validate_pdf
            )
            if failure is not None:
                return self._record(
                    AnnualReportProbe(
                        security_code,
                        report_year,
                        decision_date,
                        AnnualReportSourceState.SOURCE_UNAVAILABLE,
                        listing_url,
                        self._request_total - start_count,
                        failure.detail,
                        document=document,
                        pdf_url=parsed_url,
                        failure_kind=failure.kind,
                    )
                )
            assert isinstance(pdf, bytes)
            destination = self.cache_root / security_code / str(report_year) / document.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.read_bytes() != pdf:
                    return self._record(
                        AnnualReportProbe(
                            security_code,
                            report_year,
                            decision_date,
                            AnnualReportSourceState.SOURCE_UNAVAILABLE,
                            listing_url,
                            self._request_total - start_count,
                            "cached PDF conflicts with official response",
                            document=document,
                            pdf_url=parsed_url,
                            failure_kind="cache_conflict",
                        )
                    )
            else:
                temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
                try:
                    temporary.write_bytes(pdf)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            return self._record(
                AnnualReportProbe(
                    security_code,
                    report_year,
                    decision_date,
                    AnnualReportSourceState.AVAILABLE,
                    listing_url,
                    self._request_total - start_count,
                    "official pre-decision F04 PDF acquired",
                    document=document,
                    pdf_url=parsed_url,
                    pdf_path=destination,
                )
            )


__all__ = [
    "AnnualReportDocument",
    "AnnualReportProbe",
    "AnnualReportSourceState",
    "MopsAnnualReportAcquirer",
    "MopsTransportProtocol",
    "UrlLibMopsTransport",
]
