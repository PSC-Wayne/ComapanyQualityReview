from dataclasses import replace

import pytest

from company_quality.company_analysis.checklist_contracts import (
    GROWTH_DIMENSIONS,
    REQUIRED_COMPLETION_ITEMS,
    RISK_DIMENSIONS,
    ChecklistAssessment,
    ChecklistCoverage,
    GrowthConclusion,
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


def _assessment(**changes):
    values = {
        "generation_id": "generation-1",
        "route": "general_non_financial",
        "coverage": _coverage(),
        "growth": _growth(),
        "risks": _risks(),
    }
    values.update(changes)
    return ChecklistAssessment(**values)


def test_complete_general_company_requires_all_authoritative_dimensions() -> None:
    assessment = _assessment()
    assert assessment.detailed_check_complete is True
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


@pytest.mark.parametrize("route", ["bank", "life_insurer", "property_insurer", "securities_firm"])
def test_financial_institutions_never_use_general_company_completion(route: str) -> None:
    assessment = _assessment(route=route)
    assert assessment.detailed_check_complete is False


def test_coverage_must_declare_every_authoritative_completion_item() -> None:
    with pytest.raises(ValueError, match="every completion item"):
        _assessment(coverage=_coverage()[:-1])
