from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle, PeriodEvidence
from company_quality.company_analysis.probability_calibration import (
    EmpiricalProbabilityCalibration,
    SingleCompanyProbabilityCalibration,
    Target,
)
from company_quality.company_analysis.material_events import (
    MaterialEventCollector,
    MaterialEventError,
)
from company_quality.company_analysis.report_orchestrator import (
    ReportOrchestrationError,
    build_report_from_evidence,
)
from company_quality.company_analysis.contracts import CompanyAnalysisRequest, SourceCoverage
from company_quality.identity import CompanyIdentity
from company_quality.sources.financial import FinancialArtifact, PeriodCollection


AS_OF = "2026-07-29T13:30:00+08:00"
GENERATED_AT = "2026-07-29T13:31:00+08:00"
GENERATION = "generation-1"


def _bundle(tmp_path: Path) -> CompanyEvidenceBundle:
    path = tmp_path / "income.html"
    body = """<html><body><h1>台灣積體電路製造股份有限公司</h1><h2>民國115年第1季 綜合損益表</h2></body></html>""".encode()
    path.write_bytes(body)
    artifact = FinancialArtifact(
        artifact_id="TWSE:2330:115Q1:income:abc",
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        period="115Q1",
        report="income",
        official_url="https://mopsov.twse.com.tw/mops/web/ajax_t164sb04",
        endpoint_scope="selected_company",
        content_sha256=sha256(body).hexdigest(),
        retrieved_at=AS_OF,
        available_at=AS_OF,
        availability_basis="first_successful_retrieval",
        official_filed_at=None,
        mime_type="text/html",
        path=path,
    )
    return CompanyEvidenceBundle(
        request=CompanyAnalysisRequest("22099131", "2330", "TWSE", AS_OF),
        identity=CompanyIdentity(
            security_id="TWSE:2330",
            security_code="2330",
            issuer_id="22099131",
            company_name="台灣積體電路製造股份有限公司",
            short_name="台積電",
            market="TWSE",
            valid_from="1994-09-05T00:00:00+08:00",
        ),
        retrieved_at=AS_OF,
        periods=(
            PeriodEvidence(
                period="115Q1",
                is_annual=False,
                financial=PeriodCollection("available", (artifact,), 1.0),
                audit=None,
                missing_reasons=("115Q1:audit_or_review_pdf:missing",),
            ),
        ),
        source_coverage=(
            SourceCoverage("three_statement_html", 60, 60, ()),
            SourceCoverage("audit_or_review_pdf", 20, 3, ("audit gaps",)),
            SourceCoverage("annual_audit_pdf", 5, 0, ("annual gaps",)),
        ),
        status="partial",
    )


def _metric(target: Target, point: str) -> EmpiricalProbabilityCalibration:
    return EmpiricalProbabilityCalibration(
        target=target,
        successes=16,
        trials=18,
        point=Decimal(point),
        lower=Decimal("0.60"),
        upper=Decimal("0.95"),
        confidence_level=Decimal("0.90"),
        calibration_id=f"calibration:{target}",
    )


def _table_artifact(
    tmp_path: Path,
    *,
    period: str,
    report: str,
    rows: tuple[tuple[str, ...], ...],
) -> FinancialArtifact:
    body = (
        "<html><body><h2>綜合損益表</h2><table>"
        + "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        + "</table></body></html>"
    ).encode()
    path = tmp_path / f"{period}-{report}.html"
    path.write_bytes(body)
    return FinancialArtifact(
        artifact_id=f"TWSE:2330:{period}:{report}:fixture",
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        period=period,
        report=report,  # type: ignore[arg-type]
        official_url="https://mopsov.twse.com.tw/mops/web/ajax_t164sb04",
        endpoint_scope="selected_company",
        content_sha256=sha256(body).hexdigest(),
        retrieved_at=AS_OF,
        available_at=AS_OF,
        availability_basis="first_successful_retrieval",
        official_filed_at=None,
        mime_type="text/html",
        path=path,
    )


