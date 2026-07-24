import hashlib
from datetime import date

import pytest

from company_quality.audit.inventory import (
    AuditSourceError,
    MopsAuditInventoryCollector,
    compute_deadline,
)


class FakeTransport:
    def __init__(self, announcement: bytes, listing: bytes, staging: bytes, pdf: bytes):
        self.announcement = announcement
        self.listing = listing
        self.staging = staging
        self.pdf = pdf
        self.json_payload = None

    def post_json(self, url, payload):
        self.json_payload = payload
        return self.announcement

    def get(self, url):
        if "/pdf/" in url:
            return self.pdf
        return self.listing

    def post_form(self, url, payload):
        return self.staging


def announcement() -> bytes:
    return """{
      "code": 200,
      "message": "查詢成功",
      "result": {
        "reportType": "合併",
        "marketName": "上市公司",
        "year": "115",
        "seasonName": "第１季",
        "companyAbbreviation": "台積電",
        "IFRSAccountantReports": ["合併財務報告-意見種類：無保留結論/意見--"],
        "declarationOfFinancialReports": [{"title":"合併財務報告更(補)正：", "url":[]}],
        "illustrate": [{"content":"本公司及子公司民國一百一十五年度第一季合併財務報告，業經勤業眾信聯合會計師事務所吳世宗及陳彥君會計師核閱竣事，並出具無保留結論核閱報告在案。", "url":[]}]
      },
      "datetime": "115/07/24 10:21:50"
    }""".encode()


def listing(pdf_size: int) -> bytes:
    html = f"""
    <html><body><table>
      <tr><th>證券代號</th><th>資料年度</th><th>資料類型</th><th>結案類型</th><th>性質</th><th>資料細節說明</th><th>備註</th><th>電子檔案</th><th>檔案大小</th><th>上傳日期</th><th>財務報告更(補)正</th></tr>
      <tr><td>2330</td><td>115 年 第一季</td><td>財務報告書</td><td></td><td></td><td>IFRSs合併財報</td><td></td><td><a href='javascript:readfile2("A","2330","202601_2330_AI1.pdf");'>202601_2330_AI1.pdf</a></td><td>{pdf_size:,}</td><td>115/05/15 14:43:02</td><td>無</td></tr>
      <tr><td>2330</td><td>115 年 第一季</td><td>財務報告書</td><td></td><td></td><td>IFRSs英文版-合併財報</td><td></td><td>english.pdf</td><td>100</td><td>115/05/15 14:43:22</td><td>無</td></tr>
    </table></body></html>
    """
    return html.encode("big5", errors="xmlcharrefreplace")


def collector(pdf=b"%PDF-1.7 fake audit report"):
    staging = b"<html><a href='/pdf/generated-report.pdf'>report</a></html>"
    return MopsAuditInventoryCollector(
        FakeTransport(announcement(), listing(len(pdf)), staging, pdf)
    )


def test_deadline_separates_ordinary_holiday_and_extension() -> None:
    annual = compute_deadline(date(2023, 12, 31), "annual_audit")
    assert annual.ordinary_due_at == "2024-03-31T23:59:59+08:00"
    assert annual.holiday_adjustment_days == 1
    assert annual.statutory_due_at == "2024-04-01T23:59:59+08:00"

    extended = compute_deadline(
        date(2023, 12, 31),
        "annual_audit",
        non_business_days={date(2024, 4, 2)},
        approved_extension_days=2,
        extension_rule_id="approved-extension-case-1",
        holiday_calendar_version="tw-calendar-2024.v1",
    )
    assert extended.approved_extension_days == 2
    assert extended.extension_rule_id == "approved-extension-case-1"
    assert extended.holiday_calendar_version == "tw-calendar-2024.v1"
    assert extended.holiday_adjustment_days == 1
    assert extended.statutory_due_at == "2024-04-03T23:59:59+08:00"


def test_q1_deadline_is_45_days_after_period_end() -> None:
    result = compute_deadline(date(2026, 3, 31), "q1_review")
    assert result.ordinary_due_at == "2026-05-15T23:59:59+08:00"
    assert result.statutory_due_at == result.ordinary_due_at


