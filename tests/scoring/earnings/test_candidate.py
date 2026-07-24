import json
import hashlib
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from company_quality.facts.financial import CanonicalFinancialFact, CanonicalFinancialFacts
from company_quality.scoring.earnings import (
    EarningsMetricError,
    build_earnings_capital_efficiency_candidate,
)


def fact(concept, value, end, *, start=None, index=0):
    return CanonicalFinancialFact(
        fact_id=f"{concept}:{end}",
        concept_id=concept,
        value=None if value is None else Decimal(str(value)),
        unit="TWD_thousands",
        period_start=start,
        period_end=end,
        source_artifact_id=f"artifact:{end}",
        source_artifact_sha256=hashlib.sha256(f"{end}:{index}".encode()).hexdigest(),
        source_table_index=index,
        source_row_index=index,
        source_column_index=1,
        source_label=concept,
        source_value=str(value),
        available_at=f"{date.fromisoformat(end).isoformat()}T12:00:00+08:00",
        lineage_hash=(str((index + 1) % 10) * 64),
        conflict_state="clear",
        failure_reason=None if value is not None else "missing",
    )


def period(end, values):
    month = date.fromisoformat(end).month
    start = f"{end[:4]}-01-01"
    facts = tuple(
        fact(
            concept,
            value,
            end,
            start=start if concept.startswith(("income.", "cash_flow.")) else None,
            index=index,
        )
        for index, (concept, value) in enumerate(values.items(), 1)
    )
    return CanonicalFinancialFacts(
        status="available",
        facts=facts,
        missing_concepts=(),
        fact_coverage=Decimal("1"),
    )


def fixtures():
    current = period("2026-06-30", {
        "balance.total_assets": 5000,
        "balance.total_equity": 3000,
        "income.revenue": 1000,
        "income.gross_profit": 400,
        "income.operating_income": 300,
        "income.net_income": 200,
        "cash_flow.operating_cash_flow": 500,
        "cash_flow.acquisition_of_ppe": -200,
    })
    prior = period("2026-03-31", {
        "balance.total_assets": 4000,
        "balance.total_equity": 2500,
        "cash_flow.operating_cash_flow": 200,
        "cash_flow.acquisition_of_ppe": -80,
    })
    prior_year = period("2025-06-30", {
        "income.revenue": 800,
        "income.net_income": 100,
    })
    return current, prior, prior_year


def test_recomputes_profitability_cash_and_efficiency_metrics() -> None:
    result = build_earnings_capital_efficiency_candidate(fixtures())

    assert result.metrics.operating_cash_flow == Decimal("300")
    assert result.metrics.free_cash_flow == Decimal("180")
    assert result.metrics.gross_margin == Decimal("0.4")
    assert result.metrics.roa == Decimal("800") / Decimal("4500")
    assert result.metrics.asset_turnover == Decimal("4000") / Decimal("4500")
    assert result.metrics.accrual_ratio == Decimal("-400") / Decimal("4500")
    assert result.metrics.roic is None
    assert result.diagnostics.roe == Decimal("800") / Decimal("2750")
    assert result.diagnostics.operating_margin == Decimal("0.3")
    assert result.diagnostics.revenue_growth_yoy == Decimal("0.25")
    assert result.diagnostics.net_income_growth_yoy == Decimal("1")
    assert result.coverage == Decimal(6) / Decimal(7)
    assert result.candidate_score is None
    assert result.publication_status == "NON_PUBLISHABLE_CANDIDATE"
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"
    assert result.unavailable_reasons["roic"] == "missing_nopat_and_invested_capital_authority"


def test_missing_prior_period_keeps_average_balance_and_ytd_metrics_null() -> None:
    current, _, _ = fixtures()
    result = build_earnings_capital_efficiency_candidate((current,))

    assert result.metrics.gross_margin == Decimal("0.4")
    assert result.metrics.roa is None
    assert result.metrics.asset_turnover is None
    assert result.metrics.operating_cash_flow is None
    assert result.metrics.free_cash_flow is None
    assert result.unavailable_reasons["roa"] == "missing_immediately_preceding_quarter_assets"
    assert result.unavailable_reasons["operating_cash_flow"] == "missing_prior_ytd_operating_cash_flow"
    assert result.candidate_score is None


