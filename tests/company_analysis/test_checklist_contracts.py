from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from company_quality.company_analysis.checklist_analysis import (
    _CANONICAL_GROWTH_METRICS,
    _CANONICAL_RISK_METRICS,
    _document_checks,
    _placeholder_checks,
    _quantitative_checks,
    _ids,
)

from company_quality.company_analysis.checklist_contracts import (
    AUDIT_CHECK_IDS,
    GROWTH_CHECK_IDS,
    GROWTH_DIMENSIONS,
    GROWTH_TRANSMISSION_STAGES,
    NOTE_CHECK_IDS,
    REQUIRED_COMPLETION_ITEMS,
    RISK_CHECK_IDS,
    RISK_DIMENSIONS,
    AnalysisBasisRecord,
    ChecklistAssessment,
    ChecklistCheckResult,
    ChecklistCoverage,
    FinancialMetricValue,
    FinancialOverview,
    FinancialOverviewMetric,
    GrowthConclusion,
    GrowthTransmissionStage,
    RiskConclusion,
)


def _coverage():
    return tuple(
        ChecklistCoverage(item, "complete", (f"evidence:{item}",))
        for item in REQUIRED_COMPLETION_ITEMS
    )


def _growth():
    return tuple(
        GrowthConclusion(
            dimension=dimension,
            judgement="stable",
            core_numbers=("period:value",),
            evidence_ids=(f"evidence:growth:{dimension}",),
            counterevidence=("counter",),
            unresolved_items=(),
            invalidation_conditions=("condition",),
            monitoring_metrics=("metric",),
            confidence="medium",
        )
        for dimension in GROWTH_DIMENSIONS
    )


def _risks():
    return tuple(
        RiskConclusion(
            dimension=dimension,
            judgement="stable",
            mechanism="mechanism",
            leading_warnings=("warning",),
            current_evidence=("evidence",),
            evidence_ids=(f"evidence:risk:{dimension}",),
            buffers_and_counterevidence=("buffer",),
            stress_transmission=("transmission",),
            resolution_conditions=("condition",),
            unresolved_items=(),
            monitoring_metrics=("metric",),
            confidence="medium",
        )
        for dimension in RISK_DIMENSIONS
    )


def _checks():
    def row(check_id, domain):
        return ChecklistCheckResult(
            check_id=check_id,
            domain=domain,
            applicability="not_triggered",
            status="evaluated",
            first_detectable_at=None,
            financial_period=None,
            observations=("已完成檢查，未達觸發條件",),
            evidence_ids=(),
            supporting_evidence=(),
            counterevidence=(),
            inference_chain=(),
            mechanism=None,
            leading_warnings=(),
            buffers=(),
            monitoring_metrics=("下一期同口徑檢查",),
            monitoring_date=None,
            invalidation_or_resolution_conditions=("新資料達觸發條件",),
            severity="not_applicable",
            confidence="not_applicable",
            unresolved_reasons=(),
        )
    return (
        *(row(item, "growth") for item in GROWTH_CHECK_IDS),
        *(row(item, "risk") for item in RISK_CHECK_IDS),
        *(row(item, "note") for item in NOTE_CHECK_IDS),
        *(row(item, "audit") for item in AUDIT_CHECK_IDS),
    )


def _transmission():
    return tuple(
        GrowthTransmissionStage(stage, "not_applicable", ())
        for stage in GROWTH_TRANSMISSION_STAGES
    )


def _basis():
    return (
        AnalysisBasisRecord(
            period="114Q4",
            statement="income",
            consolidation_scope="consolidated",
            period_basis="annual",
            assurance="audit",
            currency="TWD",
            unit="thousand_twd",
            restatement_status="original",
            report_date="2026-03-01T00:00:00+08:00",
            filed_at="2026-03-01T00:00:00+08:00",
            available_at="2026-03-01T00:00:00+08:00",
            evidence_ids=("evidence:basis",),
        ),
    )


def _assessment(**changes):
    values = {
        "generation_id": "generation-1",
        "route": "general_non_financial",
        "coverage": _coverage(),
        "growth": _growth(),
        "risks": _risks(),
        "basis_records": _basis(),
        "financial_overview": FinancialOverview(("114Q4",), ()),
        "checks": _checks(),
        "growth_transmission": _transmission(),
        "industry_route": "not_applicable",
    }
    values.update(changes)
    return ChecklistAssessment(**values)


