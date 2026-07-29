"""Official selected-company MOPS financial-statement artifacts."""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, Sequence
from zoneinfo import ZoneInfo

from company_quality.filing_store import FilingStore, StoredStatement

Market = Literal["TWSE", "TPEx"]
Report = Literal["balance", "income", "cash_flow"]
_TAIPEI = ZoneInfo("Asia/Taipei")
_BASE_URL = "https://mopsov.twse.com.tw/mops/web/"
_REPORTS: tuple[tuple[Report, str, str], ...] = (
    ("balance", "t164sb03", "資產負債表"),
    ("income", "t164sb04", "綜合損益表"),
    ("cash_flow", "t164sb05", "現金流量表"),
)
_LATEST_URLS = {
    "TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
    "TPEx": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci",
}


class SourceArtifactError(RuntimeError):
    pass


class ArtifactConflictError(RuntimeError):
    pass


@dataclass(frozen=True, order=True, slots=True)
class Period:
    roc_year: int
    quarter: int

    def __post_init__(self) -> None:
        if self.roc_year < 1 or self.quarter not in (1, 2, 3, 4):
            raise ValueError("invalid ROC year or quarter")

    @property
    def key(self) -> str:
        return f"{self.roc_year}Q{self.quarter}"


@dataclass(frozen=True, slots=True)
class FinancialArtifact:
    artifact_id: str
    issuer_id: str
    security_code: str
    market: Market
    period: str
    report: Report
    official_url: str
    endpoint_scope: Literal["selected_company"]
    content_sha256: str
    retrieved_at: str
    available_at: str
    availability_basis: Literal["first_successful_retrieval"]
    official_filed_at: None
    mime_type: Literal["text/html"]
    path: Path


@dataclass(frozen=True, slots=True)
class PeriodCollection:
    status: Literal["available"]
    artifacts: tuple[FinancialArtifact, ...]
    artifact_coverage: float
    schema_version: Literal["OfficialFinancialArtifacts.v1"] = (
        "OfficialFinancialArtifacts.v1"
    )
    source_version: Literal["mops-selected-company.v1"] = (
        "mops-selected-company.v1"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )


class Transport(Protocol):
    def preload(self, endpoint: str) -> None: ...

    def post(self, endpoint: str, payload: dict[str, str]) -> bytes: ...


class MopsTransport:
    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        self.headers = {
            "User-Agent": "CompanyQualityResearch/0.1",
            "Referer": _BASE_URL,
        }
        self._preloaded: set[str] = set()

    def preload(self, endpoint: str) -> None:
        if endpoint in self._preloaded:
            return
        request = urllib.request.Request(_BASE_URL + endpoint, headers=self.headers)
        with self.opener.open(request, timeout=30) as response:
            response.read()
        self._preloaded.add(endpoint)

    def post(self, endpoint: str, payload: dict[str, str]) -> bytes:
        request = urllib.request.Request(
            _BASE_URL + endpoint,
            data=urllib.parse.urlencode(payload).encode(),
            headers=self.headers,
        )
        with self.opener.open(request, timeout=30) as response:
            return response.read()


def trailing_quarters(latest: Period, count: int = 20) -> tuple[Period, ...]:
    if count < 1:
        raise ValueError("count must be positive")
    absolute = latest.roc_year * 4 + latest.quarter - 1
    periods = []
    for offset in range(count - 1, -1, -1):
        value = absolute - offset
        year, zero_based_quarter = divmod(value, 4)
        periods.append(Period(year, zero_based_quarter + 1))
    return tuple(periods)


