from __future__ import annotations

from dataclasses import replace
from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
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
from company_quality.company_analysis.guidance_industry import (
    GuidanceIndustryCollector,
    GuidanceEvidenceError,
)
from company_quality.company_analysis.valuation import (
    MarketValuationCollector,
    ValuationEvidenceError,
    build_valuation_scenarios,
)
import company_quality.company_analysis.guidance_industry as guidance_module
from company_quality.company_analysis.report_orchestrator import (
    HermesApiCandidateAdapter,
    ReportOrchestrationError,
    admit_hermes_candidates,
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


IR_LIST = """<html><body><table>
<tr><td>9933</td><td>中鼎</td><td>115/03/11</td><td>14:30</td><td>線上法說</td><td>2025年營運回顧與展望</td><td>993320260311M001.pdf</td><td>993320260311E001.pdf</td></tr>
<tr><td>9933</td><td>中鼎</td><td>115/05/14</td><td>14:30</td><td>線上法說</td><td>2026年至今營運回顧與展望</td><td>993320260514M001.pdf</td><td>993320260514E001.pdf</td></tr>
</table></body></html>""".encode()

SEC_DEMAND = b"<html><body><p>strong demand for our leading-edge process technologies</p></body></html>"
SEC_CAPEX = b"<html><body><p>Capital expenditures (496.00) (350.76) (297.22)</p></body></html>"


class _GuidanceTransport:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.list_calls = 0
        self.pdf_calls: list[str] = []
        self.get_calls: list[str] = []

    def ir_list(self, *, roc_year: int, **_: object) -> bytes:
        self.list_calls += 1
        if self.fail:
            raise GuidanceEvidenceError("network list called")
        return IR_LIST if roc_year == 115 else "<html><body>查無資料</body></html>".encode()

    def ir_pdf(self, *, filename: str) -> bytes:
        self.pdf_calls.append(filename)
        if self.fail:
            raise GuidanceEvidenceError("network PDF called")
        return b"%PDF-test-fixture"

    def get(self, *, url: str) -> bytes:
        self.get_calls.append(url)
        if self.fail:
            raise GuidanceEvidenceError("network SEC called")
        return SEC_CAPEX if "presentation" in url else SEC_DEMAND


def _guidance_pages(_: bytes) -> tuple[str, ...]:
    return (
        "新簽約額及分布 1,025 1,118 1,256 1,813 388 截至2026/05/04 累計簽約金額已達新台幣734.46億 高科技41% 能資源循環28% 水資源及環境20%",
        "在建工程及分布 3,289 3,469 3,334 4,504 4,718",
        "合併營收及分布 951 1,035 1,199 918 172",
        "未來12個月全球潛在商機 9,760億",
        "高科技及AI商機 (1/2) 半導體 數據中心",
        "ESG商機 – 燃氣電廠 潛在商機約新台幣4,000億元 國內天然氣電廠市占率達70%",
    )


def test_guidance_collector_is_pit_local_first_and_separates_source_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guidance_module, "_pdf_pages", _guidance_pages)
    transport = _GuidanceTransport()
    current_as_of = (
        datetime.now(timezone.utc)
        .astimezone(guidance_module._TAIPEI)
        .replace(microsecond=0)
        .isoformat()
    )
    result = GuidanceIndustryCollector(transport).collect(
        market="TWSE",
        security_code="9933",
        company_name="中鼎工程股份有限公司",
        as_of=current_as_of,
        store_root=tmp_path,
    )
    assert result.issuer_presentation == "993320260514M001.pdf"
    assert len(result.facts) == 8
    assert transport.pdf_calls == ["993320260514M001.pdf"]
    assert len(transport.get_calls) == 2
    assert {fact.citation.source_tier for fact in result.facts} == {
        "issuer_primary",
        "official",
    }
    assert next(fact for fact in result.facts if fact.fact_id == "issuer:opportunity-pipeline").direction == "context"

    no_network = _GuidanceTransport(fail=True)
    cached = GuidanceIndustryCollector(no_network).collect(
        market="TWSE",
        security_code="9933",
        company_name="中鼎工程股份有限公司",
        as_of=current_as_of,
        store_root=tmp_path,
    )
    assert no_network.list_calls == 0
    assert no_network.pdf_calls == []
    assert no_network.get_calls == []
    assert cached.cache_hits == 5
    assert cached.online_fetches == 0


