"""Authoritative financial overview derived from canonical PIT facts."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from company_quality.company_analysis.checklist_contracts import (
    FinancialMetricValue,
    FinancialOverview,
    FinancialOverviewMetric,
)
from company_quality.company_analysis.evidence_bundle import (
    CompanyEvidenceBundle,
    PeriodEvidence,
)


_AMOUNT_CONCEPTS = {
    "revenue": "income.revenue",
    "gross_profit": "income.gross_profit",
    "operating_income": "income.operating_income",
    "net_income": "income.net_income",
    "cash": "balance.cash_and_cash_equivalents",
    "restricted_cash": "balance.restricted_cash",
    "receivables": "balance.accounts_receivable_net",
    "inventory": "balance.inventories",
    "contract_assets": "balance.contract_assets",
    "current_assets": "balance.current_assets",
    "current_liabilities": "balance.current_liabilities",
    "total_liabilities": "balance.total_liabilities",
    "total_equity": "balance.total_equity",
    "goodwill": "balance.goodwill",
    "intangible_assets": "balance.intangible_assets",
    "common_stock_capital": "equity.common_stock",
    "basic_eps": "income.basic_eps",
    "diluted_eps": "income.diluted_eps",
}
_FLOW_CONCEPTS = {
    "operating_cash_flow": "cash_flow.operating_cash_flow",
    "capex": "cash_flow.acquisition_of_ppe",
    "cash_dividends_paid": "cash_flow.cash_dividends_paid",
}
_LOWER_IS_BETTER = {
    "dso_days", "inventory_days", "cash_conversion_cycle_days",
    "debt_ratio", "contract_assets",
}


def _parts(period: str) -> tuple[int, int]:
    return int(period[:3]), int(period[-1])


def _previous(period: str) -> str:
    year, quarter = _parts(period)
    return f"{year - 1}Q4" if quarter == 1 else f"{year}Q{quarter - 1}"


def _days(period: str, annual: bool) -> int:
    year, quarter = _parts(period)
    gregorian = year + 1911
    if annual:
        return (date(gregorian, 12, 31) - date(gregorian, 1, 1)).days + 1
    start_month = (quarter - 1) * 3 + 1
    end_month = quarter * 3
    return (
        date(gregorian, end_month, calendar.monthrange(gregorian, end_month)[1])
        - date(gregorian, start_month, 1)
    ).days + 1


def _period_map(bundle: CompanyEvidenceBundle) -> dict[str, PeriodEvidence]:
    return {item.period: item for item in bundle.periods}


def _fact(period: PeriodEvidence | None, concept: str):
    if period is None or period.canonical_financial is None:
        return None
    return next(
        (
            item
            for item in period.canonical_financial.facts
            if item.concept_id == concept and item.value is not None
        ),
        None,
    )


def _direct(period: PeriodEvidence | None, concept: str) -> tuple[Decimal | None, tuple[str, ...]]:
    fact = _fact(period, concept)
    return (fact.value, (fact.fact_id,)) if fact is not None else (None, ())


def _sum_direct(
    period: PeriodEvidence | None, concepts: tuple[str, ...]
) -> tuple[Decimal | None, tuple[str, ...]]:
    found = [_fact(period, item) for item in concepts]
    if any(item is None for item in found):
        return None, ()
    available = [item for item in found if item is not None]
    return sum((item.value for item in available if item.value is not None), Decimal(0)), tuple(
        item.fact_id for item in available
    )


def _quarter_flow(
    periods: dict[str, PeriodEvidence], period: str, concept: str
) -> tuple[Decimal | None, tuple[str, ...]]:
    current, evidence = _direct(periods.get(period), concept)
    if current is None:
        return None, ()
    _, quarter = _parts(period)
    if quarter == 1:
        return current, evidence
    previous, previous_evidence = _direct(periods.get(_previous(period)), concept)
    if previous is None:
        return None, ()
    return current - previous, (*evidence, *previous_evidence)


def _quarter_income(
    periods: dict[str, PeriodEvidence], period: str, concept: str
) -> tuple[Decimal | None, tuple[str, ...]]:
    current, evidence = _direct(periods.get(period), concept)
    if current is None:
        return None, ()
    _, quarter = _parts(period)
    if quarter != 4:
        return current, evidence
    year, _ = _parts(period)
    prior = [_direct(periods.get(f"{year}Q{q}"), concept) for q in (1, 2, 3)]
    if any(value is None for value, _ in prior):
        return None, ()
    return current - sum((value for value, _ in prior if value is not None), Decimal(0)), (
        *evidence,
        *(item for _, ids in prior for item in ids),
    )


def _ratio(
    numerator: tuple[Decimal | None, tuple[str, ...]],
    denominator: tuple[Decimal | None, tuple[str, ...]],
) -> tuple[Decimal | None, tuple[str, ...]]:
    n, ne = numerator
    d, de = denominator
    if n is None or d in (None, Decimal(0)):
        return None, ()
    return n / d, (*ne, *de)


def _average(
    periods: dict[str, PeriodEvidence], period: str, concept: str
) -> tuple[Decimal | None, tuple[str, ...]]:
    current = _direct(periods.get(period), concept)
    previous = _direct(periods.get(_previous(period)), concept)
    if current[0] is None or previous[0] is None:
        return None, ()
    return (current[0] + previous[0]) / Decimal(2), (*current[1], *previous[1])


def _period_value(
    periods: dict[str, PeriodEvidence],
    period: str,
    metric_id: str,
    annual: bool,
) -> tuple[Decimal | None, Decimal | None, tuple[str, ...], str, str | None]:
    item = periods.get(period)
    if annual:
        income_value = lambda concept: _direct(item, concept)
        flow_value = lambda concept: _direct(item, concept)
    else:
        income_value = lambda concept: _quarter_income(periods, period, concept)
        flow_value = lambda concept: _quarter_flow(periods, period, concept)

    if metric_id == "diluted_weighted_average_shares":
        _, quarter = _parts(period)
        if not annual and quarter == 4:
            return (
                None, None, (),
                "owner-net-income-thousands-times-1000-over-diluted-eps.v1",
                None,
            )
        owner_income = income_value("income.net_income_attributable_to_owners")
        diluted_eps = income_value("income.diluted_eps")
        if owner_income[0] is None or diluted_eps[0] in (None, Decimal(0)):
            return None, None, (), "owner-net-income-thousands-times-1000-over-diluted-eps.v1", None
        shares = owner_income[0] * Decimal(1000) / diluted_eps[0]
        return shares, None, (*owner_income[1], *diluted_eps[1]), "owner-net-income-thousands-times-1000-over-diluted-eps.v1", None

    if metric_id in _AMOUNT_CONCEPTS:
        concept = _AMOUNT_CONCEPTS[metric_id]
        value = income_value(concept) if concept.startswith("income.") else _direct(item, concept)
        return value[0], None, value[1], "direct-source-value.v1", None
    if metric_id in _FLOW_CONCEPTS:
        value = flow_value(_FLOW_CONCEPTS[metric_id])
        return value[0], None, value[1], "single-period-from-ytd-difference.v1", None

    revenue = income_value("income.revenue")
    gross = income_value("income.gross_profit")
    operating = income_value("income.operating_income")
    net_income = income_value("income.net_income")
    cfo = flow_value("cash_flow.operating_cash_flow")
    capex = flow_value("cash_flow.acquisition_of_ppe")
    if metric_id == "gross_margin":
        value, evidence = _ratio(gross, revenue)
        return value, value, evidence, "gross-profit-over-revenue.v1", None
    if metric_id == "operating_margin":
        value, evidence = _ratio(operating, revenue)
        return value, value, evidence, "operating-income-over-revenue.v1", None
    if metric_id == "net_margin":
        value, evidence = _ratio(net_income, revenue)
        return value, value, evidence, "net-income-over-revenue.v1", None
    if metric_id == "current_ratio":
        value, evidence = _ratio(
            _direct(item, "balance.current_assets"),
            _direct(item, "balance.current_liabilities"),
        )
        return value, value, evidence, "current-assets-over-current-liabilities.v1", None
    if metric_id == "debt_ratio":
        value, evidence = _ratio(
            _direct(item, "balance.total_liabilities"),
            _direct(item, "balance.total_assets"),
        )
        return value, value, evidence, "liabilities-over-assets.v1", None
    if metric_id == "cfo_to_net_income":
        value, evidence = _ratio(cfo, net_income)
        return value, value, evidence, "single-period-cfo-over-net-income.v1", None
    if metric_id == "free_cash_flow":
        if cfo[0] is None or capex[0] is None:
            return None, None, (), "cfo-plus-capex-cash-outflow.v1", None
        return cfo[0] + capex[0], None, (*cfo[1], *capex[1]), "cfo-plus-capex-cash-outflow.v1", None

    day_count = Decimal(_days(period, annual))
    average_receivables = _average(periods, period, "balance.accounts_receivable_net")
    average_inventory = _average(periods, period, "balance.inventories")
    average_payables = _average(periods, period, "balance.accounts_payable")
    cost = income_value("income.cost_of_revenue")
    dso = _ratio(average_receivables, revenue)
    inventory_days = _ratio(average_inventory, (abs(cost[0]), cost[1]) if cost[0] is not None else cost)
    payable_days = _ratio(average_payables, (abs(cost[0]), cost[1]) if cost[0] is not None else cost)
    if metric_id == "dso_days":
        value = dso[0] * day_count if dso[0] is not None else None
        return value, None, dso[1], "average-receivables-over-period-revenue-times-actual-days.v1", str(int(day_count))
    if metric_id == "inventory_days":
        value = inventory_days[0] * day_count if inventory_days[0] is not None else None
        return value, None, inventory_days[1], "average-inventory-over-period-cogs-times-actual-days.v1", str(int(day_count))
    if metric_id == "payable_days":
        value = payable_days[0] * day_count if payable_days[0] is not None else None
        return value, None, payable_days[1], "average-payables-over-period-cogs-times-actual-days.v1", str(int(day_count))
    if metric_id == "cash_conversion_cycle_days":
        dso_value, inventory_value, payable_value = (
            dso[0], inventory_days[0], payable_days[0]
        )
        if dso_value is None or inventory_value is None or payable_value is None:
            return None, None, (), "dso-plus-dio-minus-dpo.v1", str(int(day_count))
        value = (dso_value + inventory_value - payable_value) * day_count
        evidence = (*dso[1], *inventory_days[1], *payable_days[1])
        return value, None, evidence, "dso-plus-dio-minus-dpo.v1", str(int(day_count))
    if metric_id == "roe":
        average_equity = _average(periods, period, "balance.total_equity")
        ratio, evidence = _ratio(net_income, average_equity)
        value = ratio * Decimal(365) / day_count if ratio is not None else None
        return value, value, evidence, "annualized-net-income-over-average-equity.v1", str(int(day_count))
    if metric_id == "roic":
        pbt = income_value("income.profit_before_tax")
        tax = income_value("income.income_tax_expense")
        tax_rate, tax_evidence = _ratio(tax, pbt)
        if tax_rate is None or tax_rate < 0 or tax_rate > 1 or operating[0] is None:
            return None, None, (), "annualized-nopat-over-average-invested-capital.v1", str(int(day_count))
        def invested(target: str) -> tuple[Decimal | None, tuple[str, ...]]:
            target_item = periods.get(target)
            equity = _direct(target_item, "balance.total_equity")
            debt = _sum_direct(target_item, (
                "balance.short_term_borrowings",
                "balance.current_portion_long_term_debt",
                "balance.long_term_borrowings",
            ))
            cash = _direct(target_item, "balance.cash_and_cash_equivalents")
            if equity[0] is None or debt[0] is None or cash[0] is None:
                return None, ()
            return equity[0] + debt[0] - cash[0], (*equity[1], *debt[1], *cash[1])
        current_capital = invested(period)
        previous_capital = invested(_previous(period))
        if current_capital[0] is None or previous_capital[0] is None:
            return None, None, (), "annualized-nopat-over-average-invested-capital.v1", str(int(day_count))
        average_capital = (
            (current_capital[0] + previous_capital[0]) / Decimal(2),
            (*current_capital[1], *previous_capital[1]),
        )
        nopat = (operating[0] * (Decimal(1) - tax_rate), (*operating[1], *tax_evidence))
        ratio, evidence = _ratio(nopat, average_capital)
        value = ratio * Decimal(365) / day_count if ratio is not None else None
        return value, value, evidence, "annualized-nopat-over-average-invested-capital.v1", str(int(day_count))
    if metric_id == "interest_bearing_debt":
        value, evidence = _sum_direct(item, (
            "balance.short_term_borrowings",
            "balance.current_portion_long_term_debt",
            "balance.long_term_borrowings",
        ))
        return value, None, evidence, "sum-interest-bearing-debt.v1", None
    if metric_id == "debt_due_within_year":
        value, evidence = _sum_direct(item, (
            "balance.short_term_borrowings",
            "balance.current_portion_long_term_debt",
        ))
        return value, None, evidence, "sum-debt-due-within-year.v1", None
    if metric_id == "goodwill_and_intangibles":
        value, evidence = _sum_direct(item, ("balance.goodwill", "balance.intangible_assets"))
        return value, None, evidence, "sum-goodwill-intangibles.v1", None
    return None, None, (), "not-implemented", None


_METRICS = (
    "revenue", "gross_profit", "operating_income", "net_income",
    "gross_margin", "operating_margin", "net_margin", "cash",
    "restricted_cash", "receivables", "inventory", "contract_assets",
    "current_ratio", "interest_bearing_debt", "debt_due_within_year",
    "total_liabilities", "debt_ratio", "goodwill_and_intangibles",
    "operating_cash_flow", "capex", "free_cash_flow", "cfo_to_net_income",
    "dso_days", "inventory_days", "payable_days",
    "cash_conversion_cycle_days", "roe", "roic", "common_stock_capital",
    "basic_eps", "diluted_eps", "diluted_weighted_average_shares",
    "cash_dividends_paid",
)


def build_financial_overview(bundle: CompanyEvidenceBundle) -> FinancialOverview | None:
    periods = _period_map(bundle)
    annual = [item.period for item in bundle.periods if item.is_annual and item.canonical_financial]
    recent = [item.period for item in bundle.periods if item.canonical_financial][-4:]
    if len(annual) < 5 or len(recent) < 4:
        return None
    columns = tuple([(item, f"{item[:3]}A", True) for item in annual[-5:]] + [(item, item, False) for item in recent])
    metrics: list[FinancialOverviewMetric] = []
    for metric_id in _METRICS:
        values: list[FinancialMetricValue] = []
        formula_id = "not-implemented"
        day_bases: list[str] = []
        for source_period, label, is_annual in columns:
            value, ratio, evidence, formula_id, day_basis = _period_value(
                periods, source_period, metric_id, is_annual
            )
            values.append(
                FinancialMetricValue(
                    period=label,
                    value=value,
                    ratio=ratio,
                    status="available" if value is not None else "not_derivable",
                    evidence_ids=tuple(dict.fromkeys(evidence)),
                )
            )
            if day_basis is not None:
                day_bases.append(day_basis)
        available = [item.value for item in values[-4:] if item.value is not None]
        if len(available) < 2 or available[-1] == available[-2]:
            trend = "stable" if len(available) >= 2 else "unresolved"
        else:
            improving = available[-1] > available[-2]
            if metric_id in _LOWER_IS_BETTER:
                improving = not improving
            trend = "improving" if improving else "deteriorating"
        metrics.append(
            FinancialOverviewMetric(
                metric_id=metric_id,
                values=tuple(values),
                trend_status=trend,
                formula_id=formula_id,
                days_basis=("actual_calendar_days:" + ",".join(day_bases) if day_bases else None),
                approximation_reason=(
                    "Q4單季EPS不能由年度EPS嚴格差分；不提供近似稀釋股數。"
                    if metric_id == "diluted_weighted_average_shares"
                    else None
                ),
            )
        )
    return FinancialOverview(
        periods=tuple(label for _, label, _ in columns),
        metrics=tuple(metrics),
    )


__all__ = ["build_financial_overview"]