def test_collects_review_inventory_with_official_receipt_and_pdf(tmp_path) -> None:
    result = collector().collect_period(
        security_code="2330",
        issuer_id="22099131",
        market="TWSE",
        roc_year=115,
        quarter=1,
        issuer_type="domestic_general",
        industry_type="general",
        output_root=tmp_path,
        retrieved_at="2026-07-24T10:30:00+08:00",
    )

    assert (result.market, result.security_code, result.issuer_id) == (
        "TWSE", "2330", "22099131"
    )
    assert result.period == "115Q1"
    assert result.filing_type == "q1_review"
    assert result.assurance_type == "review"
    assert result.report_scope == "consolidated"
    assert result.opinion_type == "unmodified"
    assert result.auditor_firm == "勤業眾信聯合會計師事務所"
    assert result.auditors == ("吳世宗", "陳彥君")
    assert result.official_filed_at == "2026-05-15T14:43:02+08:00"
    assert result.auditor_report_at is None
    assert result.official_filed_at_source == "official_filing_receipt"
    assert result.coverage == 1
    assert result.corrected is False
    assert result.pdf_path.read_bytes().startswith(b"%PDF")
    assert result.pdf_sha256 == hashlib.sha256(result.pdf_path.read_bytes()).hexdigest()
    assert result.announcement_sha256 != result.receipt_sha256
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"
    assert result.schema_version == "AuditFilingInventory.v1"


def test_announcement_query_time_is_not_used_as_filing_time(tmp_path) -> None:
    result = collector().collect_period(
        "2330", "22099131", "TWSE", 115, 1,
        "domestic_general", "general", tmp_path,
        "2026-07-24T10:30:00+08:00",
    )

    assert result.official_filed_at != "2026-07-24T10:21:50+08:00"


def test_missing_chinese_consolidated_receipt_blocks_success(tmp_path) -> None:
    pdf = b"%PDF-1.7 fake"
    bad_listing = listing(len(pdf)).replace(
        "IFRSs合併財報".encode("big5"), "IFRSs英文版-合併財報".encode("big5")
    )
    transport = FakeTransport(
        announcement(), bad_listing,
        b"<a href='/pdf/generated.pdf'>pdf</a>", pdf,
    )

    with pytest.raises(AuditSourceError, match="receipt"):
        MopsAuditInventoryCollector(transport).collect_period(
            "2330", "22099131", "TWSE", 115, 1,
            "domestic_general", "general", tmp_path,
            "2026-07-24T10:30:00+08:00",
        )

    assert not list(tmp_path.rglob("*.pdf"))


def test_non_pdf_download_is_an_explicit_coverage_gap(tmp_path) -> None:
    result = collector(pdf=b"<html>security page</html>").collect_period(
        "2330", "22099131", "TWSE", 115, 1,
        "domestic_general", "general", tmp_path,
        "2026-07-24T10:30:00+08:00",
    )

    assert result.pdf_path is None
    assert result.opinion_type is None
    assert result.mandatory_evidence_gaps == ("mandatory_audit_evidence_missing",)
    assert result.coverage < 1


def test_dynamic_query_time_is_append_only_not_a_false_conflict(tmp_path) -> None:
    pdf = b"%PDF-1.7 fake audit report"
    transport = FakeTransport(
        announcement(), listing(len(pdf)),
        b"<html><a href='/pdf/generated-report.pdf'>report</a></html>", pdf,
    )
    c = MopsAuditInventoryCollector(transport)
    first = c.collect_period(
        "2330", "22099131", "TWSE", 115, 1,
        "domestic_general", "general", tmp_path,
        "2026-07-24T10:30:00+08:00",
    )
    transport.announcement = transport.announcement.replace(
        b"10:21:50", b"10:31:50"
    )
    second = c.collect_period(
        "2330", "22099131", "TWSE", 115, 1,
        "domestic_general", "general", tmp_path,
        "2026-07-24T10:40:00+08:00",
    )

    assert first.announcement_sha256 != second.announcement_sha256
    assert len(list(tmp_path.rglob("announcement-*.json"))) == 2
    assert len(list(tmp_path.rglob("audit-report-*.pdf"))) == 1
