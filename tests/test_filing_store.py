from hashlib import sha256
from pathlib import Path
from decimal import Decimal
from dataclasses import asdict

from company_quality.audit.inventory import AuditFilingInventory, MopsAuditInventoryCollector
from company_quality.filing_store import FilingStore
from company_quality.sources.financial import MopsFinancialCollector, Period


PDF = b"%PDF-1.4\nlocal filing fixture\n%%EOF\n"
HTML = b"<html><table><tr><td>assets</td></tr></table></html>"


def _put(store: FilingStore, *, filed_at: str = "2025-03-01T12:00:00+08:00"):
    return store.put_pdf(
        body=PDF,
        market="TWSE",
        security_code="9933",
        issuer_id="20817282",
        period="113Q4",
        filing_type="annual_audit",
        report_scope="consolidated",
        official_filed_at=filed_at,
        source_url="https://doc.twse.com.tw/example.pdf",
        retrieved_at="2026-07-29T12:00:00+08:00",
        corrected=False,
        metadata={"auditors": ["甲", "乙"], "coverage": "1"},
    )


def _lookup(store: FilingStore, as_of: str):
    return store.lookup(
        market="TWSE",
        security_code="9933",
        issuer_id="20817282",
        period="113Q4",
        filing_type="annual_audit",
        as_of=as_of,
    )


def test_saves_content_addressed_pdf_and_hits_exact_pit_version(tmp_path: Path) -> None:
    store = FilingStore(tmp_path / "filing-store")
    saved = _put(store)

    hit = _lookup(store, "2025-03-02T00:00:00+08:00")

    assert hit is not None
    assert hit.content_sha256 == sha256(PDF).hexdigest()
    assert hit.path == saved.path
    assert hit.path.read_bytes() == PDF
    assert store.stats().saved == 1
    assert store.stats().hits == 1


def test_future_filing_is_not_eligible_for_earlier_as_of(tmp_path: Path) -> None:
    store = FilingStore(tmp_path / "filing-store")
    _put(store, filed_at="2025-03-01T12:00:00+08:00")

    assert _lookup(store, "2025-02-28T23:59:59+08:00") is None
    assert store.stats().misses == 1


def test_statement_artifact_is_local_first_and_pit_bounded(tmp_path: Path) -> None:
    store = FilingStore(tmp_path / "filing-store")
    saved = store.put_statement(
        body=HTML,
        market="TWSE",
        security_code="9933",
        issuer_id="20817282",
        period="113Q4",
        report="balance",
        official_url="https://mopsov.twse.com.tw/mops/web/ajax_t164sb03",
        retrieved_at="2025-03-02T12:00:00+08:00",
        available_at="2025-03-02T12:00:00+08:00",
    )
    assert store.lookup_statement(
        market="TWSE", security_code="9933", issuer_id="20817282",
        period="113Q4", report="balance",
        as_of="2025-03-02T11:59:59+08:00",
    ) is None
    hit = store.lookup_statement(
        market="TWSE", security_code="9933", issuer_id="20817282",
        period="113Q4", report="balance",
        as_of="2025-03-02T12:00:00+08:00",
    )
    assert hit is not None
    assert hit.path == saved.path
    assert hit.path.read_bytes() == HTML


def test_corrupt_blob_is_rejected_and_quarantined_on_refetch(tmp_path: Path) -> None:
    store = FilingStore(tmp_path / "filing-store")
    saved = _put(store)
    saved.path.write_bytes(b"corrupt")

    assert _lookup(store, "2025-03-02T00:00:00+08:00") is None
    restored = _put(store)

    assert restored.path.read_bytes() == PDF
    assert store.stats().corruptions >= 1
    assert tuple((tmp_path / "filing-store" / "quarantine").glob("*.pdf"))


