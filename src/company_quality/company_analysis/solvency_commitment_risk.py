"""Fail-closed solvency, refinancing, covenant, lease and commitment checks.

This producer owns R10--R18 and R38 from the authoritative financial checklist.
It admits only cited facts available at the analysis date.  Missing debt classes,
maturity schedules, facility/covenant terms, or commitment terms remain unresolved.
Oral renewals and management assertions are never financing buffers, and a waiver
obtained after ``as_of`` never repairs the point-in-time covenant state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Sequence

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation


class SolvencyEvidenceError(ValueError):
    """Raised when solvency evidence cannot be admitted safely."""


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise SolvencyEvidenceError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise SolvencyEvidenceError(f"{field} must be timezone-aware")
    return result


@dataclass(frozen=True, slots=True)
class AmountFact:
    amount: Decimal
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.evidence_ids:
            raise SolvencyEvidenceError("amount fact requires evidence")


@dataclass(frozen=True, slots=True)
class SolvencyPeriodFacts:
    period: str
    short_term_debt: AmountFact | None = None
    long_term_debt: AmountFact | None = None
    debt_due_within_12m: AmountFact | None = None
    gross_cash: AmountFact | None = None
    restricted_cash: AmountFact | None = None
    pledged_cash: AmountFact | None = None
    non_remittable_cash: AmountFact | None = None
    customer_money: AmountFact | None = None
    defensible_12m_ocf: AmountFact | None = None
    capex: AmountFact | None = None
    long_lived_assets: AmountFact | None = None
    roic: AmountFact | None = None
    expensed_interest: AmountFact | None = None
    capitalized_interest: AmountFact | None = None
    total_liabilities: AmountFact | None = None
    total_equity: AmountFact | None = None
    lease_liabilities: AmountFact | None = None


@dataclass(frozen=True, slots=True)
class EquityBridge:
    debt_repayment: Decimal | None
    equity_issuance: Decimal | None
    retained_earnings: Decimal | None
    valuation_and_oci: Decimal | None
    other_change: Decimal | None
    evidence_ids: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class CreditFacility:
    facility_id: str
    undrawn_amount: AmountFact | None
    signed: bool
    committed: bool
    cancellable_by_lender: bool | None
    conditions_satisfied: bool | None
    signed_at: str | None
    expires_at: str | None
    evidence_ids: tuple[str, ...]
    representation: Literal["contract", "oral_renewal", "management_assertion"] = "contract"


@dataclass(frozen=True, slots=True)
class CovenantTerm:
    covenant_id: str
    actual: Decimal | None
    threshold: Decimal | None
    comparator: Literal["minimum", "maximum"] | None
    actual_evidence_ids: tuple[str, ...]
    threshold_evidence_ids: tuple[str, ...]
    waiver_at: str | None = None
    waiver_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LeaseTerms:
    benefit_metric: Decimal | None
    benefit_description: str | None
    exit_or_cancellation_terms: str | None
    exit_cost: Decimal | None
    evidence_ids: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class UnpaidCommitment:
    commitment_id: str
    unpaid_amount: AmountFact | None
    cancellation_terms: str | None
    funding_source: str | None
    demand_support: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SolvencyCommitmentRiskAssessment:
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    limitations: tuple[str, ...]
    schema_version: Literal["SolvencyCommitmentRiskAssessment.v1"] = (
        "SolvencyCommitmentRiskAssessment.v1"
    )

    @property
    def by_check_id(self) -> dict[str, ChecklistCheckResult]:
        return {item.check_id: item for item in self.checks}

    def __post_init__(self) -> None:
        expected = {f"R{item:02d}" for item in range(10, 19)} | {"R38"}
        if {item.check_id for item in self.checks} != expected:
            raise SolvencyEvidenceError("assessment must contain R10-R18 and R38")
        cited = {item.evidence_id for item in self.citations}
        referenced = {value for item in self.checks for value in item.evidence_ids}
        missing = sorted(referenced - cited)
        if missing:
            raise SolvencyEvidenceError(
                "solvency checks cite missing evidence: " + ",".join(missing)
            )


def _ids(*values: object) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        candidates = (
            *(getattr(value, "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "unpaid_amount", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "undrawn_amount", None), "evidence_ids", ()) or ()),
            *(getattr(value, "actual_evidence_ids", ()) or ()),
            *(getattr(value, "threshold_evidence_ids", ()) or ()),
            *(getattr(value, "waiver_evidence_ids", ()) or ()),
        )
        for item in candidates:
            if item and item not in result:
                result.append(item)
    return tuple(result)


def _row(
    check_id: str,
    *,
    period: str,
    as_of: str,
    monitoring_date: str,
    applicability: Literal["triggered", "not_triggered", "not_applicable", "unresolved"],
    status: Literal["evaluated", "unresolved"],
    observations: Sequence[str] = (),
    evidence_ids: Sequence[str] = (),
    reasons: Sequence[str] = (),
    mechanism: str,
    monitoring: Sequence[str],
    buffers: Sequence[str] = (),
    severity: Literal["low", "medium", "high", "critical", "not_applicable"] = "low",
) -> ChecklistCheckResult:
    triggered = applicability == "triggered"
    return ChecklistCheckResult(
        check_id=check_id,
        domain="risk",
        applicability=applicability,
        status=status,
        first_detectable_at=as_of if evidence_ids else None,
        financial_period=period,
        observations=tuple(observations),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        supporting_evidence=("已取得本題指定的契約與量化證據鏈。",) if status == "evaluated" and triggered else (),
        counterevidence=("已完成本題指定範圍且未達觸發條件。",) if status == "evaluated" and not triggered else (),
        inference_chain=("官方財報／附註／已簽契約 → PIT量化 → 清單風險題",) if status == "evaluated" else (),
        mechanism=mechanism,
        leading_warnings=tuple(monitoring),
        buffers=tuple(buffers),
        monitoring_metrics=tuple(monitoring),
        monitoring_date=monitoring_date,
        invalidation_or_resolution_conditions=("新一期財報、契約、付款、融資或需求證據更新本題。",),
        severity=severity if status == "evaluated" else "not_applicable",
        confidence="high" if status == "evaluated" else "low",
        unresolved_reasons=tuple(reasons),
    )


def assess_solvency_commitment_risk(
    *,
    current: SolvencyPeriodFacts,
    prior: SolvencyPeriodFacts,
    as_of: str,
    monitoring_date: str,
    debt_classes_complete: bool,
    maturity_schedule_complete: bool,
    cash_restrictions_complete: bool,
    long_debt_use_linked: bool | None,
    long_debt_use_evidence_ids: tuple[str, ...] = (),
    equity_bridge: EquityBridge | None = None,
    facility_roster_complete: bool,
    facilities: tuple[CreditFacility, ...] = (),
    covenant_roster_complete: bool,
    covenants: tuple[CovenantTerm, ...] = (),
    lease_terms: LeaseTerms | None = None,
    commitment_roster_complete: bool,
    commitments: tuple[UnpaidCommitment, ...] = (),
    citations: tuple[EvidenceCitation, ...] = (),
) -> SolvencyCommitmentRiskAssessment:
    """Produce R10--R18 and R38 without treating absent terms as zero."""

    decision = _instant(as_of, "as_of")
    if not monitoring_date.strip():
        raise SolvencyEvidenceError("monitoring_date is required")
    rows: dict[str, ChecklistCheckResult] = {}

    def unresolved(check_id: str, reason: str, *, evidence: Sequence[str] = (), observations: Sequence[str] = (), applicability: Literal["unresolved", "triggered"] = "unresolved") -> None:
        rows[check_id] = _row(
            check_id, period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability=applicability, status="unresolved", observations=observations,
            evidence_ids=evidence, reasons=(reason,),
            mechanism="證據或契約條款不完整，不得推論沒有流動性或承諾風險。",
            monitoring=("補齊本題缺失欄位與原始契約",),
        )

    # R10: short-term borrowings only.  Total debt is deliberately not a substitute.
    if not debt_classes_complete or current.short_term_debt is None or prior.short_term_debt is None:
        unresolved("R10", "短期借款類別或比較期數值不完整；總有息負債不得替代短期借款。", evidence=_ids(current.short_term_debt, prior.short_term_debt))
    else:
        increased = current.short_term_debt.amount > prior.short_term_debt.amount
        rows["R10"] = _row(
            "R10", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if increased else "not_triggered", status="evaluated",
            observations=(f"短期借款由{prior.short_term_debt.amount}變為{current.short_term_debt.amount}；未使用總負債代理。",),
            evidence_ids=_ids(prior.short_term_debt, current.short_term_debt),
            mechanism="短期借款增加可能將營運缺口或長期投資轉化為近端再融資壓力。",
            monitoring=("短期借款", "利率／幣別／擔保", "12個月淨現金需求"),
            buffers=("後續收款可償還的季節性週轉須另有證據。",),
            severity="medium" if increased else "low",
        )

    # Only signed, committed, non-cancellable and currently eligible undrawn lines count.
    eligible: list[CreditFacility] = []
    excluded: list[str] = []
    facility_terms_missing = False
    for facility in facilities:
        if facility.representation != "contract" or not facility.signed or not facility.committed:
            excluded.append(facility.facility_id)
            continue
        if (
            facility.undrawn_amount is None
            or facility.cancellable_by_lender is None
            or facility.conditions_satisfied is None
            or facility.signed_at is None
            or facility.expires_at is None
        ):
            facility_terms_missing = True
            continue
        signed_at = _instant(facility.signed_at, f"{facility.facility_id}.signed_at")
        expires_at = _instant(facility.expires_at, f"{facility.facility_id}.expires_at")
        if signed_at <= decision <= expires_at and not facility.cancellable_by_lender and facility.conditions_satisfied:
            eligible.append(facility)
        else:
            excluded.append(facility.facility_id)
    committed_undrawn = sum((item.undrawn_amount.amount for item in eligible if item.undrawn_amount), Decimal("0"))

    cash_parts = (
        current.gross_cash, current.restricted_cash, current.pledged_cash,
        current.non_remittable_cash, current.customer_money,
    )
    free_cash: Decimal | None = None
    if cash_restrictions_complete and all(item is not None for item in cash_parts):
        gross, restricted, pledged, non_remittable, customer = cash_parts
        assert gross and restricted and pledged and non_remittable and customer
        free_cash = gross.amount - restricted.amount - pledged.amount - non_remittable.amount - customer.amount

    if (
        not maturity_schedule_complete
        or not facility_roster_complete
        or facility_terms_missing
        or current.debt_due_within_12m is None
        or current.defensible_12m_ocf is None
        or free_cash is None
    ):
        unresolved(
            "R11",
            "12個月到期表、可自由運用現金、可辯護OCF或已簽承諾未動用授信不完整；口頭續借不得補缺口。",
            evidence=_ids(current.debt_due_within_12m, current.defensible_12m_ocf, *cash_parts, *facilities),
            applicability="triggered" if current.debt_due_within_12m is not None else "unresolved",
        )
    else:
        resources = free_cash + current.defensible_12m_ocf.amount + committed_undrawn
        gap = current.debt_due_within_12m.amount - resources
        rows["R11"] = _row(
            "R11", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if gap > 0 else "not_triggered", status="evaluated",
            observations=(f"12月到期={current.debt_due_within_12m.amount}；自由現金={free_cash}；可辯護12月OCF={current.defensible_12m_ocf.amount}；已簽承諾未動用授信={committed_undrawn}；缺口={gap}；排除口頭／管理層主張或未承諾額度={','.join(excluded) or '無'}。",),
            evidence_ids=_ids(current.debt_due_within_12m, current.defensible_12m_ocf, *cash_parts, *eligible),
            mechanism="近12月到期額超過自由現金、可辯護OCF與正式授信會形成再融資缺口。",
            monitoring=("逐筆12月到期", "自由現金", "可辯護OCF", "正式未動用授信", "資金缺口"),
            buffers=("只承認已簽、承諾、不可由貸方任意撤銷且條件已滿足的額度。",),
            severity="high" if gap > 0 else "low",
        )

    r12_facts = (current.long_term_debt, prior.long_term_debt, current.capex, prior.capex, current.long_lived_assets, prior.long_lived_assets, current.roic)
    if not debt_classes_complete or any(item is None for item in r12_facts) or long_debt_use_linked is None or not long_debt_use_evidence_ids:
        unresolved("R12", "長期借款、CAPEX、長期資產、ROIC或借款用途連結不完整。", evidence=(*_ids(*r12_facts), *long_debt_use_evidence_ids))
    else:
        assert current.long_term_debt and prior.long_term_debt and current.capex and prior.capex and current.long_lived_assets and prior.long_lived_assets and current.roic
        increased = current.long_term_debt.amount > prior.long_term_debt.amount
        r12_observations = (f"長期借款{prior.long_term_debt.amount}→{current.long_term_debt.amount}；CAPEX{prior.capex.amount}→{current.capex.amount}；長期資產{prior.long_lived_assets.amount}→{current.long_lived_assets.amount}；ROIC={current.roic.amount}；用途連結={'是' if long_debt_use_linked else '否'}。",)
        rows["R12"] = _row(
            "R12", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if increased else "not_triggered", status="evaluated",
            observations=r12_observations, evidence_ids=(*_ids(*r12_facts), *long_debt_use_evidence_ids),
            mechanism="長期借款須對應CAPEX／長期資產，並以ROIC驗證回報而非只看負債期限。",
            monitoring=("長期借款", "CAPEX", "長期資產", "ROIC", "浮動利率壓力"),
            buffers=(("借款用途已連結長期投資。",) if long_debt_use_linked else ()),
            severity="medium" if increased else "low",
        )

    interest_facts = (current.expensed_interest, current.capitalized_interest, prior.expensed_interest, prior.capitalized_interest)
    if any(item is None for item in interest_facts):
        unresolved("R13", "費用化或資本化利息不完整；不得只看損益表財務成本。", evidence=_ids(*interest_facts))
    else:
        assert all(item is not None for item in interest_facts)
        assert current.expensed_interest and current.capitalized_interest
        assert prior.expensed_interest and prior.capitalized_interest
        current_total = current.expensed_interest.amount + current.capitalized_interest.amount
        prior_total = prior.expensed_interest.amount + prior.capitalized_interest.amount
        increased = current_total > prior_total
        rows["R13"] = _row(
            "R13", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if increased else "not_triggered", status="evaluated",
            observations=(f"總利息負擔（費用化＋資本化）由{prior_total}變為{current_total}；本期資本化利息={current.capitalized_interest.amount}。",),
            evidence_ids=_ids(*interest_facts), mechanism="資本化利息仍是融資成本，排除後會低估利息負擔。",
            monitoring=("費用化利息", "資本化利息", "總利息負擔", "利息保障"),
            severity="medium" if increased else "low",
        )

    if free_cash is None:
        unresolved("R14", "現金限制、質押、不可匯回或客戶款項未完整揭露；不得以現金總額宣稱安全。", evidence=_ids(*cash_parts))
    else:
        assert current.gross_cash is not None
        unavailable_cash = current.gross_cash.amount - free_cash
        rows["R14"] = _row(
            "R14", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if unavailable_cash > 0 else "not_triggered", status="evaluated",
            observations=(f"帳面現金={current.gross_cash.amount}；扣除受限制、質押、不可匯回及客戶款後自由現金={free_cash}；不可自由運用={unavailable_cash}。",),
            evidence_ids=_ids(*cash_parts), mechanism="不可自由調度的現金不能支應到期債務或承諾。",
            monitoring=("自由現金", "受限制／質押／不可匯回／客戶款"),
            severity="medium" if unavailable_cash > 0 else "low",
        )

    ratio_facts = (current.total_liabilities, current.total_equity, prior.total_liabilities, prior.total_equity)
    bridge_values = () if equity_bridge is None else (
        equity_bridge.debt_repayment, equity_bridge.equity_issuance,
        equity_bridge.retained_earnings, equity_bridge.valuation_and_oci,
        equity_bridge.other_change,
    )
    if any(item is None for item in ratio_facts) or equity_bridge is None or not equity_bridge.complete or any(item is None for item in bridge_values) or not equity_bridge.evidence_ids:
        unresolved("R15", "負債比或權益橋接不完整；比率下降不得直接稱財務改善。", evidence=_ids(*ratio_facts, equity_bridge))
    else:
        assert current.total_liabilities and current.total_equity and prior.total_liabilities and prior.total_equity
        current_denominator = current.total_liabilities.amount + current.total_equity.amount
        prior_denominator = prior.total_liabilities.amount + prior.total_equity.amount
        if current_denominator == 0 or prior_denominator == 0:
            unresolved("R15", "負債比的資產分母為零，無法計算。", evidence=_ids(*ratio_facts, equity_bridge))
        else:
            current_ratio = current.total_liabilities.amount / current_denominator
            prior_ratio = prior.total_liabilities.amount / prior_denominator
            decreased = current_ratio < prior_ratio
            assert equity_bridge is not None
            rows["R15"] = _row(
                "R15", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
                applicability="triggered" if decreased else "not_triggered", status="evaluated",
                observations=(f"負債比{prior_ratio}→{current_ratio}；權益橋接：還債={equity_bridge.debt_repayment}、增資={equity_bridge.equity_issuance}、保留盈餘={equity_bridge.retained_earnings}、評價／OCI={equity_bridge.valuation_and_oci}、其他={equity_bridge.other_change}。",),
                evidence_ids=_ids(*ratio_facts, equity_bridge), mechanism="負債比下降可能來自增資或評價增值，而非OCF還債。",
                monitoring=("負債絕對額", "增資", "保留盈餘", "評價／OCI", "OCF還債"),
                severity="medium" if decreased else "low",
            )

    if not facility_roster_complete or facility_terms_missing:
        unresolved("R16", "授信名冊或正式簽約、可撤銷、條件與到期條款不完整；口頭續借不得列為緩衝。", evidence=_ids(*facilities))
    else:
        has_buffer = committed_undrawn > 0
        rows["R16"] = _row(
            "R16", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="not_triggered" if has_buffer else "triggered", status="evaluated",
            observations=(f"可承認已簽承諾未動用額度={committed_undrawn}；排除未簽、未承諾、可撤銷、條件未滿足或口頭主張={','.join(excluded) or '無'}。",),
            evidence_ids=_ids(*facilities), mechanism="只有正式簽約且可用的承諾額度能形成流動性緩衝。",
            monitoring=("已簽承諾額度", "未動用額度", "可撤銷條款", "財務條件", "到期日"),
            buffers=((f"符合條件的未動用額度{committed_undrawn}",) if has_buffer else ()),
            severity="high" if not has_buffer else "low",
        )

    if not covenant_roster_complete:
        unresolved("R17", "債務契約名冊不完整，不能推論無契約或無違約。", evidence=_ids(*covenants))
    elif not covenants:
        rows["R17"] = _row(
            "R17", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="not_applicable", status="evaluated", observations=("完整契約名冊確認無財務比率契約。",),
            mechanism="完整名冊確認本期無財務比率門檻。", monitoring=("新借款契約",), severity="not_applicable",
        )
    elif any(item.actual is None or item.threshold is None or item.comparator is None or not item.actual_evidence_ids or not item.threshold_evidence_ids for item in covenants):
        unresolved("R17", "契約實際值、門檻、方向或證據不完整。", evidence=_ids(*covenants))
    else:
        observations: list[str] = []
        buffers: list[str] = []
        triggered = False
        for item in covenants:
            assert item.actual is not None and item.threshold is not None and item.comparator is not None
            compliant = item.actual >= item.threshold if item.comparator == "minimum" else item.actual <= item.threshold
            distance = abs(item.actual - item.threshold)
            near = distance <= abs(item.threshold) * Decimal("0.10") if item.threshold != 0 else distance == 0
            waiver_state = "無豁免"
            if item.waiver_at:
                waiver_time = _instant(item.waiver_at, f"{item.covenant_id}.waiver_at")
                if not item.waiver_evidence_ids:
                    unresolved("R17", "豁免日期存在但缺少正式豁免證據。", evidence=_ids(*covenants))
                    break
                if waiver_time <= decision:
                    waiver_state = f"期末／as-of前正式豁免={item.waiver_at}"
                    buffers.append(waiver_state)
                else:
                    waiver_state = f"as-of後豁免={item.waiver_at}，不得回填"
            observations.append(f"{item.covenant_id}: actual={item.actual}, threshold={item.threshold}, comparator={item.comparator}, {waiver_state}。")
            triggered = triggered or not compliant or near
        else:
            rows["R17"] = _row(
                "R17", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
                applicability="triggered" if triggered else "not_triggered", status="evaluated",
                observations=observations, evidence_ids=_ids(*covenants),
                mechanism="接近或違反契約門檻可能觸發加速到期、交叉違約或流動負債重分類。",
                monitoring=("契約actual", "threshold", "安全空間", "違約／豁免取得日", "交叉違約"),
                buffers=buffers, severity="high" if triggered else "low",
            )

    if current.lease_liabilities is None or prior.lease_liabilities is None or lease_terms is None or not lease_terms.complete or lease_terms.benefit_metric is None or not lease_terms.benefit_description or not lease_terms.exit_or_cancellation_terms or lease_terms.exit_cost is None or not lease_terms.evidence_ids:
        unresolved("R18", "租賃負債、營運效益或退出／取消條款不完整。", evidence=_ids(current.lease_liabilities, prior.lease_liabilities, lease_terms))
    else:
        increased = current.lease_liabilities.amount > prior.lease_liabilities.amount
        rows["R18"] = _row(
            "R18", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if increased else "not_triggered", status="evaluated",
            observations=(f"租賃負債{prior.lease_liabilities.amount}→{current.lease_liabilities.amount}；效益={lease_terms.benefit_description}:{lease_terms.benefit_metric}；退出／取消={lease_terms.exit_or_cancellation_terms}；退出成本={lease_terms.exit_cost}。",),
            evidence_ids=_ids(current.lease_liabilities, prior.lease_liabilities, lease_terms),
            mechanism="租賃負債增加形成固定付款；效益不足且退出成本高會放大營運僵固。",
            monitoring=("租賃負債", "營運效益", "不可撤銷租期", "退出／關閉成本"),
            severity="medium" if increased else "low",
        )

    positive_commitments = tuple(item for item in commitments if item.unpaid_amount is not None and item.unpaid_amount.amount > 0)
    commitment_terms_missing = any(
        item.unpaid_amount is None
        or (item.unpaid_amount.amount > 0 and (not item.cancellation_terms or not item.funding_source or not item.demand_support or not item.evidence_ids))
        for item in commitments
    )
    if not commitment_roster_complete or commitment_terms_missing:
        unresolved(
            "R38",
            "承諾名冊、未付款金額、取消條款、資金來源或需求／訂單支持不完整。",
            evidence=_ids(*commitments),
            observations=tuple(f"{item.commitment_id}: unpaid={item.unpaid_amount.amount if item.unpaid_amount else 'missing'}" for item in commitments),
            applicability="triggered" if positive_commitments else "unresolved",
        )
    else:
        total_unpaid = sum((item.unpaid_amount.amount for item in commitments if item.unpaid_amount), Decimal("0"))
        commitment_observations = tuple(
            f"{item.commitment_id}: 未付款={item.unpaid_amount.amount if item.unpaid_amount else 0}；取消={item.cancellation_terms or '不適用'}；資金={item.funding_source or '不適用'}；需求／訂單支持={item.demand_support or '不適用'}。"
            for item in commitments
        ) or ("完整承諾名冊之未付款承諾為0。",)
        rows["R38"] = _row(
            "R38", period=current.period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if total_unpaid > 0 else "not_triggered", status="evaluated",
            observations=commitment_observations, evidence_ids=_ids(*commitments),
            mechanism="未付款採購／CAPEX承諾會形成表外未來現金需求，須連結取消權、資金與需求支持。",
            monitoring=("未付款承諾", "取消條款", "資金來源", "需求／訂單支持", "支付時程"),
            severity="high" if total_unpaid > 0 else "low",
        )

    order = (*tuple(f"R{item:02d}" for item in range(10, 19)), "R38")
    limitations = tuple(dict.fromkeys(reason for row in rows.values() for reason in row.unresolved_reasons))
    return SolvencyCommitmentRiskAssessment(
        checks=tuple(rows[item] for item in order),
        citations=citations,
        limitations=limitations,
    )


__all__ = [
    "AmountFact", "CovenantTerm", "CreditFacility", "EquityBridge", "LeaseTerms",
    "SolvencyCommitmentRiskAssessment", "SolvencyEvidenceError", "SolvencyPeriodFacts",
    "UnpaidCommitment", "assess_solvency_commitment_risk",
]
