"""Residual impairment, investment and related-party Risk producers.

This module owns only R29--R36.  R37--R40, R41--R42 and R43--R48 remain
owned by the ESG, governance-insider and forecast/capital producers.  It also
builds a non-row capital-structure conclusion so issued shares, weighted share
counts, EPS denominators and fully diluted exposure cannot be conflated.
Missing valuation models, assumptions, identities, terms, periods or original
official documents fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Sequence

from company_quality.company_analysis.checklist_contracts import (
    ChecklistCheckResult,
    RiskConclusion,
)
from company_quality.company_analysis.contracts import EvidenceCitation


class ImpairmentCapitalEvidenceError(ValueError):
    """Raised when evidence references or structural identities are unsafe."""


@dataclass(frozen=True, slots=True)
class AmountFact:
    amount: Decimal
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.evidence_ids:
            raise ImpairmentCapitalEvidenceError("amount fact requires evidence")


@dataclass(frozen=True, slots=True)
class ImpairmentModel:
    model_id: str
    asset_type: Literal["goodwill", "intangible", "ppe", "right_of_use"]
    cgu: str | None
    carrying_amount: AmountFact | None
    recoverable_amount: AmountFact | None
    valuation_method: Literal["value_in_use", "fair_value_less_costs", "unknown"]
    budget_years: int | None
    terminal_growth_rate: Decimal | None
    discount_rate: Decimal | None
    headroom: Decimal | None
    sensitivity: str | None
    performance_vs_acquisition_case: str | None
    kam: bool
    assumptions_evidence_ids: tuple[str, ...]
    auditor_test_evidence_ids: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return bool(
            self.model_id and self.cgu and self.carrying_amount
            and self.recoverable_amount and self.valuation_method != "unknown"
            and self.budget_years is not None and self.terminal_growth_rate is not None
            and self.discount_rate is not None and self.headroom is not None
            and self.sensitivity and self.performance_vs_acquisition_case
            and self.assumptions_evidence_ids
            and (not self.kam or self.auditor_test_evidence_ids)
        )


@dataclass(frozen=True, slots=True)
class PpeExposure:
    asset_id: str
    carrying_amount: AmountFact | None
    utilization_rate: Decimal | None
    idle_amount: AmountFact | None
    impairment_indicator: bool | None
    impairment_model: ImpairmentModel | None
    demand_or_order_support: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EquityMethodExposure:
    investee_id: str
    investee_identity: str | None
    carrying_amount: AmountFact | None
    current_loss: AmountFact | None
    additional_funding_commitment: AmountFact | None
    guarantee_or_obligation: AmountFact | None
    exit_or_recovery_plan: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FinancialAssetExposure:
    position_id: str
    instrument: str | None
    amount: AmountFact | None
    fair_value_level: Literal["level_1", "level_2", "level_3", "amortized_cost", "unknown"]
    concentration_ratio: Decimal | None
    leveraged: bool | None
    liquidity: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelatedPartyTransaction:
    transaction_id: str
    counterparty_identity: str | None
    relationship: str | None
    transaction_type: str | None
    amount: AmountFact | None
    benchmark_terms: str | None
    commercial_rationale: str | None
    settlement_status: str | None
    original_document_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelatedPartyFunding:
    funding_id: str
    counterparty_identity: str | None
    relationship: str | None
    purpose: str | None
    amount: AmountFact | None
    interest_rate: Decimal | None
    limit: AmountFact | None
    overdue: bool | None
    collateral: str | None
    recoverability: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GuaranteeExposure:
    guarantee_id: str
    counterparty_identity: str | None
    relationship: str | None
    amount: AmountFact | None
    expiry: str | None
    amount_drawn: AmountFact | None
    recourse: str | None
    counterparty_financial_condition: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DilutiveInstrument:
    instrument_id: str
    instrument_type: Literal["convertible_bond", "warrant", "option", "restricted_share", "other"]
    potential_shares: AmountFact
    terms: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShareStructure:
    issued_shares: AmountFact
    basic_weighted_average_shares: AmountFact
    diluted_weighted_average_shares: AmountFact
    fully_diluted_exposure: AmountFact
    instruments: tuple[DilutiveInstrument, ...]
    roster_complete: bool


@dataclass(frozen=True, slots=True)
class CapitalAllocationDecision:
    decision_id: str
    decision_type: Literal["capex", "cash_raise", "convertible_bond", "acquisition", "buyback", "dividend", "other"]
    lifecycle: Literal["proposed", "authorized", "completed"]
    amount: AmountFact
    purpose: str | None
    announced_at: str
    effective_at: str | None
    follow_up_roic: Decimal | None
    official_event_evidence_id: str | None
    original_document_evidence_id: str | None
    note_evidence_id: str | None


@dataclass(frozen=True, slots=True)
class ImpairmentCapitalRiskAssessment:
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    limitations: tuple[str, ...]
    shareholder_dilution_and_capital_allocation: RiskConclusion | None
    share_structure: ShareStructure | None
    schema_version: Literal["ImpairmentCapitalRiskAssessment.v1"] = "ImpairmentCapitalRiskAssessment.v1"

    @property
    def by_check_id(self) -> dict[str, ChecklistCheckResult]:
        return {item.check_id: item for item in self.checks}

    def __post_init__(self) -> None:
        if {item.check_id for item in self.checks} != {f"R{i:02d}" for i in range(29, 37)}:
            raise ImpairmentCapitalEvidenceError("assessment must contain exactly R29-R36")
        cited = {item.evidence_id for item in self.citations}
        referenced = {value for row in self.checks for value in row.evidence_ids}
        if self.shareholder_dilution_and_capital_allocation is not None:
            referenced.update(self.shareholder_dilution_and_capital_allocation.evidence_ids)
        missing = sorted(referenced - cited)
        if missing:
            raise ImpairmentCapitalEvidenceError(
                "impairment/capital checks cite missing evidence: " + ",".join(missing)
            )


def _ids(*values: object) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        candidates = (
            *(getattr(value, "evidence_ids", ()) or ()),
            *(getattr(value, "assumptions_evidence_ids", ()) or ()),
            *(getattr(value, "auditor_test_evidence_ids", ()) or ()),
            *(getattr(value, "original_document_evidence_ids", ()) or ()),
            *(getattr(getattr(value, "carrying_amount", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "recoverable_amount", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "idle_amount", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "current_loss", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "additional_funding_commitment", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "guarantee_or_obligation", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "amount", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "limit", None), "evidence_ids", ()) or ()),
            *(getattr(getattr(value, "amount_drawn", None), "evidence_ids", ()) or ()),
            *(item for item in (
                getattr(value, "official_event_evidence_id", None),
                getattr(value, "original_document_evidence_id", None),
                getattr(value, "note_evidence_id", None),
            ) if item),
        )
        for item in candidates:
            if item and item not in result:
                result.append(item)
    return tuple(result)


def _row(
    check_id: str, *, period: str, as_of: str, monitoring_date: str,
    applicability: Literal["triggered", "not_triggered", "not_applicable", "unresolved"],
    status: Literal["evaluated", "unresolved"], mechanism: str,
    monitoring: Sequence[str], observations: Sequence[str] = (),
    evidence_ids: Sequence[str] = (), reasons: Sequence[str] = (),
    buffers: Sequence[str] = (), severity: Literal["low", "medium", "high", "critical", "not_applicable"] = "low",
) -> ChecklistCheckResult:
    return ChecklistCheckResult(
        check_id=check_id, domain="risk", applicability=applicability, status=status,
        first_detectable_at=as_of if evidence_ids else None, financial_period=period,
        observations=tuple(observations), evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        supporting_evidence=("已取得數字、附註、假設／條款與官方原始文件證據鏈。",)
        if status == "evaluated" and applicability == "triggered" else (),
        counterevidence=("完整有界名冊已檢查且未達觸發條件。",)
        if status == "evaluated" and applicability in {"not_triggered", "not_applicable"} else (),
        inference_chain=("canonical facts → 正式附註／估值模型／事件原文 → 反證與敏感度",)
        if status == "evaluated" else (),
        mechanism=mechanism, leading_warnings=tuple(monitoring), buffers=tuple(buffers),
        monitoring_metrics=tuple(monitoring), monitoring_date=monitoring_date,
        invalidation_or_resolution_conditions=("新一期原始申報、事件、估值模型、交易或還款證據更新本題。",),
        severity=severity if status == "evaluated" else "not_applicable",
        confidence="high" if status == "evaluated" else "low",
        unresolved_reasons=tuple(reasons),
    )


def assess_impairment_capital_risk(
    *, period: str, as_of: str, monitoring_date: str,
    prior_goodwill: AmountFact | None, current_goodwill: AmountFact | None,
    prior_intangibles: AmountFact | None, current_intangibles: AmountFact | None,
    impairment_roster_complete: bool, impairment_models: tuple[ImpairmentModel, ...],
    ppe_roster_complete: bool, ppe_exposures: tuple[PpeExposure, ...],
    equity_method_roster_complete: bool, equity_method_exposures: tuple[EquityMethodExposure, ...],
    financial_asset_roster_complete: bool, financial_asset_exposures: tuple[FinancialAssetExposure, ...],
    related_party_roster_complete: bool, related_party_transactions: tuple[RelatedPartyTransaction, ...],
    funding_roster_complete: bool, related_party_funding: tuple[RelatedPartyFunding, ...],
    guarantee_roster_complete: bool, guarantees: tuple[GuaranteeExposure, ...],
    share_structure: ShareStructure | None,
    capital_allocation_roster_complete: bool,
    capital_allocation_decisions: tuple[CapitalAllocationDecision, ...],
    citations: tuple[EvidenceCitation, ...] = (),
) -> ImpairmentCapitalRiskAssessment:
    """Produce R29--R36 and a companion capital-structure conclusion."""

    rows: dict[str, ChecklistCheckResult] = {}
    limitations: list[str] = []

    def unresolved(check_id: str, reason: str, evidence: Sequence[str] = ()) -> None:
        rows[check_id] = _row(
            check_id, period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="unresolved", status="unresolved", reasons=(reason,),
            evidence_ids=evidence, mechanism="證據不完整，不得由單一數字或未找到推論安全。",
            monitoring=("補齊原始文件、身分、期間、假設、條款與有界名冊",),
        )

    amounts = (prior_goodwill, current_goodwill, prior_intangibles, current_intangibles)
    if any(item is None for item in amounts) or not impairment_roster_complete:
        unresolved("R29", "商譽／無形資產比較期、企業合併／減損名冊或原始附註不完整。", _ids(*amounts, *impairment_models))
    else:
        assert all(item is not None for item in amounts)
        assert prior_goodwill and current_goodwill and prior_intangibles and current_intangibles
        increased = current_goodwill.amount > prior_goodwill.amount or current_intangibles.amount > prior_intangibles.amount
        rows["R29"] = _row(
            "R29", period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if increased else "not_triggered", status="evaluated",
            observations=(f"商譽{prior_goodwill.amount}→{current_goodwill.amount}；無形資產{prior_intangibles.amount}→{current_intangibles.amount}；模型數={len(impairment_models)}。",),
            evidence_ids=_ids(*amounts, *impairment_models),
            mechanism="商譽／無形資產增加須回溯收購對價、CGU分配、原收購假設與實績。",
            monitoring=("商譽與無形資產", "CGU", "原收購假設與實績", "減損"),
            buffers=("金額未增加也不證明估值模型或安全空間充足。",),
            severity="medium" if increased else "low",
        )

    goodwill_models = tuple(item for item in impairment_models if item.asset_type in {"goodwill", "intangible"})
    if not impairment_roster_complete or not goodwill_models or any(not item.complete for item in goodwill_models):
        unresolved("R30", "缺少完整CGU、帳面／可回收金額、估值法、預算期、成長率、折現率、安全空間、敏感度、原收購實績或KAM查核方式。", _ids(*goodwill_models))
    else:
        thin = any(item.headroom is not None and item.headroom <= item.carrying_amount.amount * Decimal("0.10") for item in goodwill_models if item.carrying_amount)
        kam = any(item.kam for item in goodwill_models)
        observations = tuple(
            f"{item.model_id}/{item.asset_type}/{item.cgu}: 帳面={item.carrying_amount.amount if item.carrying_amount else 'missing'}；可回收={item.recoverable_amount.amount if item.recoverable_amount else 'missing'}；安全空間={item.headroom}；預算期={item.budget_years}；成長率={item.terminal_growth_rate}；折現率={item.discount_rate}；敏感度={item.sensitivity}；原收購實績={item.performance_vs_acquisition_case}；KAM={item.kam}。"
            for item in goodwill_models
        )
        rows["R30"] = _row(
            "R30", period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if thin or kam else "not_triggered", status="evaluated",
            observations=observations, evidence_ids=_ids(*goodwill_models),
            mechanism="薄安全空間或KAM代表估值對預測、成長率與折現率敏感；有無已認列減損不是唯一判據。",
            monitoring=("CGU實績", "預算期", "成長率", "折現率", "安全空間", "敏感度", "KAM跨年變化"),
            buffers=("單一數值或單一敏感度結果永遠不單獨證明安全。",),
            severity="high" if thin else "medium" if kam else "low",
        )

    ppe_incomplete = any(
        not item.asset_id or item.carrying_amount is None or item.utilization_rate is None
        or item.idle_amount is None or item.impairment_indicator is None
        or not item.demand_or_order_support or not item.evidence_ids
        or (item.impairment_indicator and (item.impairment_model is None or not item.impairment_model.complete))
        for item in ppe_exposures
    )
    if not ppe_roster_complete or ppe_incomplete:
        unresolved("R31", "PPE／使用權資產名冊、稼動率、閒置金額、減損跡象、需求支持或可回收模型不完整。", _ids(*ppe_exposures, *(item.impairment_model for item in ppe_exposures)))
    else:
        triggered_ppe = any(
            (item.impairment_indicator is True) or (item.idle_amount and item.idle_amount.amount > 0)
            or (item.utilization_rate is not None and item.utilization_rate < Decimal("0.60"))
            for item in ppe_exposures
        )
        observations = tuple(
            f"{item.asset_id}: 帳面={item.carrying_amount.amount if item.carrying_amount else 'missing'}；稼動率={item.utilization_rate}；閒置={item.idle_amount.amount if item.idle_amount else 'missing'}；減損跡象={item.impairment_indicator}；需求／訂單={item.demand_or_order_support}。"
            for item in ppe_exposures
        ) or ("完整有界PPE減損名冊未見具帳面暴險之項目。",)
        rows["R31"] = _row(
            "R31", period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if triggered_ppe else "not_triggered", status="evaluated",
            observations=observations, evidence_ids=_ids(*ppe_exposures, *(item.impairment_model for item in ppe_exposures)),
            mechanism="低稼動、閒置或需求永久下降可能透過後續減損與折舊負擔侵蝕獲利。",
            monitoring=("稼動率", "閒置資產", "資產週轉", "部門損益", "訂單／需求", "可回收金額"),
            buffers=("暫時停工與訂單恢復須有獨立文件及後續實績。",),
            severity="high" if triggered_ppe else "low",
        )

    equity_incomplete = any(
        not item.investee_id or not item.investee_identity or item.carrying_amount is None
        or item.current_loss is None or item.additional_funding_commitment is None
        or item.guarantee_or_obligation is None or not item.exit_or_recovery_plan
        or not item.evidence_ids for item in equity_method_exposures
    )
    if not equity_method_roster_complete or equity_incomplete:
        unresolved("R32", "權益法被投資公司身分、損益、帳面額、追加出資、擔保／義務或退出／改善計畫不完整。", _ids(*equity_method_exposures))
    else:
        exposed = any(
            (item.current_loss and item.current_loss.amount > 0)
            or (item.additional_funding_commitment and item.additional_funding_commitment.amount > 0)
            or (item.guarantee_or_obligation and item.guarantee_or_obligation.amount > 0)
            for item in equity_method_exposures
        )
        observations = tuple(
            f"{item.investee_identity}: 帳面={item.carrying_amount.amount if item.carrying_amount else 0}；損失={item.current_loss.amount if item.current_loss else 0}；追加出資={item.additional_funding_commitment.amount if item.additional_funding_commitment else 0}；擔保／義務={item.guarantee_or_obligation.amount if item.guarantee_or_obligation else 0}；計畫={item.exit_or_recovery_plan}。"
            for item in equity_method_exposures
        ) or ("完整有界權益法投資名冊未見帳面或表外暴險。",)
        rows["R32"] = _row(
            "R32", period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if exposed else "not_triggered", status="evaluated",
            observations=observations, evidence_ids=_ids(*equity_method_exposures),
            mechanism="被投資公司虧損可透過追加出資、擔保或其他義務使最大損失超過帳面價值。",
            monitoring=("投資損益", "帳面價值", "追加出資", "擔保／義務", "退出／改善里程碑"),
            severity="high" if exposed else "low",
        )

    financial_incomplete = any(
        not item.position_id or not item.instrument or item.amount is None
        or item.fair_value_level == "unknown" or item.concentration_ratio is None
        or item.leveraged is None or not item.liquidity or not item.evidence_ids
        for item in financial_asset_exposures
    )
    if not financial_asset_roster_complete or financial_incomplete:
        unresolved("R33", "金融資產工具、金額、公允價值層級、集中度、槓桿或流動性不完整。", _ids(*financial_asset_exposures))
    else:
        risky = any(
            item.fair_value_level == "level_3" or item.leveraged
            or (item.concentration_ratio is not None and item.concentration_ratio >= Decimal("0.20"))
            or item.liquidity != "liquid"
            for item in financial_asset_exposures
        )
        observations = tuple(
            f"{item.instrument}: 金額={item.amount.amount if item.amount else 0}；層級={item.fair_value_level}；集中={item.concentration_ratio}；槓桿={item.leveraged}；流動性={item.liquidity}。"
            for item in financial_asset_exposures
        ) or ("完整有界金融資產名冊未見部位。",)
        rows["R33"] = _row(
            "R33", period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if risky else "not_triggered", status="evaluated",
            observations=observations, evidence_ids=_ids(*financial_asset_exposures),
            mechanism="高集中、Level 3、槓桿或低流動部位會把營運現金暴露於估值與退出風險。",
            monitoring=("部位／權益", "Level 1/2/3", "集中度", "槓桿", "流動性", "未實現損益"),
            severity="high" if risky else "low",
        )

    related_incomplete = any(
        not item.transaction_id or not item.counterparty_identity or not item.relationship
        or not item.transaction_type or item.amount is None or not item.benchmark_terms
        or not item.commercial_rationale or not item.settlement_status
        or len(item.original_document_evidence_ids) < 2
        for item in related_party_transactions
    )
    if not related_party_roster_complete or related_incomplete:
        unresolved("R34", "關係人名冊、交易對手身分／關係、交易種類、一般客戶基準條件、商業理由、收付狀態或原始文件不完整。", _ids(*related_party_transactions))
    else:
        non_arm = any(item.settlement_status != "settled" or "一致" not in (item.benchmark_terms or "") for item in related_party_transactions)
        observations = tuple(
            f"{item.counterparty_identity}/{item.relationship}/{item.transaction_type}: 金額={item.amount.amount if item.amount else 0}；一般客戶基準={item.benchmark_terms}；理由={item.commercial_rationale}；收付={item.settlement_status}。"
            for item in related_party_transactions
        ) or ("完整有界關係人交易名冊未見交易。",)
        rows["R34"] = _row(
            "R34", period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if non_arm else "not_triggered", status="evaluated",
            observations=observations, evidence_ids=_ids(*related_party_transactions),
            mechanism="非一般交易條件或久未收付可能造成利益移轉與信用損失。",
            monitoring=("關係人交易占比", "一般客戶／供應商條件差異", "帳齡與收付", "商業合理性"),
            buffers=("交易存在或單一占比不單獨證明正常或異常。",),
            severity="high" if non_arm else "low",
        )

    funding_incomplete = any(
        not item.funding_id or not item.counterparty_identity or not item.relationship
        or not item.purpose or item.amount is None or item.interest_rate is None
        or item.limit is None or item.overdue is None or not item.collateral
        or not item.recoverability or not item.evidence_ids for item in related_party_funding
    )
    if not funding_roster_complete or funding_incomplete:
        unresolved("R35", "資金貸與對象身分／關係、用途、金額、利率、限額、逾期、擔保或可收回性不完整。", _ids(*related_party_funding))
    else:
        risky_funding = any(item.overdue or (item.amount and item.limit and item.amount.amount > item.limit.amount) or "虧損" in (item.recoverability or "") for item in related_party_funding)
        observations = tuple(
            f"{item.counterparty_identity}: 用途={item.purpose}；金額={item.amount.amount if item.amount else 0}；利率={item.interest_rate}；限額={item.limit.amount if item.limit else 0}；逾期={item.overdue}；擔保={item.collateral}；可收回性={item.recoverability}。"
            for item in related_party_funding
        ) or ("完整有界資金貸與名冊未見餘額。",)
        rows["R35"] = _row(
            "R35", period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if risky_funding else "not_triggered", status="evaluated",
            observations=observations, evidence_ids=_ids(*related_party_funding),
            mechanism="對虧損、不透明或逾期關係企業貸款會形成實質信用與資金外流風險。",
            monitoring=("資金貸與餘額", "利率／限額", "逾期", "擔保", "可收回性"),
            severity="high" if risky_funding else "low",
        )

    guarantee_incomplete = any(
        not item.guarantee_id or not item.counterparty_identity or not item.relationship
        or item.amount is None or not item.expiry or item.amount_drawn is None
        or not item.recourse or not item.counterparty_financial_condition
        or not item.evidence_ids for item in guarantees
    )
    if not guarantee_roster_complete or guarantee_incomplete:
        unresolved("R36", "背書保證對象身分／關係、金額、到期、實際動支、追索權或對手方財務狀況不完整。", _ids(*guarantees))
    else:
        risky_guarantee = any((item.amount_drawn and item.amount_drawn.amount > 0) or "虧損" in (item.counterparty_financial_condition or "") for item in guarantees)
        observations = tuple(
            f"{item.counterparty_identity}: 保證={item.amount.amount if item.amount else 0}；到期={item.expiry}；動支={item.amount_drawn.amount if item.amount_drawn else 0}；追索={item.recourse}；財務={item.counterparty_financial_condition}。"
            for item in guarantees
        ) or ("完整有界背書保證名冊未見暴險。",)
        rows["R36"] = _row(
            "R36", period=period, as_of=as_of, monitoring_date=monitoring_date,
            applicability="triggered" if risky_guarantee else "not_triggered", status="evaluated",
            observations=observations, evidence_ids=_ids(*guarantees),
            mechanism="表外保證在對手方動支或財務惡化時可能轉成現金支出與負債。",
            monitoring=("保證金額／權益", "實際動支", "到期", "追索權", "對手方財務"),
            severity="high" if risky_guarantee else "low",
        )

    capital_conclusion: RiskConclusion | None = None
    share_complete = bool(
        share_structure and share_structure.roster_complete
        and all(item.terms and item.evidence_ids for item in share_structure.instruments)
        and share_structure.fully_diluted_exposure.amount
        == share_structure.issued_shares.amount
        + sum((item.potential_shares.amount for item in share_structure.instruments), Decimal("0"))
    )
    decisions_complete = bool(
        capital_allocation_roster_complete
        and all(
            item.lifecycle == "completed" and item.effective_at and item.purpose
            and item.follow_up_roic is not None and item.official_event_evidence_id
            and item.original_document_evidence_id and item.note_evidence_id
            for item in capital_allocation_decisions
        )
    )
    if not share_complete:
        limitations.append("完全稀釋工具名冊、條款、潛在股數或 issued＋工具＝fully diluted 勾稽不完整；加權股數與EPS分母不得替代。")
    if not decisions_complete:
        limitations.append("資本配置完成事件、正式公告、原始文件、財報附註、用途、期間或後續ROIC不完整。")
    if share_complete and decisions_complete and share_structure is not None:
        share_ids = _ids(
            share_structure.issued_shares, share_structure.basic_weighted_average_shares,
            share_structure.diluted_weighted_average_shares, share_structure.fully_diluted_exposure,
            *share_structure.instruments,
            *(item.potential_shares for item in share_structure.instruments),
        )
        decision_ids = _ids(*capital_allocation_decisions)
        exposure = share_structure.fully_diluted_exposure.amount - share_structure.issued_shares.amount
        weak_allocation = any(item.follow_up_roic is not None and item.follow_up_roic < Decimal("0.05") for item in capital_allocation_decisions)
        judgement: Literal["stable", "deteriorating"] = "deteriorating" if exposure > 0 or weak_allocation else "stable"
        summary = (
            f"期末已發行股數={share_structure.issued_shares.amount}；"
            f"基本加權平均股數={share_structure.basic_weighted_average_shares.amount}；"
            f"稀釋加權平均股數={share_structure.diluted_weighted_average_shares.amount}；"
            f"完全稀釋暴險={share_structure.fully_diluted_exposure.amount}；"
            f"工具潛在股數={exposure}；完成資本配置事件={len(capital_allocation_decisions)}。"
        )
        capital_conclusion = RiskConclusion(
            dimension="shareholder_dilution_and_capital_allocation", judgement=judgement,
            mechanism="潛在普通股增加每股稀釋；資本投入若後續ROIC不足，會形成永久每股價值損失。",
            leading_warnings=("期末已發行股數", "基本／稀釋加權平均股數", "各CB／warrant／option潛在股數", "完全稀釋暴險", "完成事件後ROIC"),
            current_evidence=(summary,), evidence_ids=(*share_ids, *decision_ids),
            buffers_and_counterevidence=("工具條款、到期／歸屬、反稀釋與實際轉換歷史須逐項追蹤；單一事件或股數不證明安全。",),
            stress_transmission=("完全轉換／行使增加分母；低回報用途削弱每股現金流與再融資能力。",),
            resolution_conditions=("工具到期失效或完成轉換並勾稽股數，且資本用途按期產生可驗證ROIC與現金。",),
            unresolved_items=(), monitoring_metrics=("fully diluted exposure", "issued shares", "weighted shares", "diluted EPS", "capital allocation ROIC"),
            confidence="high",
        )

    ordered = tuple(rows[f"R{i:02d}"] for i in range(29, 37))
    limitations.extend(reason for row in ordered for reason in row.unresolved_reasons)
    return ImpairmentCapitalRiskAssessment(
        checks=ordered, citations=citations,
        limitations=tuple(dict.fromkeys(limitations)),
        shareholder_dilution_and_capital_allocation=capital_conclusion,
        share_structure=share_structure,
    )


__all__ = [
    "AmountFact", "CapitalAllocationDecision", "DilutiveInstrument",
    "EquityMethodExposure", "FinancialAssetExposure", "GuaranteeExposure",
    "ImpairmentCapitalEvidenceError", "ImpairmentCapitalRiskAssessment",
    "ImpairmentModel", "PpeExposure", "RelatedPartyFunding",
    "RelatedPartyTransaction", "ShareStructure", "assess_impairment_capital_risk",
]
