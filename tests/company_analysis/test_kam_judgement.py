from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import threading
from urllib.request import urlopen

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.company_analysis.contracts import CompanyAnalysisRequest, SourceCoverage
from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle, PeriodEvidence
from company_quality.company_analysis.report_orchestrator import build_kam_judgement
from company_quality.dashboard_jobs import AnalysisJobService
from company_quality.dashboard_server import make_server
from company_quality.identity import CompanyIdentity, OfficialIdentitySource


AS_OF = "2026-07-29T13:30:00+08:00"
GENERATION = "kam-generation-1"
ISSUER = "22099131"


def _audit(tmp_path: Path, period: str, *, opinion: str = "unmodified", firm: str = "甲會計師事務所") -> AuditFilingInventory:
    path = tmp_path / f"{period}.pdf"
    body = f"%PDF-{period}".encode()
    path.write_bytes(body)
    return AuditFilingInventory(
        security_code="2330",
        issuer_id=ISSUER,
        market="TWSE",
        period=period,
        filing_type="annual_audit",
        issuer_type="domestic_general",
        industry_type="general",
        fiscal_period_start=f"{int(period[:3]) + 1911}-01-01",
        fiscal_period_end=f"{int(period[:3]) + 1911}-12-31",
        assurance_type="audit",
        report_scope="consolidated",
        deadline_rule_id="rule",
        deadline_rule_version="v1",
        ordinary_due_at=AS_OF,
        holiday_adjustment_days=0,
        approved_extension_days=0,
        extension_rule_id=None,
        statutory_due_at=AS_OF,
        holiday_calendar_version="v1",
        official_filed_at="2026-03-01T10:00:00+08:00",
        auditor_report_at=None,
        official_filed_at_source="official_filing_receipt",
        opinion_type=opinion,  # type: ignore[arg-type]
        auditor_firm=firm,
        auditors=("王大明", "李小華"),
        corrected=False,
        announcement_url="https://mops.test/announcement",
        announcement_sha256="a" * 64,
        receipt_url="https://mops.test/receipt",
        receipt_sha256="b" * 64,
        pdf_filename=path.name,
        pdf_source_url=f"https://mops.test/{path.name}",
        pdf_sha256=sha256(body).hexdigest(),
        pdf_path=path,
        retrieved_at=AS_OF,
        available_at="2026-03-01T10:00:00+08:00",
        evidence_ids=(f"audit:{period}",),
        mandatory_evidence_gaps=(),
        coverage=Decimal("1"),
    )


def _bundle(tmp_path: Path, periods: tuple[str, ...] = ("112Q4", "113Q4", "114Q4")) -> CompanyEvidenceBundle:
    audits = {
        period: _audit(
            tmp_path,
            period,
            opinion="qualified" if period == "114Q4" else "unmodified",
            firm="乙會計師事務所" if period == "114Q4" else "甲會計師事務所",
        )
        for period in periods
    }
    return CompanyEvidenceBundle(
        request=CompanyAnalysisRequest(ISSUER, "2330", "TWSE", AS_OF),
        identity=CompanyIdentity(
            security_id="TWSE:2330",
            security_code="2330",
            issuer_id=ISSUER,
            company_name="台灣積體電路製造股份有限公司",
            short_name="台積電",
            market="TWSE",
            valid_from="1994-09-05T00:00:00+08:00",
        ),
        retrieved_at=AS_OF,
        periods=tuple(
            PeriodEvidence(period, True, None, audits[period], ()) for period in periods
        ),
        source_coverage=(SourceCoverage("annual_audit_pdf", 3, len(periods), ("111Q4:pdf_missing",) if len(periods) < 3 else ()),),
        status="available" if len(periods) == 3 else "partial",
    )


def _pages(path: Path) -> tuple[str, ...]:
    period = path.stem
    extras = {
        "112Q4": "繼續經營有關之重大不確定性 公司仍有充分資金。",
        "113Q4": "強調事項 本段不影響查核意見。",
        "114Q4": "",
    }
    return (
        f"{period} 查核報告首頁",
        f"關鍵查核事項 {period} 收入認列涉及重大判斷。查核程序包括抽核合約。 {extras.get(period, '')}",
    )


