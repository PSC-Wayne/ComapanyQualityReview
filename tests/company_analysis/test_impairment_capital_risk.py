from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.impairment_capital_risk import (
    AmountFact,
    CapitalAllocationDecision,
    DilutiveInstrument,
    EquityMethodExposure,
    FinancialAssetExposure,
    GuaranteeExposure,
    ImpairmentModel,
    PpeExposure,
    RelatedPartyFunding,
    RelatedPartyTransaction,
    ShareStructure,
    assess_impairment_capital_risk,
)

AS_OF = "2026-08-03T12:00:00+08:00"
MONITOR = "2026-11-14"


def _citation(evidence_id: str = "note") -> EvidenceCitation:
    excerpt = f"official note evidence {evidence_id}"
    return EvidenceCitation(
        evidence_id=evidence_id, source_id=f"annual:114:{evidence_id}",
        source_tier="official", url=f"https://mops.example/{evidence_id}.pdf",
        content_sha256=sha256(excerpt.encode()).hexdigest(), period="114",
        available_at="2026-03-31T18:00:00+08:00", page=42,
        coordinate=(Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1")),
        verbatim_excerpt=excerpt,
    )


def _f(value: str, evidence_id: str = "note") -> AmountFact:
    return AmountFact(Decimal(value), (evidence_id,))


def _model(*, asset_type: str = "goodwill", headroom: str = "5") -> ImpairmentModel:
    return ImpairmentModel(
        model_id=f"model-{asset_type}", asset_type=asset_type, cgu="consumer-CGU",
        carrying_amount=_f("100"), recoverable_amount=_f("105"),
        valuation_method="value_in_use", budget_years=5,
        terminal_growth_rate=Decimal("0.03"), discount_rate=Decimal("0.10"),
        headroom=Decimal(headroom), sensitivity="折現率增加1%即消耗安全空間",
        performance_vs_acquisition_case="低於原收購營收承諾10%",
        kam=True, assumptions_evidence_ids=("note",), auditor_test_evidence_ids=("note",),
    )


def _complete(**overrides: object):
    values: dict[str, object] = {
        "period": "114", "as_of": AS_OF, "monitoring_date": MONITOR,
        "prior_goodwill": _f("80"), "current_goodwill": _f("100"),
        "prior_intangibles": _f("20"), "current_intangibles": _f("25"),
        "impairment_roster_complete": True,
        "impairment_models": (_model(), _model(asset_type="intangible", headroom="20")),
        "ppe_roster_complete": True,
        "ppe_exposures": (PpeExposure(
            asset_id="fab", carrying_amount=_f("500"), utilization_rate=Decimal("0.40"),
            idle_amount=_f("100"), impairment_indicator=True,
            impairment_model=_model(asset_type="ppe", headroom="2"),
            demand_or_order_support="訂單恢復尚未完成", evidence_ids=("note",),
        ),),
        "equity_method_roster_complete": True,
        "equity_method_exposures": (EquityMethodExposure(
            investee_id="JV-1", investee_identity="合資公司甲", carrying_amount=_f("30"),
            current_loss=_f("8"), additional_funding_commitment=_f("20"),
            guarantee_or_obligation=_f("10"), exit_or_recovery_plan="尚無正式退出",
            evidence_ids=("note",),
        ),),
        "financial_asset_roster_complete": True,
        "financial_asset_exposures": (FinancialAssetExposure(
            position_id="fund-1", instrument="私募基金", amount=_f("60"),
            fair_value_level="level_3", concentration_ratio=Decimal("0.25"),
            leveraged=True, liquidity="locked", evidence_ids=("note",),
        ),),
        "related_party_roster_complete": True,
        "related_party_transactions": (RelatedPartyTransaction(
            transaction_id="rp-sale", counterparty_identity="關係企業乙",
            relationship="同一最終控制者", transaction_type="sale",
            amount=_f("50"), benchmark_terms="付款期較一般客戶長90日",
            commercial_rationale="集團通路", settlement_status="overdue",
            original_document_evidence_ids=("event", "note"),
        ),),
        "funding_roster_complete": True,
        "related_party_funding": (RelatedPartyFunding(
            funding_id="loan-1", counterparty_identity="關係企業乙",
            relationship="同一最終控制者", purpose="營運週轉", amount=_f("40"),
            interest_rate=Decimal("0.01"), limit=_f("50"), overdue=True,
            collateral="無", recoverability="對手方持續虧損", evidence_ids=("event", "note"),
        ),),
        "guarantee_roster_complete": True,
        "guarantees": (GuaranteeExposure(
            guarantee_id="g-1", counterparty_identity="關係企業乙", relationship="子公司",
            amount=_f("70"), expiry="2027-12-31", amount_drawn=_f("30"),
            recourse="有限追索", counterparty_financial_condition="虧損",
            evidence_ids=("event", "note"),
        ),),
        "share_structure": ShareStructure(
            issued_shares=_f("1000"), basic_weighted_average_shares=_f("980"),
            diluted_weighted_average_shares=_f("1020"), fully_diluted_exposure=_f("1250"),
            instruments=(
                DilutiveInstrument("cb", "convertible_bond", _f("150"), "轉換價與到期賣回完整", ("terms",)),
                DilutiveInstrument("option", "option", _f("100"), "履約價與歸屬期完整", ("terms",)),
            ), roster_complete=True,
        ),
        "capital_allocation_roster_complete": True,
        "capital_allocation_decisions": (CapitalAllocationDecision(
            decision_id="capex-1", decision_type="capex", lifecycle="completed",
            amount=_f("200"), purpose="擴產", announced_at="2025-02-01T18:00:00+08:00",
            effective_at="2025-06-01", follow_up_roic=Decimal("0.04"),
            official_event_evidence_id="event", original_document_evidence_id="terms",
            note_evidence_id="note",
        ),),
        "citations": (_citation(), _citation("event"), _citation("terms")),
    }
    values.update(overrides)
    return assess_impairment_capital_risk(**values)  # type: ignore[arg-type]


def test_triggered_rows_require_models_terms_identities_and_official_documents() -> None:
    result = _complete()
    assert set(result.by_check_id) == {f"R{i:02d}" for i in range(29, 37)}
    assert all(row.status == "evaluated" for row in result.checks)
    assert all(row.applicability == "triggered" for row in result.checks)
    assert "安全空間=5" in " ".join(result.by_check_id["R30"].observations)
    assert "稼動率=0.40" in " ".join(result.by_check_id["R31"].observations)
    assert "付款期較一般客戶" in " ".join(result.by_check_id["R34"].observations)
    assert result.shareholder_dilution_and_capital_allocation is not None
    dilution = result.shareholder_dilution_and_capital_allocation
    assert "期末已發行股數=1000" in dilution.current_evidence[0]
    assert "基本加權平均股數=980" in dilution.current_evidence[0]
    assert "稀釋加權平均股數=1020" in dilution.current_evidence[0]
    assert "完全稀釋暴險=1250" in dilution.current_evidence[0]
    assert all(row.monitoring_date == MONITOR for row in result.checks)


def test_complete_bounded_rosters_can_evaluate_not_triggered_without_claiming_one_number_is_safe() -> None:
    zero = _f("0")
    result = _complete(
        prior_goodwill=_f("100"), current_goodwill=_f("100"),
        prior_intangibles=_f("25"), current_intangibles=_f("25"),
        impairment_models=(replace(_model(), headroom=Decimal("50"), kam=False,
                                   performance_vs_acquisition_case="達成原收購案例"),),
        ppe_exposures=(PpeExposure("fab", _f("500"), Decimal("0.90"), zero, False, None,
                                   "已有訂單支持", ("note",)),),
        equity_method_exposures=(), financial_asset_exposures=(),
        related_party_transactions=(), related_party_funding=(), guarantees=(),
    )
    assert all(row.status == "evaluated" for row in result.checks)
    assert all(row.applicability in {"not_triggered", "not_applicable"} for row in result.checks)
    assert "單一數值" in " ".join(result.by_check_id["R30"].buffers)


def test_missing_models_terms_identities_periods_or_original_filings_stay_unresolved() -> None:
    incomplete_share = replace(
        _complete().share_structure,  # type: ignore[arg-type]
        instruments=(DilutiveInstrument("cb", "convertible_bond", _f("150"), None, ("terms",)),),
        roster_complete=False,
    )
    result = _complete(
        impairment_roster_complete=False, impairment_models=(),
        ppe_roster_complete=False, ppe_exposures=(),
        equity_method_roster_complete=False, equity_method_exposures=(),
        financial_asset_roster_complete=False, financial_asset_exposures=(),
        related_party_roster_complete=False,
        related_party_transactions=(RelatedPartyTransaction(
            "rp", "", "", "sale", _f("1"), None, None, None, (),
        ),),
        funding_roster_complete=False, related_party_funding=(),
        guarantee_roster_complete=False, guarantees=(),
        share_structure=incomplete_share,
        capital_allocation_roster_complete=False,
        capital_allocation_decisions=(CapitalAllocationDecision(
            "raise", "cash_raise", "authorized", _f("100"), "補充營運資金",
            "2026-01-01T18:00:00+08:00", None, None, "event", None, None,
        ),),
    )
    assert all(row.status == "unresolved" for row in result.checks)
    assert "原始文件" in " ".join(result.by_check_id["R34"].unresolved_reasons)
    assert result.shareholder_dilution_and_capital_allocation is None
    assert any("完全稀釋" in item for item in result.limitations)
    assert any("資本配置" in item for item in result.limitations)
