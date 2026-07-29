"""Official audit/review filing inventory and statutory deadline reconstruction."""

from __future__ import annotations

import calendar
import hashlib
import http.cookiejar
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, fields, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from company_quality.filing_store import FilingStore, StoredFiling

_TAIPEI = ZoneInfo("Asia/Taipei")
_ANNOUNCEMENT_URL = "https://mops.twse.com.tw/mops/api/t163sb01"
_DOCUMENT_URL = "https://doc.twse.com.tw/server-java/t57sb01"
_DEADLINE_RULE_URL = "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0400001&flno=36"
_HOLIDAY_RULE_URL = "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=A0030055&flno=48"
_QUARTER_NAMES = {1: "第一季", 2: "第二季", 3: "第三季", 4: "第四季"}

Market = Literal["TWSE", "TPEx"]
FilingType = Literal["annual_audit", "q1_review", "q2_review", "q3_review"]
IssuerType = Literal["domestic_general", "foreign_primary", "foreign_secondary"]
IndustryType = Literal["general", "financial_insurance", "other_regulated"]
AssuranceType = Literal["audit", "review"]
OpinionType = Literal["unmodified", "qualified", "adverse", "disclaimer"]


class AuditSourceError(RuntimeError):
    pass


class AuditArtifactConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DeadlineResult:
    ordinary_due_at: str
    holiday_adjustment_days: int
    approved_extension_days: int
    extension_rule_id: str | None
    statutory_due_at: str
    holiday_calendar_version: str
    deadline_rule_id: Literal["securities-exchange-act-36"] = (
        "securities-exchange-act-36"
    )
    deadline_rule_version: Literal["2026-07-24.v1"] = "2026-07-24.v1"
    deadline_rule_url: str = _DEADLINE_RULE_URL
    holiday_rule_url: str = _HOLIDAY_RULE_URL


@dataclass(frozen=True, slots=True)
class AuditFilingInventory:
    security_code: str
    issuer_id: str
    market: Market
    period: str
    filing_type: FilingType
    issuer_type: IssuerType
    industry_type: IndustryType
    fiscal_period_start: str
    fiscal_period_end: str
    assurance_type: AssuranceType
    report_scope: Literal["consolidated", "individual"]
    deadline_rule_id: str
    deadline_rule_version: str
    ordinary_due_at: str
    holiday_adjustment_days: int
    approved_extension_days: int
    extension_rule_id: str | None
    statutory_due_at: str
    holiday_calendar_version: str
    official_filed_at: str
    auditor_report_at: None
    official_filed_at_source: Literal["official_filing_receipt"]
    opinion_type: OpinionType | None
    auditor_firm: str | None
    auditors: tuple[str, ...]
    corrected: bool
    announcement_url: str
    announcement_sha256: str
    receipt_url: str
    receipt_sha256: str
    pdf_filename: str
    pdf_source_url: str | None
    pdf_sha256: str | None
    pdf_path: Path | None
    retrieved_at: str
    available_at: str
    evidence_ids: tuple[str, ...]
    mandatory_evidence_gaps: tuple[str, ...]
    coverage: Decimal
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["AuditFilingInventory.v1"] = "AuditFilingInventory.v1"
    source_version: Literal["mops-audit-inventory.v1"] = "mops-audit-inventory.v1"
    formula_version: Literal["tw-statute-deadline.v1"] = "tw-statute-deadline.v1"
    model_version: Literal["no-rating-model.v1"] = "no-rating-model.v1"


def _store_metadata(inventory: AuditFilingInventory) -> dict[str, object]:
    metadata = asdict(inventory)
    metadata.pop("pdf_path", None)
    metadata["coverage"] = str(inventory.coverage)
    return metadata


def _inventory_from_store(stored: StoredFiling) -> AuditFilingInventory:
    metadata: dict[str, Any] = dict(stored.metadata)
    metadata["pdf_path"] = stored.path
    metadata["pdf_sha256"] = stored.content_sha256
    metadata["pdf_source_url"] = stored.source_url
    metadata["coverage"] = Decimal(str(metadata["coverage"]))
    for name in ("auditors", "evidence_ids", "mandatory_evidence_gaps"):
        metadata[name] = tuple(metadata.get(name, ()))
    allowed = {field.name for field in fields(AuditFilingInventory)}
    return AuditFilingInventory(
        **{key: value for key, value in metadata.items() if key in allowed}
    )


class Transport(Protocol):
    def post_json(self, url: str, payload: dict[str, object]) -> bytes: ...

    def get(self, url: str) -> bytes: ...

    def post_form(self, url: str, payload: dict[str, str]) -> bytes: ...