def latest_published_period(market: Market, security_code: str) -> Period:
    request = urllib.request.Request(
        _LATEST_URLS[market], headers={"User-Agent": "CompanyQualityResearch/0.1"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        rows = json.load(response)
    if not isinstance(rows, list) or not rows:
        raise SourceArtifactError("official latest-quarter source returned no rows")
    code_field = "公司代號" if market == "TWSE" else "SecuritiesCompanyCode"
    year_field = "年度" if market == "TWSE" else "Year"
    quarter_field = "季別" if market == "TWSE" else "Season"
    company_rows = [
        row for row in rows if str(row.get(code_field, "")).strip() == security_code
    ]
    candidates = {
        Period(int(row[year_field]), int(row[quarter_field]))
        for row in company_rows
        if str(row.get(year_field, "")).isdigit()
        and str(row.get(quarter_field, "")).isdigit()
    }
    if not candidates:
        raise SourceArtifactError("company has no official published financial quarter")
    return max(candidates)


def _now() -> str:
    return datetime.now(_TAIPEI).isoformat(timespec="seconds")


def _validate_body(
    body: bytes,
    company_name: str,
    company_short_name: str,
    period: Period,
    title: str,
) -> None:
    text = body.decode("utf-8", "replace")
    if "查無公司資料" in text:
        raise SourceArtifactError("no official company data")
    if "驗證碼" in text or "captcha" in text.lower():
        raise SourceArtifactError("MOPS security/interstitial response")
    if company_name not in text and company_short_name not in text:
        raise SourceArtifactError("official response company identity mismatch")
    if f"民國{period.roc_year}年第{period.quarter}季" not in text:
        raise SourceArtifactError("official response period mismatch")
    if title not in text or "<table" not in text.lower():
        raise SourceArtifactError("official response statement type mismatch")


class MopsFinancialCollector:
    def __init__(
        self,
        transport: Transport | None = None,
        filing_store: FilingStore | None = None,
    ) -> None:
        self.transport = transport or MopsTransport()
        self.filing_store = filing_store

    @staticmethod
    def _stored_artifact(stored: StoredStatement) -> FinancialArtifact:
        return FinancialArtifact(
            artifact_id=(
                f"{stored.market}:{stored.security_code}:{stored.period}:"
                f"{stored.report}:{stored.content_sha256[:16]}"
            ),
            issuer_id=stored.issuer_id,
            security_code=stored.security_code,
            market=stored.market,  # type: ignore[arg-type]
            period=stored.period,
            report=stored.report,  # type: ignore[arg-type]
            official_url=stored.official_url,
            endpoint_scope="selected_company",
            content_sha256=stored.content_sha256,
            retrieved_at=stored.retrieved_at,
            available_at=stored.available_at,
            availability_basis="first_successful_retrieval",
            official_filed_at=None,
            mime_type="text/html",
            path=stored.path,
        )

    def collect_period(
        self,
        security_code: str,
        company_name: str,
        company_short_name: str,
        issuer_id: str,
        market: Market,
        period: Period,
        output_root: Path,
        retrieved_at: str | None = None,
        as_of: str | None = None,
    ) -> PeriodCollection:
        typek = "sii" if market == "TWSE" else "otc"
        retrieved = retrieved_at or _now()
        payload = {
            "step": "1",
            "firstin": "ture",
            "off": "1",
            "keyword4": "",
            "code1": "",
            "TYPEK2": "",
            "checkbtn": "",
            "queryName": "co_id",
            "inpuType": "co_id",
            "TYPEK": typek,
            "co_id": security_code,
            "year": str(period.roc_year),
            "season": f"{period.quarter:02d}",
        }

        if self.filing_store is not None and as_of is not None:
            artifacts: list[FinancialArtifact] = []
            for report, landing, title in _REPORTS:
                stored = self.filing_store.lookup_statement(
                    market=market,
                    security_code=security_code,
                    issuer_id=issuer_id,
                    period=period.key,
                    report=report,
                    as_of=as_of,
                )
                if stored is None:
                    self.transport.preload(landing)
                    endpoint = "ajax_" + landing
                    body = self.transport.post(endpoint, payload)
                    _validate_body(body, company_name, company_short_name, period, title)
                    stored = self.filing_store.put_statement(
                        body=body,
                        market=market,
                        security_code=security_code,
                        issuer_id=issuer_id,
                        period=period.key,
                        report=report,
                        official_url=_BASE_URL + endpoint,
                        retrieved_at=retrieved,
                        available_at=retrieved,
                    )
                artifacts.append(self._stored_artifact(stored))
            return PeriodCollection("available", tuple(artifacts), 1.0)

        downloaded: list[tuple[Report, str, bytes]] = []
        for report, landing, title in _REPORTS:
            self.transport.preload(landing)
            endpoint = "ajax_" + landing
            body = self.transport.post(endpoint, payload)
            _validate_body(body, company_name, company_short_name, period, title)
            downloaded.append((report, endpoint, body))

        directory = output_root / market / security_code / period.key
        destinations = {
            report: directory / f"{report}.html" for report, _, _ in downloaded
        }
        for report, _, body in downloaded:
            destination = destinations[report]
            if destination.exists() and destination.read_bytes() != body:
                raise ArtifactConflictError(
                    f"existing raw artifact changed: {destination}"
                )

        directory.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for report, endpoint, body in downloaded:
            destination = destinations[report]
            if not destination.exists():
                temporary = destination.with_suffix(".html.tmp")
                temporary.write_bytes(body)
                os.replace(temporary, destination)
            digest = hashlib.sha256(body).hexdigest()
            artifacts.append(
                FinancialArtifact(
                    artifact_id=(
                        f"{market}:{security_code}:{period.key}:{report}:{digest[:16]}"
                    ),
                    issuer_id=issuer_id,
                    security_code=security_code,
                    market=market,
                    period=period.key,
                    report=report,
                    official_url=_BASE_URL + endpoint,
                    endpoint_scope="selected_company",
                    content_sha256=digest,
                    retrieved_at=retrieved,
                    available_at=retrieved,
                    availability_basis="first_successful_retrieval",
                    official_filed_at=None,
                    mime_type="text/html",
                    path=destination,
                )
            )
        return PeriodCollection("available", tuple(artifacts), 1.0)

    def collect_five_years(
        self,
        security_code: str,
        company_name: str,
        company_short_name: str,
        issuer_id: str,
        market: Market,
        output_root: Path,
        periods: Sequence[Period] | None = None,
    ) -> tuple[PeriodCollection, ...]:
        requested = tuple(periods) if periods is not None else trailing_quarters(
            latest_published_period(market, security_code)
        )
        return tuple(
            self.collect_period(
                security_code,
                company_name,
                company_short_name,
                issuer_id,
                market,
                period,
                output_root,
            )
            for period in requested
        )