def test_q1_cash_flow_is_already_single_quarter() -> None:
    q1 = period("2026-03-31", {
        "balance.total_assets": 5000,
        "income.revenue": 1000,
        "income.gross_profit": 400,
        "income.net_income": 200,
        "cash_flow.operating_cash_flow": 300,
        "cash_flow.acquisition_of_ppe": -120,
    })
    prior_q4 = period("2025-12-31", {"balance.total_assets": 4000})
    result = build_earnings_capital_efficiency_candidate((q1, prior_q4))
    assert result.metrics.operating_cash_flow == 300
    assert result.metrics.free_cash_flow == 180


def test_zero_denominators_are_null_with_reason() -> None:
    current, prior, prior_year = fixtures()
    facts = tuple(
        replace(item, value=Decimal("0")) if item.concept_id == "income.revenue" else item
        for item in current.facts
    )
    result = build_earnings_capital_efficiency_candidate(
        (replace(current, facts=facts), prior, prior_year)
    )
    assert result.metrics.gross_margin is None
    assert result.diagnostics.operating_margin is None
    assert result.unavailable_reasons["gross_margin"] == "revenue_zero"


def test_missing_capex_does_not_substitute_investing_cash_flow() -> None:
    current, prior, prior_year = fixtures()
    facts = tuple(
        item for item in current.facts
        if item.concept_id != "cash_flow.acquisition_of_ppe"
    ) + (
        fact("cash_flow.investing_cash_flow", -999, "2026-06-30", start="2026-01-01", index=20),
    )
    result = build_earnings_capital_efficiency_candidate(
        (replace(current, facts=facts), prior, prior_year)
    )
    assert result.metrics.free_cash_flow is None
    assert result.unavailable_reasons["free_cash_flow"] == "missing_current_ytd_capex"


def test_duplicate_concept_or_source_coordinate_blocks() -> None:
    current, prior, prior_year = fixtures()
    with pytest.raises(EarningsMetricError, match="duplicate concept"):
        build_earnings_capital_efficiency_candidate(
            (replace(current, facts=current.facts + (current.facts[0],)), prior, prior_year)
        )
    duplicate_coordinate = replace(
        current.facts[1],
        source_artifact_sha256=current.facts[0].source_artifact_sha256,
        source_table_index=current.facts[0].source_table_index,
        source_row_index=current.facts[0].source_row_index,
        source_column_index=current.facts[0].source_column_index,
    )
    with pytest.raises(EarningsMetricError, match="source coordinate"):
        build_earnings_capital_efficiency_candidate(
            (replace(current, facts=(current.facts[0], duplicate_coordinate, *current.facts[2:])), prior, prior_year)
        )


def test_cycle_flags_are_explicit_and_none_is_exclusive() -> None:
    with pytest.raises(EarningsMetricError, match="cycle flag"):
        build_earnings_capital_efficiency_candidate(
            fixtures(), cycle_flags=("none", "peak_margin")
        )
    result = build_earnings_capital_efficiency_candidate(
        fixtures(), cycle_flags=("construction_lumpiness",)
    )
    assert result.cycle_flags == ("construction_lumpiness",)


def test_unapproved_schema_and_missing_facts_block() -> None:
    current, prior, prior_year = fixtures()
    with pytest.raises(EarningsMetricError, match="CanonicalFinancialFacts.v1"):
        build_earnings_capital_efficiency_candidate(
            (replace(current, schema_version="CanonicalFinancialFacts.v2"), prior, prior_year)
        )
    with pytest.raises(EarningsMetricError, match="facts"):
        build_earnings_capital_efficiency_candidate((replace(current, facts=()),))


def test_json_schema_is_closed_and_valid() -> None:
    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/scoring/earnings/contracts/EarningsCapitalEfficiencyCandidate.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "EarningsCapitalEfficiencyCandidate.v1"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["publication_status"]["const"] == "NON_PUBLISHABLE_CANDIDATE"