class HttpTransport:
    def __init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        self.headers = {"User-Agent": "CompanyQualityResearch/0.1"}
        self._listing_cache: dict[str, bytes] = {}

    def post_json(self, url: str, payload: dict[str, object]) -> bytes:
        headers = {**self.headers, "Content-Type": "application/json"}
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers
        )
        with self.opener.open(request, timeout=30) as response:
            return response.read()

    def get(self, url: str) -> bytes:
        if url in self._listing_cache:
            return self._listing_cache[url]
        request = urllib.request.Request(url, headers=self.headers)
        with self.opener.open(request, timeout=60) as response:
            raw = response.read()
        if url.startswith(_DOCUMENT_URL) and "step=1" in url:
            self._listing_cache[url] = raw
        return raw

    def post_form(self, url: str, payload: dict[str, str]) -> bytes:
        headers = {**self.headers, "Referer": url}
        request = urllib.request.Request(
            url, data=urllib.parse.urlencode(payload).encode(), headers=headers
        )
        with self.opener.open(request, timeout=30) as response:
            return response.read()


def _timestamp(day: date) -> str:
    return datetime(
        day.year, day.month, day.day, 23, 59, 59, tzinfo=_TAIPEI
    ).isoformat()


def _add_months(day: date, months: int) -> date:
    absolute = day.year * 12 + day.month - 1 + months
    year, zero_month = divmod(absolute, 12)
    month = zero_month + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def compute_deadline(
    fiscal_period_end: date,
    filing_type: FilingType,
    non_business_days: set[date] | frozenset[date] = frozenset(),
    approved_extension_days: int = 0,
    extension_rule_id: str | None = None,
    holiday_calendar_version: str = "weekends-only.v1",
) -> DeadlineResult:
    if approved_extension_days < 0:
        raise ValueError("approved_extension_days cannot be negative")
    if approved_extension_days and not extension_rule_id:
        raise ValueError("extension_rule_id is required for an approved extension")
    ordinary = (
        _add_months(fiscal_period_end, 3)
        if filing_type == "annual_audit"
        else fiscal_period_end + timedelta(days=45)
    )
    candidate = ordinary + timedelta(days=approved_extension_days)
    adjusted = candidate
    while adjusted.weekday() >= 5 or adjusted in non_business_days:
        adjusted += timedelta(days=1)
    return DeadlineResult(
        ordinary_due_at=_timestamp(ordinary),
        holiday_adjustment_days=(adjusted - candidate).days,
        approved_extension_days=approved_extension_days,
        extension_rule_id=extension_rule_id,
        statutory_due_at=_timestamp(adjusted),
        holiday_calendar_version=holiday_calendar_version,
    )


@dataclass(frozen=True, slots=True)
class _Receipt:
    filename: str
    size: int
    uploaded_at: str
    corrected: bool


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).replace("\xa0", " ").split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _roc_timestamp(value: str) -> str:
    match = re.fullmatch(r"(\d{2,3})/(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2})", value)
    if match is None:
        raise AuditSourceError("invalid official filing receipt timestamp")
    year, month, day, hour, minute, second = map(int, match.groups())
    return datetime(year + 1911, month, day, hour, minute, second, tzinfo=_TAIPEI).isoformat()


def _receipt(
    raw: bytes, security_code: str, roc_year: int, quarter: int, report_scope: str
) -> _Receipt:
    parser = _ListingParser()
    parser.feed(raw.decode("big5", "replace"))
    required = [
        "證券代號", "資料年度", "資料類型", "結案類型", "性質",
        "資料細節說明", "備註", "電子檔案", "檔案大小", "上傳日期",
        "財務報告更(補)正",
    ]
    header = next((row for row in parser.rows if row == required), None)
    if header is None:
        raise AuditSourceError("official filing receipt table not found")
    expected_period = f"{roc_year} 年 {_QUARTER_NAMES[quarter]}"
    expected_detail = "IFRSs合併財報" if report_scope == "consolidated" else "IFRSs個別財報"
    matches = [
        row for row in parser.rows
        if len(row) == len(required)
        and row[0] == security_code
        and row[1] == expected_period
        and row[2] == "財務報告書"
        and row[5] == expected_detail
        and row[7].lower().endswith(".pdf")
    ]
    if len(matches) != 1:
        raise AuditSourceError("exact Chinese financial-report receipt is not unique")
    row = matches[0]
    try:
        size = int(row[8].replace(",", ""))
    except ValueError as exc:
        raise AuditSourceError("invalid official PDF byte count") from exc
    return _Receipt(
        filename=row[7],
        size=size,
        uploaded_at=_roc_timestamp(row[9]),
        corrected=row[10] != "無",
    )