def _detailed_bundle(tmp_path: Path) -> CompanyEvidenceBundle:
    base = _bundle(tmp_path)
    annual_income = _table_artifact(
        tmp_path,
        period="114Q4",
        report="income",
        rows=(
            ("營業收入合計", "3,800,000", "100", "2,900,000", "100"),
            ("營業毛利（毛損）", "2,280,000", "60", "1,624,000", "56"),
            ("營業利益（損失）", "1,938,000", "51", "1,305,000", "45"),
            ("本期淨利（淨損）", "1,650,000", "43", "1,150,000", "40"),
        ),
    )
    annual_balance = _table_artifact(
        tmp_path,
        period="114Q4",
        report="balance",
        rows=(
            ("現金及約當現金", "2,700,000", "34", "2,100,000", "31"),
            ("應收帳款淨額", "279,000", "4", "270,000", "4"),
            ("存貨", "288,000", "4", "287,000", "4"),
            ("流動資產合計", "3,800,000", "48", "3,080,000", "46"),
            ("流動負債合計", "1,450,000", "18", "1,260,000", "19"),
            ("負債總額", "2,470,000", "31", "2,360,000", "35"),
            ("權益總額", "5,460,000", "69", "4,320,000", "65"),
            ("不動產、廠房及設備", "3,690,000", "47", "3,230,000", "48"),
            ("其他非流動資產", "310,000", "4", "300,000", "4"),
            ("非流動資產合計", "4,000,000", "50", "3,530,000", "53"),
            ("資產總額", "7,930,000", "100", "6,680,000", "100"),
        ),
    )
    annual_cash = _table_artifact(
        tmp_path,
        period="114Q4",
        report="cash_flow",
        rows=(
            ("營業活動之淨現金流入（流出）", "2,270,000", "1,820,000"),
            ("取得不動產、廠房及設備", "-1,270,000", "-956,000"),
        ),
    )
    quarter_income = _table_artifact(
        tmp_path,
        period="115Q1",
        report="income",
        rows=(
            ("營業收入合計", "1,130,000", "100", "1,130,000", "100", "839,000", "100", "839,000", "100"),
            ("營業毛利（毛損）", "751,000", "66", "751,000", "66", "493,000", "59", "493,000", "59"),
            ("營業利益（損失）", "659,000", "58", "659,000", "58", "407,000", "49", "407,000", "49"),
            ("本期淨利（淨損）", "573,000", "51", "573,000", "51", "361,000", "43", "361,000", "43"),
        ),
    )
    quarter_balance = _table_artifact(
        tmp_path,
        period="115Q1",
        report="balance",
        rows=(
            ("不動產、廠房及設備", "3,800,000", "42", "3,690,000", "47"),
            ("其他非流動資產", "2,200,000", "24", "310,000", "4"),
            ("非流動資產合計", "6,000,000", "67", "4,000,000", "50"),
            ("資產總額", "9,000,000", "100", "7,930,000", "100"),
        ),
    )
    return replace(
        base,
        periods=(
            PeriodEvidence(
                period="114Q4",
                is_annual=True,
                financial=PeriodCollection(
                    "available", (annual_income, annual_balance, annual_cash), 1.0
                ),
                audit=None,
                missing_reasons=("114Q4:annual_audit_pdf:missing",),
            ),
            PeriodEvidence(
                period="115Q1",
                is_annual=False,
                financial=PeriodCollection(
                    "available", (quarter_income, quarter_balance), 1.0
                ),
                audit=None,
                missing_reasons=("115Q1:audit_or_review_pdf:missing",),
            ),
        ),
    )


def _calibration() -> SingleCompanyProbabilityCalibration:
    return SingleCompanyProbabilityCalibration(
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        season_month=7,
        final_oos_start="2026-01-01",
        observations=(),
        positive_return=_metric("positive_total_return", "0.88"),
        official_outperformance=_metric("outperformed_official_market", "0.77"),
        minimum_observations=15,
        status="formal",
        failure_reasons={},
        ignored_final_oos_company_points=0,
        ignored_final_oos_benchmark_points=0,
        company_source_ref="FinLab:etl:adj_close",
        official_benchmark_source_ref="https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U",
        generated_at=GENERATED_AT,
        generation_id=GENERATION,
    )


def test_builds_valid_blocked_report_without_inventing_narrative(tmp_path: Path) -> None:
    report = build_report_from_evidence(
        bundle=_bundle(tmp_path),
        generation_id=GENERATION,
        generated_at=GENERATED_AT,
    )

    assert report.schema_version == "SingleCompanyResearchReport.v2"
    assert report.downside.status == "blocked"
    assert report.upside.status == "blocked"
    assert report.upside.positive_return_probability.status == "unavailable"
    assert report.citations[0].source_format == "html"
    assert "綜合損益表" in report.citations[0].verbatim_excerpt
    assert "KAM" in " ".join(report.limitations)


def test_same_generation_formal_calibration_enters_upside_probabilities(tmp_path: Path) -> None:
    report = build_report_from_evidence(
        bundle=_bundle(tmp_path),
        generation_id=GENERATION,
        generated_at=GENERATED_AT,
        calibration=_calibration(),
    )

    assert report.upside.positive_return_probability.status == "formal"
    assert report.upside.positive_return_probability.point == Decimal("0.88")
    assert report.upside.benchmark_outperform_probability.point == Decimal("0.77")


def test_builds_detailed_research_cases_from_financial_evidence(tmp_path: Path) -> None:
    report = build_report_from_evidence(
        bundle=_detailed_bundle(tmp_path),
        generation_id=GENERATION,
        generated_at=GENERATED_AT,
        calibration=_calibration(),
    )

    assert report.downside.status == "research_only"
    assert report.upside.status == "research_only"
    statements = " ".join(
        item.statement for item in (*report.downside.findings, *report.upside.findings)
    )
    assert "營業現金流" in statements
    assert "最新季度" in statements
    assert "優先監控" in statements
    assert "blocked_by_missing_evidence" in statements
    assert "非流動資產" in statements
    assert any(item.kind == "judgement" for item in report.downside.findings)
    assert len(report.citations) >= 18


