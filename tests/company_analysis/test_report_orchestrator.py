from __future__ import annotations

from dataclasses import replace
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
                financial=PeriodCollection("available", (quarter_income,), 1.0),
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