def test_guidance_ir_exact_time_pit_and_identity_fail_closed() -> None:
    records = guidance_module._parse_ir_list(IR_LIST, "9933")
    latest = max(records, key=lambda record: record.event_date)
    assert guidance_module._ir_available_at(latest).isoformat() == "2026-05-14T14:30:00+08:00"
    assert guidance_module._ir_available_at(latest) > guidance_module._instant(
        "2026-05-14T14:29:59+08:00", "as_of"
    )
    with pytest.raises(GuidanceEvidenceError, match="identity mismatch"):
        guidance_module._parse_ir_list(IR_LIST.replace(b"9933", b"9999"), "9933")


class _ValuationTransport:
    def __init__(self, market_date: str = "1150728") -> None:
        self.market_date = market_date
        self.calls = 0

    def get(self, *, url: str) -> bytes:
        self.calls += 1
        if "BWIBBU" in url:
            rows = [
                {"Date": self.market_date, "Code": "9933", "Name": "中鼎", "PEratio": "9.24", "DividendYield": "2.56", "PBratio": "1.69"},
                {"Date": self.market_date, "Code": "6139", "Name": "亞翔", "PEratio": "19.54", "DividendYield": "3.27", "PBratio": "7.57"},
                {"Date": self.market_date, "Code": "6196", "Name": "帆宣", "PEratio": "30.22", "DividendYield": "1.36", "PBratio": "5.98"},
                {"Date": self.market_date, "Code": "6691", "Name": "洋基工程", "PEratio": "23.90", "DividendYield": "3.41", "PBratio": "13.06"},
            ]
        else:
            rows = [{"Date": self.market_date, "Code": "9933", "Name": "中鼎", "ClosingPrice": "39.10"}]
        return json.dumps(rows, ensure_ascii=False).encode()


class _FailValuationTransport:
    def get(self, *, url: str) -> bytes:
        raise AssertionError(f"network called: {url}")


def test_valuation_snapshot_is_pit_local_first_and_scenarios_are_monotonic(
    tmp_path: Path,
) -> None:
    transport = _ValuationTransport()
    snapshot = MarketValuationCollector(transport).collect(
        market="TWSE",
        security_code="9933",
        company_name="中鼎工程股份有限公司",
        as_of=AS_OF,
        store_root=tmp_path,
    )
    assert transport.calls == 2
    assert snapshot.closing_price == Decimal("39.10")
    assert snapshot.pe_ratio == Decimal("9.24")
    assert snapshot.peer_pe_median == Decimal("23.90")
    cached = MarketValuationCollector(_FailValuationTransport()).collect(
        market="TWSE",
        security_code="9933",
        company_name="中鼎工程股份有限公司",
        as_of=AS_OF,
        store_root=tmp_path,
    )
    assert (cached.cache_hits, cached.online_fetches) == (2, 0)
    result = build_valuation_scenarios(
        market=cached,
        ttm_revenue_twd_100m=Decimal("1050"),
        ttm_eps=Decimal("4.23"),
        backlog_twd_100m=Decimal("4718"),
    )
    prices = [scenario.implied_price for scenario in result.scenarios]
    assert prices == sorted(prices)
    assert result.scenarios[1].name == "base"
    assert result.scenarios[1].backlog_conversion == Decimal("0.22")


def test_valuation_snapshot_rejects_future_market_date(tmp_path: Path) -> None:
    with pytest.raises(ValuationEvidenceError, match="future-dated"):
        MarketValuationCollector(_ValuationTransport("1150730")).collect(
            market="TWSE",
            security_code="9933",
            company_name="中鼎工程股份有限公司",
            as_of=AS_OF,
            store_root=tmp_path,
        )


class _FakeHermesAdapter:
    def __init__(self, candidates: list[dict[str, str]] | None = None, *, fail: bool = False) -> None:
        self.candidates = candidates or []
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def extract_candidates(self, **kwargs: object) -> list[dict[str, str]]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("Hermes API unavailable")
        return self.candidates