def _opinion(values: list[str]) -> OpinionType:
    text = " ".join(values)
    if "無保留" in text:
        return "unmodified"
    if "無法表示" in text:
        return "disclaimer"
    if "否定" in text:
        return "adverse"
    if "保留" in text:
        return "qualified"
    raise AuditSourceError("auditor opinion/conclusion is unavailable")


def _auditors(narrative: str) -> tuple[str | None, tuple[str, ...]]:
    match = re.search(
        r"業經([^，。]+?會計師事務所)([\u4e00-\u9fff]{2,4})及([\u4e00-\u9fff]{2,4})會計師(?:核閱|查核(?:簽證)?)竣事",
        narrative,
    )
    if match is None:
        return None, ()
    return match.group(1), (match.group(2), match.group(3))


def _period(
    roc_year: int, quarter: int
) -> tuple[date, date, FilingType, AssuranceType]:
    year = roc_year + 1911
    end_month = quarter * 3
    end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    start = date(year, 1, 1)
    if quarter == 4:
        return start, end, "annual_audit", "audit"
    filing_type: FilingType = ("q1_review", "q2_review", "q3_review")[quarter - 1]
    return start, end, filing_type, "review"


def _write_verified(destination: Path, raw: bytes) -> None:
    if destination.exists():
        if destination.read_bytes() != raw:
            raise AuditArtifactConflictError(f"existing audit artifact changed: {destination}")
        return
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, destination)


