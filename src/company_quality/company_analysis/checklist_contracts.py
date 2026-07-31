"""Authoritative completion and conclusion contracts for single-company research.

The behavioral authority is ``Financial_Statement_Growth_Risk_Checklist.md``.
These contracts fail closed: an unresolved required item prevents a detailed
check from being described as complete.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    "revenue_momentum",
    "margin_and_product_mix",
    "operating_leverage",
    "earnings_quality",
    "cash_conversion",
    "reinvestment_and_roic",
    "per_share_value_and_dilution",
)

RISK_DIMENSIONS = (
    "liquidity_and_refinancing",
    "receivables_and_collection",
    "inventory_and_impairment",
    "contract_assets_and_revenue_recognition",
    "earnings_quality",
    "goodwill_and_asset_impairment",
    "related_parties_and_governance",
    "customer_and_supplier_concentration",
    "litigation_guarantees_and_commitments",
    "shareholder_dilution_and_capital_allocation",
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

    def __post_init__(self) -> None:
        coverage_ids = tuple(item.item_id for item in self.coverage)
        if len(set(coverage_ids)) != len(coverage_ids):
            raise ValueError("duplicate checklist coverage item")
        if set(coverage_ids) != set(REQUIRED_COMPLETION_ITEMS):
            raise ValueError("assessment must declare every completion item")
        if len({item.dimension for item in self.growth}) != len(self.growth):
            raise ValueError("duplicate growth dimension")
        if len({item.dimension for item in self.risks}) != len(self.risks):
            raise ValueError("duplicate risk dimension")

    @property
    def detailed_check_complete(self) -> bool:
        if self.route != "general_non_financial":
            return False
        return (
            all(item.status in {"complete", "not_applicable"} for item in self.coverage)
            and {item.dimension for item in self.growth} == set(GROWTH_DIMENSIONS)
            and {item.dimension for item in self.risks} == set(RISK_DIMENSIONS)
            and all(item.judgement != "unresolved" for item in (*self.growth, *self.risks))
        )

    @property
    def unresolved_reasons(self) -> tuple[str, ...]:
        reasons = [
            item.unresolved_reason
            for item in self.coverage
            if item.status == "unresolved" and item.unresolved_reason is not None
        ]
        reasons.extend(
            unresolved
            for conclusion in (*self.growth, *self.risks)
            for unresolved in conclusion.unresolved_items
        )
        return tuple(dict.fromkeys(reasons))
