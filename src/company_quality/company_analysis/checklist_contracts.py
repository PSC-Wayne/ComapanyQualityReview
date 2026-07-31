"""Executable contracts for the authoritative company-analysis checklist.

The behavioral authority is ``Financial_Statement_Growth_Risk_Checklist.md``.
Missing evidence always fails closed; it is never interpreted as no risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

AUTHORITY_DOCUMENT = "Financial_Statement_Growth_Risk_Checklist.md"
CoverageStatus = Literal["complete", "unresolved", "not_applicable"]
Judgement = Literal["improving", "stable", "deteriorating", "unresolved"]
Confidence = Literal["high", "medium", "low"]
CompanyRoute = Literal[
    "general_non_financial",
    "bank",
    "life_insurer",
    "property_insurer",
    "securities_firm",
    "financial_institution_unrouted",
]
IndustryRoute = Literal[
    "manufacturing_hardware", "ecommerce_platform", "project_engineering_epc",
    "software_ai", "financial", "biotech", "energy",
    "not_applicable", "unresolved",
]

REQUIRED_COMPLETION_ITEMS = (
    "five_year_annual_consolidated_statements",
    "twelve_quarter_consolidated_statements",
    "thirty_six_month_revenue",
    "audit_and_review_reports_distinguished",
    "consolidated_and_separate_scope_confirmed",
    "single_period_and_cumulative_basis_confirmed",
    "four_statements_cross_checked",
    "auditor_opinion_going_concern_emphasis_other_matters_and_kam_read",
    "minimum_notes_coverage_complete",
    "growth_drivers_have_evidence_counterevidence_invalidation_and_monitoring",
    "risks_have_mechanism_warning_buffer_threshold_and_monitoring",
    "history_peer_seasonality_and_business_model_considered",
    "missing_evidence_preserved_as_unresolved",
)
GROWTH_DIMENSIONS = (
    "revenue_momentum", "margin_and_product_mix", "operating_leverage",
    "earnings_quality", "cash_conversion", "reinvestment_and_roic",
    "per_share_value_and_dilution",
)
RISK_DIMENSIONS = (
    "liquidity_and_refinancing", "receivables_and_collection",
    "inventory_and_impairment", "contract_assets_and_revenue_recognition",
    "earnings_quality", "goodwill_and_asset_impairment",
    "related_parties_and_governance", "customer_and_supplier_concentration",
    "litigation_guarantees_and_commitments",
    "shareholder_dilution_and_capital_allocation",
)
GROWTH_CHECK_IDS = tuple(f"G{i:02d}" for i in range(1, 26))
RISK_CHECK_IDS = tuple(f"R{i:02d}" for i in range(1, 49))
NOTE_CHECK_IDS = (
    "N01_revenue_recognition", "N02_receivables", "N03_inventory",
    "N04_contract_assets", "N05_ppe", "N06_goodwill_intangibles",
    "N07_borrowings_bonds", "N08_liquidity", "N09_restricted_cash",
    "N10_related_parties", "N11_guarantees", "N12_contingencies_litigation",
    "N13_commitments", "N14_income_tax", "N15_financial_instruments",
    "N16_share_based_payments", "N17_eps", "N18_segments",
    "N19_subsequent_events",
)
AUDIT_CHECK_IDS = (
    "A01_auditor_opinion",
    "A02_going_concern",
    "A03_emphasis_and_other_matters",
    "A04_three_year_kam",
)
REQUIRED_CHECK_IDS = (
    *GROWTH_CHECK_IDS, *RISK_CHECK_IDS, *NOTE_CHECK_IDS, *AUDIT_CHECK_IDS,
)
INDUSTRY_CHECK_IDS = {
    "manufacturing_hardware": tuple(f"I-MFG-{item:02d}" for item in range(1, 8)),
    "ecommerce_platform": tuple(f"I-ECOM-{item:02d}" for item in range(1, 5)),
    "project_engineering_epc": tuple(f"I-EPC-{item:02d}" for item in range(1, 6)),
    "software_ai": tuple(f"I-SW-{item:02d}" for item in range(1, 6)),
    "financial": tuple(f"I-FIN-{item:02d}" for item in range(1, 5)),
    "biotech": tuple(f"I-BIO-{item:02d}" for item in range(1, 6)),
    "energy": tuple(f"I-ENERGY-{item:02d}" for item in range(1, 6)),
}
GROWTH_TRANSMISSION_STAGES = (
    "demand", "opportunity", "order", "backlog", "revenue", "margin", "cash"
)


@dataclass(frozen=True, slots=True)
class ChecklistCoverage:
    item_id: str
    status: CoverageStatus
    evidence_ids: tuple[str, ...]
    unresolved_reason: str | None = None

    def __post_init__(self) -> None:
        if self.item_id not in REQUIRED_COMPLETION_ITEMS:
            raise ValueError(f"unknown checklist completion item: {self.item_id}")
        if self.status == "complete" and not self.evidence_ids:
            raise ValueError("completed checklist item requires evidence")
        if self.status == "unresolved" and not self.unresolved_reason:
            raise ValueError("unresolved checklist item requires a reason")
        if self.status != "unresolved" and self.unresolved_reason is not None:
            raise ValueError("only unresolved checklist items may have a reason")


@dataclass(frozen=True, slots=True)
class AnalysisBasisRecord:
    period: str
    statement: Literal["balance", "income", "cash_flow", "equity_changes", "monthly_revenue", "audit_report"]
    consolidation_scope: Literal["consolidated", "individual", "not_applicable", "unknown"]
    period_basis: Literal["point_in_time", "single_period", "single_and_ytd", "year_to_date", "annual", "not_applicable", "unknown"]
    assurance: Literal["audit", "review", "unaudited", "not_applicable", "unknown"]
    currency: str | None
    unit: str | None
    restatement_status: Literal["original", "restated", "corrected", "unknown"]
    report_date: str | None
    filed_at: str | None
    available_at: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.period or not self.evidence_ids or not self.available_at:
            raise ValueError("basis record requires period, availability and evidence")


@dataclass(frozen=True, slots=True)
class FinancialMetricValue:
    period: str
    value: Decimal | None
    ratio: Decimal | None
    status: Literal["available", "not_disclosed", "not_derivable", "not_applicable"]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status == "available" and (self.value is None or not self.evidence_ids):
            raise ValueError("available metric value requires value and evidence")
        if self.status != "available" and self.value is not None:
            raise ValueError("unavailable metric value cannot carry a numeric value")


@dataclass(frozen=True, slots=True)
class FinancialOverviewMetric:
    metric_id: str
    values: tuple[FinancialMetricValue, ...]
    trend_status: Judgement | Literal["mixed"]
    formula_id: str | None
    days_basis: str | None
    approximation_reason: str | None


@dataclass(frozen=True, slots=True)
class FinancialOverview:
    periods: tuple[str, ...]
    metrics: tuple[FinancialOverviewMetric, ...]
    schema_version: Literal["FinancialOverview.v1"] = "FinancialOverview.v1"

    def __post_init__(self) -> None:
        if len(set(self.periods)) != len(self.periods):
            raise ValueError("duplicate financial overview period")
        if len({item.metric_id for item in self.metrics}) != len(self.metrics):
            raise ValueError("duplicate financial overview metric")


@dataclass(frozen=True, slots=True)
class ChecklistCheckResult:
    check_id: str
    domain: Literal["growth", "risk", "note", "audit", "industry"]
    applicability: Literal["triggered", "not_triggered", "not_applicable", "unresolved"]
    status: Literal["evaluated", "unresolved"]
    first_detectable_at: str | None
    financial_period: str | None
    observations: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    counterevidence: tuple[str, ...]
    inference_chain: tuple[str, ...]
    mechanism: str | None
    leading_warnings: tuple[str, ...]
    buffers: tuple[str, ...]
    monitoring_metrics: tuple[str, ...]
    monitoring_date: str | None
    invalidation_or_resolution_conditions: tuple[str, ...]
    severity: Literal["low", "medium", "high", "critical", "not_applicable"]
    confidence: Literal["high", "medium", "low", "not_applicable"]
    unresolved_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status == "unresolved" and not self.unresolved_reasons:
            raise ValueError("unresolved check requires reasons")
        if self.status == "evaluated" and self.applicability == "triggered" and not self.evidence_ids:
            raise ValueError("triggered evaluated check requires evidence")
        if self.status == "evaluated" and self.unresolved_reasons:
            raise ValueError("evaluated check cannot retain unresolved reasons")


@dataclass(frozen=True, slots=True)
class GrowthTransmissionStage:
    stage: str
    status: Literal["verified", "partially_verified", "unverified", "unresolved", "not_applicable"]
    evidence_ids: tuple[str, ...]
    unresolved_reason: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in GROWTH_TRANSMISSION_STAGES:
            raise ValueError(f"unknown growth transmission stage: {self.stage}")
        if self.status in {"verified", "partially_verified"} and not self.evidence_ids:
            raise ValueError("verified transmission stage requires evidence")
        if self.status in {"unverified", "unresolved"} and not self.unresolved_reason:
            raise ValueError("unverified transmission stage requires a reason")


@dataclass(frozen=True, slots=True)
class GrowthConclusion:
    dimension: str
    judgement: Judgement
    core_numbers: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    counterevidence: tuple[str, ...]
    unresolved_items: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    monitoring_metrics: tuple[str, ...]
    confidence: Confidence

    def __post_init__(self) -> None:
        if self.dimension not in GROWTH_DIMENSIONS:
            raise ValueError(f"unknown growth dimension: {self.dimension}")
        if self.judgement == "unresolved" and not self.unresolved_items:
            raise ValueError("unresolved growth conclusion requires unresolved items")
        if self.judgement != "unresolved" and not self.core_numbers:
            raise ValueError("resolved growth conclusion requires core numbers")


@dataclass(frozen=True, slots=True)
class RiskConclusion:
    dimension: str
    judgement: Judgement
    mechanism: str
    leading_warnings: tuple[str, ...]
    current_evidence: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    buffers_and_counterevidence: tuple[str, ...]
    stress_transmission: tuple[str, ...]
    resolution_conditions: tuple[str, ...]
    unresolved_items: tuple[str, ...]
    monitoring_metrics: tuple[str, ...]
    confidence: Confidence

    def __post_init__(self) -> None:
        if self.dimension not in RISK_DIMENSIONS:
            raise ValueError(f"unknown risk dimension: {self.dimension}")
        if self.judgement == "unresolved" and not self.unresolved_items:
            raise ValueError("unresolved risk conclusion requires unresolved items")
        if self.judgement != "unresolved" and not self.current_evidence:
            raise ValueError("resolved risk conclusion requires current evidence")


@dataclass(frozen=True, slots=True)
class ChecklistAssessment:
    generation_id: str
    route: CompanyRoute
    coverage: tuple[ChecklistCoverage, ...]
    growth: tuple[GrowthConclusion, ...]
    risks: tuple[RiskConclusion, ...]
    basis_records: tuple[AnalysisBasisRecord, ...] = ()
    financial_overview: FinancialOverview | None = None
    checks: tuple[ChecklistCheckResult, ...] = ()
    growth_transmission: tuple[GrowthTransmissionStage, ...] = ()
    industry_route: IndustryRoute = "unresolved"
    detailed_check_status: Literal["complete", "incomplete_unresolved", "not_applicable_company_route"] = field(init=False)
    schema_version: Literal["ChecklistAssessment.v1"] = "ChecklistAssessment.v1"

    def __post_init__(self) -> None:
        coverage_ids = tuple(item.item_id for item in self.coverage)
        if len(set(coverage_ids)) != len(coverage_ids):
            raise ValueError("duplicate checklist coverage item")
        if set(coverage_ids) != set(REQUIRED_COMPLETION_ITEMS):
            raise ValueError("assessment must declare every completion item")
        if {item.dimension for item in self.growth} != set(GROWTH_DIMENSIONS):
            raise ValueError("assessment must declare all growth dimensions")
        if {item.dimension for item in self.risks} != set(RISK_DIMENSIONS):
            raise ValueError("assessment must declare all risk dimensions")
        check_ids = tuple(item.check_id for item in self.checks)
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("duplicate checklist check")
        required_checks = (*REQUIRED_CHECK_IDS, *INDUSTRY_CHECK_IDS.get(self.industry_route, ()))
        if set(check_ids) != set(required_checks):
            raise ValueError("assessment must declare every G, R, note and routed industry check")
        stages = tuple(item.stage for item in self.growth_transmission)
        if len(set(stages)) != len(stages) or set(stages) != set(GROWTH_TRANSMISSION_STAGES):
            raise ValueError("assessment must declare every growth transmission stage")
        complete = (
            self.route == "general_non_financial"
            and bool(self.basis_records)
            and self.financial_overview is not None
            and self.industry_route != "unresolved"
            and all(item.status in {"complete", "not_applicable"} for item in self.coverage)
            and all(item.status == "evaluated" and item.applicability != "unresolved" for item in self.checks)
            and all(item.status in {"verified", "partially_verified", "not_applicable"} for item in self.growth_transmission)
            and all(item.judgement != "unresolved" for item in (*self.growth, *self.risks))
        )
        status = (
            "not_applicable_company_route"
            if self.route != "general_non_financial"
            else "complete" if complete else "incomplete_unresolved"
        )
        object.__setattr__(self, "detailed_check_status", status)

    @property
    def detailed_check_complete(self) -> bool:
        return self.detailed_check_status == "complete"

    @property
    def unresolved_reasons(self) -> tuple[str, ...]:
        reasons = [
            item.unresolved_reason
            for item in self.coverage
            if item.status == "unresolved" and item.unresolved_reason is not None
        ]
        reasons.extend(
            reason
            for conclusion in (*self.growth, *self.risks)
            for reason in conclusion.unresolved_items
        )
        reasons.extend(reason for item in self.checks for reason in item.unresolved_reasons)
        reasons.extend(
            item.unresolved_reason
            for item in self.growth_transmission
            if item.unresolved_reason is not None
        )
        if not self.basis_records:
            reasons.append("分析口徑紀錄尚未建立。")
        if self.financial_overview is None:
            reasons.append("權威財務總覽尚未建立。")
        return tuple(dict.fromkeys(reason for reason in reasons if reason))


__all__ = [
    "AUDIT_CHECK_IDS", "AUTHORITY_DOCUMENT", "GROWTH_CHECK_IDS", "GROWTH_DIMENSIONS",
    "GROWTH_TRANSMISSION_STAGES", "INDUSTRY_CHECK_IDS", "NOTE_CHECK_IDS", "REQUIRED_CHECK_IDS",
    "REQUIRED_COMPLETION_ITEMS", "RISK_CHECK_IDS", "RISK_DIMENSIONS",
    "AnalysisBasisRecord", "ChecklistAssessment", "ChecklistCheckResult",
    "ChecklistCoverage", "FinancialMetricValue", "FinancialOverview",
    "FinancialOverviewMetric", "GrowthConclusion", "GrowthTransmissionStage",
    "RiskConclusion",
]
