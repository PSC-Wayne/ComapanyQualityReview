"""Working-capital and revenue-quality risk producer for checklist R01-R09/R19/R20.

The producer consumes already PIT-admitted, period-aligned facts.  Quantitative
signals may trigger follow-up, but documentary gaps never become an evaluated
safety conclusion.  Peer inventory evidence is retained as context only.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Literal, Mapping, Sequence

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation

_CHECK_IDS = tuple([*(f"R{i:02d}" for i in range(1, 10)), "R19", "R20"])
_PERIOD = re.compile(r"^(\d{2,3})Q([1-4])$")
QualitativeKind = Literal[
    "receivables_aging",
    "ecl_assessment",
    "receivables_roll_forward",
    "contract_asset_roll_forward",
    "inventory_aging",
    "inventory_allowance_roll_forward",
    "prepayment_roll_forward",
    "payables_roll_forward",
    "subsequent_collection",
    "subsequent_sale",
    "revenue_recognition_kam",
]


@dataclass(frozen=True, slots=True)
class WorkingCapitalPeriod:
    period: str
    annual: bool
    period_days: int
    revenue: Decimal | None
    cost_of_revenue: Decimal | None
    purchases: Decimal | None
    receivables: Decimal | None
    contract_assets: Decimal | None
    inventory: Decimal | None
    prepayments: Decimal | None
    accounts_payable: Decimal | None
    operating_cash_flow: Decimal | None
    net_income: Decimal | None
    capex: Decimal | None
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.period or self.period_days <= 0:
            raise ValueError("working-capital period requires period and positive period_days")
        if not self.evidence_ids:
            raise ValueError("working-capital period requires fact evidence")


@dataclass(frozen=True, slots=True)
class WorkingCapitalQualitativeEvidence:
    kind: QualitativeKind
    signal: Literal["risk", "counterevidence"]
    citation: EvidenceCitation


@dataclass(frozen=True, slots=True)
class WorkingCapitalRiskEvidence:
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    peer_inventory_context_ids: tuple[str, ...]
    unresolved_reasons: tuple[str, ...]
    schema_version: Literal["WorkingCapitalRiskEvidence.v1"] = "WorkingCapitalRiskEvidence.v1"

    @property
    def by_check_id(self) -> Mapping[str, ChecklistCheckResult]:
        return {item.check_id: item for item in self.checks}


_REQUIRED_SAFETY_EVIDENCE: dict[str, frozenset[QualitativeKind]] = {
    "R01": frozenset({"receivables_aging", "ecl_assessment", "receivables_roll_forward", "subsequent_collection"}),
    "R02": frozenset({"ecl_assessment", "contract_asset_roll_forward", "subsequent_collection"}),
    "R03": frozenset({"inventory_aging", "inventory_allowance_roll_forward", "subsequent_sale"}),
    "R04": frozenset({"inventory_aging", "inventory_allowance_roll_forward", "subsequent_sale"}),
    "R05": frozenset({"prepayment_roll_forward"}),
    "R06": frozenset({"payables_roll_forward"}),
    "R08": frozenset({"subsequent_collection", "subsequent_sale"}),
    "R09": frozenset({"subsequent_collection", "subsequent_sale"}),
    "R19": frozenset({"receivables_aging", "ecl_assessment", "receivables_roll_forward", "contract_asset_roll_forward", "subsequent_collection", "revenue_recognition_kam"}),
}
_MONITORING = {
    "R01": ("應收／營收", "DSO", "帳齡", "ECL", "期後收款"),
    "R02": ("合約資產／營收", "轉應收速度", "減損", "期後收款"),
    "R03": ("存貨／COGS", "存貨天數", "庫齡", "跌價", "期後銷售"),
    "R04": ("存貨下降率", "毛利率", "缺貨", "報廢", "後續營收"),
    "R05": ("預付款／採購", "供應商履約", "後續收貨"),
    "R06": ("應付／採購", "DPO", "逾期付款", "OCF"),
    "R07": ("OCF", "應收釋放", "存貨釋放", "應付增加", "可重複核心OCF"),
    "R08": ("3A/5A累計CFO／淨利", "應收", "存貨", "收入認列"),
    "R09": ("3A/5A累計FCF", "CAPEX", "資金跑道", "再融資"),
    "R19": ("營收", "應收", "合約資產", "OCF", "期後收款"),
    "R20": ("三年收入認列KAM", "截止測試", "合約抽查", "函證", "現金一致性"),
}


def _ids(*groups: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in groups for item in group))


def _unresolved(
    check_id: str,
    reason: str,
    *,
    applicability: Literal["triggered", "unresolved"] = "unresolved",
    observations: Sequence[str] = (),
    evidence_ids: Sequence[str] = (),
) -> ChecklistCheckResult:
    return ChecklistCheckResult(
        check_id=check_id,
        domain="risk",
        applicability=applicability,
        status="unresolved",
        first_detectable_at=None,
        financial_period=None,
        observations=tuple(observations),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        supporting_evidence=(),
        counterevidence=(),
        inference_chain=("PIT period-aligned facts → quantitative screen → required documentary evidence",),
        mechanism="量化訊號只觸發追查；資料缺口不得解讀為沒有風險。",
        leading_warnings=_MONITORING[check_id],
        buffers=(),
        monitoring_metrics=_MONITORING[check_id],
        monitoring_date=None,
        invalidation_or_resolution_conditions=("補齊指定附註、KAM、roll-forward及期後證據。",),
        severity="medium" if applicability == "triggered" else "not_applicable",
        confidence="low",
        unresolved_reasons=(reason,),
    )


def _evaluated(
    check_id: str,
    *,
    triggered: bool,
    period: str,
    observations: Sequence[str],
    evidence_ids: Sequence[str],
    documentary: Sequence[WorkingCapitalQualitativeEvidence] = (),
) -> ChecklistCheckResult:
    citations = tuple(item.citation for item in documentary)
    all_ids = _ids(tuple(evidence_ids), tuple(item.evidence_id for item in citations))
    excerpts = tuple(item.verbatim_excerpt for item in citations)
    return ChecklistCheckResult(
        check_id=check_id,
        domain="risk",
        applicability="triggered" if triggered else "not_triggered",
        status="evaluated",
        first_detectable_at=citations[-1].available_at if citations else None,
        financial_period=period,
        observations=tuple(observations),
        evidence_ids=all_ids,
        supporting_evidence=tuple(item.citation.verbatim_excerpt for item in documentary if item.signal == "risk"),
        counterevidence=tuple(item.citation.verbatim_excerpt for item in documentary if item.signal == "counterevidence"),
        inference_chain=("同口徑facts → 平均餘額／累計期間計算 → 原始附註及期後證據",),
        mechanism="營運資金與收入收現若背離，會吸收現金並削弱盈餘品質。",
        leading_warnings=_MONITORING[check_id],
        buffers=excerpts if not triggered else (),
        monitoring_metrics=_MONITORING[check_id],
        monitoring_date=None,
        invalidation_or_resolution_conditions=("新一期同口徑數值或原始文件更新目前判定。",),
        severity="medium" if triggered else "low",
        confidence="high" if citations else "medium",
        unresolved_reasons=(),
    )


def _growth(prior: Decimal, current: Decimal) -> Decimal | None:
    return current / prior - Decimal(1) if prior > 0 else None


def _period_parts(period: str) -> tuple[int, int] | None:
    match = _PERIOD.fullmatch(period)
    if match is None:
        return None
    year, quarter = match.groups()
    return int(year), int(quarter)


def _screen(
    *,
    check_id: str,
    prior: WorkingCapitalPeriod,
    current: WorkingCapitalPeriod,
    balance_name: str,
    prior_balance: Decimal | None,
    current_balance: Decimal | None,
    denominator_name: str,
    prior_denominator: Decimal | None,
    current_denominator: Decimal | None,
    qualitative: Sequence[WorkingCapitalQualitativeEvidence],
    decrease: bool = False,
) -> ChecklistCheckResult:
    values = (prior_balance, current_balance, prior_denominator, current_denominator)
    if any(value is None for value in values):
        return _unresolved(check_id, f"{check_id}:missing_component;missing_is_not_zero")
    assert prior_balance is not None and current_balance is not None
    assert prior_denominator is not None and current_denominator is not None
    if prior_denominator <= 0 or current_denominator <= 0 or prior_balance < 0 or current_balance < 0:
        return _unresolved(check_id, f"{check_id}:nonpositive_denominator_or_invalid_balance")
    balance_growth = _growth(prior_balance, current_balance)
    denominator_growth = _growth(prior_denominator, current_denominator)
    if balance_growth is None or denominator_growth is None:
        return _unresolved(check_id, f"{check_id}:nonpositive_growth_base")
    average_balance = (prior_balance + current_balance) / Decimal(2)
    ratio = average_balance / current_denominator
    observations = (
        f"{balance_name}_growth={balance_growth}",
        f"{denominator_name}_growth={denominator_growth}",
        f"average_{balance_name}/{denominator_name}={ratio};period_days={current.period_days}",
    )
    triggered = (
        balance_growth <= Decimal("-0.25") and balance_growth < denominator_growth
        if decrease
        else balance_growth > 0 and balance_growth > denominator_growth
    )
    if triggered:
        return _unresolved(
            check_id,
            f"{check_id}:quantitative_anomaly_requires_documentary_resolution",
            applicability="triggered",
            observations=observations,
            evidence_ids=_ids(prior.evidence_ids, current.evidence_ids),
        )
    required = _REQUIRED_SAFETY_EVIDENCE[check_id]
    admitted = tuple(item for item in qualitative if item.kind in required)
    present = {item.kind for item in admitted}
    missing = sorted(required - present)
    if missing:
        return _unresolved(
            check_id,
            f"{check_id}:safety_evidence_missing:" + ",".join(missing),
            observations=observations,
            evidence_ids=_ids(prior.evidence_ids, current.evidence_ids),
        )
    return _evaluated(
        check_id,
        triggered=False,
        period=current.period,
        observations=observations,
        evidence_ids=_ids(prior.evidence_ids, current.evidence_ids),
        documentary=admitted,
    )


def _horizon_check(
    check_id: str,
    annual: Sequence[WorkingCapitalPeriod],
    qualitative: Sequence[WorkingCapitalQualitativeEvidence],
) -> ChecklistCheckResult:
    if len(annual) < 5:
        return _unresolved(check_id, f"{check_id}:partial_3A_5A_horizon:{len(annual)}/5")
    years = tuple(annual[-5:])
    period_parts = tuple(_period_parts(item.period) for item in years)
    if (
        any(item is None or item[1] != 4 for item in period_parts)
        or any(
            current_part[0] != prior_part[0] + 1
            for prior_part, current_part in zip(period_parts, period_parts[1:])
            if prior_part is not None and current_part is not None
        )
    ):
        return _unresolved(check_id, f"{check_id}:nonconsecutive_annual_horizon")
    if not all(item.annual for item in years):
        return _unresolved(check_id, f"{check_id}:nonannual_horizon_component")
    required_values = (
        tuple(item.operating_cash_flow for item in years),
        tuple(item.net_income for item in years),
        tuple(item.capex for item in years),
    )
    if any(value is None for group in required_values for value in group):
        return _unresolved(check_id, f"{check_id}:missing_annual_component;missing_is_not_zero")
    cfo = tuple(item.operating_cash_flow for item in years)
    net = tuple(item.net_income for item in years)
    capex = tuple(item.capex for item in years)
    assert all(item is not None for item in (*cfo, *net, *capex))
    cfo_values = tuple(item for item in cfo if item is not None)
    net_values = tuple(item for item in net if item is not None)
    capex_values = tuple(item for item in capex if item is not None)
    observations: list[str] = []
    outcomes: list[bool] = []
    for horizon in (3, 5):
        cfo_sum = sum(cfo_values[-horizon:], Decimal(0))
        net_sum = sum(net_values[-horizon:], Decimal(0))
        fcf_sum = sum(
            (cfo_value + capex_value)
            for cfo_value, capex_value in zip(cfo_values[-horizon:], capex_values[-horizon:])
        )
        if net_sum <= 0:
            return _unresolved(check_id, f"{check_id}:nonpositive_{horizon}A_net_income_denominator")
        observations.extend((
            f"{horizon}A_cumulative_CFO={cfo_sum};net_income={net_sum};CFO/NI={cfo_sum / net_sum}",
            f"{horizon}A_cumulative_FCF={fcf_sum}",
        ))
        outcomes.append(cfo_sum < net_sum if check_id == "R08" else fcf_sum < 0)
    evidence_ids = _ids(*(item.evidence_ids for item in years))
    if any(outcomes):
        return _unresolved(
            check_id,
            f"{check_id}:3A_or_5A_quantitative_anomaly_requires_documentary_resolution",
            applicability="triggered",
            observations=observations,
            evidence_ids=evidence_ids,
        )
    required = _REQUIRED_SAFETY_EVIDENCE[check_id]
    admitted = tuple(item for item in qualitative if item.kind in required)
    missing = sorted(required - {item.kind for item in admitted})
    if missing:
        return _unresolved(
            check_id,
            f"{check_id}:safety_evidence_missing:" + ",".join(missing),
            observations=observations,
            evidence_ids=evidence_ids,
        )
    return _evaluated(
        check_id,
        triggered=False,
        period=years[-1].period,
        observations=observations,
        evidence_ids=evidence_ids,
        documentary=admitted,
    )


def build_working_capital_risk(
    *,
    comparison_periods: Sequence[WorkingCapitalPeriod],
    annual_periods: Sequence[WorkingCapitalPeriod],
    qualitative_evidence: Sequence[WorkingCapitalQualitativeEvidence],
    current_feed_available: bool = True,
    peer_inventory_context_ids: Sequence[str] = (),
) -> WorkingCapitalRiskEvidence:
    """Produce R01-R09/R19/R20 without treating absence or peers as safety."""

    if not current_feed_available:
        reason = "current_feed_absence;absence_is_not_zero_or_no_risk"
        checks = tuple(_unresolved(check_id, reason) for check_id in _CHECK_IDS)
        return WorkingCapitalRiskEvidence(
            checks,
            tuple(dict.fromkeys(item.citation for item in qualitative_evidence)),
            tuple(dict.fromkeys(peer_inventory_context_ids)),
            (reason,),
        )
    if len(comparison_periods) != 2:
        reason = f"period_aligned_comparison_requires_exactly_2_periods:{len(comparison_periods)}"
        checks = tuple(_unresolved(check_id, reason) for check_id in _CHECK_IDS)
        return WorkingCapitalRiskEvidence(
            checks,
            tuple(dict.fromkeys(item.citation for item in qualitative_evidence)),
            tuple(dict.fromkeys(peer_inventory_context_ids)),
            (reason,),
        )
    prior, current = comparison_periods
    prior_parts = _period_parts(prior.period)
    current_parts = _period_parts(current.period)
    if (
        prior.annual != current.annual
        or prior.period_days != current.period_days
        or prior_parts is None
        or current_parts is None
        or prior_parts[1] != current_parts[1]
        or current_parts[0] <= prior_parts[0]
    ):
        reason = "comparison_period_basis_days_or_season_mismatch"
        checks = tuple(_unresolved(check_id, reason) for check_id in _CHECK_IDS)
        return WorkingCapitalRiskEvidence(
            checks,
            tuple(dict.fromkeys(item.citation for item in qualitative_evidence)),
            tuple(dict.fromkeys(peer_inventory_context_ids)),
            (reason,),
        )

    purchases_basis = (
        (prior.purchases, current.purchases, "purchases")
        if prior.purchases is not None and current.purchases is not None
        else (prior.cost_of_revenue, current.cost_of_revenue, "COGS approximation")
    )
    r01 = _screen(
        check_id="R01", prior=prior, current=current, balance_name="receivables",
        prior_balance=prior.receivables, current_balance=current.receivables,
        denominator_name="revenue", prior_denominator=prior.revenue,
        current_denominator=current.revenue, qualitative=qualitative_evidence,
    )
    r02 = _screen(
        check_id="R02", prior=prior, current=current, balance_name="contract_assets",
        prior_balance=prior.contract_assets, current_balance=current.contract_assets,
        denominator_name="revenue", prior_denominator=prior.revenue,
        current_denominator=current.revenue, qualitative=qualitative_evidence,
    )
    r03 = _screen(
        check_id="R03", prior=prior, current=current, balance_name="inventory",
        prior_balance=prior.inventory, current_balance=current.inventory,
        denominator_name="COGS", prior_denominator=prior.cost_of_revenue,
        current_denominator=current.cost_of_revenue, qualitative=qualitative_evidence,
    )
    r04 = _screen(
        check_id="R04", prior=prior, current=current, balance_name="inventory",
        prior_balance=prior.inventory, current_balance=current.inventory,
        denominator_name="COGS", prior_denominator=prior.cost_of_revenue,
        current_denominator=current.cost_of_revenue, qualitative=qualitative_evidence,
        decrease=True,
    )
    r05 = _screen(
        check_id="R05", prior=prior, current=current, balance_name="prepayments",
        prior_balance=prior.prepayments, current_balance=current.prepayments,
        denominator_name=purchases_basis[2], prior_denominator=purchases_basis[0],
        current_denominator=purchases_basis[1], qualitative=qualitative_evidence,
    )
    r06 = _screen(
        check_id="R06", prior=prior, current=current, balance_name="accounts_payable",
        prior_balance=prior.accounts_payable, current_balance=current.accounts_payable,
        denominator_name=purchases_basis[2], prior_denominator=purchases_basis[0],
        current_denominator=purchases_basis[1], qualitative=qualitative_evidence,
    )

    if prior.operating_cash_flow is None or current.operating_cash_flow is None:
        r07 = _unresolved("R07", "R07:missing_OCF_component;missing_is_not_zero")
    else:
        releases: list[str] = []
        for label, before, after, release_if in (
            ("receivables_release", prior.receivables, current.receivables, "decrease"),
            ("contract_asset_release", prior.contract_assets, current.contract_assets, "decrease"),
            ("inventory_release", prior.inventory, current.inventory, "decrease"),
            ("prepayment_release", prior.prepayments, current.prepayments, "decrease"),
            ("payables_release", prior.accounts_payable, current.accounts_payable, "increase"),
        ):
            if before is not None and after is not None and (
                (release_if == "decrease" and after < before)
                or (release_if == "increase" and after > before)
            ):
                releases.append(label)
        sudden = current.operating_cash_flow > prior.operating_cash_flow
        if sudden and releases:
            r07 = _evaluated(
                "R07", triggered=True, period=current.period, observations=tuple(releases),
                evidence_ids=_ids(prior.evidence_ids, current.evidence_ids),
            )
        elif sudden:
            r07 = _unresolved(
                "R07", "R07:OCF_increase_without_supported_working_capital_release",
                observations=(f"OCF={prior.operating_cash_flow}->{current.operating_cash_flow}",),
                evidence_ids=_ids(prior.evidence_ids, current.evidence_ids),
            )
        else:
            r07 = _evaluated(
                "R07", triggered=False, period=current.period,
                observations=(f"OCF={prior.operating_cash_flow}->{current.operating_cash_flow}",),
                evidence_ids=_ids(prior.evidence_ids, current.evidence_ids),
            )

    r08 = _horizon_check("R08", annual_periods, qualitative_evidence)
    r09 = _horizon_check("R09", annual_periods, qualitative_evidence)

    if any(value is None for value in (
        prior.revenue, current.revenue, prior.receivables, current.receivables,
        prior.contract_assets, current.contract_assets, prior.operating_cash_flow,
        current.operating_cash_flow,
    )):
        r19 = _unresolved("R19", "R19:missing_component;missing_is_not_zero")
    elif prior.revenue is not None and current.revenue is not None and (
        prior.revenue <= 0 or current.revenue <= 0
    ):
        r19 = _unresolved("R19", "R19:nonpositive_revenue_denominator")
    else:
        assert all(value is not None for value in (
            prior.revenue, current.revenue, prior.receivables, current.receivables,
            prior.contract_assets, current.contract_assets, prior.operating_cash_flow,
            current.operating_cash_flow,
        ))
        revenue_growth = _growth(prior.revenue, current.revenue)  # type: ignore[arg-type]
        receivable_growth = _growth(prior.receivables, current.receivables)  # type: ignore[arg-type]
        contract_growth = _growth(prior.contract_assets, current.contract_assets)  # type: ignore[arg-type]
        ocf_growth = _growth(prior.operating_cash_flow, current.operating_cash_flow)  # type: ignore[arg-type]
        if any(item is None for item in (revenue_growth, receivable_growth, contract_growth, ocf_growth)):
            r19 = _unresolved("R19", "R19:nonpositive_growth_base")
        else:
            assert revenue_growth is not None and receivable_growth is not None
            assert contract_growth is not None and ocf_growth is not None
            divergence = revenue_growth > 0 and (
                receivable_growth > revenue_growth
                or contract_growth > revenue_growth
                or ocf_growth < revenue_growth
            )
            observations = (
                f"revenue_growth={revenue_growth}",
                f"receivables_growth={receivable_growth}",
                f"contract_assets_growth={contract_growth}",
                f"OCF_growth={ocf_growth}",
            )
            if divergence:
                r19 = _unresolved(
                    "R19", "R19:revenue_collection_divergence_requires_cutoff_and_subsequent_collection_evidence",
                    applicability="triggered", observations=observations,
                    evidence_ids=_ids(prior.evidence_ids, current.evidence_ids),
                )
            else:
                required = _REQUIRED_SAFETY_EVIDENCE["R19"]
                admitted = tuple(item for item in qualitative_evidence if item.kind in required)
                missing = sorted(required - {item.kind for item in admitted})
                r19 = (
                    _unresolved(
                        "R19", "R19:safety_evidence_missing:" + ",".join(missing),
                        observations=observations,
                        evidence_ids=_ids(prior.evidence_ids, current.evidence_ids),
                    )
                    if missing
                    else _evaluated(
                        "R19", triggered=False, period=current.period, observations=observations,
                        evidence_ids=_ids(prior.evidence_ids, current.evidence_ids), documentary=admitted,
                    )
                )

    kam = tuple(item for item in qualitative_evidence if item.kind == "revenue_recognition_kam")
    kam_periods = {item.citation.period for item in kam}
    if len(kam) != 3 or len(kam_periods) != 3:
        r20 = _unresolved(
            "R20", f"R20:three_year_revenue_recognition_KAM_required:{len(kam_periods)}/3",
            evidence_ids=tuple(item.citation.evidence_id for item in kam),
        )
    else:
        risk = any(item.signal == "risk" for item in kam)
        r20 = _evaluated(
            "R20", triggered=risk, period=max(kam_periods),
            observations=tuple(f"{item.citation.period}:{item.citation.verbatim_excerpt}" for item in kam),
            evidence_ids=(), documentary=kam,
        )

    checks = (r01, r02, r03, r04, r05, r06, r07, r08, r09, r19, r20)
    reasons = tuple(dict.fromkeys(reason for item in checks for reason in item.unresolved_reasons))
    citations = tuple({item.citation.evidence_id: item.citation for item in qualitative_evidence}.values())
    return WorkingCapitalRiskEvidence(
        checks=checks,
        citations=citations,
        peer_inventory_context_ids=tuple(dict.fromkeys(peer_inventory_context_ids)),
        unresolved_reasons=reasons,
    )


__all__ = [
    "WorkingCapitalPeriod",
    "WorkingCapitalQualitativeEvidence",
    "WorkingCapitalRiskEvidence",
    "build_working_capital_risk",
]