def test_rejects_stale_or_wrong_company_calibration(tmp_path: Path) -> None:
    with pytest.raises(ReportOrchestrationError, match="generation"):
        build_report_from_evidence(
            bundle=_bundle(tmp_path),
            generation_id=GENERATION,
            generated_at=GENERATED_AT,
            calibration=replace(_calibration(), generation_id="older-generation"),
        )
    with pytest.raises(ReportOrchestrationError, match="identity"):
        build_report_from_evidence(
            bundle=_bundle(tmp_path),
            generation_id=GENERATION,
            generated_at=GENERATED_AT,
            calibration=replace(_calibration(), security_code="2454"),
        )


EVENT_LIST = """<html><body><table>
<tr><th>公司代號</th><th>公司名稱</th><th>發言日期</th><th>發言時間</th><th>主旨</th><th></th></tr>
<tr><td>9933</td><td>中鼎</td><td>113/08/02</td><td>09:01:53</td><td>法人說明會</td>
<td><input value="詳細資料" onclick="document.t05st01_fm.seq_no.value='1';document.t05st01_fm.spoke_time.value='90153';document.t05st01_fm.spoke_date.value='20240802';document.t05st01_fm.co_id.value='9933';document.t05st01_fm.TYPEK.value='sii';"></td></tr>
<tr><td>9933</td><td>中鼎</td><td>113/12/13</td><td>17:11:15</td>
<td>中鼎公告董事會決議將南科再生水廠資產分割讓與子公司案</td>
<td><input value="詳細資料" onclick="document.t05st01_fm.seq_no.value='4';document.t05st01_fm.spoke_time.value='171115';document.t05st01_fm.spoke_date.value='20241213';document.t05st01_fm.co_id.value='9933';document.t05st01_fm.TYPEK.value='sii';"></td></tr>
</table></body></html>""".encode()

EVENT_DETAIL = """<html><body><table>
<tr><td>序號</td><td>4</td><td>發言日期</td><td>113/12/13</td><td>發言時間</td><td>17:11:15</td></tr>
<tr><td>主旨</td><td>中鼎公告董事會決議將南科再生水廠資產分割讓與子公司案</td></tr>
<tr><td>符合條款</td><td>第 11 款</td><td>事實發生日</td><td>113/12/13</td></tr>
<tr><td>說明</td><td>1.併購種類:分割 2.交易係集團組織調整 3.營業價值新台幣2,434,594仟元</td></tr>
</table></body></html>""".encode()


class _EventTransport:
    def __init__(self, *, fail: bool = False) -> None:
        self.list_calls = 0
        self.detail_calls = 0
        self.fail = fail

    def list_year(self, **_: object) -> bytes:
        self.list_calls += 1
        if self.fail:
            raise MaterialEventError("official source unavailable")
        return EVENT_LIST

    def detail(self, **_: object) -> bytes:
        self.detail_calls += 1
        return EVENT_DETAIL


def _collect_events(tmp_path: Path, transport: _EventTransport, as_of: str):
    return MaterialEventCollector(transport).collect(
        market="TWSE",
        security_code="9933",
        company_name="中鼎工程股份有限公司",
        roc_year=113,
        start_date=date(2024, 10, 1),
        end_date=date(2024, 12, 31),
        as_of=as_of,
        store_root=tmp_path,
    )


def test_material_event_collector_is_pit_local_first_and_display_only(tmp_path: Path) -> None:
    transport = _EventTransport()
    result = _collect_events(tmp_path, transport, "2024-12-14T00:00:00+08:00")
    assert (transport.list_calls, transport.detail_calls) == (1, 1)
    assert result.online_fetches == 2
    assert result.events[0].disposition == "display_only"
    assert result.events[0].announced_at == "2024-12-13T17:11:15+08:00"
    assert result.events[0].effective_at == "2024-12-13"

    no_network = _EventTransport(fail=True)
    cached = _collect_events(tmp_path, no_network, AS_OF)
    assert (no_network.list_calls, no_network.detail_calls) == (0, 0)
    assert cached.cache_hits == 2

    before = _collect_events(tmp_path, no_network, "2024-12-13T17:11:14+08:00")
    assert before.events == ()


def test_material_event_source_failure_is_not_reported_as_zero(tmp_path: Path) -> None:
    with pytest.raises(MaterialEventError, match="official source unavailable"):
        _collect_events(tmp_path, _EventTransport(fail=True), AS_OF)


def test_material_event_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    class WrongIdentity(_EventTransport):
        def list_year(self, **_: object) -> bytes:
            return EVENT_LIST.replace(b"9933", b"9999")

    with pytest.raises(MaterialEventError, match="identity mismatch"):
        _collect_events(tmp_path, WrongIdentity(), AS_OF)
