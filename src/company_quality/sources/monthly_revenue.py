"""Official selected-company MOPS monthly consolidated revenue evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from company_quality.filing_store import FilingStore, StoredStatement
from company_quality.sources.financial import MopsTransport, Transport

Market = Literal["TWSE", "TPEx"]


class MonthlyRevenueError(RuntimeError):
    pass


@dataclass(frozen=True, order=True, slots=True)
class RevenueMonth:
    roc_year: int
    month: int

    def __post_init__(self) -> None:
        if self.roc_year < 1 or not 1 <= self.month <= 12:
            raise ValueError("invalid ROC revenue month")

    @property
    def key(self) -> str:
        return f"{self.roc_year}-{self.month:02d}"


@dataclass(frozen=True, slots=True)
class MonthlyRevenueArtifact:
    artifact_id: str
    issuer_id: str
    security_code: str
    market: Market
    month: str
    revenue_thousand_twd: Decimal
    prior_year_revenue_thousand_twd: Decimal
    yoy_percent: Decimal
    cumulative_revenue_thousand_twd: Decimal
    prior_year_cumulative_revenue_thousand_twd: Decimal
    cumulative_yoy_percent: Decimal
    explanation: str | None
    official_url: str
    available_at: str
    content_sha256: str
    path: Path
    unit: Literal["TWD_thousand"] = "TWD_thousand"
    report_scope: Literal["consolidated_ifrs"] = "consolidated_ifrs"


class _Rows(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            assert self._row is not None
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def trailing_months(latest: RevenueMonth, count: int = 60) -> tuple[RevenueMonth, ...]:
    if count < 1:
        raise ValueError("count must be positive")
    absolute = latest.roc_year * 12 + latest.month - 1
    result = []
    for offset in range(count - 1, -1, -1):
        value = absolute - offset
        year, zero_based_month = divmod(value, 12)
        result.append(RevenueMonth(year, zero_based_month + 1))
    return tuple(result)


def _decimal(raw: str, field: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "").strip())
    except InvalidOperation as exc:
        raise MonthlyRevenueError(f"invalid monthly revenue {field}") from exc


def _parse(body: bytes) -> dict[str, str]:
    parser = _Rows()
    parser.feed(body.decode("utf-8", "replace"))
    values: dict[str, str] = {}
    for row in parser.rows:
        if len(row) >= 2 and row[0]:
            values.setdefault(row[0], row[1])
    return values


def _artifact(
    stored: StoredStatement,
    *,
    market: Market,
    security_code: str,
    issuer_id: str,
    month: RevenueMonth,
) -> MonthlyRevenueArtifact:
    body = stored.path.read_bytes()
    values = _parse(body)
    required = {
        "本月",
        "去年同期",
        "增減百分比",
        "本年累計",
        "去年累計",
    }
    if not required.issubset(values):
        raise MonthlyRevenueError("official monthly revenue table missing required rows")
    percentages = [row[1] for row in _RowsFromBody(body).rows if row and row[0] == "增減百分比"]
    if len(percentages) < 2:
        raise MonthlyRevenueError("official monthly revenue table missing percentage rows")
    explanation = values.get("備註 / 營收變化原因說明") or None
    return MonthlyRevenueArtifact(
        artifact_id=f"{market}:{security_code}:{month.key}:monthly-revenue:{stored.content_sha256[:16]}",
        issuer_id=issuer_id,
        security_code=security_code,
        market=market,
        month=month.key,
        revenue_thousand_twd=_decimal(values["本月"], "current"),
        prior_year_revenue_thousand_twd=_decimal(values["去年同期"], "prior year"),
        yoy_percent=_decimal(percentages[0], "YoY"),
        cumulative_revenue_thousand_twd=_decimal(values["本年累計"], "cumulative"),
        prior_year_cumulative_revenue_thousand_twd=_decimal(values["去年累計"], "prior cumulative"),
        cumulative_yoy_percent=_decimal(percentages[1], "cumulative YoY"),
        explanation=explanation,
        official_url=stored.official_url,
        available_at=stored.available_at,
        content_sha256=stored.content_sha256,
        path=stored.path,
    )


class _RowsFromBody:
    def __init__(self, body: bytes) -> None:
        parser = _Rows()
        parser.feed(body.decode("utf-8", "replace"))
        self.rows = parser.rows


class MopsMonthlyRevenueCollector:
    endpoint = "t05st10_ifrs"

    def __init__(
        self,
        transport: Transport | None = None,
        filing_store: FilingStore | None = None,
    ) -> None:
        self.transport = transport or MopsTransport()
        self.filing_store = filing_store

    def collect_month(
        self,
        *,
        security_code: str,
        company_name: str,
        company_short_name: str,
        issuer_id: str,
        market: Market,
        month: RevenueMonth,
        retrieved_at: str,
        as_of: str,
    ) -> MonthlyRevenueArtifact:
        stored = None
        if self.filing_store is not None:
            stored = self.filing_store.lookup_statement(
                market=market,
                security_code=security_code,
                issuer_id=issuer_id,
                period=month.key,
                report="monthly_revenue",
                as_of=as_of,
            )
        if stored is None:
            payload = {
                "step": "1",
                "firstin": "true",
                "off": "1",
                "keyword4": "",
                "code1": "",
                "TYPEK2": "",
                "checkbtn": "",
                "queryName": "co_id",
                "inpuType": "co_id",
                "TYPEK": "sii" if market == "TWSE" else "otc",
                "co_id": security_code,
                "year": str(month.roc_year),
                "month": f"{month.month:02d}",
            }
            self.transport.preload(self.endpoint)
            official_endpoint = "ajax_" + self.endpoint
            body = self.transport.post(official_endpoint, payload)
            text = body.decode("utf-8", "replace")
            if "查無公司資料" in text:
                raise MonthlyRevenueError("no official monthly revenue data")
            if company_name not in text and company_short_name not in text:
                raise MonthlyRevenueError("official monthly revenue company mismatch")
            if f"民國{month.roc_year}年{month.month:02d}月" not in text:
                raise MonthlyRevenueError("official monthly revenue period mismatch")
            if "營業收入淨額" not in text or "<table" not in text.lower():
                raise MonthlyRevenueError("official monthly revenue table mismatch")
            if self.filing_store is None:
                raise MonthlyRevenueError("monthly revenue requires a filing store")
            stored = self.filing_store.put_statement(
                body=body,
                market=market,
                security_code=security_code,
                issuer_id=issuer_id,
                period=month.key,
                report="monthly_revenue",
                official_url=f"https://mopsov.twse.com.tw/mops/web/{official_endpoint}",
                retrieved_at=retrieved_at,
                available_at=retrieved_at,
            )
        return _artifact(
            stored,
            market=market,
            security_code=security_code,
            issuer_id=issuer_id,
            month=month,
        )


__all__ = [
    "MonthlyRevenueArtifact",
    "MonthlyRevenueError",
    "MopsMonthlyRevenueCollector",
    "RevenueMonth",
    "trailing_months",
]
