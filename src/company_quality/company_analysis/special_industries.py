"""Fail-closed evidence producers for biotech and energy industry checks.

The official company-list route selects the applicable checklist; cited issuer-
bound facts evaluate it.  Security codes, issuer names, headings and other
context records never select a route or complete a requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.industry.routing import IndustryRoute

SpecialIndustryFactType = Literal[
    "clinical_stage",
    "trial_endpoint",
    "enrollment",
    "regulatory_status",
    "approval_status",
    "ip_rights",
    "commercial_evidence",
    "reserves",
    "capacity",
    "utilization",
    "contract_terms",
    "commodity_exposure",
    "capex",
    "decommissioning",
]
SpecialIndustrySignal = Literal["risk", "counterevidence"]
EvidenceRole = Literal["substantive", "context"]

_FACT_TYPES = frozenset(SpecialIndustryFactType.__args__)  # type: ignore[attr-defined]
_BIOTECH_REQUIREMENTS: Mapping[str, tuple[SpecialIndustryFactType, ...]] = {
    "I-BIO-01": ("clinical_stage",),
    "I-BIO-02": ("trial_endpoint", "enrollment"),
    "I-BIO-03": ("regulatory_status", "approval_status"),
    "I-BIO-04": ("ip_rights",),
    "I-BIO-05": ("commercial_evidence",),
}
_ENERGY_REQUIREMENTS: Mapping[str, tuple[SpecialIndustryFactType, ...]] = {
    "I-ENERGY-01": ("reserves",),
    "I-ENERGY-02": ("capacity", "utilization"),
    "I-ENERGY-03": ("contract_terms",),
    "I-ENERGY-04": ("commodity_exposure",),
    "I-ENERGY-05": ("capex", "decommissioning"),
}
_MONITORING: Mapping[str, tuple[str, ...]] = {
    "I-BIO-01": ("臨床階段",),
    "I-BIO-02": ("試驗終點", "收案進度"),
    "I-BIO-03": ("監管進度", "核准狀態"),
    "I-BIO-04": ("智慧財產權與有效期間",),
    "I-BIO-05": ("商業化與收入證據",),
    "I-ENERGY-01": ("儲量",),
    "I-ENERGY-02": ("產能", "利用率"),
    "I-ENERGY-03": ("合約條款",),
    "I-ENERGY-04": ("商品價格曝險",),
    "I-ENERGY-05": ("資本支出", "除役義務"),
}
_MECHANISMS: Mapping[str, str] = {
    "I-BIO-01": "臨床階段決定研發時程、資金需求與失敗風險。",
    "I-BIO-02": "試驗終點與收案進度共同決定臨床結果能否按期形成。",
    "I-BIO-03": "監管及核准狀態決定產品能否合法進入市場。",
    "I-BIO-04": "智慧財產權的範圍與有效期間影響排他性及未來現金流。",
    "I-BIO-05": "商業化證據決定研發成果是否已傳導至收入與現金。",
    "I-ENERGY-01": "可採儲量限制未來產量、收入與資產價值。",
    "I-ENERGY-02": "產能與利用率共同影響固定成本吸收、收入與現金流。",
    "I-ENERGY-03": "合約期限、定價與取消條款決定收入能見度及固定義務。",
    "I-ENERGY-04": "商品價格曝險會傳導至營收、毛利與營運現金流。",
    "I-ENERGY-05": "資本支出與除役義務共同形成長期資金需求及尾端負債。",
}


class SpecialIndustryEvidenceError(ValueError):
    """Raised when specialised-industry evidence violates its contract."""


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SpecialIndustryEvidenceError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise SpecialIndustryEvidenceError(f"{field} must be timezone-aware")
    return result


@dataclass(frozen=True, slots=True)
class SpecialIndustryEvidenceFact:
    issuer_id: str
    fact_type: SpecialIndustryFactType
    value: str
    period: str
    signal: SpecialIndustrySignal
    evidence_role: EvidenceRole
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if not self.issuer_id.strip():
            raise SpecialIndustryEvidenceError("special-industry fact requires issuer_id")
        if self.fact_type not in _FACT_TYPES:
            raise SpecialIndustryEvidenceError(
                f"unsupported special-industry fact: {self.fact_type}"
            )
        if self.signal not in {"risk", "counterevidence"}:
            raise SpecialIndustryEvidenceError("invalid special-industry signal")
        if self.evidence_role not in {"substantive", "context"}:
            raise SpecialIndustryEvidenceError("invalid special-industry evidence role")
        if not self.value.strip() or not self.period.strip():
            raise SpecialIndustryEvidenceError(
                "special-industry fact requires value and period"
            )
        if self.period != self.citation.period:
            raise SpecialIndustryEvidenceError(
                "special-industry fact period must match citation period"
            )
        if self.citation.source_tier not in {"official", "issuer_primary"}:
            raise SpecialIndustryEvidenceError(
                "special-industry facts require official or issuer-primary citations"
            )
        if not self.citation.evidence_id.strip() or not self.citation.verbatim_excerpt.strip():
            raise SpecialIndustryEvidenceError(
                "special-industry fact requires claim-specific verbatim evidence"
            )
        _instant(self.citation.available_at, "citation available_at")


@dataclass(frozen=True, slots=True)
class SpecialIndustryAssessment:
    issuer_id: str
    industry_route: Literal["biotech", "energy"]
    route_status: Literal["routed"]
    route_evidence_ids: tuple[str, ...]
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    context_evidence_ids: tuple[str, ...]
    schema_version: Literal["SpecialIndustryAssessment.v1"] = (
        "SpecialIndustryAssessment.v1"
    )

    def check(self, check_id: str) -> ChecklistCheckResult:
        try:
            return next(item for item in self.checks if item.check_id == check_id)
        except StopIteration as exc:
            raise KeyError(check_id) from exc

    @property
    def by_check_id(self) -> Mapping[str, ChecklistCheckResult]:
        return {item.check_id: item for item in self.checks}


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in values if item))


def _route_requirements(
    route: IndustryRoute,
) -> tuple[Literal["biotech", "energy"], Mapping[str, tuple[SpecialIndustryFactType, ...]]]:
    if route.status != "routed":
        raise SpecialIndustryEvidenceError("special-industry route must be routed")
    if not route.evidence_ids:
        raise SpecialIndustryEvidenceError("special-industry route evidence is required")
    if (
        route.industry_code == "22"
        and route.sector_code == "biotechnology"
        and "specialised_route:biotech" in route.business_model_tags
    ):
        return "biotech", _BIOTECH_REQUIREMENTS
    if (
        route.industry_code in {"23", "35"}
        and route.sector_code == "energy_utilities"
        and "specialised_route:energy" in route.business_model_tags
    ):
        return "energy", _ENERGY_REQUIREMENTS
    raise SpecialIndustryEvidenceError(
        "official specialised route does not match biotech or energy semantics"
    )


def _build_row(
    check_id: str,
    requirements: Sequence[SpecialIndustryFactType],
    facts: Sequence[SpecialIndustryEvidenceFact],
) -> ChecklistCheckResult:
    required = set(requirements)
    relevant = tuple(item for item in facts if item.fact_type in required)
    substantive = tuple(item for item in relevant if item.evidence_role == "substantive")
    present = {item.fact_type for item in substantive}
    missing = [item for item in requirements if item not in present]
    evidence_ids = _unique(tuple(item.citation.evidence_id for item in relevant))
    observations = _unique(tuple(item.value for item in relevant))
    risk = tuple(item for item in substantive if item.signal == "risk")
    counter = tuple(item for item in substantive if item.signal == "counterevidence")
    # The authority requires every conclusion to retain counterevidence.  A risk
    # claim by itself therefore triggers the row but cannot complete it.
    if risk and not counter:
        missing.append("反證（單一風險主張不得完成本題）")
    periods = sorted({item.period for item in substantive})

    if missing:
        reason = (
            "未取得本題任何claim-specific官方／公司原始證據；資料缺口不得解讀為沒有風險。"
            if not relevant
            else "已保留部分官方／公司原始證據；尚缺："
            + "、".join(missing)
            + "，完整證據鏈尚未完成。"
        )
        return ChecklistCheckResult(
            check_id=check_id,
            domain="industry",
            applicability="triggered" if risk else "unresolved",
            status="unresolved",
            first_detectable_at=min(
                (item.citation.available_at for item in relevant), default=None
            ),
            financial_period="/".join(periods) or None,
            observations=observations,
            evidence_ids=evidence_ids,
            supporting_evidence=_unique(tuple(item.value for item in risk)),
            counterevidence=_unique(tuple(item.value for item in counter)),
            inference_chain=(
                "官方產業路由 → issuer-bound claim-specific證據 → 必要領域 → 尚未完成",
            ),
            mechanism=_MECHANISMS[check_id],
            leading_warnings=_MONITORING[check_id],
            buffers=_unique(tuple(item.value for item in counter)),
            monitoring_metrics=_MONITORING[check_id],
            monitoring_date=None,
            invalidation_or_resolution_conditions=("補齊缺少領域後重新評估。",),
            severity="medium" if risk else "not_applicable",
            confidence="low",
            unresolved_reasons=(reason,),
        )

    return ChecklistCheckResult(
        check_id=check_id,
        domain="industry",
        applicability="triggered" if risk else "not_triggered",
        status="evaluated",
        first_detectable_at=min(item.citation.available_at for item in substantive),
        financial_period="/".join(periods),
        observations=observations,
        evidence_ids=evidence_ids,
        supporting_evidence=_unique(tuple(item.value for item in risk)),
        counterevidence=_unique(tuple(item.value for item in counter)),
        inference_chain=(
            "官方產業路由 → issuer-bound claim-specific證據 → 完整必要領域 → 風險與反證分列",
        ),
        mechanism=_MECHANISMS[check_id],
        leading_warnings=_MONITORING[check_id],
        buffers=_unique(tuple(item.value for item in counter)),
        monitoring_metrics=_MONITORING[check_id],
        monitoring_date=None,
        invalidation_or_resolution_conditions=("新一期證據或狀態更新目前判定。",),
        severity="high" if risk else "low",
        confidence="high",
        unresolved_reasons=(),
    )


def build_special_industry_assessment(
    route: IndustryRoute,
    facts: Sequence[SpecialIndustryEvidenceFact],
) -> SpecialIndustryAssessment:
    """Evaluate exact I-BIO-01..05 or I-ENERGY-01..05 requirements."""

    industry_route, requirements = _route_requirements(route)
    decision_time = _instant(route.decision_time, "route decision_time")
    for item in facts:
        if item.issuer_id != route.issuer_id:
            raise SpecialIndustryEvidenceError("special-industry fact issuer mismatch")
        if _instant(item.citation.available_at, "citation available_at") > decision_time:
            raise SpecialIndustryEvidenceError(
                "special-industry evidence violates PIT decision-time boundary"
            )

    citations = tuple(
        {item.citation.evidence_id: item.citation for item in facts}.values()
    )
    return SpecialIndustryAssessment(
        issuer_id=route.issuer_id,
        industry_route=industry_route,
        route_status="routed",
        route_evidence_ids=tuple(route.evidence_ids),
        checks=tuple(
            _build_row(check_id, row_requirements, facts)
            for check_id, row_requirements in requirements.items()
        ),
        citations=citations,
        context_evidence_ids=_unique(
            tuple(
                item.citation.evidence_id
                for item in facts
                if item.evidence_role == "context"
            )
        ),
    )


__all__ = [
    "SpecialIndustryAssessment",
    "SpecialIndustryEvidenceError",
    "SpecialIndustryEvidenceFact",
    "build_special_industry_assessment",
]
