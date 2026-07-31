from dataclasses import fields
from decimal import Decimal

import pytest

from company_quality.company_analysis.contracts import (
    CaseProbability,
    CompanyAnalysisRequest,
    CompanyAnalysisContractError,
    DownsideCase,
    EvidenceCitation,
    Finding,
    SourceCoverage,
    UpsideCase,
    build_single_company_research_report,
)


AS_OF = "2026-07-29T11:30:00+08:00"
GENERATION = "2330-20260729T113000+0800"


def _citation(*, available_at: str = "2026-03-10T17:00:00+08:00") -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id="mops:2330:114Q4:kam:1",
        source_id="mops:annual-report:2330:114",
        source_tier="official",
        url="https://doc.twse.com.tw/example.pdf",
        content_sha256="a" * 64,
        period="2025Q4",
        available_at=available_at,
        page=72,
        coordinate=(Decimal("0.10"), Decimal("0.20"), Decimal("0.90"), Decimal("0.40")),
        verbatim_excerpt="關鍵查核事項：收入認列",
    )


def _fact() -> Finding:
    return Finding(
        finding_id="fact:kam-revenue-recognition",
        kind="fact",
        direction="counter",
        statement="會計師將收入認列列為關鍵查核事項。",
        materiality=Decimal("0.70"),
        evidence_ids=("mops:2330:114Q4:kam:1",),
        supporting_finding_ids=(),
        counter_finding_ids=(),
        counter_evidence_reason=None,
    )


def _judgement(*, finding_id: str, direction: str) -> Finding:
    return Finding(
        finding_id=finding_id,
        kind="judgement",
        direction=direction,
        statement="此事項需要持續監測，但目前不足以單獨推導投資結論。",
        materiality=Decimal("0.50"),
        evidence_ids=(),
        supporting_finding_ids=("fact:kam-revenue-recognition",),
        counter_finding_ids=(),
        counter_evidence_reason="目前未發現查核意見修正式或收入更正。",
    )


def _build(**overrides):
    downside = DownsideCase(
        generation_id=GENERATION,
        status="research_only",
        headline="收入認列屬監測風險，尚無重大錯報證據。",
        findings=(_fact(), _judgement(finding_id="downside:revenue-risk", direction="counter")),
        twelve_month_drawdown_probability=CaseProbability(
            status="research_only",
            lower=Decimal("0.20"),
            point=None,
            upper=Decimal("0.40"),
            confidence=Decimal("0.35"),
            calibration_id=None,
            reason="evidence-derived calibration not completed",
        ),
        confidence=Decimal("0.50"),
    )
    upside = UpsideCase(
        generation_id=GENERATION,
        status="research_only",
        headline="成長條件需由產業與公司證據共同確認。",
        findings=(_fact(), _judgement(finding_id="upside:growth-case", direction="support")),
        positive_return_probability=CaseProbability(
            status="unavailable",
            lower=None,
            point=None,
            upper=None,
            confidence=None,
            calibration_id=None,
            reason="probability_not_formally_calibrated",
        ),
        benchmark_outperform_probability=CaseProbability(
            status="unavailable",
            lower=None,
            point=None,
            upper=None,
            confidence=None,
            calibration_id=None,
            reason="probability_not_formally_calibrated",
        ),
        confidence=Decimal("0.40"),
    )
    params = {
        "request": CompanyAnalysisRequest(
            issuer_id="03536005",
            security_code="2330",
            market="TWSE",
            as_of=AS_OF,
        ),
        "generation_id": GENERATION,
        "generated_at": "2026-07-29T11:31:00+08:00",
        "citations": (_citation(),),
        "source_coverage": (
            SourceCoverage(
                family="annual_report_pdf",
                required=5,
                available=5,
                missing_reasons=(),
            ),
        ),
        "downside": downside,
        "upside": upside,
        "limitations": ("industry evidence pending",),
    }
    params.update(overrides)
    return build_single_company_research_report(**params)


def test_report_keeps_evidence_first_downside_and_upside_cases_independent() -> None:
    report = _build()

    assert report.schema_version == "SingleCompanyResearchReport.v4"
    assert report.request.security_code == "2330"
    assert report.downside.headline != report.upside.headline
    assert report.downside.twelve_month_drawdown_probability.point is None
    assert report.upside.positive_return_probability.status == "unavailable"
    assert "combined_score" not in {field.name for field in fields(report)}


def test_html_citation_uses_line_locator_without_fake_pdf_page() -> None:
    citation = EvidenceCitation(
        evidence_id="mops:2330:114Q4:kam:1",
        source_id="sec:6-k:2026q2:ex99.1",
        source_tier="official",
        url="https://www.sec.gov/Archives/edgar/data/1046179/filing.htm",
        content_sha256="b" * 64,
        period="2026Q2",
        available_at="2026-07-16T00:00:00+00:00",
        page=None,
        coordinate=None,
        verbatim_excerpt="Revenue is expected to be between US$44.6 billion and US$45.8 billion.",
        source_format="html",
        locator="lines:13-17",
    )
    report = _build(citations=(citation,))

    assert report.citations[0].locator == "lines:13-17"
    assert report.citations[0].page is None


def test_report_rejects_evidence_published_after_analysis_as_of() -> None:
    with pytest.raises(CompanyAnalysisContractError, match="after analysis as_of"):
        _build(citations=(_citation(available_at="2026-07-30T09:00:00+08:00"),))


def test_report_rejects_fact_without_citation() -> None:
    bad_fact = Finding(
        finding_id="fact:unsupported",
        kind="fact",
        direction="context",
        statement="沒有來源的事實。",
        materiality=Decimal("0.20"),
        evidence_ids=(),
        supporting_finding_ids=(),
        counter_finding_ids=(),
        counter_evidence_reason=None,
    )
    downside = _build().downside
    bad_downside = DownsideCase(
        generation_id=downside.generation_id,
        status=downside.status,
        headline=downside.headline,
        findings=(bad_fact,),
        twelve_month_drawdown_probability=downside.twelve_month_drawdown_probability,
        confidence=downside.confidence,
    )

    with pytest.raises(CompanyAnalysisContractError, match="fact requires evidence"):
        _build(downside=bad_downside)


def test_report_rejects_judgement_without_support_or_counter_evidence_handling() -> None:
    unsupported = Finding(
        finding_id="judgement:unsupported",
        kind="judgement",
        direction="support",
        statement="沒有證據鏈的判斷。",
        materiality=Decimal("0.30"),
        evidence_ids=(),
        supporting_finding_ids=(),
        counter_finding_ids=(),
        counter_evidence_reason=None,
    )
    upside = _build().upside
    bad_upside = UpsideCase(
        generation_id=upside.generation_id,
        status=upside.status,
        headline=upside.headline,
        findings=(unsupported,),
        positive_return_probability=upside.positive_return_probability,
        benchmark_outperform_probability=upside.benchmark_outperform_probability,
        confidence=upside.confidence,
    )

    with pytest.raises(CompanyAnalysisContractError, match="supporting findings"):
        _build(upside=bad_upside)


def test_report_rejects_mixed_case_generation() -> None:
    upside = _build().upside
    mismatched = UpsideCase(
        generation_id="other-generation",
        status=upside.status,
        headline=upside.headline,
        findings=upside.findings,
        positive_return_probability=upside.positive_return_probability,
        benchmark_outperform_probability=upside.benchmark_outperform_probability,
        confidence=upside.confidence,
    )

    with pytest.raises(CompanyAnalysisContractError, match="same generation"):
        _build(upside=mismatched)