def test_complete_general_company_requires_all_authoritative_dimensions() -> None:
    assessment = _assessment()
    assert assessment.detailed_check_complete is True
    assert assessment.detailed_check_status == "complete"
    assert assessment.unresolved_reasons == ()


def test_evidence_id_collection_supports_audit_inventory_tuple() -> None:
    assert _ids((SimpleNamespace(evidence_ids=("audit:receipt", "audit:pdf")),)) == (
        "audit:receipt",
        "audit:pdf",
    )


def test_canonical_growth_metric_mapping_uses_only_authority_dimensions() -> None:
    assert set(_CANONICAL_GROWTH_METRICS) == set(GROWTH_DIMENSIONS)
    assert set(_CANONICAL_RISK_METRICS).issubset(RISK_DIMENSIONS)


def _metric(metric_id: str, previous: str, latest: str) -> FinancialOverviewMetric:
    return FinancialOverviewMetric(
        metric_id=metric_id,
        values=(
            FinancialMetricValue("114Q4", Decimal(previous), None, "available", (f"{metric_id}:previous",)),
            FinancialMetricValue("115Q1", Decimal(latest), None, "available", (f"{metric_id}:latest",)),
        ),
        trend_status="improving" if Decimal(latest) >= Decimal(previous) else "deteriorating",
        formula_id=f"{metric_id}.v1",
        days_basis=None,
        approximation_reason=None,
    )


def test_r01_receivables_rule_does_not_use_current_ratio() -> None:
    overview = FinancialOverview(
        ("114Q4", "115Q1"),
        (
            _metric("receivables", "120", "100"),
            _metric("revenue", "100", "110"),
            _metric("dso_days", "60", "55"),
            _metric("operating_cash_flow", "40", "45"),
            _metric("current_ratio", "3", "1"),
        ),
    )

    rows = {item.check_id: item for item in _quantitative_checks(overview, "pending")}

    assert rows["R01"].status == "evaluated"
    assert rows["R01"].applicability == "not_triggered"
    assert "current_ratio" not in rows["R01"].monitoring_metrics


def test_r03_inventory_trigger_stays_unresolved_until_note_and_kam_review() -> None:
    overview = FinancialOverview(
        ("114Q4", "115Q1"),
        (
            _metric("inventory", "100", "150"),
            _metric("revenue", "100", "110"),
            _metric("inventory_days", "40", "55"),
            _metric("gross_margin", "0.4", "0.35"),
        ),
    )

    rows = {item.check_id: item for item in _quantitative_checks(overview, "pending")}

    assert rows["R03"].status == "unresolved"
    assert rows["R03"].applicability == "triggered"
    assert "存貨附註" in rows["R03"].unresolved_reasons[0]


@pytest.mark.parametrize(
    ("finding_id", "check_id"),
    [
        ("downside:long-term-commitments", "R38"),
        ("downside:customer-concentration", "R39"),
        ("downside:repeated-kam", "R31"),
    ],
)
def test_direct_official_findings_map_to_authority_checks(
    finding_id: str, check_id: str
) -> None:
    statement = "設備折舊與固定承諾及客戶集中均有官方原文。"
    finding = SimpleNamespace(
        finding_id=finding_id,
        kind="fact",
        direction="support",
        statement=statement,
        evidence_ids=(f"evidence:{finding_id}",),
    )
    detailed = SimpleNamespace(downside_findings=(finding,), upside_findings=())

    rows = {
        item.check_id: item
        for item in _document_checks(_checks(), None, detailed)
    }

    assert rows[check_id].status == "evaluated"
    assert rows[check_id].applicability == "triggered"
    assert rows[check_id].evidence_ids == (f"evidence:{finding_id}",)


def test_manufacturing_add_on_preserves_partial_evidence_and_fail_closed() -> None:
    findings = (
        SimpleNamespace(
            finding_id="downside:long-term-commitments", kind="fact",
            direction="support", statement="長期原料與設備承諾",
            evidence_ids=("evidence:commitments",),
        ),
        SimpleNamespace(
            finding_id="downside:capex-intensity", kind="fact",
            direction="support", statement="CAPEX與設備增加",
            evidence_ids=("evidence:capex",),
        ),
        SimpleNamespace(
            finding_id="downside:repeated-kam", kind="fact",
            direction="support", statement="設備折舊開始時點連續列為KAM",
            evidence_ids=("evidence:kam",),
        ),
    )
    detailed = SimpleNamespace(downside_findings=findings, upside_findings=())

    rows = {
        item.check_id: item
        for item in _document_checks(
            _placeholder_checks("missing", "manufacturing_hardware"), None, detailed
        )
    }

    assert rows["I-MFG-03"].status == "evaluated"
    assert rows["I-MFG-01"].status == "unresolved"
    assert rows["I-MFG-01"].evidence_ids == ("evidence:capex", "evidence:kam")
    assert "稼動率" in rows["I-MFG-01"].unresolved_reasons[0]


