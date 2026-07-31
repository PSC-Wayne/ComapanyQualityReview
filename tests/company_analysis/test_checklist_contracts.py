from dataclasses import replace

import pytest

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
    FinancialOverview,
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
