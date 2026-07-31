"""Build the authoritative checklist view without upgrading missing evidence to safety."""

from __future__ import annotations

from typing import Iterable

from company_quality.company_analysis.checklist_contracts import (
    GROWTH_DIMENSIONS,
    REQUIRED_COMPLETION_ITEMS,
    RISK_DIMENSIONS,
    ChecklistAssessment,
    ChecklistCoverage,
    CompanyRoute,
    GrowthConclusion,
    RiskConclusion,
)
from company_quality.company_analysis.contracts import FinancialDeteriorationSection
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

    if route != "general_non_financial":
        reason = "金融保險業須使用專用模型；目前尚未可靠細分銀行、壽險、產險或證券。"
        return ChecklistAssessment(
            generation_id=generation_id,
            route=route,
            coverage=tuple(_unresolved(item, reason) for item in REQUIRED_COMPLETION_ITEMS),
            growth=tuple(_growth_unresolved(item, reason) for item in GROWTH_DIMENSIONS),
            risks=tuple(_risk_unresolved(item, reason) for item in RISK_DIMENSIONS),
        )

    annual = [item for item in bundle.periods if item.is_annual and item.financial]
    quarters = [item for item in bundle.periods if item.financial]
    latest_twelve = quarters[-12:]
    coverage: dict[str, ChecklistCoverage] = {}
    coverage["five_year_annual_consolidated_statements"] = (
        _complete("five_year_annual_consolidated_statements", financial_ids)
        if len(annual) >= 5 and all(
            item.financial is not None and len(item.financial.artifacts) == 4
            for item in annual[-5:]
        )
        else _unresolved("five_year_annual_consolidated_statements", "未取得最近五個年度完整四表。")
    )
    coverage["twelve_quarter_consolidated_statements"] = (
        _complete("twelve_quarter_consolidated_statements", financial_ids)
        if len(latest_twelve) == 12
        and all(
            item.financial is not None and len(item.financial.artifacts) == 4
            for item in latest_twelve
        )
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
    equity_ids = _ids(item for item in financial if getattr(item, "report", None) == "equity_changes")
    coverage["four_statements_cross_checked"] = (
        _complete("four_statements_cross_checked", equity_ids)
        if len(equity_ids) >= 12
        else _unresolved("four_statements_cross_checked", "權益變動表不足十二季。")
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

    return ChecklistAssessment(
        generation_id=generation_id,
        route=route,
        coverage=tuple(coverage[item] for item in REQUIRED_COMPLETION_ITEMS),
        growth=tuple(growth[item] for item in GROWTH_DIMENSIONS),
        risks=tuple(risks[item] for item in RISK_DIMENSIONS),
    )


__all__ = ["build_checklist_assessment"]