def _candidate(**overrides: str) -> dict[str, str]:
    candidate = {
        "candidate_id": "hermes:income-statement",
        "issuer_id": "22099131",
        "statement": "官方來源包含115Q1綜合損益表。",
        "verbatim_quote": "民國115年第1季 綜合損益表",
        "value": "115",
        "unit": "第1季",
        "period": "115Q1",
        "evidence_id": "TWSE:2330:115Q1:income:abc",
        "citation_locator": "document-text:contains(綜合損益表)",
    }
    candidate.update(overrides)
    return candidate


def test_fixed_hermes_candidate_enters_same_generation_report(tmp_path: Path) -> None:
    adapter = _FakeHermesAdapter([_candidate()])
    report = build_report_from_evidence(
        bundle=_bundle(tmp_path),
        generation_id=GENERATION,
        generated_at=GENERATED_AT,
        candidate_adapter=adapter,
    )

    assert adapter.calls[0]["generation_id"] == GENERATION
    assert any(item.finding_id == "hermes:income-statement" for item in report.downside.findings)
    assert "Hermes候選抽取：available" in " ".join(report.limitations)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"issuer_id": "wrong-issuer"}, "issuer_identity_mismatch"),
        ({"value": "999"}, "numeric_value_mismatch"),
        ({"verbatim_quote": "不存在的原文 115 第1季"}, "original_text_missing"),
        ({"unit": "億元"}, "unit_mismatch"),
        ({"period": "114Q4"}, "period_mismatch"),
        ({"citation_locator": ""}, "citation_locator_missing"),
    ],
)
def test_candidate_admission_returns_typed_rejections(
    tmp_path: Path, overrides: dict[str, str], reason: str
) -> None:
    base = build_report_from_evidence(
        bundle=_bundle(tmp_path), generation_id=GENERATION, generated_at=GENERATED_AT
    )
    result = admit_hermes_candidates(
        candidates=[_candidate(**overrides)],
        issuer_id="22099131",
        as_of=AS_OF,
        citations=base.citations,
    )

    assert result.admitted == ()
    assert result.rejected[0].reason == reason


def test_candidate_admission_rejects_future_source(tmp_path: Path) -> None:
    base = build_report_from_evidence(
        bundle=_bundle(tmp_path), generation_id=GENERATION, generated_at=GENERATED_AT
    )
    future = replace(base.citations[0], available_at="2026-07-30T00:00:00+08:00")
    result = admit_hermes_candidates(
        candidates=[_candidate()],
        issuer_id="22099131",
        as_of=AS_OF,
        citations=(future,),
    )

    assert result.rejected[0].reason == "pit_violation"


def test_hermes_failure_only_marks_llm_dependent_report_slice_partial(tmp_path: Path) -> None:
    report = build_report_from_evidence(
        bundle=_bundle(tmp_path),
        generation_id=GENERATION,
        generated_at=GENERATED_AT,
        candidate_adapter=_FakeHermesAdapter(fail=True),
    )

    assert report.citations
    assert report.downside.findings
    assert "Hermes候選抽取：partial (hermes_unavailable)" in " ".join(report.limitations)


def test_http_adapter_uses_openai_endpoint_and_dedicated_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            content = json.dumps({"candidates": [_candidate()]})
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def fake_urlopen(request, timeout: float):
        captured.update(
            url=request.full_url,
            headers=dict(request.headers),
            body=json.loads(request.data),
            timeout=timeout,
        )
        return _Response()

    monkeypatch.setattr("company_quality.company_analysis.candidate_admission.urlopen", fake_urlopen)
    adapter = HermesApiCandidateAdapter(
        base_url="http://127.0.0.1:8642/v1",
        api_key="test-only",
        session_id="company-quality-generation-1",
    )
    candidates = adapter.extract_candidates(
        issuer_id="22099131",
        as_of=AS_OF,
        generation_id=GENERATION,
        citations=(),
    )

    assert candidates == [_candidate()]
    assert captured["url"] == "http://127.0.0.1:8642/v1/chat/completions"
    assert captured["headers"]["X-hermes-session-id"] == "company-quality-generation-1"
    assert captured["body"]["model"] == "hermes-agent"
    assert captured["body"]["stream"] is False
    assert captured["body"]["tools"] == []