def test_audit_collector_uses_exact_local_hit_without_network(tmp_path: Path) -> None:
    store = FilingStore(tmp_path / "filing-store")
    inventory = AuditFilingInventory(
        security_code="9933",
        issuer_id="20817282",
        market="TWSE",
        period="113Q4",
        filing_type="annual_audit",
        issuer_type="domestic_general",
        industry_type="general",
        fiscal_period_start="2024-01-01",
        fiscal_period_end="2024-12-31",
        assurance_type="audit",
        report_scope="consolidated",
        deadline_rule_id="rule",
        deadline_rule_version="v1",
        ordinary_due_at="2025-03-31T23:59:59+08:00",
        holiday_adjustment_days=0,
        approved_extension_days=0,
        extension_rule_id=None,
        statutory_due_at="2025-03-31T23:59:59+08:00",
        holiday_calendar_version="v1",
        official_filed_at="2025-03-01T12:00:00+08:00",
        auditor_report_at=None,
        official_filed_at_source="official_filing_receipt",
        opinion_type="unmodified",
        auditor_firm="測試會計師事務所",
        auditors=("甲", "乙"),
        corrected=False,
        announcement_url="https://mops.twse.com.tw/a",
        announcement_sha256="a" * 64,
        receipt_url="https://doc.twse.com.tw/r",
        receipt_sha256="b" * 64,
        pdf_filename="report.pdf",
        pdf_source_url="https://doc.twse.com.tw/report.pdf",
        pdf_sha256=sha256(PDF).hexdigest(),
        pdf_path=tmp_path / "unused.pdf",
        retrieved_at="2026-07-29T12:00:00+08:00",
        available_at="2025-03-01T12:00:00+08:00",
        evidence_ids=(f"pdf:{sha256(PDF).hexdigest()}",),
        mandatory_evidence_gaps=(),
        coverage=Decimal("1"),
    )
    metadata = asdict(inventory)
    metadata.pop("pdf_path")
    metadata["coverage"] = "1"
    store.put_pdf(
        body=PDF,
        market=inventory.market,
        security_code=inventory.security_code,
        issuer_id=inventory.issuer_id,
        period=inventory.period,
        filing_type=inventory.filing_type,
        report_scope=inventory.report_scope,
        official_filed_at=inventory.official_filed_at,
        source_url=inventory.pdf_source_url or "",
        retrieved_at=inventory.retrieved_at,
        corrected=inventory.corrected,
        metadata=metadata,
    )

    class NoNetwork:
        def post_json(self, url, payload):
            raise AssertionError("network post_json must not be called on cache hit")

        def get(self, url):
            raise AssertionError("network get must not be called on cache hit")

        def post_form(self, url, payload):
            raise AssertionError("network post_form must not be called on cache hit")

    hit = MopsAuditInventoryCollector(
        transport=NoNetwork(), filing_store=store
    ).collect_period(
        security_code="9933",
        issuer_id="20817282",
        market="TWSE",
        roc_year=113,
        quarter=4,
        issuer_type="domestic_general",
        industry_type="general",
        output_root=tmp_path / "generation",
        retrieved_at="2026-07-29T12:00:00+08:00",
        as_of="2026-07-29T12:00:00+08:00",
    )

    assert hit.pdf_path is not None
    assert "filing-store/blobs" in hit.pdf_path.as_posix()
    assert hit.pdf_sha256 == sha256(PDF).hexdigest()


def test_financial_collector_uses_three_local_hits_without_network(tmp_path: Path) -> None:
    store = FilingStore(tmp_path / "filing-store")
    for report, endpoint in (
        ("balance", "ajax_t164sb03"),
        ("income", "ajax_t164sb04"),
        ("cash_flow", "ajax_t164sb05"),
    ):
        store.put_statement(
            body=HTML.replace(b"assets", report.encode()),
            market="TWSE",
            security_code="9933",
            issuer_id="20817282",
            period="113Q4",
            report=report,
            official_url=f"https://mopsov.twse.com.tw/mops/web/{endpoint}",
            retrieved_at="2025-03-02T12:00:00+08:00",
            available_at="2025-03-02T12:00:00+08:00",
        )

    class NoNetwork:
        def preload(self, endpoint):
            raise AssertionError("network preload must not be called on cache hit")

        def post(self, endpoint, payload):
            raise AssertionError("network post must not be called on cache hit")

    result = MopsFinancialCollector(
        transport=NoNetwork(), filing_store=store
    ).collect_period(
        security_code="9933",
        company_name="中鼎工程股份有限公司",
        company_short_name="中鼎",
        issuer_id="20817282",
        market="TWSE",
        period=Period(113, 4),
        output_root=tmp_path / "generation",
        retrieved_at="2026-07-29T12:00:00+08:00",
        as_of="2026-07-29T12:00:00+08:00",
    )

    assert {artifact.report for artifact in result.artifacts} == {
        "balance", "income", "cash_flow"
    }
    assert all("filing-store/html" in artifact.path.as_posix() for artifact in result.artifacts)
