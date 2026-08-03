from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from company_quality.company_analysis.checklist_metrics import build_financial_overview
from company_quality.company_analysis.checklist_analysis import (
    _industry_route,
    _quantitative_checks,
    _transmission_from_overview,
)


def _fact(concept, value, period):
    return SimpleNamespace(
        concept_id=concept,
        value=Decimal(str(value)),
        fact_id=f"{period}:{concept}",
    )


def _period(period, *, annual, revenue, cfo, capex, ar, inventory, payable, equity):
    year = int(period[:3])
    quarter = int(period[-1])
    facts = (
        _fact("income.revenue", revenue, period),
        _fact("income.cost_of_revenue", Decimal(revenue) * Decimal("0.6"), period),
        _fact("income.gross_profit", Decimal(revenue) * Decimal("0.4"), period),
        _fact("income.operating_income", Decimal(revenue) * Decimal("0.2"), period),
        _fact("income.profit_before_tax", Decimal(revenue) * Decimal("0.18"), period),
        _fact("income.income_tax_expense", Decimal(revenue) * Decimal("0.036"), period),
        _fact("income.net_income", Decimal(revenue) * Decimal("0.14"), period),
        _fact("income.net_income_attributable_to_owners", Decimal(revenue) * Decimal("0.14"), period),
        _fact("income.diluted_eps", Decimal(revenue) * Decimal("0.0014"), period),
        _fact("cash_flow.operating_cash_flow", cfo, period),
        _fact("cash_flow.acquisition_of_ppe", capex, period),
        _fact("balance.cash_and_cash_equivalents", 50, period),
        _fact("balance.accounts_receivable_net", ar, period),
        _fact("balance.inventories", inventory, period),
        _fact("balance.accounts_payable", payable, period),
        _fact("balance.current_assets", 500, period),
        _fact("balance.current_liabilities", 250, period),
        _fact("balance.short_term_borrowings", 20, period),
        _fact("balance.current_portion_long_term_debt", 10, period),
        _fact("balance.long_term_borrowings", 70, period),
        _fact("balance.total_assets", 1000, period),
        _fact("balance.total_liabilities", 1000 - Decimal(equity), period),
        _fact("balance.total_equity", equity, period),
        _fact("equity.common_stock", 100, period),
        _fact("equity.total_equity", equity, period),
    )
    return SimpleNamespace(
        period=period,
        is_annual=annual,
        canonical_financial=SimpleNamespace(facts=facts),
    )


def _metric(overview, metric_id):
    return next(item for item in overview.metrics if item.metric_id == metric_id)


def test_industry_route_uses_official_industry_code_and_preserves_ambiguity() -> None:
    semiconductor = cast(Any, SimpleNamespace(identity=SimpleNamespace(industry_code="24")))
    construction = cast(Any, SimpleNamespace(identity=SimpleNamespace(industry_code="14")))
    assert _industry_route(semiconductor, "general_non_financial") == "manufacturing_hardware"
    assert _industry_route(construction, "general_non_financial") == "unresolved"
    assert _industry_route(semiconductor, "financial_institution_unrouted") == "financial"


def test_overview_uses_five_annual_and_four_recent_quarters_with_correct_flows() -> None:
    periods = (
        _period("110Q4", annual=True, revenue=600, cfo=240, capex=-60, ar=70, inventory=50, payable=40, equity=500),
        _period("111Q4", annual=True, revenue=700, cfo=280, capex=-70, ar=75, inventory=55, payable=42, equity=540),
        _period("112Q4", annual=True, revenue=800, cfo=330, capex=-80, ar=80, inventory=60, payable=45, equity=580),
        _period("113Q4", annual=True, revenue=900, cfo=400, capex=-90, ar=90, inventory=70, payable=50, equity=620),
        _period("114Q1", annual=False, revenue=180, cfo=100, capex=-20, ar=100, inventory=80, payable=55, equity=650),
        _period("114Q2", annual=False, revenue=210, cfo=220, capex=-45, ar=110, inventory=90, payable=60, equity=680),
        _period("114Q3", annual=False, revenue=210, cfo=360, capex=-75, ar=120, inventory=100, payable=65, equity=710),
        _period("114Q4", annual=True, revenue=1000, cfo=520, capex=-120, ar=130, inventory=110, payable=70, equity=750),
    )
    overview = build_financial_overview(cast(Any, SimpleNamespace(periods=periods)))

    assert overview is not None
    assert overview.periods == (
        "110A", "111A", "112A", "113A", "114A",
        "114Q1", "114Q2", "114Q3", "114Q4",
    )
    revenue = _metric(overview, "revenue")
    cfo = _metric(overview, "operating_cash_flow")
    fcf = _metric(overview, "free_cash_flow")
    assert revenue.values[-1].value == Decimal("400")
    assert cfo.values[-3].value == Decimal("120")
    assert cfo.values[-1].value == Decimal("160")
    assert fcf.values[-1].value == Decimal("115")

    dso = _metric(overview, "dso_days")
    dio = _metric(overview, "inventory_days")
    dpo = _metric(overview, "payable_days")
    ccc = _metric(overview, "cash_conversion_cycle_days")
    assert dso.values[-1].value == Decimal("28.750")
    assert dio.values[-1].value == Decimal("40.25")
    assert dpo.values[-1].value == Decimal("25.875")
    assert ccc.values[-1].value == Decimal("43.125")
    assert dso.formula_id == "average-receivables-over-period-revenue-times-actual-days.v1"
    assert dso.days_basis is not None and "92" in dso.days_basis

    cfo_quality = _metric(overview, "cfo_to_net_income")
    assert cfo_quality.values[-1].value == Decimal("160") / Decimal("56")

    diluted_shares = _metric(overview, "diluted_weighted_average_shares")
    assert diluted_shares.values[-2].value == Decimal("100000")
    assert diluted_shares.values[-1].status == "not_derivable"
    assert diluted_shares.values[-1].value is None
    assert diluted_shares.approximation_reason == "Q4單季EPS不能由年度EPS嚴格差分；不提供近似稀釋股數。"

    checks = {item.check_id: item for item in _quantitative_checks(overview, "missing")}
    assert checks["G01"].status == "unresolved"
    assert checks["G01"].applicability == "triggered"
    assert checks["R10"].status == "evaluated"
    assert checks["R10"].applicability == "not_triggered"
    assert checks["R10"].monitoring_metrics[0] == "有息負債"
    assert checks["G22"].status == "unresolved"
    assert checks["G22"].applicability == "triggered"
    assert checks["N01_revenue_recognition"].status == "unresolved"

    transmission = {item.stage: item for item in _transmission_from_overview(overview)}
    assert transmission["revenue"].status == "verified"
    assert transmission["margin"].status == "verified"
    assert transmission["cash"].status == "verified"
    assert transmission["demand"].status == "unresolved"
    assert transmission["order"].status == "unresolved"
