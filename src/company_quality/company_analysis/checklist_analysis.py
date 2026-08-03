"""Build the authoritative checklist view without upgrading missing evidence to safety."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Iterable, Literal

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.company_analysis.checklist_contracts import (
    AUDIT_CHECK_IDS,
    GROWTH_CHECK_IDS,
    GROWTH_DIMENSIONS,
    GROWTH_TRANSMISSION_STAGES,
    INDUSTRY_CHECK_IDS,
    NOTE_CHECK_IDS,
    REQUIRED_COMPLETION_ITEMS,
    RISK_CHECK_IDS,
    RISK_DIMENSIONS,
    AnalysisBasisRecord,
    ChecklistAssessment,
    ChecklistCheckResult,
    ChecklistCoverage,
    CompanyRoute,
    FinancialOverview,
    IndustryRoute,
    GrowthConclusion,
    GrowthTransmissionStage,
    RiskConclusion,
)
from company_quality.company_analysis.contracts import FinancialDeteriorationSection
from company_quality.company_analysis.checklist_metrics import build_financial_overview
from company_quality.company_analysis.checklist_evidence import (
    collect_checklist_document_evidence,
)
from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle
from company_quality.company_analysis.esg_supply_chain import EsgLegalEvidence
from company_quality.company_analysis.forecast_capital import (
    ForecastDividendCapitalAssessment,
)

if TYPE_CHECKING:
    from company_quality.sources.governance_insiders import GovernanceEvidenceCollection
    from company_quality.company_analysis.working_capital_risk import WorkingCapitalRiskEvidence


_CANONICAL_GROWTH_METRICS = {
    "revenue_momentum": ("revenue", "營收趨勢"),
    "margin_and_product_mix": ("gross_margin", "毛利率趨勢"),
    "operating_leverage": ("operating_margin", "營業利益率趨勢"),
    "earnings_quality": ("cfo_to_net_income", "CFO／淨利品質"),
    "cash_conversion": ("cash_conversion_cycle_days", "現金轉換週期"),
    "reinvestment_and_roic": ("roic", "ROIC"),
    "per_share_value_and_dilution": ("diluted_eps", "稀釋每股盈餘"),
}
_CANONICAL_RISK_METRICS = {
    "liquidity_and_refinancing": ("current_ratio", ("流動比率", "一年內到期債務")),
    "receivables_and_collection": ("dso_days", ("平均餘額DSO", "應收成長相對營收")),
    "inventory_and_impairment": ("inventory_days", ("平均存貨週轉天數", "跌價損失")),
    "contract_assets_and_revenue_recognition": ("contract_assets", ("合約資產", "收入認列政策")),
    "earnings_quality": ("cfo_to_net_income", ("CFO／淨利", "自由現金流")),
    "shareholder_dilution_and_capital_allocation": (
        "common_stock_capital", ("股本", "完全稀釋股數")
    ),
}


@dataclass(frozen=True, slots=True)
class PeerFinancialComparison:
    """Same-market, exact-official-industry comparison from MOPS facts."""

    status: Literal["available", "partial", "blocked"]
    current_period: str | None
    prior_period: str | None
    peer_security_codes: tuple[str, ...]
    target_inventory_change: Decimal | None
    peer_median_inventory_change: Decimal | None
    target_revenue_change: Decimal | None
    peer_median_revenue_change: Decimal | None
    evidence_ids: tuple[str, ...]
    source_urls: tuple[str, ...]
    unresolved_reasons: tuple[str, ...]


def _direction(value: Decimal) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _percent(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value:.2%}"


def _apply_peer_financial_comparison(
    checks: tuple[ChecklistCheckResult, ...],
    comparison: PeerFinancialComparison | None,
) -> tuple[ChecklistCheckResult, ...]:
    rows = {item.check_id: item for item in checks}
    if "I-MFG-07" not in rows or comparison is None or comparison.status != "available":
        return checks
    if (
        comparison.target_inventory_change is None
        or comparison.peer_median_inventory_change is None
        or not comparison.evidence_ids
    ):
        return checks
    diverges = _direction(comparison.target_inventory_change) != _direction(
        comparison.peer_median_inventory_change
    )
    observation = (
        f"{comparison.current_period}較{comparison.prior_period}：公司存貨"
        f"{_percent(comparison.target_inventory_change)}、同市場同官方產業同業中位數"
        f"{_percent(comparison.peer_median_inventory_change)}；公司營收"
        f"{_percent(comparison.target_revenue_change)}、同業營收中位數"
        f"{_percent(comparison.peer_median_revenue_change)}。"
    )
    rows["I-MFG-07"] = ChecklistCheckResult(
        check_id="I-MFG-07",
        domain="industry",
        applicability="triggered" if diverges else "not_triggered",
        status="evaluated",
        first_detectable_at=None,
        financial_period=comparison.current_period,
        observations=(observation,),
        evidence_ids=comparison.evidence_ids,
        supporting_evidence=("已取得同市場、同官方產業分類同業的同期間MOPS canonical facts。",),
        counterevidence=((
            "公司與同業存貨方向相反，可能是公司特有因素。"
            if diverges
            else "公司與同業存貨方向一致，仍須結合公司營收與跌價證據。"
        ),),
        inference_chain=("官方產業身分 → 同期間MOPS財務facts → 同業中位數 → 公司對照",),
        mechanism="公司存貨若與同業方向背離，可能反映公司特有備貨、去化或產品週期差異。",
        leading_warnings=("公司存貨年增率", "同業存貨年增率中位數", "公司與同業營收年增率"),
        buffers=("同業比較只作公司特有與產業共同因素辨識，不單獨證明存貨安全。",),
        monitoring_metrics=("存貨年增率", "營收年增率", "存貨週轉天數", "跌價損失"),
        monitoring_date=None,
        invalidation_or_resolution_conditions=("同業樣本少於3家、官方產業分類或同期間口徑改變。",),
        severity="medium" if diverges else "low",
        confidence="medium",
        unresolved_reasons=(),
    )
    return tuple(rows[item.check_id] for item in checks)


def _ids(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        candidates = (
            getattr(value, "artifact_id", None),
            getattr(value, "filing_id", None),
            getattr(value, "evidence_id", None),
            *(getattr(value, "evidence_ids", ()) or ()),
        )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate and candidate not in result:
                result.append(candidate)
    return tuple(result)


def _financial_artifacts(bundle: CompanyEvidenceBundle) -> tuple[object, ...]:
    return tuple(
        artifact
        for period in bundle.periods
        if period.financial is not None
        for artifact in period.financial.artifacts
    )


def _audit_artifacts(bundle: CompanyEvidenceBundle) -> tuple[object, ...]:
    return tuple(
        period.audit
        for period in bundle.periods
        if period.audit is not None and period.audit.pdf_path is not None
    )


def _annual_audit_filings(
    bundle: CompanyEvidenceBundle,
) -> tuple[AuditFilingInventory, ...]:
    return tuple(
        period.audit
        for period in bundle.periods
        if period.is_annual
        and period.audit is not None
        and period.audit.pdf_path is not None
        and period.audit.pdf_sha256 is not None
        and period.audit.pdf_source_url is not None
    )


def _complete(item_id: str, evidence_ids: tuple[str, ...]) -> ChecklistCoverage:
    return ChecklistCoverage(item_id, "complete", evidence_ids)


def _unresolved(item_id: str, reason: str) -> ChecklistCoverage:
    return ChecklistCoverage(item_id, "unresolved", (), reason)


def _growth_unresolved(dimension: str, reason: str) -> GrowthConclusion:
    return GrowthConclusion(
        dimension=dimension,
        judgement="unresolved",
        core_numbers=(),
        evidence_ids=(),
        counterevidence=(),
        unresolved_items=(reason,),
        invalidation_conditions=(),
        monitoring_metrics=(),
        confidence="low",
    )


def _growth_resolved(
    dimension: str,
    judgement: str,
    core_numbers: tuple[str, ...],
    evidence_ids: tuple[str, ...],
) -> GrowthConclusion:
    return GrowthConclusion(
        dimension=dimension,
        judgement=judgement,  # type: ignore[arg-type]
        core_numbers=core_numbers,
        evidence_ids=evidence_ids,
        counterevidence=("其他成長鏈環節仍須獨立驗證。",),
        unresolved_items=(),
        invalidation_conditions=("後續同口徑指標反轉時失效。",),
        monitoring_metrics=core_numbers,
        confidence="medium",
    )


def _risk_unresolved(dimension: str, reason: str) -> RiskConclusion:
    return RiskConclusion(
        dimension=dimension,
        judgement="unresolved",
        mechanism="證據不足，不能推論沒有風險。",
        leading_warnings=(),
        current_evidence=(),
        evidence_ids=(),
        buffers_and_counterevidence=(),
        stress_transmission=(),
        resolution_conditions=(),
        unresolved_items=(reason,),
        monitoring_metrics=(),
        confidence="low",
    )


def _risk_resolved(
    dimension: str,
    judgement: str,
    evidence: str,
    evidence_ids: tuple[str, ...],
    monitoring: tuple[str, ...],
) -> RiskConclusion:
    return RiskConclusion(
        dimension=dimension,
        judgement=judgement,  # type: ignore[arg-type]
        mechanism=evidence,
        leading_warnings=monitoring,
        current_evidence=(evidence,),
        evidence_ids=evidence_ids,
        buffers_and_counterevidence=("須與附註及後續期間交叉驗證。",),
        stress_transmission=("若趨勢惡化，可能傳導至現金流、融資或獲利。",),
        resolution_conditions=("同口徑指標改善且附註無新增重大風險。",),
        unresolved_items=(),
        monitoring_metrics=monitoring,
        confidence="medium",
    )


def _judgement(metric: object) -> str:
    direction = getattr(metric, "direction", "mixed")
    return {
        "improving": "improving",
        "deteriorating": "deteriorating",
        "flat": "stable",
        "mixed": "unresolved",
    }[direction]


def _metrics(
    section: FinancialDeteriorationSection | None,
) -> dict[str, object]:
    if section is None or not section.periods:
        return {}
    return {item.metric_id: item for item in section.periods[-1].metrics}


def _basis_records(bundle: CompanyEvidenceBundle) -> tuple[AnalysisBasisRecord, ...]:
    records: list[AnalysisBasisRecord] = []
    for period in bundle.periods:
        if period.financial is not None:
            for artifact in period.financial.artifacts:
                canonical = (
                    period.canonical_financial.facts
                    if period.canonical_financial is not None
                    else ()
                )
                artifact_has_canonical_facts = any(
                    fact.source_artifact_id == artifact.artifact_id for fact in canonical
                )
                records.append(
                    AnalysisBasisRecord(
                        period=artifact.period,
                        statement=artifact.report,
                        consolidation_scope=artifact.statement_scope,
                        period_basis=artifact.period_basis,
                        assurance="unaudited",
                        currency="TWD" if artifact_has_canonical_facts else None,
                        unit="TWD_thousands" if artifact_has_canonical_facts else None,
                        restatement_status="unknown",
                        report_date=None,
                        filed_at=None,
                        available_at=artifact.available_at,
                        evidence_ids=(artifact.artifact_id,),
                    )
                )
        if period.audit is not None and period.audit.pdf_path is not None:
            records.append(
                AnalysisBasisRecord(
                    period=period.period,
                    statement="audit_report",
                    consolidation_scope=period.audit.report_scope,
                    period_basis="annual" if period.is_annual else "not_applicable",
                    assurance="audit" if period.is_annual else "review",
                    currency=None,
                    unit=None,
                    restatement_status="unknown",
                    report_date=period.audit.auditor_report_at,
                    filed_at=period.audit.official_filed_at,
                    available_at=period.audit.available_at,
                    evidence_ids=period.audit.evidence_ids,
                )
            )
    records.extend(
        AnalysisBasisRecord(
            period=item.month,
            statement="monthly_revenue",
            consolidation_scope="consolidated",
            period_basis="single_period",
            assurance="unaudited",
            currency="TWD",
            unit="thousand_twd",
            restatement_status="unknown",
            report_date=None,
            filed_at=None,
            available_at=item.available_at,
            evidence_ids=(item.artifact_id,),
        )
        for item in bundle.monthly_revenue
    )
    return tuple(records)


def _canonical_period_complete(period: object) -> bool:
    canonical = getattr(period, "canonical_financial", None)
    financial = getattr(period, "financial", None)
    required = {
        "balance.cash_and_cash_equivalents",
        "balance.accounts_receivable_net",
        "balance.inventories",
        "balance.current_assets",
        "balance.current_liabilities",
        "balance.total_assets",
        "balance.total_liabilities",
        "balance.total_equity",
        "income.revenue",
        "income.gross_profit",
        "income.operating_income",
        "income.net_income",
        "cash_flow.operating_cash_flow",
        "cash_flow.acquisition_of_ppe",
        "equity.common_stock",
        "equity.total_equity",
    }
    values = (
        {item.concept_id: item.value for item in canonical.facts}
        if canonical is not None
        else {}
    )
    return bool(
        canonical is not None
        and all(values.get(item) is not None for item in required)
        and financial is not None
        and len(financial.artifacts) == 4
        and all(item.statement_scope != "unknown" for item in financial.artifacts)
    )


def _equity_cross_check_complete(period: object) -> bool:
    canonical = getattr(period, "canonical_financial", None)
    if canonical is None:
        return False
    values = {item.concept_id: item.value for item in canonical.facts}
    balance = values.get("balance.total_equity")
    equity = values.get("equity.total_equity")
    return balance is not None and equity is not None and balance == equity


def _industry_route(bundle: CompanyEvidenceBundle, route: CompanyRoute) -> IndustryRoute:
    if route != "general_non_financial":
        return "financial"
    code = bundle.identity.industry_code
    if code == "30":
        return "software_ai"
    if code == "22":
        return "biotech"
    if code == "23":
        return "energy"
    if code in {"01", "02", "03", "04", "05", "06", "08", "09", "10", "11", "12", "21", "24", "25", "26", "27", "28", "31"}:
        return "manufacturing_hardware"
    if code in {"14"}:
        return "unresolved"
    return "not_applicable"


def _placeholder_checks(
    reason: str,
    industry_route: IndustryRoute = "not_applicable",
) -> tuple[ChecklistCheckResult, ...]:
    def row(check_id: str, domain: str) -> ChecklistCheckResult:
        return ChecklistCheckResult(
            check_id=check_id,
            domain=domain,  # type: ignore[arg-type]
            applicability="unresolved",
            status="unresolved",
            first_detectable_at=None,
            financial_period=None,
            observations=(),
            evidence_ids=(),
            supporting_evidence=(),
            counterevidence=(),
            inference_chain=(),
            mechanism=None,
            leading_warnings=(),
            buffers=(),
            monitoring_metrics=(),
            monitoring_date=None,
            invalidation_or_resolution_conditions=(),
            severity="not_applicable",
            confidence="low",
            unresolved_reasons=(reason,),
        )
    return (
        *(row(item, "growth") for item in GROWTH_CHECK_IDS),
        *(row(item, "risk") for item in RISK_CHECK_IDS),
        *(row(item, "note") for item in NOTE_CHECK_IDS),
        *(row(item, "audit") for item in AUDIT_CHECK_IDS),
        *(row(item, "industry") for item in INDUSTRY_CHECK_IDS.get(industry_route, ())),
    )


def _overview_metric(overview: FinancialOverview | None, metric_id: str):
    if overview is None:
        return None
    return next((item for item in overview.metrics if item.metric_id == metric_id), None)


def _quantitative_checks(
    overview: FinancialOverview | None,
    unresolved_reason: str,
    industry_route: IndustryRoute = "not_applicable",
) -> tuple[ChecklistCheckResult, ...]:
    rows = {
        item.check_id: item
        for item in _placeholder_checks(unresolved_reason, industry_route)
    }

    def comparison(metric_ids: tuple[str, ...]):
        metrics = {item: _overview_metric(overview, item) for item in metric_ids}
        if any(item is None for item in metrics.values()) or overview is None:
            return None
        by_metric = {
            metric_id: {
                value.period: value
                for value in metric.values
                if value.status == "available"
            }
            for metric_id, metric in metrics.items()
            if metric is not None
        }
        common = [
            period
            for period in overview.periods
            if all(period in values for values in by_metric.values())
        ]
        if len(common) < 2:
            return None
        previous_period, latest_period = common[-2:]
        previous = {item: values[previous_period] for item, values in by_metric.items()}
        latest = {item: values[latest_period] for item, values in by_metric.items()}
        return previous_period, latest_period, previous, latest

    def evidence(previous: dict[str, Any], latest: dict[str, Any]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item
                for value in (*previous.values(), *latest.values())
                for item in value.evidence_ids
            )
        )

    def not_triggered(
        check_id: str,
        domain: str,
        period: str,
        observations: tuple[str, ...],
        evidence_ids: tuple[str, ...],
        monitoring: tuple[str, ...],
    ) -> None:
        rows[check_id] = ChecklistCheckResult(
            check_id=check_id, domain=domain,  # type: ignore[arg-type]
            applicability="not_triggered", status="evaluated",
            first_detectable_at=None, financial_period=period,
            observations=observations, evidence_ids=evidence_ids,
            supporting_evidence=(), counterevidence=("未達本題量化觸發條件。",),
            inference_chain=("同口徑canonical facts → 量化觸發條件",),
            mechanism="本期未觸發；新資料仍須重新檢查。",
            leading_warnings=monitoring, buffers=("目前量化條件未觸發",),
            monitoring_metrics=monitoring, monitoring_date=None,
            invalidation_or_resolution_conditions=("後續同口徑數值達觸發條件。",),
            severity="low" if domain == "risk" else "not_applicable",
            confidence="medium", unresolved_reasons=(),
        )

    def triggered(
        check_id: str,
        domain: str,
        period: str,
        observations: tuple[str, ...],
        evidence_ids: tuple[str, ...],
        monitoring: tuple[str, ...],
        reason: str,
    ) -> None:
        rows[check_id] = ChecklistCheckResult(
            check_id=check_id, domain=domain,  # type: ignore[arg-type]
            applicability="triggered", status="unresolved",
            first_detectable_at=None, financial_period=period,
            observations=observations, evidence_ids=evidence_ids,
            supporting_evidence=(), counterevidence=(),
            inference_chain=("同口徑canonical facts → 量化異常觸發",),
            mechanism="量化異常已觸發，必須完成權威文件與反證查核。",
            leading_warnings=monitoring, buffers=(), monitoring_metrics=monitoring,
            monitoring_date=None,
            invalidation_or_resolution_conditions=("完成指定附註、KAM與期後證據查核。",),
            severity="medium" if domain == "risk" else "not_applicable",
            confidence="low", unresolved_reasons=(reason,),
        )

    def value(items: dict[str, Any], metric_id: str):
        result = items[metric_id].value
        assert result is not None
        return result

    def growth(previous: dict[str, Any], latest: dict[str, Any], metric_id: str):
        base = value(previous, metric_id)
        if base <= 0:
            return None
        return value(latest, metric_id) / base - 1

    def faster_growth(
        previous: dict[str, Any], latest: dict[str, Any], left: str, right: str
    ) -> bool | None:
        left_growth = growth(previous, latest, left)
        right_growth = growth(previous, latest, right)
        if left_growth is None or right_growth is None:
            return None
        return left_growth > right_growth

    def evaluate(
        check_id: str,
        domain: str,
        metric_ids: tuple[str, ...],
        predicate: Any,
        reason: str,
        monitoring: tuple[str, ...],
    ) -> None:
        compared = comparison(metric_ids)
        if compared is None:
            return
        _, period, previous, latest = compared
        outcome = predicate(previous, latest)
        if outcome is None:
            return
        observations = tuple(
            f"{item}由{previous[item].value}變為{latest[item].value}"
            for item in metric_ids
        )
        args = (
            check_id, domain, period, observations,
            evidence(previous, latest), monitoring,
        )
        triggered(*args, reason) if outcome else not_triggered(*args)

    evaluate(
        "G01", "growth", ("revenue",),
        lambda p, l: value(l, "revenue") > value(p, "revenue"),
        "營收增加已觸發；尚須拆分數量、價格、產品組合、匯率、併購與有機成長。",
        ("營收YoY/QoQ/TTM", "月營收"),
    )
    evaluate(
        "G03", "growth", ("revenue", "gross_margin"),
        lambda p, l: value(l, "revenue") > value(p, "revenue")
        and value(l, "gross_margin") < value(p, "gross_margin"),
        "營收增而毛利率降；尚須查產品組合、成本、存貨跌價、新廠與匯率。",
        ("營收", "毛利率", "產品組合"),
    )
    evaluate(
        "G04", "growth", ("revenue", "gross_margin"),
        lambda p, l: value(l, "revenue") > value(p, "revenue")
        and value(l, "gross_margin") > value(p, "gross_margin"),
        "營收與毛利率同升；尚須排除跌價回轉、原料與匯率短期效果。",
        ("營收", "毛利率", "營業利益率", "營業現金流"),
    )
    evaluate(
        "G05", "growth", ("gross_margin", "operating_margin"),
        lambda p, l: value(l, "gross_margin") > value(p, "gross_margin")
        and value(l, "operating_margin") <= value(p, "operating_margin"),
        "毛利率改善但營益率未改善；尚須查研發、銷售、管理與股份給付。",
        ("毛利率", "營業利益率", "費用率"),
    )
    evaluate(
        "G06", "growth", ("revenue", "operating_income"),
        lambda p, l: faster_growth(p, l, "operating_income", "revenue"),
        "營業利益成長快於營收；尚須驗證固定成本攤薄及必要費用未被延後。",
        ("營收成長", "營業利益成長", "研發與費用率"),
    )
    evaluate(
        "G07", "growth", ("operating_income", "net_income"),
        lambda p, l: faster_growth(p, l, "net_income", "operating_income"),
        "淨利成長快於營業利益；尚須分離匯兌、處分、評價、投資與稅務利益。",
        ("營業利益成長", "淨利成長", "業外與稅率"),
    )
    evaluate(
        "G09", "growth",
        ("net_income", "diluted_eps", "diluted_weighted_average_shares"),
        lambda p, l: value(l, "net_income") > value(p, "net_income")
        and (
            value(l, "diluted_eps") <= value(p, "diluted_eps")
            or value(l, "diluted_weighted_average_shares")
            > value(p, "diluted_weighted_average_shares")
        ),
        "淨利增加但每股成果落後；尚須查增資、可轉債、員工認股與併購發股。",
        ("淨利", "稀釋EPS", "稀釋加權股數"),
    )
    for check_id, predicate, reason in (
        (
            "G10",
            lambda p, l: value(l, "net_income") > value(p, "net_income")
            and value(l, "operating_cash_flow") > value(p, "operating_cash_flow"),
            "OCF與淨利同步增加；尚須確認現金來自收款而非延後付款或一次性預收。",
        ),
        (
            "G11",
            lambda p, l: value(l, "net_income") > value(p, "net_income")
            and value(l, "operating_cash_flow") < value(p, "operating_cash_flow"),
            "淨利增加但OCF下降；尚須定位應收、存貨、合約資產、預付款或應付變化。",
        ),
        (
            "G12",
            lambda p, l: value(l, "operating_cash_flow") > value(p, "operating_cash_flow")
            and value(l, "net_income") <= value(p, "net_income"),
            "OCF增加但淨利未增；尚須區分收款改善與一次性營運資金釋放。",
        ),
    ):
        evaluate(
            check_id, "growth", ("net_income", "operating_cash_flow"),
            predicate, reason, ("淨利", "營業現金流", "營運資金"),
        )
    evaluate(
        "G13", "growth", ("capex",),
        lambda p, l: abs(value(l, "capex")) > abs(value(p, "capex")),
        "CAPEX增加；尚須查用途、完工日、預算、資金來源、訂單與稼動率。",
        ("CAPEX", "在建工程", "產能與稼動率"),
    )
    evaluate(
        "G22", "growth", ("roe",),
        lambda p, l: value(l, "roe") > value(p, "roe"),
        "ROE上升；尚須用利潤率、週轉、槓桿與權益變化做杜邦拆解。",
        ("ROE", "淨利率", "槓桿", "權益"),
    )
    evaluate(
        "G23", "growth", ("roic",),
        lambda p, l: value(l, "roic") > value(p, "roic"),
        "ROIC上升；尚須固定NOPAT與投入資本口徑並比較資金成本。",
        ("ROIC", "NOPAT", "投入資本"),
    )
    evaluate(
        "G24", "growth", ("cash_dividends_paid", "free_cash_flow"),
        lambda p, l: abs(value(l, "cash_dividends_paid"))
        > abs(value(p, "cash_dividends_paid")),
        "現金股利增加；尚須驗證FCF、淨利、淨負債及投資需求的可持續性。",
        ("現金股利", "FCF", "淨利", "淨負債"),
    )

    evaluate(
        "R01", "risk", ("receivables", "revenue", "dso_days", "operating_cash_flow"),
        lambda p, l: value(l, "receivables") > value(p, "receivables"),
        "應收增加已觸發；尚須完成應收帳款附註、帳齡、備抵、集中度、KAM與期後收款查核。",
        ("應收帳款相對營收", "DSO", "營業現金流"),
    )
    evaluate(
        "R02", "risk", ("contract_assets", "revenue", "operating_cash_flow"),
        lambda p, l: value(l, "contract_assets") > value(p, "contract_assets"),
        "合約資產增加；尚須查未開票原因、驗收、轉應收、減損與期後收現。",
        ("合約資產相對營收", "轉應收速度", "營業現金流"),
    )
    evaluate(
        "R03", "risk", ("inventory", "revenue", "inventory_days", "gross_margin"),
        lambda p, l: value(l, "inventory") > value(p, "inventory"),
        "存貨增加已觸發；尚須完成存貨附註、組成、庫齡、跌價、KAM與期後銷售查核。",
        ("存貨相對營收", "存貨週轉天數", "毛利率"),
    )
    evaluate(
        "R10", "risk", ("interest_bearing_debt", "cash", "operating_cash_flow"),
        lambda p, l: value(l, "interest_bearing_debt") > value(p, "interest_bearing_debt"),
        "有息負債增加；尚須拆短期借款用途、利率、幣別、擔保、到期與展期。",
        ("有息負債", "現金", "營業現金流"),
    )
    evaluate(
        "R11", "risk", ("debt_due_within_year", "cash", "operating_cash_flow"),
        lambda p, l: value(l, "debt_due_within_year") > value(p, "debt_due_within_year"),
        "一年內到期債務增加；尚須逐筆查到期日、契約、再融資與正式授信。",
        ("一年內到期債務", "現金", "營業現金流"),
    )
    evaluate(
        "R12", "risk", ("interest_bearing_debt", "capex", "roic"),
        lambda p, l: value(l, "interest_bearing_debt") > value(p, "interest_bearing_debt"),
        "長期融資風險可能觸發；尚須拆長短債、資產匹配、浮動利率與壓力情境。",
        ("有息負債", "CAPEX", "ROIC"),
    )
    evaluate(
        "R15", "risk", ("debt_ratio", "total_liabilities"),
        lambda p, l: value(l, "debt_ratio") < value(p, "debt_ratio"),
        "負債比下降；尚須確認來自還債、增資、重估或保留盈餘。",
        ("負債比", "負債絕對額", "權益來源"),
    )
    evaluate(
        "R19", "risk",
        ("revenue", "receivables", "contract_assets", "operating_cash_flow"),
        lambda p, l: value(l, "revenue") > value(p, "revenue")
        and (
            value(l, "receivables") > value(p, "receivables")
            or value(l, "contract_assets") > value(p, "contract_assets")
            or value(l, "operating_cash_flow") < value(p, "operating_cash_flow")
        ),
        "營收與收款可能背離；尚須查收入截止、驗收、退貨、應收／合約資產及期後收款。",
        ("營收", "應收", "合約資產", "營業現金流"),
    )
    evaluate(
        "R29", "risk", ("goodwill_and_intangibles",),
        lambda p, l: value(l, "goodwill_and_intangibles")
        > value(p, "goodwill_and_intangibles"),
        "商譽與無形資產增加；尚須拆企業合併、CGU、折現率、成長率與實績。",
        ("商譽與無形資產", "併購實績", "減損假設"),
    )
    evaluate(
        "R43", "risk", ("common_stock_capital", "roic"),
        lambda p, l: value(l, "common_stock_capital")
        > value(p, "common_stock_capital"),
        "股本增加；尚須確認是否現金增資、用途、股數增幅與後續ROIC。",
        ("股本", "增資用途", "ROIC"),
    )
    evaluate(
        "R46", "risk", ("cash_dividends_paid", "free_cash_flow"),
        lambda p, l: abs(value(l, "cash_dividends_paid"))
        > max(value(l, "free_cash_flow"), 0),
        "現金股利超過簡化FCF；尚須查是否由借款、出售資產或暫時營運資金波動支應。",
        ("現金股利", "FCF", "借款", "現金"),
    )
    return tuple(
        rows[item]
        for item in (
            *GROWTH_CHECK_IDS,
            *RISK_CHECK_IDS,
            *NOTE_CHECK_IDS,
            *AUDIT_CHECK_IDS,
            *INDUSTRY_CHECK_IDS.get(industry_route, ()),
        )
    )


def _document_checks(
    checks: tuple[ChecklistCheckResult, ...],
    document_evidence: object | None,
    detailed_analysis: object | None = None,
) -> tuple[ChecklistCheckResult, ...]:
    rows = {item.check_id: item for item in checks}
    for check_id, citation in getattr(document_evidence, "note_citations", ()):
        rows[check_id] = ChecklistCheckResult(
            check_id=check_id,
            domain="note",
            applicability="triggered",
            status="evaluated",
            first_detectable_at=citation.available_at,
            financial_period=citation.period,
            observations=(citation.verbatim_excerpt,),
            evidence_ids=(citation.evidence_id,),
            supporting_evidence=("已定位並讀取官方附註原文。",),
            counterevidence=(),
            inference_chain=("官方查核報告附註 → 對應最低附註類別",),
            mechanism="附註原文已納入；相關量化風險仍由對應R題判定。",
            leading_warnings=("附註內容或會計政策於後續期間變更",),
            buffers=("後續期間無重大變更且量化指標改善",),
            monitoring_metrics=(check_id,),
            monitoring_date=None,
            invalidation_or_resolution_conditions=("新一期附註取代本期原文。",),
            severity="not_applicable",
            confidence="medium",
            unresolved_reasons=(),
        )
    opinion_citations: tuple[Any, ...] = tuple(
        getattr(document_evidence, "audit_opinion_citations", ())
    )
    opinion_types: tuple[tuple[str, str], ...] = tuple(
        getattr(document_evidence, "audit_opinion_types", ())
    )
    if len(opinion_citations) == 3 and len(opinion_types) == 3:
        rows["A01_auditor_opinion"] = ChecklistCheckResult(
            check_id="A01_auditor_opinion", domain="audit", applicability="triggered",
            status="evaluated", first_detectable_at=opinion_citations[-1].available_at,
            financial_period=opinion_citations[-1].period,
            observations=tuple(f"{period}: {opinion}" for period, opinion in opinion_types),
            evidence_ids=tuple(item.evidence_id for item in opinion_citations),
            supporting_evidence=("MOPS公告意見類型與查核報告原文均已取得。",),
            counterevidence=(), inference_chain=("公告 opinion_type → PDF查核意見段",),
            mechanism="非無保留意見可能限制財報可靠性或揭露重大爭議。",
            leading_warnings=("意見類型轉差",), buffers=("連續無保留意見",),
            monitoring_metrics=("auditor_opinion_type",), monitoring_date=None,
            invalidation_or_resolution_conditions=("新年度查核意見取代目前判定。",),
            severity="high" if any(item[1] != "unmodified" for item in opinion_types) else "low",
            confidence="high", unresolved_reasons=(),
        )

    def explicit_audit_paragraph(check_id: str, citations: tuple[Any, ...], label: str) -> None:
        if not citations:
            return
        latest = citations[-1]
        rows[check_id] = ChecklistCheckResult(
            check_id=check_id, domain="audit", applicability="triggered",
            status="evaluated", first_detectable_at=latest.available_at,
            financial_period=latest.period,
            observations=tuple(item.verbatim_excerpt for item in citations),
            evidence_ids=tuple(item.evidence_id for item in citations),
            supporting_evidence=(f"查核報告明確出現{label}段落。",), counterevidence=(),
            inference_chain=(f"查核報告原文 → {label}",),
            mechanism=f"{label}可能揭露財報之外的重大不確定性或注意事項。",
            leading_warnings=(f"{label}持續或擴大",), buffers=(),
            monitoring_metrics=(label,), monitoring_date=None,
            invalidation_or_resolution_conditions=("後續查核報告明確解除或更新。",),
            severity="high", confidence="high", unresolved_reasons=(),
        )

    explicit_audit_paragraph(
        "A02_going_concern",
        getattr(document_evidence, "going_concern_citations", ()),
        "繼續經營重大不確定性",
    )
    explicit_audit_paragraph(
        "A03_emphasis_and_other_matters",
        getattr(document_evidence, "emphasis_other_citations", ()),
        "強調或其他事項",
    )
    search_complete_periods = getattr(
        document_evidence, "audit_text_search_complete_periods", ()
    )
    if len(search_complete_periods) == 3:
        search_evidence_ids = tuple(
            item.evidence_id for item in (*opinion_citations, *getattr(document_evidence, "kam_citations", ()))
        )
        for check_id, label in (
            ("A02_going_concern", "繼續經營重大不確定性"),
            ("A03_emphasis_and_other_matters", "強調或其他事項"),
        ):
            if rows[check_id].status == "evaluated":
                continue
            rows[check_id] = ChecklistCheckResult(
                check_id=check_id, domain="audit", applicability="not_triggered",
                status="evaluated", first_detectable_at=opinion_citations[-1].available_at,
                financial_period=opinion_citations[-1].period,
                observations=(f"最近三年可搜尋查核報告未命中{label}段落。",),
                evidence_ids=search_evidence_ids,
                supporting_evidence=(), counterevidence=(f"未發現{label}段落。",),
                inference_chain=("三年查核報告全文搜尋 → 未命中",),
                mechanism=f"目前沒有明確{label}訊號；不代表未來不會出現。",
                leading_warnings=(f"後續新增{label}",), buffers=("三年未見明確段落",),
                monitoring_metrics=(label,), monitoring_date=None,
                invalidation_or_resolution_conditions=(f"新報告出現{label}。",),
                severity="low", confidence="medium", unresolved_reasons=(),
            )
    kam_citations = getattr(document_evidence, "kam_citations", ())
    if len(kam_citations) == 3:
        rows["A04_three_year_kam"] = ChecklistCheckResult(
            check_id="A04_three_year_kam", domain="audit", applicability="triggered",
            status="evaluated", first_detectable_at=kam_citations[-1].available_at,
            financial_period=kam_citations[-1].period,
            observations=tuple(item.verbatim_excerpt for item in kam_citations),
            evidence_ids=tuple(item.evidence_id for item in kam_citations),
            supporting_evidence=("最近三年KAM原文均已取得。",), counterevidence=(),
            inference_chain=("三年年度查核報告 → KAM逐年比較",),
            mechanism="KAM持續或新增反映重大估計及查核關注。",
            leading_warnings=("KAM新增、範圍擴大或措辭惡化",), buffers=(),
            monitoring_metrics=("KAM逐年變化",), monitoring_date=None,
            invalidation_or_resolution_conditions=("新年度KAM取代目前比較。",),
            severity="medium", confidence="high", unresolved_reasons=(),
        )

    findings = {
        item.finding_id: item
        for item in (
            *getattr(detailed_analysis, "downside_findings", ()),
            *getattr(detailed_analysis, "upside_findings", ()),
        )
        if getattr(item, "kind", None) == "fact"
    }

    def documented_finding(
        check_id: str,
        finding_id: str,
        mechanism: str,
        monitoring: tuple[str, ...],
        severity: str,
    ) -> None:
        finding = findings.get(finding_id)
        if finding is None or not finding.evidence_ids:
            return
        rows[check_id] = ChecklistCheckResult(
            check_id=check_id,
            domain=rows[check_id].domain,
            applicability="triggered",
            status="evaluated",
            first_detectable_at=None,
            financial_period=None,
            observations=(finding.statement,),
            evidence_ids=tuple(finding.evidence_ids),
            supporting_evidence=(finding.statement,),
            counterevidence=(),
            inference_chain=("官方附註／KAM原文 → 結構化fact → 權威題目",),
            mechanism=mechanism,
            leading_warnings=monitoring,
            buffers=(),
            monitoring_metrics=monitoring,
            monitoring_date=None,
            invalidation_or_resolution_conditions=("新一期官方文件更新本項事實。",),
            severity=severity,  # type: ignore[arg-type]
            confidence="high",
            unresolved_reasons=(),
        )

    documented_finding(
        "R38",
        "downside:long-term-commitments",
        "不可取消或長期採購、設備及能源承諾會形成未來固定現金需求。",
        ("未付款承諾", "取消條款", "資金來源", "產能利用率"),
        "medium",
    )
    documented_finding(
        "R39",
        "downside:customer-concentration",
        "客戶集中會放大單一客戶需求、議價及信用事件的營收與收款衝擊。",
        ("最大客戶營收占比", "前十大客戶應收占比", "期後收款"),
        "high",
    )
    repeated_kam = findings.get("downside:repeated-kam")
    if repeated_kam is not None and any(
        keyword in repeated_kam.statement for keyword in ("設備", "廠房", "折舊", "減損")
    ):
        documented_finding(
            "R31",
            "downside:repeated-kam",
            "設備、廠房、折舊或減損估計持續被列為KAM，須追蹤稼動與可回收性。",
            ("稼動率", "折舊開始時點", "資產減損", "KAM跨年變化"),
            "medium",
        )

    note_by_id = dict(getattr(document_evidence, "note_citations", ()))
    commitment_note = note_by_id.get("N13_commitments")
    if commitment_note is not None and rows["R38"].status != "evaluated":
        monitoring = ("未付款承諾", "取消條款", "資金來源")
        rows["R38"] = ChecklistCheckResult(
            check_id="R38",
            domain=rows["R38"].domain,
            applicability="triggered",
            status="evaluated",
            first_detectable_at=commitment_note.available_at,
            financial_period=commitment_note.period,
            observations=(commitment_note.verbatim_excerpt,),
            evidence_ids=(commitment_note.evidence_id,),
            supporting_evidence=("已取得官方重大承諾附註原文。",),
            counterevidence=(),
            inference_chain=("官方重大承諾附註 → 長約／承諾題",),
            mechanism="長約、採購或其他不可取消承諾形成未來固定現金需求。",
            leading_warnings=monitoring,
            buffers=(),
            monitoring_metrics=monitoring,
            monitoring_date=None,
            invalidation_or_resolution_conditions=("新一期官方附註更新承諾內容。",),
            severity="medium",
            confidence="high",
            unresolved_reasons=(),
        )
    working = findings.get("downside:working-capital-discipline")
    if working is not None and working.direction == "counter":
        for check_id, note_id, monitoring in (
            ("R01", "N02_receivables", ("應收相對營收", "DSO", "期後收款")),
            ("R03", "N03_inventory", ("存貨相對營收", "週轉天數", "跌價與期後銷售")),
        ):
            current = rows[check_id]
            citation = note_by_id.get(note_id)
            if current.applicability != "triggered" or citation is None:
                continue
            rows[check_id] = ChecklistCheckResult(
                check_id=check_id,
                domain="risk",
                applicability="triggered",
                status="evaluated",
                first_detectable_at=citation.available_at,
                financial_period=current.financial_period,
                observations=(*current.observations, working.statement, citation.verbatim_excerpt),
                evidence_ids=tuple(dict.fromkeys((*current.evidence_ids, *working.evidence_ids, citation.evidence_id))),
                supporting_evidence=("已讀取對應官方附註原文。",),
                counterevidence=(working.statement,),
                inference_chain=("量化觸發 → 年度相對增速比對 → 官方附註原文",),
                mechanism=current.mechanism,
                leading_warnings=monitoring,
                buffers=("目前相對營收增速未達營運資金red flag門檻。",),
                monitoring_metrics=monitoring,
                monitoring_date=None,
                invalidation_or_resolution_conditions=("後續相對增速、週轉或期後回收惡化。",),
                severity="low",
                confidence="medium",
                unresolved_reasons=(),
            )

    def partial_check(
        check_id: str,
        observations: tuple[str, ...],
        evidence_ids: tuple[str, ...],
        reason: str,
        monitoring: tuple[str, ...],
    ) -> None:
        if check_id not in rows or not evidence_ids:
            return
        rows[check_id] = ChecklistCheckResult(
            check_id=check_id,
            domain=rows[check_id].domain,
            applicability="triggered",
            status="unresolved",
            first_detectable_at=None,
            financial_period=None,
            observations=observations,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            supporting_evidence=("已取得部分官方證據。",),
            counterevidence=(),
            inference_chain=("官方文件／canonical facts → 權威題目部分證據",),
            mechanism="目前只完成部分證據鏈，尚不能形成最終判定。",
            leading_warnings=monitoring,
            buffers=(),
            monitoring_metrics=monitoring,
            monitoring_date=None,
            invalidation_or_resolution_conditions=("補齊本題所有指定營運與財務證據。",),
            severity="not_applicable",
            confidence="low",
            unresolved_reasons=(reason,),
        )

    capex_finding = findings.get("downside:capex-intensity")
    if capex_finding is not None:
        kam_evidence = repeated_kam.evidence_ids if repeated_kam is not None else ()
        kam_statement = (repeated_kam.statement,) if repeated_kam is not None else ()
        partial_check(
            "I-MFG-01",
            (capex_finding.statement, *kam_statement),
            (*capex_finding.evidence_ids, *kam_evidence),
            "已取得CAPEX／設備與折舊KAM，但尚缺產能、稼動率及良率同期間原始數據。",
            ("產能", "稼動率", "良率", "折舊負擔"),
        )

    inventory_note = note_by_id.get("N03_inventory")
    if inventory_note is not None:
        partial_check(
            "I-MFG-02",
            (inventory_note.verbatim_excerpt,),
            (inventory_note.evidence_id,),
            "已讀存貨附註，但尚未取得原料、在製品、製成品的完整跨期拆分與庫齡。",
            ("原料", "在製品", "製成品", "庫齡與跌價"),
        )

    concentration = findings.get("downside:customer-concentration")
    if concentration is not None:
        partial_check(
            "I-MFG-04",
            (concentration.statement,),
            tuple(concentration.evidence_ids),
            "已取得客戶集中證據，但尚缺終端應用分布與替代客戶驗證。",
            ("最大客戶占比", "終端應用分布", "替代客戶"),
        )

    financial_instruments = note_by_id.get("N15_financial_instruments")
    if financial_instruments is not None:
        partial_check(
            "I-MFG-06",
            (financial_instruments.verbatim_excerpt,),
            (financial_instruments.evidence_id,),
            "已讀金融工具附註，但尚未拆分匯率對營收、毛利與業外的不同影響。",
            ("交易幣別", "營收匯率影響", "毛利匯率影響", "業外匯兌"),
        )

    quarter_guidance = findings.get("upside:guidance:issuer:quarter-guidance")
    annual_guidance = findings.get("upside:guidance:issuer:annual-growth-guidance")
    guidance_items = tuple(
        item for item in (quarter_guidance, annual_guidance) if item is not None
    )
    if guidance_items:
        guidance_observations = tuple(item.statement for item in guidance_items)
        guidance_evidence = tuple(
            evidence_id for item in guidance_items for evidence_id in item.evidence_ids
        )
        partial_check(
            "G02",
            guidance_observations,
            guidance_evidence,
            "已取得公司成長指引，但尚缺需求、訂單與產能三端交叉驗證。",
            ("月營收加速度", "訂單／backlog", "產能利用率", "guidance達成率"),
        )
        partial_check(
            "G25",
            guidance_observations,
            guidance_evidence,
            "目前只有最新一期指引，尚未建立多期指引與Actual的命中紀錄。",
            ("指引中位數", "Actual", "命中率", "修正方向"),
        )

    product_roadmap = findings.get("upside:guidance:issuer:product-roadmap")
    if product_roadmap is not None:
        partial_check(
            "G19",
            (product_roadmap.statement,),
            tuple(product_roadmap.evidence_ids),
            "已取得產品design-in／量產路線圖，但尚缺新品營收與毛利貢獻拆分。",
            ("design-in", "production-ready", "ramp-up", "新品營收占比", "新品毛利率"),
        )
        partial_check(
            "I-MFG-05",
            (product_roadmap.statement,),
            tuple(product_roadmap.evidence_ids),
            "已取得產品路線圖，但尚缺客戶認證、design-win與量產收入的完整轉換證據。",
            ("客戶認證", "design-win", "ramp-up", "量產收入"),
        )

    fx_one_time = findings.get("upside:guidance:issuer:fx-one-time")
    if fx_one_time is not None:
        partial_check(
            "R21",
            (fx_one_time.statement,),
            tuple(fx_one_time.evidence_ids),
            "已確認一次性匯兌影響，但尚缺業外各項金額占淨利的完整拆分。",
            ("匯兌損益", "業外占淨利", "本業營業利益"),
        )
    return tuple(rows[item.check_id] for item in checks)


def _transmission_from_overview(
    overview: FinancialOverview | None,
) -> tuple[GrowthTransmissionStage, ...]:
    metric_by_stage = {
        "revenue": "revenue",
        "margin": "gross_margin",
        "cash": "operating_cash_flow",
    }
    result: list[GrowthTransmissionStage] = []
    for stage in GROWTH_TRANSMISSION_STAGES:
        metric = _overview_metric(overview, metric_by_stage.get(stage, ""))
        latest = (
            next((item for item in reversed(metric.values) if item.status == "available"), None)
            if metric is not None
            else None
        )
        if latest is not None:
            result.append(GrowthTransmissionStage(stage, "verified", latest.evidence_ids))
        else:
            result.append(
                GrowthTransmissionStage(
                    stage,
                    "unresolved",
                    (),
                    "該傳導階段尚未完成公司原始證據與反證准入。",
                )
            )
    return tuple(result)


def _apply_esg_legal_evidence(
    checks: tuple[ChecklistCheckResult, ...],
    evidence: EsgLegalEvidence | None,
) -> tuple[ChecklistCheckResult, ...]:
    """Overlay claim-specific rows; context cannot erase stronger evidence."""

    if evidence is None:
        return checks
    rows = {item.check_id: item for item in checks}
    for incoming in evidence.checks:
        current = rows.get(incoming.check_id)
        if current is None:
            # I-MFG-03 is absent outside the official manufacturing route.
            continue
        if incoming.status == "evaluated":
            rows[incoming.check_id] = incoming
        elif current.status != "evaluated":
            rows[incoming.check_id] = replace(
                incoming,
                observations=tuple(
                    dict.fromkeys((*current.observations, *incoming.observations))
                ),
                evidence_ids=tuple(
                    dict.fromkeys((*current.evidence_ids, *incoming.evidence_ids))
                ),
                unresolved_reasons=tuple(
                    dict.fromkeys(
                        (*current.unresolved_reasons, *incoming.unresolved_reasons)
                    )
                ),
            )
    return tuple(rows[item.check_id] for item in checks)


def _transmission(reason: str) -> tuple[GrowthTransmissionStage, ...]:
    return tuple(
        GrowthTransmissionStage(item, "unresolved", (), reason)
        for item in GROWTH_TRANSMISSION_STAGES
    )


def build_checklist_assessment(
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    financial_section: FinancialDeteriorationSection | None,
    detailed_analysis: object | None = None,
    peer_financial_comparison: PeerFinancialComparison | None = None,
    esg_legal_evidence: EsgLegalEvidence | None = None,
    forecast_capital_assessment: ForecastDividendCapitalAssessment | None = None,
    governance_evidence: GovernanceEvidenceCollection | None = None,
    working_capital_risk: WorkingCapitalRiskEvidence | None = None,
) -> ChecklistAssessment:
    route: CompanyRoute = (
        "financial_institution_unrouted"
        if bundle.identity.industry_code == "17"
        else "general_non_financial"
    )
    financial = _financial_artifacts(bundle)
    financial_ids = _ids(financial)
    monthly_ids = _ids(bundle.monthly_revenue)
    audit_ids = _ids(_audit_artifacts(bundle))
    basis_records = _basis_records(bundle)
    overview = build_financial_overview(bundle)
    industry_route = _industry_route(bundle, route)
    document_evidence = getattr(detailed_analysis, "checklist_document_evidence", None)
    if document_evidence is None:
        document_evidence = collect_checklist_document_evidence(
            _annual_audit_filings(bundle)
        )

    if route != "general_non_financial":
        reason = "金融保險業須使用專用模型；目前尚未可靠細分銀行、壽險、產險或證券。"
        return ChecklistAssessment(
            generation_id=generation_id,
            route=route,
            coverage=tuple(_unresolved(item, reason) for item in REQUIRED_COMPLETION_ITEMS),
            growth=tuple(_growth_unresolved(item, reason) for item in GROWTH_DIMENSIONS),
            risks=tuple(_risk_unresolved(item, reason) for item in RISK_DIMENSIONS),
            basis_records=basis_records,
            financial_overview=overview,
            checks=_placeholder_checks(reason, industry_route),
            growth_transmission=_transmission(reason),
            industry_route=industry_route,
        )

    annual = [item for item in bundle.periods if item.is_annual and item.financial]
    quarters = [item for item in bundle.periods if item.financial]
    latest_twelve = quarters[-12:]
    coverage: dict[str, ChecklistCoverage] = {}
    coverage["five_year_annual_consolidated_statements"] = (
        _complete("five_year_annual_consolidated_statements", financial_ids)
        if len(annual) >= 5 and all(_canonical_period_complete(item) for item in annual[-5:])
        else _unresolved("five_year_annual_consolidated_statements", "未取得最近五個年度完整四表。")
    )
    coverage["twelve_quarter_consolidated_statements"] = (
        _complete("twelve_quarter_consolidated_statements", financial_ids)
        if len(latest_twelve) == 12
        and all(_canonical_period_complete(item) for item in latest_twelve)
        else _unresolved("twelve_quarter_consolidated_statements", "未取得最近十二季完整四表。")
    )
    coverage["thirty_six_month_revenue"] = (
        _complete("thirty_six_month_revenue", monthly_ids)
        if len(bundle.monthly_revenue) >= 36
        else _unresolved("thirty_six_month_revenue", f"月營收僅取得{len(bundle.monthly_revenue)}個月。")
    )
    coverage["audit_and_review_reports_distinguished"] = (
        _complete("audit_and_review_reports_distinguished", audit_ids)
        if len(_audit_artifacts(bundle)) >= 12
        else _unresolved("audit_and_review_reports_distinguished", "最近十二季查核／核閱來源不完整。")
    )
    scopes = {getattr(item, "statement_scope", "unknown") for item in financial}
    coverage["consolidated_and_separate_scope_confirmed"] = (
        _complete("consolidated_and_separate_scope_confirmed", financial_ids)
        if scopes and "unknown" not in scopes
        else _unresolved("consolidated_and_separate_scope_confirmed", "部分四表無法辨識合併或個體口徑。")
    )
    bases = {getattr(item, "period_basis", None) for item in financial}
    coverage["single_period_and_cumulative_basis_confirmed"] = (
        _complete("single_period_and_cumulative_basis_confirmed", financial_ids)
        if {"point_in_time", "single_period", "single_and_ytd", "year_to_date"}.issubset(bases)
        else _unresolved("single_period_and_cumulative_basis_confirmed", "單季／累計口徑尚未完整。")
    )
    cross_check_periods = tuple(dict.fromkeys((*annual[-5:], *latest_twelve)))
    coverage["four_statements_cross_checked"] = (
        _complete("four_statements_cross_checked", financial_ids)
        if len(annual) >= 5
        and len(latest_twelve) == 12
        and all(_equity_cross_check_complete(item) for item in cross_check_periods)
        else _unresolved(
            "four_statements_cross_checked",
            "權益變動表尚未完成canonical parse，或總權益未與資產負債表逐期勾稽。",
        )
    )
    opinion_citations = getattr(document_evidence, "audit_opinion_citations", ())
    kam_citations = getattr(document_evidence, "kam_citations", ())
    audit_evidence_ids = tuple(
        item.evidence_id for item in (*opinion_citations, *kam_citations)
    )
    search_complete_periods = getattr(
        document_evidence, "audit_text_search_complete_periods", ()
    )
    going_concern_read = bool(
        getattr(document_evidence, "going_concern_citations", ())
    ) or len(search_complete_periods) == 3
    emphasis_other_read = bool(
        getattr(document_evidence, "emphasis_other_citations", ())
    ) or len(search_complete_periods) == 3
    coverage["auditor_opinion_going_concern_emphasis_other_matters_and_kam_read"] = (
        _complete(
            "auditor_opinion_going_concern_emphasis_other_matters_and_kam_read",
            audit_evidence_ids,
        )
        if (
            len(opinion_citations) == 3
            and len(kam_citations) == 3
            and going_concern_read
            and emphasis_other_read
        )
        else _unresolved(
            "auditor_opinion_going_concern_emphasis_other_matters_and_kam_read",
            f"最近三年查核意見取得{len(opinion_citations)}/3、KAM取得{len(kam_citations)}/3；"
            f"繼續經營判定={'完成' if going_concern_read else '未完成'}、"
            f"強調/其他事項判定={'完成' if emphasis_other_read else '未完成'}。",
        )
    )
    note_citations = getattr(document_evidence, "note_citations", ())
    note_ids = {item[0] for item in note_citations}
    note_evidence_ids = tuple(item[1].evidence_id for item in note_citations)
    coverage["minimum_notes_coverage_complete"] = (
        _complete("minimum_notes_coverage_complete", note_evidence_ids)
        if note_ids == set(NOTE_CHECK_IDS)
        else _unresolved(
            "minimum_notes_coverage_complete",
            f"最低附註覆蓋{len(note_ids)}/{len(NOTE_CHECK_IDS)}；未取得不代表沒有該風險。",
        )
    )
    fixed_unresolved = {
        "growth_drivers_have_evidence_counterevidence_invalidation_and_monitoring": "需求至現金的成長鏈仍有未解項目。",
        "risks_have_mechanism_warning_buffer_threshold_and_monitoring": "各風險的機制、緩衝、門檻及監控尚未全部建立。",
        "history_peer_seasonality_and_business_model_considered": "同業、季節性與商業模式比較尚未全部准入。",
    }
    coverage.update({key: _unresolved(key, reason) for key, reason in fixed_unresolved.items()})

    metrics = _metrics(financial_section)
    growth = {item: _growth_unresolved(item, "缺少可准入的公司原始證據與反證。") for item in GROWTH_DIMENSIONS}
    metric_growth = {
        "revenue_momentum": ("revenue", "營收與60個月月營收趨勢"),
        "margin_and_product_mix": ("gross_profit", "毛利與毛利率趨勢"),
        "operating_leverage": ("operating_profit", "營業利益與營益率趨勢"),
        "earnings_quality": ("net_income", "淨利趨勢"),
        "cash_conversion": ("receivables", "平均餘額DSO與現金回收趨勢"),
    }
    for dimension, (metric_id, label) in metric_growth.items():
        metric = metrics.get(metric_id)
        if metric is not None and not (dimension == "cash_conversion" and getattr(metric, "turnover_days", None) is None):
            evidence_ids = getattr(metric, "evidence_ids", ())
            if dimension == "revenue_momentum":
                evidence_ids = (*monthly_ids, *evidence_ids)
            judgement = _judgement(metric)
            if judgement != "unresolved":
                growth[dimension] = _growth_resolved(dimension, judgement, (label,), evidence_ids)

    for dimension, (metric_id, label) in _CANONICAL_GROWTH_METRICS.items():
        metric = _overview_metric(overview, metric_id)
        if metric is None or metric.trend_status == "unresolved":
            continue
        available = [item for item in metric.values[-4:] if item.status == "available"]
        if len(available) < 2:
            continue
        evidence_ids = tuple(
            dict.fromkeys(item for value in available[-2:] for item in value.evidence_ids)
        )
        if dimension == "revenue_momentum":
            evidence_ids = (*monthly_ids, *evidence_ids)
        growth[dimension] = _growth_resolved(
            dimension,
            metric.trend_status,
            (f"{label}；formula_id={metric.formula_id}",),
            evidence_ids,
        )

    risks = {item: _risk_unresolved(item, "缺少清單要求的附註、量化或反證。") for item in RISK_DIMENSIONS}
    metric_risks = {
        "liquidity_and_refinancing": ("liquidity", "流動性與財務結構趨勢", ("流動比率", "到期債務")),
        "receivables_and_collection": ("receivables", "平均餘額DSO與收款速度", ("DSO", "應收成長相對營收")),
        "inventory_and_impairment": ("inventory", "存貨與營收相對趨勢", ("存貨週轉", "跌價損失")),
        "earnings_quality": ("operating_cash_flow", "營業現金流與獲利趨勢", ("CFO/淨利", "自由現金流")),
    }
    for dimension, (metric_id, label, monitoring) in metric_risks.items():
        metric = metrics.get(metric_id)
        if metric is not None:
            judgement = _judgement(metric)
            if judgement != "unresolved":
                risks[dimension] = _risk_resolved(
                    dimension, judgement, label, getattr(metric, "evidence_ids", ()), monitoring
                )

    for dimension, (metric_id, monitoring) in _CANONICAL_RISK_METRICS.items():
        metric = _overview_metric(overview, metric_id)
        if metric is None or metric.trend_status == "unresolved":
            continue
        available = [item for item in metric.values[-4:] if item.status == "available"]
        if len(available) < 2:
            continue
        evidence_ids = tuple(
            dict.fromkeys(item for value in available[-2:] for item in value.evidence_ids)
        )
        risks[dimension] = _risk_resolved(
            dimension,
            metric.trend_status,
            f"{metric_id}趨勢；formula_id={metric.formula_id}",
            evidence_ids,
            monitoring,
        )

    checks = _apply_esg_legal_evidence(
        _apply_peer_financial_comparison(
            _document_checks(
                _quantitative_checks(
                    overview,
                    "該題尚未完成權威逐項 producer 與反證准入。",
                    industry_route,
                ),
                document_evidence,
                detailed_analysis,
            ),
            peer_financial_comparison,
        ),
        esg_legal_evidence,
    )
    if forecast_capital_assessment is not None:
        replacements = forecast_capital_assessment.by_check_id
        checks = tuple(replacements.get(item.check_id, item) for item in checks)
    if governance_evidence is not None:
        # Local import keeps the source producer independent from the checklist
        # builder while giving the authoritative assessment one narrow hook.
        from company_quality.sources.governance_insiders import apply_governance_checks

        checks = apply_governance_checks(checks, governance_evidence)
    if working_capital_risk is not None:
        replacements = working_capital_risk.by_check_id
        checks = tuple(replacements.get(item.check_id, item) for item in checks)
    transmission = _transmission_from_overview(overview)
    growth_rows = tuple(item for item in checks if item.domain == "growth")
    risk_rows = tuple(item for item in checks if item.domain == "risk")
    growth_complete = (
        all(item.status == "evaluated" for item in growth_rows)
        and all(
            item.status in {"verified", "partially_verified", "not_applicable"}
            for item in transmission
        )
        and all(
            item.judgement != "unresolved"
            and bool(item.evidence_ids)
            and bool(item.counterevidence)
            and bool(item.invalidation_conditions)
            and bool(item.monitoring_metrics)
            for item in growth.values()
        )
    )
    risk_complete = (
        all(item.status == "evaluated" for item in risk_rows)
        and all(
            item.judgement != "unresolved"
            and bool(item.evidence_ids)
            and bool(item.leading_warnings)
            and bool(item.buffers_and_counterevidence)
            and bool(item.stress_transmission)
            and bool(item.resolution_conditions)
            and bool(item.monitoring_metrics)
            for item in risks.values()
        )
    )
    completion_evidence = tuple(
        dict.fromkeys((*financial_ids, *monthly_ids, *audit_ids, *note_evidence_ids))
    )
    coverage["growth_drivers_have_evidence_counterevidence_invalidation_and_monitoring"] = (
        _complete(
            "growth_drivers_have_evidence_counterevidence_invalidation_and_monitoring",
            completion_evidence,
        )
        if growth_complete
        else _unresolved(
            "growth_drivers_have_evidence_counterevidence_invalidation_and_monitoring",
            "需求至現金的成長鏈仍有未解項目。",
        )
    )
    coverage["risks_have_mechanism_warning_buffer_threshold_and_monitoring"] = (
        _complete(
            "risks_have_mechanism_warning_buffer_threshold_and_monitoring",
            completion_evidence,
        )
        if risk_complete
        else _unresolved(
            "risks_have_mechanism_warning_buffer_threshold_and_monitoring",
            "各風險的機制、緩衝、門檻及監控尚未全部建立。",
        )
    )
    coverage["missing_evidence_preserved_as_unresolved"] = _complete(
        "missing_evidence_preserved_as_unresolved", completion_evidence
    )
    detailed_findings = (
        *getattr(detailed_analysis, "downside_findings", ()),
        *getattr(detailed_analysis, "upside_findings", ()),
    )
    business_findings = tuple(
        item
        for item in detailed_findings
        if item.finding_id == "upside:guidance:issuer:business-model"
    )
    context_evidence = tuple(
        dict.fromkeys(
            (
                *financial_ids,
                *monthly_ids,
                *(peer_financial_comparison.evidence_ids if peer_financial_comparison else ()),
                *(
                    evidence_id
                    for item in business_findings
                    for evidence_id in item.evidence_ids
                ),
            )
        )
    )
    context_gaps: list[str] = []
    if len(annual) < 5:
        context_gaps.append("五年歷史")
    if len(bundle.monthly_revenue) < 36:
        context_gaps.append("36個月季節性")
    if not business_findings:
        context_gaps.append("官方商業模式")
    if peer_financial_comparison is None or peer_financial_comparison.status != "available":
        context_gaps.extend(
            peer_financial_comparison.unresolved_reasons
            if peer_financial_comparison is not None
            else ("同市場同業財務比較尚未接入runtime",)
        )
    coverage["history_peer_seasonality_and_business_model_considered"] = (
        _complete("history_peer_seasonality_and_business_model_considered", context_evidence)
        if not context_gaps and context_evidence
        else ChecklistCoverage(
            item_id="history_peer_seasonality_and_business_model_considered",
            status="unresolved",
            evidence_ids=context_evidence,
            unresolved_reason="；".join(context_gaps),
        )
    )

    return ChecklistAssessment(
        generation_id=generation_id,
        route=route,
        coverage=tuple(coverage[item] for item in REQUIRED_COMPLETION_ITEMS),
        growth=tuple(growth[item] for item in GROWTH_DIMENSIONS),
        risks=tuple(risks[item] for item in RISK_DIMENSIONS),
        basis_records=basis_records,
        financial_overview=overview,
        checks=checks,
        growth_transmission=transmission,
        industry_route=industry_route,
    )


__all__ = ["PeerFinancialComparison", "build_checklist_assessment"]
