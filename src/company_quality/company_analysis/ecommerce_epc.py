"""Official-evidence routing and producers for e-commerce and EPC checklist rows.

The public seam deliberately accepts neither company names nor broad industry codes.
A vertical is selected only when every authority-defined business-model claim part is
supported by point-in-time-safe official or issuer-primary evidence.  Metric values,
terms and their issuer definitions are preserved verbatim; this module applies no
invented thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation

BusinessModel = Literal["ecommerce_platform", "project_engineering_epc"]
RouteClaimPart = Literal[
    "platform_operations",
    "third_party_transactions",
    "transaction_linked_revenue",
    "engineering_procurement_construction",
    "customer_project_contracts",
    "project_performance_revenue",
]
IndustryFactType = Literal[
    "gmv", "revenue", "take_rate",
    "traffic", "conversion_rate", "customer_acquisition_cost", "retention",
    "merchant_concentration", "customer_concentration",
    "logistics_model", "inventory_ownership", "fulfilment_cost",
    "customer_collection_timing", "merchant_settlement_timing",
    "signed_backlog", "binding_terms", "cancellation_terms", "price_adjustment",
    "execution_period", "progress_measure", "total_cost_estimate", "project_margin",
    "cost_overrun", "contract_assets", "contract_liabilities", "billing_milestone",
    "receivable_conversion", "retention_receivable", "warranty_provision",
    "change_orders", "claims", "acceptance_disputes", "customer_collection",
    "supplier_payment", "advance_receipts", "project_cash_conversion",
]
EvidenceSignal = Literal["risk", "counterevidence"]
EvidenceRole = Literal["substantive", "context"]
RouteStatus = Literal["routed", "unresolved"]

_ROUTE_REQUIREMENTS: Mapping[BusinessModel, tuple[RouteClaimPart, ...]] = {
    "ecommerce_platform": (
        "platform_operations", "third_party_transactions", "transaction_linked_revenue",
    ),
    "project_engineering_epc": (
        "engineering_procurement_construction", "customer_project_contracts",
        "project_performance_revenue",
    ),
}
_ROW_REQUIREMENTS: Mapping[str, tuple[IndustryFactType, ...]] = {
    "I-ECOM-01": ("gmv", "revenue", "take_rate"),
    "I-ECOM-02": ("traffic", "conversion_rate", "customer_acquisition_cost", "retention"),
    "I-ECOM-03": ("merchant_concentration", "customer_concentration"),
    "I-ECOM-04": (
        "logistics_model", "inventory_ownership", "fulfilment_cost",
        "customer_collection_timing", "merchant_settlement_timing",
    ),
    "I-EPC-01": (
        "signed_backlog", "binding_terms", "cancellation_terms", "price_adjustment",
        "execution_period",
    ),
    "I-EPC-02": ("progress_measure", "total_cost_estimate", "project_margin", "cost_overrun"),
    "I-EPC-03": (
        "contract_assets", "contract_liabilities", "billing_milestone", "receivable_conversion",
    ),
    "I-EPC-04": (
        "retention_receivable", "warranty_provision", "change_orders", "claims",
        "acceptance_disputes",
    ),
    "I-EPC-05": (
        "customer_collection", "supplier_payment", "advance_receipts", "project_cash_conversion",
    ),
}
_ROUTE_ROWS: Mapping[BusinessModel, tuple[str, ...]] = {
    "ecommerce_platform": tuple(item for item in _ROW_REQUIREMENTS if item.startswith("I-ECOM")),
    "project_engineering_epc": tuple(item for item in _ROW_REQUIREMENTS if item.startswith("I-EPC")),
}
_MONITORING: Mapping[str, tuple[str, ...]] = {
    "I-ECOM-01": ("依公司定義的GMV", "依公司收入認列口徑的營收", "依公司定義的take rate"),
    "I-ECOM-02": ("流量", "轉換率", "獲客成本CAC", "留存"),
    "I-ECOM-03": ("商家集中度", "客戶集中度"),
    "I-ECOM-04": ("物流模式與成本", "存貨所有權", "收款與商家結算時點", "營運資金占用"),
    "I-EPC-01": ("已簽約在手訂單", "取消與調價條款", "預計執行期"),
    "I-EPC-02": ("完工程度", "估計總成本", "專案毛利", "成本追加／超支"),
    "I-EPC-03": ("合約資產", "合約負債", "請款里程碑", "轉應收時點"),
    "I-EPC-04": ("保留款", "保固準備", "變更單", "索賠", "驗收與爭議"),
    "I-EPC-05": ("業主收款", "供應商付款", "預收款", "專案現金轉換"),
}
_MECHANISMS: Mapping[str, str] = {
    "I-ECOM-01": "GMV不等於收入；必須保留公司各自GMV、收入與take rate定義後才能比較其轉換。",
    "I-ECOM-02": "流量經轉換形成交易，獲客成本與留存共同決定成長是否可持續。",
    "I-ECOM-03": "商家或客戶集中會把單一對手方流失傳導至交易、收入及收款。",
    "I-ECOM-04": "自營／平台、存貨所有權、履約成本及收付時點共同決定物流負擔與營運資金占用。",
    "I-EPC-01": "只有已簽約且條款可辨識的backlog才可連到執行期；在手訂單不直接等於收入。",
    "I-EPC-02": "完工程度與估計總成本共同影響專案收入、毛利及成本超支重估。",
    "I-EPC-03": "履約、請款里程碑、合約資產轉應收及合約負債轉收入的時差影響收現。",
    "I-EPC-04": "保留款、保固、變更單、索賠及驗收爭議會影響可收金額、準備及最終毛利。",
    "I-EPC-05": "業主收款、預收與供應商付款時序共同決定專案現金轉換，不以單一合約餘額替代。",
}


class EcommerceEpcEvidenceError(ValueError):
    """Raised when route or producer evidence violates the closed contract."""


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise EcommerceEpcEvidenceError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise EcommerceEpcEvidenceError(f"{field} must be timezone-aware")
    return result


def _validate_citation(citation: EvidenceCitation, period: str) -> None:
    if citation.period != period:
        raise EcommerceEpcEvidenceError("evidence period must match citation period")
    if citation.source_tier not in {"official", "issuer_primary"}:
        raise EcommerceEpcEvidenceError("route and industry facts require official evidence")
    if not citation.verbatim_excerpt.strip():
        raise EcommerceEpcEvidenceError("verbatim evidence is required")
    _instant(citation.available_at, "citation available_at")


@dataclass(frozen=True, slots=True)
class BusinessModelRouteClaim:
    business_model: BusinessModel
    claim_part: RouteClaimPart
    value: str
    period: str
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if self.business_model not in _ROUTE_REQUIREMENTS:
            raise EcommerceEpcEvidenceError("unsupported business model")
        if self.claim_part not in _ROUTE_REQUIREMENTS[self.business_model]:
            raise EcommerceEpcEvidenceError("claim part does not belong to business model")
        if not self.value.strip() or not self.period.strip():
            raise EcommerceEpcEvidenceError("route claim requires value and period")
        _validate_citation(self.citation, self.period)


@dataclass(frozen=True, slots=True)
class EcommerceEpcEvidenceFact:
    fact_type: IndustryFactType
    value: str
    definition: str
    period: str
    scope: str
    signal: EvidenceSignal
    evidence_role: EvidenceRole
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if self.fact_type not in IndustryFactType.__args__:  # type: ignore[attr-defined]
            raise EcommerceEpcEvidenceError(f"unsupported industry fact: {self.fact_type}")
        if not self.value.strip() or not self.definition.strip():
            raise EcommerceEpcEvidenceError("industry fact requires value and definition")
        if not self.period.strip() or not self.scope.strip():
            raise EcommerceEpcEvidenceError("industry fact requires period and scope")
        if self.signal not in {"risk", "counterevidence"}:
            raise EcommerceEpcEvidenceError("invalid evidence signal")
        if self.evidence_role not in {"substantive", "context"}:
            raise EcommerceEpcEvidenceError("invalid evidence role")
        _validate_citation(self.citation, self.period)


@dataclass(frozen=True, slots=True)
class EcommerceEpcAssessment:
    route: BusinessModel | Literal["unresolved"]
    route_status: RouteStatus
    route_evidence_ids: tuple[str, ...]
    route_unresolved_reasons: tuple[str, ...]
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    excluded_future_evidence_ids: tuple[str, ...]
    schema_version: Literal["EcommerceEpcAssessment.v1"] = "EcommerceEpcAssessment.v1"

    def check(self, check_id: str) -> ChecklistCheckResult:
        try:
            return next(item for item in self.checks if item.check_id == check_id)
        except StopIteration as exc:
            raise KeyError(check_id) from exc

    @property
    def by_check_id(self) -> Mapping[str, ChecklistCheckResult]:
        return {item.check_id: item for item in self.checks}


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _build_row(check_id: str, facts: Sequence[EcommerceEpcEvidenceFact]) -> ChecklistCheckResult:
    requirements = _ROW_REQUIREMENTS[check_id]
    relevant = tuple(item for item in facts if item.fact_type in requirements)
    substantive = tuple(item for item in relevant if item.evidence_role == "substantive")
    present = {item.fact_type for item in substantive}
    missing = tuple(item for item in requirements if item not in present)
    risk = tuple(item for item in substantive if item.signal == "risk")
    counter = tuple(item for item in substantive if item.signal == "counterevidence")
    periods = sorted({item.period for item in substantive})
    triggered = bool(risk)
    evidence_ids = _unique(tuple(item.citation.evidence_id for item in relevant))
    observations = _unique(tuple(item.value for item in relevant))
    definitions = _unique(tuple(item.definition for item in relevant))

    if missing:
        reason = (
            "未取得本題任何claim-specific官方證據；資料缺口不得解讀為沒有風險。"
            if not relevant
            else "已保留部分官方證據；尚缺：" + "、".join(missing) + "。"
        )
        return ChecklistCheckResult(
            check_id=check_id, domain="industry",
            applicability="triggered" if triggered else "unresolved", status="unresolved",
            first_detectable_at=min((item.citation.available_at for item in relevant), default=None),
            financial_period="/".join(periods) or None,
            observations=observations, evidence_ids=evidence_ids,
            supporting_evidence=_unique(tuple(item.value for item in risk)),
            counterevidence=_unique(tuple(item.value for item in counter)),
            inference_chain=definitions,
            mechanism=_MECHANISMS[check_id], leading_warnings=_MONITORING[check_id],
            buffers=_unique(tuple(item.value for item in counter)),
            monitoring_metrics=_MONITORING[check_id], monitoring_date=None,
            invalidation_or_resolution_conditions=("補齊缺少的原始定義、數值或條款後重新評估。",),
            severity="medium" if triggered else "not_applicable", confidence="low",
            unresolved_reasons=(reason,),
        )

    return ChecklistCheckResult(
        check_id=check_id, domain="industry",
        applicability="triggered" if triggered else "not_triggered", status="evaluated",
        first_detectable_at=min(item.citation.available_at for item in substantive),
        financial_period="/".join(periods), observations=observations,
        evidence_ids=evidence_ids,
        supporting_evidence=_unique(tuple(item.value for item in risk)),
        counterevidence=_unique(tuple(item.value for item in counter)),
        inference_chain=definitions,
        mechanism=_MECHANISMS[check_id], leading_warnings=_MONITORING[check_id],
        buffers=_unique(tuple(item.value for item in counter)),
        monitoring_metrics=_MONITORING[check_id], monitoring_date=None,
        invalidation_or_resolution_conditions=("新一期同定義數值或合約條款更新目前判定。",),
        severity="high" if triggered else "low", confidence="high",
        unresolved_reasons=(),
    )


def build_ecommerce_epc_assessment(
    route_claims: Sequence[BusinessModelRouteClaim],
    facts: Sequence[EcommerceEpcEvidenceFact],
    *,
    as_of: str,
) -> EcommerceEpcAssessment:
    """Route and assess I-ECOM-01..04 or I-EPC-01..05 from official claims."""

    decision_time = _instant(as_of, "as_of")
    admitted_claims = tuple(
        item for item in route_claims
        if _instant(item.citation.available_at, "citation available_at") <= decision_time
    )
    admitted_facts = tuple(
        item for item in facts
        if _instant(item.citation.available_at, "citation available_at") <= decision_time
    )
    excluded = _unique(tuple(
        item.citation.evidence_id
        for item in (*route_claims, *facts)
        if _instant(item.citation.available_at, "citation available_at") > decision_time
    ))
    complete_models: tuple[BusinessModel, ...] = tuple(
        model for model, requirements in _ROUTE_REQUIREMENTS.items()
        if set(requirements).issubset({item.claim_part for item in admitted_claims if item.business_model == model})
    )
    route_evidence_ids = _unique(tuple(item.citation.evidence_id for item in admitted_claims))
    citations = tuple({
        item.citation.evidence_id: item.citation for item in (*admitted_claims, *admitted_facts)
    }.values())

    if len(complete_models) != 1:
        if len(complete_models) > 1:
            reasons = ("conflicting complete official business-model routes",)
        elif not admitted_claims:
            reasons = ("missing point-in-time official business-model route evidence",)
        else:
            missing_parts = tuple(
                f"{model}:{part}"
                for model, requirements in _ROUTE_REQUIREMENTS.items()
                for part in requirements
                if part not in {item.claim_part for item in admitted_claims if item.business_model == model}
            )
            reasons = ("incomplete official business-model route claims: " + ",".join(missing_parts),)
        return EcommerceEpcAssessment(
            route="unresolved", route_status="unresolved",
            route_evidence_ids=route_evidence_ids, route_unresolved_reasons=reasons,
            checks=(), citations=citations, excluded_future_evidence_ids=excluded,
        )

    route = complete_models[0]
    return EcommerceEpcAssessment(
        route=route, route_status="routed", route_evidence_ids=route_evidence_ids,
        route_unresolved_reasons=(),
        checks=tuple(_build_row(check_id, admitted_facts) for check_id in _ROUTE_ROWS[route]),
        citations=citations, excluded_future_evidence_ids=excluded,
    )


__all__ = [
    "BusinessModelRouteClaim", "EcommerceEpcAssessment", "EcommerceEpcEvidenceError",
    "EcommerceEpcEvidenceFact", "build_ecommerce_epc_assessment",
]
