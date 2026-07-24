"""PIT-safe cash, balance-sheet and capital-allocation candidate metrics."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence, Literal

from company_quality.audit.high_risk_notes import HighRiskNoteRegister
from company_quality.facts.financial import CanonicalFinancialFact, CanonicalFinancialFacts


class CashBalanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CashConversion:
    cfo_to_ebit: Decimal | None
    fcf_to_net_income: Decimal | None
    working_capital_days: Decimal | None


@dataclass(frozen=True, slots=True)
class Leverage:
    net_debt_to_ebitda: Decimal | None
    debt_to_equity: Decimal | None
    interest_coverage: Decimal | None


@dataclass(frozen=True, slots=True)
class Liquidity:
    current_ratio: Decimal | None
    quick_ratio: Decimal | None
    cash_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class Dilution:
    five_year_share_change_pct: Decimal | None
    convertible_overhang_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class Allocation:
    capex_to_sales: Decimal | None
    dividend_payout: Decimal | None
    buyback_pct: Decimal | None
    acquisition_spend: Decimal | None


@dataclass(frozen=True, slots=True)
class BalanceChecks:
    balance_equation_delta: Decimal | None
    balance_equation_pass: bool | None
    ending_cash_delta: Decimal | None
    ending_cash_match: bool | None


@dataclass(frozen=True, slots=True)
class CashBalanceAllocationCandidate:
    cash_conversion: CashConversion
    leverage: Leverage
    liquidity: Liquidity
    dilution: Dilution
    allocation: Allocation
    balance_checks: BalanceChecks
    evidence_family_ids: tuple[str, ...]
    note_evidence_ids: tuple[str, ...]
    metric_lineage: dict[str, tuple[str, ...]]
    unavailable_reasons: dict[str, str]
    coverage: Decimal
    candidate_score: Decimal | None
    available_at: str
    publication_status: Literal["NON_PUBLISHABLE_CANDIDATE"] = (
        "NON_PUBLISHABLE_CANDIDATE"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["CashBalanceAllocationCandidate.v1"] = (
        "CashBalanceAllocationCandidate.v1"
    )
    source_version: Literal[
        "CanonicalFinancialFacts.v1+HighRiskNoteRegister.v1"
    ] = "CanonicalFinancialFacts.v1+HighRiskNoteRegister.v1"
    formula_version: Literal["cash-balance-allocation.v1"] = (
        "cash-balance-allocation.v1"
    )
    model_version: Literal["unscored-candidate.v1"] = "unscored-candidate.v1"


def _previous_quarter(period: date) -> date:
    if period.month == 3:
        return date(period.year - 1, 12, 31)
    month = period.month - 3
    return date(period.year, month, calendar.monthrange(period.year, month)[1])


def _period(bundle: CanonicalFinancialFacts) -> date:
    if bundle.schema_version != "CanonicalFinancialFacts.v1":
        raise CashBalanceError("expected CanonicalFinancialFacts.v1")
    if not bundle.facts:
        raise CashBalanceError("canonical financial facts are required")
    values = {fact.period_end for fact in bundle.facts}
    if len(values) != 1:
        raise CashBalanceError("one canonical bundle must contain one period")
    try:
        period = date.fromisoformat(next(iter(values)))
    except ValueError as exc:
        raise CashBalanceError("invalid canonical period") from exc
    if period.month not in (3, 6, 9, 12):
        raise CashBalanceError("canonical period must be a quarter end")
    return period


def _prepare(
    bundles: Sequence[CanonicalFinancialFacts],
) -> tuple[date, dict[str, CanonicalFinancialFact], dict[str, CanonicalFinancialFact] | None, list[datetime]]:
    by_period: dict[date, dict[str, CanonicalFinancialFact]] = {}
    coordinates: set[tuple[str, int, int, int]] = set()
    timestamps: list[datetime] = []
    for bundle in bundles:
        period = _period(bundle)
        if period in by_period:
            raise CashBalanceError("duplicate canonical period")
        concepts: dict[str, CanonicalFinancialFact] = {}
        for fact in bundle.facts:
            if fact.concept_id in concepts:
                raise CashBalanceError("duplicate canonical concept")
            coordinate = (
                fact.source_artifact_sha256,
                fact.source_table_index,
                fact.source_row_index,
                fact.source_column_index,
            )
            if any(value < 0 for value in coordinate[1:]):
                raise CashBalanceError("negative source coordinate")
            if coordinate in coordinates:
                raise CashBalanceError("duplicate source coordinate")
            coordinates.add(coordinate)
            if fact.unit != "TWD_thousands":
                raise CashBalanceError("unsupported canonical unit")
            try:
                timestamp = datetime.fromisoformat(fact.available_at)
            except ValueError as exc:
                raise CashBalanceError("invalid fact available_at") from exc
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise CashBalanceError("fact available_at must be timezone-aware")
            timestamps.append(timestamp)
            concepts[fact.concept_id] = fact
        by_period[period] = concepts
    if not by_period:
        raise CashBalanceError("at least one canonical period is required")
    current_period = max(by_period)
    return (
        current_period,
        by_period[current_period],
        by_period.get(_previous_quarter(current_period)),
        timestamps,
    )


def _value(
    concepts: dict[str, CanonicalFinancialFact] | None, concept: str
) -> Decimal | None:
    if concepts is None or concept not in concepts:
        return None
    return concepts[concept].value


def _fact_ids(
    *facts: CanonicalFinancialFact | None,
) -> tuple[str, ...]:
    return tuple(fact.fact_id for fact in facts if fact is not None)


def build_cash_balance_allocation_candidate(
    bundles: Sequence[CanonicalFinancialFacts],
    notes: HighRiskNoteRegister,
) -> CashBalanceAllocationCandidate:
    if notes.schema_version != "HighRiskNoteRegister.v1":
        raise CashBalanceError("expected HighRiskNoteRegister.v1")
    current_period, current, prior, timestamps = _prepare(bundles)
    expected_note_period = f"{current_period.year - 1911}Q{current_period.month // 3}"
    if any(item.period != expected_note_period for item in notes.items):
        raise CashBalanceError("high-risk note period conflicts with financial period")
    try:
        note_timestamp = datetime.fromisoformat(notes.available_at)
    except ValueError as exc:
        raise CashBalanceError("invalid note available_at") from exc
    if note_timestamp.tzinfo is None or note_timestamp.utcoffset() is None:
        raise CashBalanceError("note available_at must be timezone-aware")
    timestamps.append(note_timestamp)

    reasons = {
        "cfo_to_ebit": "missing_exact_ebit_authority",
        "working_capital_days": "missing_accounts_payable_authority",
        "net_debt_to_ebitda": "missing_complete_debt_and_ebitda",
        "debt_to_equity": "missing_complete_interest_bearing_debt",
        "interest_coverage": "missing_interest_expense_authority",
        "current_ratio": "missing_current_assets_and_current_liabilities",
        "quick_ratio": "missing_current_assets_and_current_liabilities",
        "cash_ratio": "missing_current_liabilities",
        "five_year_share_change_pct": "missing_five_year_share_count_history",
        "convertible_overhang_pct": "missing_convertible_dilution_authority",
        "dividend_payout": "missing_dividend_authority",
        "buyback_pct": "missing_buyback_and_share_count_authority",
        "acquisition_spend": "missing_acquisition_spend_authority",
        "candidate_score": "normalisation_and_subweights_not_calibrated",
    }
    lineage: dict[str, tuple[str, ...]] = {}

    def source(concept: str) -> CanonicalFinancialFact | None:
        return current.get(concept)

    def prior_source(concept: str) -> CanonicalFinancialFact | None:
        return None if prior is None else prior.get(concept)

    def single_quarter(concept: str, reason_name: str) -> Decimal | None:
        current_value = _value(current, concept)
        if current_value is None:
            reasons[reason_name] = f"missing_current_ytd_{reason_name}"
            return None
        if current_period.month == 3:
            return current_value
        previous_value = _value(prior, concept)
        if previous_value is None:
            reasons[reason_name] = f"missing_prior_ytd_{reason_name}"
            return None
        return current_value - previous_value

    cfo = single_quarter("cash_flow.operating_cash_flow", "operating_cash_flow")
    capex = single_quarter("cash_flow.acquisition_of_ppe", "capex")
    net_income = _value(current, "income.net_income")
    revenue = _value(current, "income.revenue")
    lineage["fcf_to_net_income"] = _fact_ids(
        source("cash_flow.operating_cash_flow"),
        prior_source("cash_flow.operating_cash_flow"),
        source("cash_flow.acquisition_of_ppe"),
        prior_source("cash_flow.acquisition_of_ppe"),
        source("income.net_income"),
    )
    lineage["capex_to_sales"] = _fact_ids(
        source("cash_flow.acquisition_of_ppe"),
        prior_source("cash_flow.acquisition_of_ppe"),
        source("income.revenue"),
    )

    if cfo is None:
        fcf_to_net_income = None
        reasons["fcf_to_net_income"] = reasons["operating_cash_flow"]
    elif capex is None:
        fcf_to_net_income = None
        reasons["fcf_to_net_income"] = reasons["capex"]
    elif capex > 0:
        fcf_to_net_income = None
        reasons["fcf_to_net_income"] = "capex_cash_flow_not_outflow"
    elif net_income is None:
        fcf_to_net_income = None
        reasons["fcf_to_net_income"] = "missing_current_net_income"
    elif net_income == 0:
        fcf_to_net_income = None
        reasons["fcf_to_net_income"] = "net_income_zero"
    else:
        fcf_to_net_income = (cfo + capex) / net_income

    if capex is None:
        capex_to_sales = None
        reasons["capex_to_sales"] = reasons["capex"]
    elif capex > 0:
        capex_to_sales = None
        reasons["capex_to_sales"] = "capex_cash_flow_not_outflow"
    elif revenue is None:
        capex_to_sales = None
        reasons["capex_to_sales"] = "missing_current_revenue"
    elif revenue == 0:
        capex_to_sales = None
        reasons["capex_to_sales"] = "revenue_zero"
    else:
        capex_to_sales = -capex / revenue

    assets = _value(current, "balance.total_assets")
    liabilities = _value(current, "balance.total_liabilities")
    equity = _value(current, "balance.total_equity")
    lineage["balance_equation"] = _fact_ids(
        source("balance.total_assets"),
        source("balance.total_liabilities"),
        source("balance.total_equity"),
    )
    if None in (assets, liabilities, equity):
        balance_delta = None
        balance_pass = None
        reasons["balance_equation"] = "missing_balance_equation_component"
    else:
        assert assets is not None and liabilities is not None and equity is not None
        balance_delta = assets - liabilities - equity
        balance_pass = abs(balance_delta) <= Decimal(1)

    balance_cash = _value(current, "balance.cash_and_cash_equivalents")
    ending_cash = _value(current, "cash_flow.ending_cash")
    lineage["ending_cash_match"] = _fact_ids(
        source("balance.cash_and_cash_equivalents"),
        source("cash_flow.ending_cash"),
    )
    if balance_cash is None or ending_cash is None:
        ending_cash_delta = None
        ending_cash_match = None
        reasons["ending_cash_match"] = "missing_cross_statement_cash_component"
    else:
        ending_cash_delta = balance_cash - ending_cash
        ending_cash_match = abs(ending_cash_delta) <= Decimal(1)

    available_components = sum(value is not None for value in (
        None,
        fcf_to_net_income,
        None,
        None, None, None,
        None, None, None,
        None, None,
        capex_to_sales, None, None, None,
    ))
    note_evidence = tuple(dict.fromkeys(
        item.evidence_id for item in notes.items if item.evidence_id is not None
    ))
    return CashBalanceAllocationCandidate(
        cash_conversion=CashConversion(
            cfo_to_ebit=None,
            fcf_to_net_income=fcf_to_net_income,
            working_capital_days=None,
        ),
        leverage=Leverage(None, None, None),
        liquidity=Liquidity(None, None, None),
        dilution=Dilution(None, None),
        allocation=Allocation(
            capex_to_sales=capex_to_sales,
            dividend_payout=None,
            buyback_pct=None,
            acquisition_spend=None,
        ),
        balance_checks=BalanceChecks(
            balance_equation_delta=balance_delta,
            balance_equation_pass=balance_pass,
            ending_cash_delta=ending_cash_delta,
            ending_cash_match=ending_cash_match,
        ),
        evidence_family_ids=(
            "cash_conversion",
            "balance_sheet",
            "capital_allocation",
            "high_risk_notes",
        ),
        note_evidence_ids=note_evidence,
        metric_lineage=lineage,
        unavailable_reasons=reasons,
        coverage=Decimal(available_components) / Decimal(15),
        candidate_score=None,
        available_at=max(timestamps).isoformat(),
    )