class MopsAuditInventoryCollector:
    def __init__(
        self,
        transport: Transport | None = None,
        filing_store: FilingStore | None = None,
    ) -> None:
        self.transport = transport or HttpTransport()
        self.filing_store = filing_store

    def collect_period(
        self,
        security_code: str,
        issuer_id: str,
        market: Market,
        roc_year: int,
        quarter: int,
        issuer_type: IssuerType,
        industry_type: IndustryType,
        output_root: Path,
        retrieved_at: str,
        as_of: str | None = None,
        non_business_days: set[date] | frozenset[date] = frozenset(),
        approved_extension_days: int = 0,
        extension_rule_id: str | None = None,
        holiday_calendar_version: str = "weekends-only.v1",
    ) -> AuditFilingInventory:
        if quarter not in (1, 2, 3, 4):
            raise ValueError("quarter must be 1..4")
        fiscal_start, fiscal_end, filing_type, assurance = _period(roc_year, quarter)
        period_key = f"{roc_year}Q{quarter}"
        if self.filing_store is not None and as_of is not None:
            stored = self.filing_store.lookup(
                market=market,
                security_code=security_code,
                issuer_id=issuer_id,
                period=period_key,
                filing_type=filing_type,
                as_of=as_of,
            )
            if stored is not None:
                return _inventory_from_store(stored)
        payload: dict[str, object] = {
            "companyId": security_code,
            "dataType": "2",
            "year": str(roc_year),
            "season": str(quarter),
            "subsidiaryCompanyId": "",
        }
        announcement_raw = self.transport.post_json(_ANNOUNCEMENT_URL, payload)
        try:
            envelope = json.loads(announcement_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditSourceError("invalid MOPS announcement JSON") from exc
        if envelope.get("code") != 200 or not isinstance(envelope.get("result"), dict):
            raise AuditSourceError("official audit announcement is unavailable")
        result = envelope["result"]
        if str(result.get("year")) != str(roc_year):
            raise AuditSourceError("official audit announcement period mismatch")
        scope = "consolidated" if result.get("reportType") == "合併" else "individual"
        opinion = _opinion(result.get("IFRSAccountantReports") or [])
        narrative = " ".join(
            item.get("content", "") for item in result.get("illustrate", [])
            if isinstance(item, dict)
        )
        firm, signing_auditors = _auditors(narrative)

        listing_url = (
            f"{_DOCUMENT_URL}?step=1&colorchg=1&seamon=&mtype=A"
            f"&co_id={urllib.parse.quote(security_code)}&year={roc_year}"
        )
        receipt_raw = self.transport.get(listing_url)
        receipt = _receipt(receipt_raw, security_code, roc_year, quarter, scope)
        staging_raw = self.transport.post_form(
            _DOCUMENT_URL,
            {
                "colorchg": "1", "step": "9", "kind": "A",
                "co_id": security_code, "filename": receipt.filename, "DEBUG": "",
            },
        )
        match = re.search(rb"href=['\"]([^'\"]*/pdf/[^'\"]+\.pdf)['\"]", staging_raw)
        pdf_url = None
        pdf_raw = None
        if match is not None:
            pdf_url = urllib.parse.urljoin(_DOCUMENT_URL, match.group(1).decode("ascii"))
            candidate = self.transport.get(pdf_url)
            if candidate.startswith(b"%PDF") and len(candidate) == receipt.size:
                pdf_raw = candidate

        deadline = compute_deadline(
            fiscal_end,
            filing_type,
            non_business_days=non_business_days,
            approved_extension_days=approved_extension_days,
            extension_rule_id=extension_rule_id,
            holiday_calendar_version=holiday_calendar_version,
        )
        announcement_hash = hashlib.sha256(announcement_raw).hexdigest()
        receipt_hash = hashlib.sha256(receipt_raw).hexdigest()
        pdf_hash = hashlib.sha256(pdf_raw).hexdigest() if pdf_raw is not None else None
        directory = output_root / market / security_code / period_key
        announcement_path = directory / f"announcement-{announcement_hash[:16]}.json"
        receipt_path = directory / f"filing-receipt-{receipt_hash[:16]}.html"
        pdf_path = directory / f"audit-report-{pdf_hash[:16]}.pdf" if pdf_hash else None
        directory.mkdir(parents=True, exist_ok=True)
        _write_verified(announcement_path, announcement_raw)
        _write_verified(receipt_path, receipt_raw)
        if pdf_path is not None and pdf_raw is not None:
            _write_verified(pdf_path, pdf_raw)
        corrected = receipt.corrected or any(
            bool(item.get("url"))
            for item in result.get("declarationOfFinancialReports", [])
            if isinstance(item, dict)
        )
        inventory = AuditFilingInventory(
            security_code=security_code,
            issuer_id=issuer_id,
            market=market,
            period=period_key,
            filing_type=filing_type,
            issuer_type=issuer_type,
            industry_type=industry_type,
            fiscal_period_start=fiscal_start.isoformat(),
            fiscal_period_end=fiscal_end.isoformat(),
            assurance_type=assurance,
            report_scope=scope,
            deadline_rule_id=deadline.deadline_rule_id,
            deadline_rule_version=deadline.deadline_rule_version,
            ordinary_due_at=deadline.ordinary_due_at,
            holiday_adjustment_days=deadline.holiday_adjustment_days,
            approved_extension_days=deadline.approved_extension_days,
            extension_rule_id=deadline.extension_rule_id,
            statutory_due_at=deadline.statutory_due_at,
            holiday_calendar_version=deadline.holiday_calendar_version,
            official_filed_at=receipt.uploaded_at,
            auditor_report_at=None,
            official_filed_at_source="official_filing_receipt",
            opinion_type=opinion if pdf_hash else None,
            auditor_firm=firm,
            auditors=signing_auditors,
            corrected=corrected,
            announcement_url=_ANNOUNCEMENT_URL,
            announcement_sha256=announcement_hash,
            receipt_url=listing_url,
            receipt_sha256=receipt_hash,
            pdf_filename=receipt.filename,
            pdf_source_url=pdf_url if pdf_hash else None,
            pdf_sha256=pdf_hash,
            pdf_path=pdf_path,
            retrieved_at=retrieved_at,
            available_at=receipt.uploaded_at,
            evidence_ids=tuple(item for item in (
                f"announcement:{announcement_hash}",
                f"receipt:{receipt_hash}",
                f"pdf:{pdf_hash}" if pdf_hash else None,
            ) if item is not None),
            mandatory_evidence_gaps=(
                *(("mandatory_audit_evidence_missing",) if not pdf_hash else ()),
                *(("auditor_metadata_unavailable",) if firm is None else ()),
            ),
            coverage=Decimal("1") if pdf_hash else Decimal(2) / Decimal(3),
        )
        if (
            self.filing_store is not None
            and pdf_raw is not None
            and inventory.pdf_source_url is not None
        ):
            stored = self.filing_store.put_pdf(
                body=pdf_raw,
                market=inventory.market,
                security_code=inventory.security_code,
                issuer_id=inventory.issuer_id,
                period=inventory.period,
                filing_type=inventory.filing_type,
                report_scope=inventory.report_scope,
                official_filed_at=inventory.official_filed_at,
                source_url=inventory.pdf_source_url,
                retrieved_at=inventory.retrieved_at,
                corrected=inventory.corrected,
                metadata=_store_metadata(inventory),
            )
            inventory = replace(inventory, pdf_path=stored.path)
        return inventory