def test_commitment_note_directly_evaluates_r38_and_manufacturing_commitments() -> None:
    citation = SimpleNamespace(
        evidence_id="evidence:n13",
        period="114Q4",
        available_at="2026-03-31T18:00:00+08:00",
        verbatim_excerpt="重大承諾：原料採購約定及未來租賃付款。",
    )
    document = SimpleNamespace(
        note_citations=(("N13_commitments", citation),),
        audit_opinion_citations=(),
        opinion_types=(),
        going_concern_citations=(),
        emphasis_other_citations=(),
        kam_citations=(),
        text_search_complete_periods=(),
    )
    detailed = SimpleNamespace(downside_findings=(), upside_findings=())

    rows = {
        item.check_id: item
        for item in _document_checks(
            _placeholder_checks("missing", "manufacturing_hardware"),
            document,
            detailed,
        )
    }

    assert rows["R38"].status == "evaluated"
    assert rows["I-MFG-03"].status == "evaluated"
    assert rows["R38"].evidence_ids == ("evidence:n13",)
    assert rows["I-MFG-03"].evidence_ids == ("evidence:n13",)

    citation.verbatim_excerpt = "重大承諾：產品權利金及銀行保證票據。"
    rows = {
        item.check_id: item
        for item in _document_checks(
            _placeholder_checks("missing", "manufacturing_hardware"),
            document,
            detailed,
        )
    }
    assert rows["R38"].status == "evaluated"
    assert rows["I-MFG-03"].status == "unresolved"


def test_missing_twelve_quarters_fails_closed() -> None:
    coverage = tuple(
        replace(
            item,
            status="unresolved",
            evidence_ids=(),
            unresolved_reason="最近12季尚未完整取得",
        )
        if item.item_id == "twelve_quarter_consolidated_statements"
        else item
        for item in _coverage()
    )
    assessment = _assessment(coverage=coverage)
    assert assessment.detailed_check_complete is False
    assert assessment.unresolved_reasons == ("最近12季尚未完整取得",)


def test_unresolved_growth_cannot_be_published_as_complete() -> None:
    first = replace(
        _growth()[0],
        judgement="unresolved",
        core_numbers=(),
        unresolved_items=("月營收來源不足",),
    )
    assessment = _assessment(growth=(first, *_growth()[1:]))
    assert assessment.detailed_check_complete is False
    assert "月營收來源不足" in assessment.unresolved_reasons


@pytest.mark.parametrize(
    "route",
    ["bank", "life_insurer", "property_insurer", "securities_firm", "financial_institution_unrouted"],
)
def test_financial_institutions_never_use_general_company_completion(route: str) -> None:
    assessment = _assessment(route=route)
    assert assessment.detailed_check_complete is False
    assert assessment.detailed_check_status == "not_applicable_company_route"


def test_coverage_must_declare_every_authoritative_completion_item() -> None:
    with pytest.raises(ValueError, match="every completion item"):
        _assessment(coverage=_coverage()[:-1])


def test_every_growth_risk_and_note_check_is_required() -> None:
    with pytest.raises(ValueError, match="every G, R, note and routed industry check"):
        _assessment(checks=_checks()[:-1])


def test_routed_industry_requires_its_add_on_checks() -> None:
    with pytest.raises(ValueError, match="routed industry check"):
        _assessment(industry_route="manufacturing_hardware")


def test_every_growth_transmission_stage_is_required() -> None:
    with pytest.raises(ValueError, match="every growth transmission stage"):
        _assessment(growth_transmission=_transmission()[:-1])


def test_unresolved_check_fails_closed() -> None:
    first = replace(
        _checks()[0],
        applicability="unresolved",
        status="unresolved",
        observations=(),
        unresolved_reasons=("G01證據不足",),
    )
    assessment = _assessment(checks=(first, *_checks()[1:]))
    assert assessment.detailed_check_complete is False
    assert "G01證據不足" in assessment.unresolved_reasons