class FakeKamAdapter:
    def __init__(self, *, response: dict[str, object] | None = None, fail: bool = False) -> None:
        self.response = response
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def judge_kam(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("Hermes unavailable")
        if self.response is not None:
            return self.response
        citations = kwargs["citations"]
        return {
            "issuer_id": ISSUER,
            "change_summary": "三年皆涉及收入認列，114年度說明範圍擴大。",
            "risk_mechanism": "長約估計變動可能改變收入認列時點。",
            "counterevidence": "查核程序包含合約抽核，KAM存在本身不代表錯誤。",
            "severity": "medium",
            "confidence": "0.78",
            "monitoring": "監控合約資產與估計變更。",
            "invalidation": "若後續原始報告顯示議題已消失且估計差異不重大。",
            "yearly_citations": [
                {
                    "period": item.period,
                    "evidence_id": item.evidence_id,
                    "verbatim_quote": item.verbatim_excerpt,
                    "citation_locator": f"page:{item.page}",
                }
                for item in citations
            ],
        }


def test_three_year_kam_judgement_keeps_audit_facts_separate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("company_quality.company_analysis.report_orchestrator._pdf_pages", _pages)
    adapter = FakeKamAdapter()

    result = build_kam_judgement(
        bundle=_bundle(tmp_path), generation_id=GENERATION, candidate_adapter=adapter
    )

    assert result.generation_id == GENERATION
    assert result.status == "available"
    assert [year.period for year in result.years] == ["114Q4", "113Q4", "112Q4"]
    assert all(year.citation.verbatim_excerpt.startswith("關鍵查核事項") for year in result.years)
    assert result.change_summary and result.risk_mechanism and result.counterevidence
    assert result.severity == "medium"
    assert result.confidence == Decimal("0.78")
    assert result.monitoring and result.invalidation
    newest, middle, oldest = result.years
    assert newest.modified_opinion is True
    assert newest.auditor_change is True
    assert middle.emphasis_matter is True
    assert oldest.going_concern is True
    assert all(year.kam_present is True for year in result.years)
    assert adapter.calls[0]["generation_id"] == GENERATION


def test_less_than_three_years_is_partial_and_hermes_failure_preserves_timeline(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("company_quality.company_analysis.report_orchestrator._pdf_pages", _pages)

    result = build_kam_judgement(
        bundle=_bundle(tmp_path, ("113Q4", "114Q4")),
        generation_id=GENERATION,
        candidate_adapter=FakeKamAdapter(fail=True),
    )

    assert result.status == "partial"
    assert len(result.years) == 2
    assert "111Q4:pdf_missing" in result.missing_year_reasons
    assert "hermes_unavailable" in result.rejection_reasons
    assert result.change_summary is None


def test_kam_admission_rejects_wrong_page_missing_quote_wrong_issuer_and_future(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("company_quality.company_analysis.report_orchestrator._pdf_pages", _pages)
    baseline = build_kam_judgement(
        bundle=_bundle(tmp_path), generation_id=GENERATION, candidate_adapter=None
    )
    response = FakeKamAdapter().judge_kam(
        issuer_id=ISSUER,
        as_of=AS_OF,
        generation_id=GENERATION,
        citations=tuple(year.citation for year in baseline.years),
    )
    response["issuer_id"] = "wrong-issuer"
    yearly = response["yearly_citations"]
    assert isinstance(yearly, list)
    yearly[0]["citation_locator"] = "page:1"
    yearly[1]["verbatim_quote"] = "不存在的原文"

    rejected = build_kam_judgement(
        bundle=_bundle(tmp_path),
        generation_id=GENERATION,
        candidate_adapter=FakeKamAdapter(response=response),
    )
    assert rejected.status == "partial"
    assert {"issuer_identity_mismatch", "citation_locator_mismatch", "original_text_missing"}.issubset(
        set(rejected.rejection_reasons)
    )

    wrong_bundle = _bundle(tmp_path)
    wrong_audit = replace(wrong_bundle.periods[-1].audit, issuer_id="wrong")
    wrong_bundle = replace(
        wrong_bundle,
        periods=(*wrong_bundle.periods[:-1], replace(wrong_bundle.periods[-1], audit=wrong_audit)),
    )
    future_audit = replace(wrong_bundle.periods[-2].audit, available_at="2026-07-30T00:00:00+08:00")
    wrong_bundle = replace(
        wrong_bundle,
        periods=(wrong_bundle.periods[0], replace(wrong_bundle.periods[1], audit=future_audit), wrong_bundle.periods[2]),
    )
    excluded = build_kam_judgement(
        bundle=wrong_bundle, generation_id=GENERATION, candidate_adapter=None
    )
    assert len(excluded.years) == 1
    assert any("wrong_issuer" in reason for reason in excluded.missing_year_reasons)
    assert any("after_as_of" in reason for reason in excluded.missing_year_reasons)


SOURCES = (
    OfficialIdentitySource(
        market="TWSE",
        url="https://official.test/twse",
        available_at="2026-07-29T00:00:00+08:00",
        rows=({"security_code": "2330", "company_name": "台灣積體電路製造股份有限公司", "short_name": "台積電", "issuer_id": ISSUER, "listing_date": "19940905"},),
    ),
)


@dataclass(frozen=True)
class FakeResult:
    generation_id: str
    kam_judgement: object


def test_dashboard_and_json_expose_kam_problem_section(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("company_quality.company_analysis.report_orchestrator._pdf_pages", _pages)
    kam = build_kam_judgement(
        bundle=_bundle(tmp_path), generation_id=GENERATION, candidate_adapter=FakeKamAdapter()
    )
    service = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=lambda: SOURCES,
        analyzer=lambda **kwargs: FakeResult(str(kwargs["generation_id"]), kam),
    )
    service.start()
    created = service.create_job(identifier="2330", market="TWSE", as_of=AS_OF)
    service._queue.join()
    payload = service.get_result(str(created["job_id"]))
    assert payload["kam_judgement"]["generation_id"] == GENERATION
    assert payload["kam_judgement"]["years"][0]["citation"]["verbatim_excerpt"]
    assert payload["kam_judgement"]["severity"] == "medium"

    server = make_server(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
            html = response.read().decode()
        assert "KAM問題" in html
        assert "kam_judgement" in html
        assert "risk_mechanism" in html
        assert "KAM存在本身不等於問題" in html
    finally:
        server.shutdown()
        server.server_close()
        service.stop()
