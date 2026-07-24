import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from company_quality.audit.high_risk_notes import CATEGORIES, HighRiskNoteItem, HighRiskNoteRegister
from company_quality.facts.financial import CanonicalFinancialFact, CanonicalFinancialFacts
from company_quality.scoring.cash_balance import (
    CashBalanceError,
    build_cash_balance_allocation_candidate,
)


def fact(concept, value, end, index):
    quarter = int(end[5:7]) // 3
    start = (
        f"{end[:4]}-01-01" if concept.startswith("cash_flow.")
        else f"{end[:4]}-{(quarter - 1) * 3 + 1:02d}-01"
        if concept.startswith("income.") else None
    )
    return CanonicalFinancialFact(
        fact_id=f"{concept}:{end}", concept_id=concept,
        value=Decimal(str(value)), unit="TWD_thousands",
        period_start=start, period_end=end,
        source_artifact_id=f"artifact:{end}",
        source_artifact_sha256=hashlib.sha256(f"{end}:{index}".encode()).hexdigest(),
        source_table_index=index, source_row_index=index, source_column_index=1,
        source_label=concept, source_value=str(value),
        available_at="2026-07-20T12:00:00+08:00",
        lineage_hash=hashlib.sha256(f"lineage:{end}:{index}".encode()).hexdigest(),
        conflict_state="clear", failure_reason=None,
    )


def period(end, values):
    return CanonicalFinancialFacts(
        status="available",
        facts=tuple(fact(key, value, end, i) for i, (key, value) in enumerate(values.items(), 1)),
        missing_concepts=(), fact_coverage=Decimal("1"),
    )


def notes(period="115Q2", available_at="2026-07-21T09:00:00+08:00"):
    items = tuple(HighRiskNoteItem(
        category=category, state="missing", reason="not_extracted",
        amount=None, unit=None, period=period, evidence_id=None,
        page=None, coordinate=None, materiality=None,
    ) for category in CATEGORIES)
    return HighRiskNoteRegister(
        items=items, categories_covered=(), missing_categories=CATEGORIES,
        coverage=Decimal("0"), available_at=available_at,
    )


def fixtures():
    current = period("2026-06-30", {
        "balance.cash_and_cash_equivalents": 600,
        "balance.total_assets": 5000,
        "balance.long_term_borrowings": 700,
        "balance.total_liabilities": 2000,
        "balance.total_equity": 3000,
        "income.revenue": 1000,
        "income.operating_income": 300,
        "income.net_income": 200,
        "cash_flow.operating_cash_flow": 500,
        "cash_flow.investing_cash_flow": -400,
        "cash_flow.acquisition_of_ppe": -200,
        "cash_flow.ending_cash": 600,
    })
    prior = period("2026-03-31", {
        "cash_flow.operating_cash_flow": 200,
        "cash_flow.acquisition_of_ppe": -80,
    })
    return current, prior


def test_computes_only_authorised_cash_and_allocation_metrics() -> None:
    result = build_cash_balance_allocation_candidate(fixtures(), notes())
    assert result.cash_conversion.fcf_to_net_income == Decimal("0.9")
    assert result.allocation.capex_to_sales == Decimal("0.12")
    assert result.cash_conversion.cfo_to_ebit is None
    assert result.leverage.debt_to_equity is None
    assert result.liquidity.current_ratio is None
    assert result.coverage == Decimal(2) / Decimal(15)
    assert result.balance_checks.balance_equation_delta == 0
    assert result.balance_checks.balance_equation_pass is True
    assert result.balance_checks.ending_cash_delta == 0
    assert result.balance_checks.ending_cash_match is True
    assert result.candidate_score is None
    assert result.publication_status == "NON_PUBLISHABLE_CANDIDATE"
    assert result.available_at == "2026-07-21T09:00:00+08:00"


def test_missing_prior_ytd_reduces_coverage_without_fabrication() -> None:
    current, _ = fixtures()
    result = build_cash_balance_allocation_candidate((current,), notes())
    assert result.cash_conversion.fcf_to_net_income is None
    assert result.allocation.capex_to_sales is None
    assert result.unavailable_reasons["fcf_to_net_income"] == "missing_prior_ytd_operating_cash_flow"
    assert result.coverage == 0


def test_positive_capex_cash_flow_is_not_relabelled_as_spend() -> None:
    current, prior = fixtures()
    changed = tuple(
        replace(item, value=Decimal("200"))
        if item.concept_id == "cash_flow.acquisition_of_ppe" else item
        for item in current.facts
    )
    result = build_cash_balance_allocation_candidate(
        (replace(current, facts=changed), prior), notes()
    )
    assert result.allocation.capex_to_sales is None
    assert result.cash_conversion.fcf_to_net_income is None
    assert result.unavailable_reasons["capex_to_sales"] == "capex_cash_flow_not_outflow"


def test_total_liabilities_and_long_term_debt_are_not_full_debt_proxies() -> None:
    result = build_cash_balance_allocation_candidate(fixtures(), notes())
    assert result.leverage.net_debt_to_ebitda is None
    assert result.leverage.debt_to_equity is None
    assert result.unavailable_reasons["debt_to_equity"] == "missing_complete_interest_bearing_debt"


def test_balance_mismatch_is_exposed_not_silently_reconciled() -> None:
    current, prior = fixtures()
    changed = tuple(
        replace(item, value=Decimal("4900"))
        if item.concept_id == "balance.total_assets" else item
        for item in current.facts
    )
    result = build_cash_balance_allocation_candidate(
        (replace(current, facts=changed), prior), notes()
    )
    assert result.balance_checks.balance_equation_delta == Decimal("-100")
    assert result.balance_checks.balance_equation_pass is False


def test_note_period_and_schema_mismatch_block() -> None:
    with pytest.raises(CashBalanceError, match="period"):
        build_cash_balance_allocation_candidate(fixtures(), notes("115Q1"))
    with pytest.raises(CashBalanceError, match="HighRiskNoteRegister.v1"):
        build_cash_balance_allocation_candidate(
            fixtures(), replace(notes(), schema_version="HighRiskNoteRegister.v2")
        )


def test_zero_net_income_or_revenue_is_null_with_reason() -> None:
    current, prior = fixtures()
    changed = tuple(
        replace(item, value=Decimal("0"))
        if item.concept_id in ("income.net_income", "income.revenue") else item
        for item in current.facts
    )
    result = build_cash_balance_allocation_candidate(
        (replace(current, facts=changed), prior), notes()
    )
    assert result.cash_conversion.fcf_to_net_income is None
    assert result.allocation.capex_to_sales is None
    assert result.unavailable_reasons["fcf_to_net_income"] == "net_income_zero"
    assert result.unavailable_reasons["capex_to_sales"] == "revenue_zero"


def test_json_schema_is_closed_and_valid() -> None:
    path = Path(__file__).parents[3] / "src/company_quality/scoring/cash_balance/contracts/CashBalanceAllocationCandidate.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "CashBalanceAllocationCandidate.v1"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["publication_status"]["const"] == "NON_PUBLISHABLE_CANDIDATE"
