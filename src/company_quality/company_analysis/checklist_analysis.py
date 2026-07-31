"""Build the authoritative checklist view without upgrading missing evidence to safety."""

from __future__ import annotations

from typing import Iterable

from company_quality.company_analysis.checklist_contracts import (
    GROWTH_CHECK_IDS,
    GROWTH_DIMENSIONS,
    GROWTH_TRANSMISSION_STAGES,
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
    GrowthConclusion,
    GrowthTransmissionStage,
    RiskConclusion,
)
from company_quality.company_analysis.contracts import FinancialDeteriorationSection
from company_quality.company_analysis.checklist_metrics import build_financial_overview
from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle


def _ids(values: Iterable[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        candidate = getattr(value, "artifact_id", None) or getattr(value, "filing_id", None)
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


def _placeholder_checks(reason: str) -> tuple[ChecklistCheckResult, ...]:
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
    )


_QUANTITATIVE_CHECKS = {
    "G01": "revenue", "G05": "gross_profit", "G06": "gross_margin",
    "G07": "operating_income", "G08": "operating_margin",
    "G09": "net_income", "G10": "net_margin", "G12": "dso_days",
    "G14": "inventory_days", "G15": "cfo_to_net_income",
    "G16": "free_cash_flow", "G17": "capex", "G18": "capex",
    "G19": "roic", "G20": "common_stock_capital",
    "G21": "diluted_weighted_average_shares",
    "R01": "current_ratio", "R02": "current_ratio", "R03": "cash",
    "R04": "restricted_cash", "R05": "debt_due_within_year",
    "R06": "interest_bearing_debt", "R09": "receivables",
    "R10": "dso_days", "R14": "inventory", "R15": "inventory_days",
    "R18": "contract_assets", "R21": "cfo_to_net_income",
    "R22": "free_cash_flow", "R27": "goodwill_and_intangibles",
    "R43": "common_stock_capital", "R44": "diluted_weighted_average_shares",
    "R46": "cash_dividends_paid", "R47": "roic",
}


def _overview_metric(overview: FinancialOverview | None, metric_id: str):
    if overview is None:
        return None
    return next((item for item in overview.metrics if item.metric_id == metric_id), None)


def _quantitative_checks(
    overview: FinancialOverview | None,
    unresolved_reason: str,
) -> tuple[ChecklistCheckResult, ...]:
    rows = {item.check_id: item for item in _placeholder_checks(unresolved_reason)}
    for check_id, metric_id in _QUANTITATIVE_CHECKS.items():
        metric = _overview_metric(overview, metric_id)
        if metric is None:
            continue
        available = [item for item in metric.values[-4:] if item.status == "available"]
        if len(available) < 2:
            continue
        previous, latest = available[-2:]
        assert previous.value is not None and latest.value is not None
        domain = "growth" if check_id.startswith("G") else "risk"
        deterioration = metric.trend_status == "deteriorating"
        rows[check_id] = ChecklistCheckResult(
            check_id=check_id,
            domain=domain,
            applicability="triggered",
            status="evaluated",
            first_detectable_at=None,
            financial_period=latest.period,
            observations=(
                f"{metric_id}由{previous.value}變為{latest.value}；趨勢={metric.trend_status}",
                f"formula_id={metric.formula_id}",
            ),
            evidence_ids=tuple(dict.fromkeys((*previous.evidence_ids, *latest.evidence_ids))),
            supporting_evidence=("量化趨勢改善或持平。",) if not deterioration else (),
            counterevidence=("量化趨勢惡化。",) if deterioration else (),
            inference_chain=(f"canonical facts → {metric.formula_id} → 趨勢判定",),
            mechanism=f"追蹤{metric_id}對成長品質或風險承受力的變化。",
            leading_warnings=(f"{metric_id}連續惡化",),
            buffers=(f"{metric_id}改善或維持",),
            monitoring_metrics=(metric_id,),
            monitoring_date=None,
            invalidation_or_resolution_conditions=("下一期同口徑資料使趨勢反轉。",),
            severity=("high" if deterioration else "low") if domain == "risk" else "not_applicable",
            confidence="medium",
            unresolved_reasons=(),
        )
    return tuple(
        rows[item] for item in (*GROWTH_CHECK_IDS, *RISK_CHECK_IDS, *NOTE_CHECK_IDS)
    )


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


def _transmission(reason: str) -> tuple[GrowthTransmissionStage, ...]:
    return tuple(
        GrowthTransmissionStage(item, "unresolved", (), reason)
        for item in GROWTH_TRANSMISSION_STAGES
    )


def build_checklist_assessment(
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    financial_section: FinancialDeteriorationSection | None,
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
            checks=_placeholder_checks(reason),
            growth_transmission=_transmission(reason),
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
    fixed_unresolved = {
        "auditor_opinion_going_concern_emphasis_other_matters_and_kam_read": "最近三年KAM與查核意見尚未全部逐字抽取並准入。",
        "minimum_notes_coverage_complete": "重大承諾、或有事項、關係人、減損及政策附註尚未逐項完成。",
        "growth_drivers_have_evidence_counterevidence_invalidation_and_monitoring": "需求至現金的成長鏈仍有未解項目。",
        "risks_have_mechanism_warning_buffer_threshold_and_monitoring": "各風險的機制、緩衝、門檻及監控尚未全部建立。",
        "history_peer_seasonality_and_business_model_considered": "同業、季節性與商業模式比較尚未全部准入。",
        "missing_evidence_preserved_as_unresolved": "目前仍有未解證據；已保留為未解而非零風險。",
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

    canonical_growth = {
        "revenue_momentum": ("revenue", "營收趨勢"),
        "margin_and_product_mix": ("gross_margin", "毛利率趨勢"),
        "operating_leverage": ("operating_margin", "營業利益率趨勢"),
        "earnings_quality": ("cfo_to_net_income", "CFO／淨利品質"),
        "cash_conversion": ("cash_conversion_cycle_days", "現金轉換週期"),
        "reinvestment_efficiency": ("roic", "ROIC"),
        "per_share_value": ("diluted_eps", "稀釋每股盈餘"),
    }
    for dimension, (metric_id, label) in canonical_growth.items():
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

    canonical_risks = {
        "liquidity_and_refinancing": ("current_ratio", ("流動比率", "一年內到期債務")),
        "receivables_and_collection": ("dso_days", ("平均餘額DSO", "應收成長相對營收")),
        "inventory_and_impairment": ("inventory_days", ("平均存貨週轉天數", "跌價損失")),
        "contract_assets_and_revenue_recognition": ("contract_assets", ("合約資產", "收入認列政策")),
        "earnings_quality": ("cfo_to_net_income", ("CFO／淨利", "自由現金流")),
        "capital_structure_and_dilution": ("common_stock_capital", ("股本", "完全稀釋股數")),
    }
    for dimension, (metric_id, monitoring) in canonical_risks.items():
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

    return ChecklistAssessment(
        generation_id=generation_id,
        route=route,
        coverage=tuple(coverage[item] for item in REQUIRED_COMPLETION_ITEMS),
        growth=tuple(growth[item] for item in GROWTH_DIMENSIONS),
        risks=tuple(risks[item] for item in RISK_DIMENSIONS),
        basis_records=basis_records,
        financial_overview=overview,
        checks=_quantitative_checks(
            overview, "該題尚未完成權威逐項 producer 與反證准入。"
        ),
        growth_transmission=_transmission_from_overview(overview),
    )


__all__ = ["build_checklist_assessment"]
