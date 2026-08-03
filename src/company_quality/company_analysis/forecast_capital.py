"""Formal-forecast, dividend, and capital-allocation checklist evidence.

Formal forecasts are distinct from ordinary issuer guidance.  Capital proposals
and authorizations remain distinct from completed events.  Missing filings,
financial capacity facts, terms, or transaction history fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation


@dataclass(frozen=True, slots=True)
class FormalForecast:
    forecast_id: str
    fiscal_period: str
    period_basis: Literal["single_period", "year_to_date", "annual"]
    metric: str
    lower: Decimal
    upper: Decimal
    revision_sequence: int
    announced_at: str
    source_window_evidence_id: str
    original_filing_evidence_id: str | None


@dataclass(frozen=True, slots=True)
class ActualResult:
    fiscal_period: str
    period_basis: Literal["single_period", "year_to_date", "annual"]
    metric: str
    value: Decimal
    evidence_id: str


@dataclass(frozen=True, slots=True)
class DividendResolution:
    dividend_id: str
    fiscal_period: str
    lifecycle: Literal["proposed", "approved", "paid"]
    proposal_date: str
    approval_date: str | None
    payment_date: str | None
    cash_dividend: Decimal
    capital_reserve_dividend: Decimal
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FinancialCapacity:
    fiscal_period: str
    operating_cash_flow: Decimal | None
    capex: Decimal | None
    net_income: Decimal | None
    debt: Decimal | None
    cash: Decimal | None
    investment_need: Decimal | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapitalEvent:
    event_id: str
    event_type: Literal[
        "acquisition", "cash_raise", "convertible_bond", "share_award", "buyback"
    ]
    lifecycle: Literal["proposed", "authorized", "completed"]
    announced_at: str
    effective_at: str | None
    amount: Decimal | None
    mops_event_evidence_id: str | None
    prospectus_evidence_id: str | None
    note_evidence_id: str | None
    conversion_terms_evidence_id: str | None = None
    transaction_history_evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class ForecastDividendCapitalAssessment:
    checks: tuple[ChecklistCheckResult, ...]
    limitations: tuple[str, ...]
    citations: tuple[EvidenceCitation, ...] = ()

    @property
    def by_check_id(self) -> dict[str, ChecklistCheckResult]:
        return {item.check_id: item for item in self.checks}


def _row(
    check_id: str,
    domain: Literal["growth", "risk"],
    *,
    applicability: Literal["triggered", "not_triggered", "not_applicable", "unresolved"],
    status: Literal["evaluated", "unresolved"],
    observations: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    period: str | None = None,
    first_detectable_at: str | None = None,
    severity: Literal["low", "medium", "high", "critical", "not_applicable"] = "not_applicable",
) -> ChecklistCheckResult:
    triggered = applicability == "triggered"
    monitoring = {
        "G25": ("正式財測修正序號", "同期間同口徑Actual", "命中率"),
        "G24": ("核准現金股利", "OCF", "CAPEX", "FCF", "淨利", "淨負債", "投資需求"),
        "R46": ("現金股利", "FCF", "有息負債", "現金", "投資需求"),
        "G21": ("收購生效日", "有機營收", "商譽", "被收購事業實績"),
        "R47": ("收購對價", "商譽", "負債", "股數", "整合實績"),
        "R43": ("增資完成日", "公開說明書用途", "後續ROIC"),
        "R44": ("轉換價", "賣回權", "到期日", "實際轉換歷史"),
        "R45": ("股份給付條件", "費用", "實際稀釋歷史"),
        "R48": ("實際買回股數", "註銷", "借款", "回購價格"),
    }[check_id]
    return ChecklistCheckResult(
        check_id=check_id,
        domain=domain,
        applicability=applicability,
        status=status,
        first_detectable_at=first_detectable_at,
        financial_period=period,
        observations=observations,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        supporting_evidence=("已取得題目所需權威證據鏈。",) if status == "evaluated" and triggered else (),
        counterevidence=("已檢查但未達觸發條件。",) if status == "evaluated" and not triggered else (),
        inference_chain=(
            "官方來源視窗 → 原始申報／決議／交易文件 → 同期間canonical facts",
        ) if status == "evaluated" else (),
        mechanism="僅依已完成且可追溯的事件與同期間財務事實判定。",
        leading_warnings=monitoring,
        buffers=("提案、授權或公告不視為已完成事件。",),
        monitoring_metrics=monitoring,
        monitoring_date=None,
        invalidation_or_resolution_conditions=("新申報、決議、付款或完成交易證據更新本題。",),
        severity=severity,
        confidence="high" if status == "evaluated" else "low",
        unresolved_reasons=reasons,
    )


def _unresolved(check_id: str, domain: Literal["growth", "risk"], *reasons: str) -> ChecklistCheckResult:
    return _row(
        check_id,
        domain,
        applicability="unresolved",
        status="unresolved",
        reasons=tuple(reasons) or ("權威證據不足。",),
    )


def _event_evidence(event: CapitalEvent) -> tuple[str, ...]:
    return tuple(
        item
        for item in (
            event.mops_event_evidence_id,
            event.prospectus_evidence_id,
            event.note_evidence_id,
            event.conversion_terms_evidence_id,
            event.transaction_history_evidence_id,
        )
        if item
    )


def assess_forecast_dividend_capital(
    *,
    forecast_window_status: Literal["available", "unresolved"],
    bounded_no_formal_forecast: bool = False,
    formal_forecasts: tuple[FormalForecast, ...] = (),
    actuals: tuple[ActualResult, ...] = (),
    ordinary_guidance_evidence_ids: tuple[str, ...] = (),
    dividends: tuple[DividendResolution, ...] = (),
    financial_capacity: tuple[FinancialCapacity, ...] = (),
    capital_events: tuple[CapitalEvent, ...] = (),
    capital_history_complete: bool = False,
    citations: tuple[EvidenceCitation, ...] = (),
) -> ForecastDividendCapitalAssessment:
    """Evaluate only exact evidence families; ordinary guidance is never G25."""

    del ordinary_guidance_evidence_ids  # Explicitly separate and intentionally not admitted.
    rows: dict[str, ChecklistCheckResult] = {
        "G25": _unresolved("G25", "growth", "正式財測來源視窗或原始申報尚未完成。"),
        "G24": _unresolved("G24", "growth", "股利決議或現金能力證據尚未完整。"),
        "G21": _unresolved("G21", "growth", "併購完成與後續財報證據尚未完整。"),
        "R43": _unresolved("R43", "risk", "現金增資完成、公開說明書及附註證據尚未完整。"),
        "R44": _unresolved("R44", "risk", "可轉債條件、附註及轉換歷史尚未完整。"),
        "R45": _unresolved("R45", "risk", "股份給付條件、附註及稀釋歷史尚未完整。"),
        "R46": _unresolved("R46", "risk", "股利、CAPEX、負債或自由現金流證據尚未完整。"),
        "R47": _unresolved("R47", "risk", "收購完成與企業合併附註尚未完整。"),
        "R48": _unresolved("R48", "risk", "庫藏股實際交易、附註或註銷歷史尚未完整。"),
    }

    if forecast_window_status == "available" and bounded_no_formal_forecast and not formal_forecasts:
        rows["G25"] = _row(
            "G25", "growth", applicability="not_applicable", status="evaluated",
            observations=("本次有界正式財測來源視窗未見該公司可用正式財測；不以一般法說指引替代。",),
        )
    elif formal_forecasts:
        missing_filing = [item for item in formal_forecasts if not item.original_filing_evidence_id]
        if missing_filing:
            rows["G25"] = _unresolved("G25", "growth", "缺少原始正式財測申報，來源視窗不可單獨完成判定。")
        else:
            matched: list[tuple[FormalForecast, ActualResult]] = []
            for forecast in formal_forecasts:
                actual = next(
                    (
                        item for item in actuals
                        if (item.fiscal_period, item.period_basis, item.metric)
                        == (forecast.fiscal_period, forecast.period_basis, forecast.metric)
                    ),
                    None,
                )
                if actual is not None:
                    matched.append((forecast, actual))
            if len(matched) != len(formal_forecasts):
                rows["G25"] = _unresolved("G25", "growth", "缺少同期間、同單期／累計口徑Actual。")
            else:
                observations = tuple(
                    f"{forecast.fiscal_period}/{forecast.period_basis}/{forecast.metric} "
                    f"正式財測{forecast.lower}~{forecast.upper}；Actual={actual.value}；"
                    f"{'命中' if forecast.lower <= actual.value <= forecast.upper else '未命中'}。"
                    for forecast, actual in matched
                )
                evidence = tuple(
                    item
                    for forecast, actual in matched
                    for item in (
                        forecast.source_window_evidence_id,
                        forecast.original_filing_evidence_id,
                        actual.evidence_id,
                    )
                    if item
                )
                rows["G25"] = _row(
                    "G25", "growth", applicability="triggered", status="evaluated",
                    observations=observations, evidence_ids=evidence,
                    period=matched[-1][0].fiscal_period,
                    first_detectable_at=matched[-1][0].announced_at,
                )

    approved = [item for item in dividends if item.lifecycle in {"approved", "paid"} and item.approval_date]
    if dividends and len(approved) != len(dividends):
        rows["G24"] = _unresolved("G24", "growth", "股利仍為提案，不能當成已核准或已支付。")
        rows["R46"] = _unresolved("R46", "risk", "股利仍為提案，不能當成已核准或已支付。")
    elif len(approved) >= 2:
        latest = approved[-1]
        capacity = next((item for item in financial_capacity if item.fiscal_period == latest.fiscal_period), None)
        complete_capacity = capacity is not None and all(
            value is not None
            for value in (
                capacity.operating_cash_flow,
                capacity.capex,
                capacity.net_income,
                capacity.debt,
                capacity.cash,
                capacity.investment_need,
            )
        ) and bool(capacity.evidence_ids)
        if not complete_capacity:
            rows["G24"] = _unresolved("G24", "growth", "缺少OCF、CAPEX、FCF、淨利、負債、現金或投資需求。")
            rows["R46"] = _unresolved("R46", "risk", "缺少OCF、CAPEX、FCF、淨利、負債、現金或投資需求。")
        else:
            assert capacity is not None and capacity.operating_cash_flow is not None
            assert capacity.capex is not None and capacity.investment_need is not None
            assert capacity.net_income is not None and capacity.debt is not None
            assert capacity.cash is not None
            previous_total = approved[-2].cash_dividend + approved[-2].capital_reserve_dividend
            latest_total = latest.cash_dividend + latest.capital_reserve_dividend
            fcf = capacity.operating_cash_flow - abs(capacity.capex)
            cash_after_investment = fcf - capacity.investment_need
            net_debt = capacity.debt - capacity.cash
            evidence = (*approved[-2].evidence_ids, *latest.evidence_ids, *capacity.evidence_ids)
            observation = (
                f"核准現金股利由{previous_total}增至{latest_total}；其中資本公積"
                f"{latest.capital_reserve_dividend}；OCF={capacity.operating_cash_flow}、"
                f"CAPEX={capacity.capex}、簡化FCF={fcf}、投資後現金能力={cash_after_investment}、"
                f"淨利={capacity.net_income}、淨負債={net_debt}、投資需求={capacity.investment_need}。"
            )
            rows["G24"] = _row(
                "G24", "growth",
                applicability="triggered" if latest_total > previous_total else "not_triggered",
                status="evaluated", observations=(observation,), evidence_ids=evidence,
                period=latest.fiscal_period,
            )
            insufficient = (
                latest_total > cash_after_investment
                or latest_total > capacity.net_income
                or (net_debt > 0 and latest_total > capacity.cash)
            )
            rows["R46"] = _row(
                "R46", "risk",
                applicability="triggered" if insufficient else "not_triggered",
                status="evaluated", observations=(observation,), evidence_ids=evidence,
                period=latest.fiscal_period, severity="high" if insufficient else "low",
            )

    def assess_event(
        event_type: str,
        check_id: str,
        domain: Literal["growth", "risk"],
        required: tuple[str, ...],
    ) -> None:
        candidates = [item for item in capital_events if item.event_type == event_type]
        if not candidates:
            if capital_history_complete:
                rows[check_id] = _row(
                    check_id, domain, applicability="not_triggered", status="evaluated",
                    observations=("完整有界事件歷史未見本題事件。",),
                )
            return
        latest = candidates[-1]
        missing: list[str] = []
        if latest.lifecycle != "completed" or not latest.effective_at:
            missing.append("事件僅為提案／授權／公告，尚無完成證據")
        labels = {
            "mops_event_evidence_id": "MOPS事件",
            "prospectus_evidence_id": "公開說明書",
            "note_evidence_id": "財報附註",
            "conversion_terms_evidence_id": "轉換條件",
            "transaction_history_evidence_id": "實際交易／轉換歷史",
        }
        missing.extend(labels[field] for field in required if not getattr(latest, field))
        if missing:
            rows[check_id] = _unresolved(check_id, domain, "、".join(missing) + "尚未取得。")
            return
        rows[check_id] = _row(
            check_id, domain, applicability="triggered", status="evaluated",
            observations=(
                f"{latest.event_type}已完成；公告日{latest.announced_at}、生效日{latest.effective_at}、"
                f"金額{latest.amount if latest.amount is not None else '未揭露'}。",
            ),
            evidence_ids=_event_evidence(latest),
            first_detectable_at=latest.announced_at,
            severity="medium" if domain == "risk" else "not_applicable",
        )

    assess_event("cash_raise", "R43", "risk", ("mops_event_evidence_id", "prospectus_evidence_id", "note_evidence_id"))
    assess_event("convertible_bond", "R44", "risk", (
        "mops_event_evidence_id", "prospectus_evidence_id", "note_evidence_id",
        "conversion_terms_evidence_id", "transaction_history_evidence_id",
    ))
    assess_event("share_award", "R45", "risk", (
        "mops_event_evidence_id", "note_evidence_id", "conversion_terms_evidence_id",
        "transaction_history_evidence_id",
    ))
    assess_event("buyback", "R48", "risk", (
        "mops_event_evidence_id", "note_evidence_id", "transaction_history_evidence_id",
    ))
    assess_event("acquisition", "R47", "risk", ("mops_event_evidence_id", "note_evidence_id"))
    assess_event("acquisition", "G21", "growth", ("mops_event_evidence_id", "note_evidence_id"))

    ordered = ("G21", "G24", "G25", "R43", "R44", "R45", "R46", "R47", "R48")
    limitations = tuple(
        dict.fromkeys(reason for item in rows.values() for reason in item.unresolved_reasons)
    )
    cited_ids = {item.evidence_id for item in citations}
    if citations:
        referenced = {
            evidence_id
            for item in rows.values()
            for evidence_id in item.evidence_ids
        }
        missing_citations = sorted(referenced - cited_ids)
        if missing_citations:
            raise ValueError(
                "forecast/capital checks cite missing report evidence: "
                + ",".join(missing_citations)
            )
    return ForecastDividendCapitalAssessment(
        tuple(rows[item] for item in ordered), limitations, citations
    )


__all__ = [
    "ActualResult",
    "CapitalEvent",
    "DividendResolution",
    "FinancialCapacity",
    "ForecastDividendCapitalAssessment",
    "FormalForecast",
    "assess_forecast_dividend_capital",
]
