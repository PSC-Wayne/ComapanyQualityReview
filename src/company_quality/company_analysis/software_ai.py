"""PIT software/AI routing and claim-complete I-SW-01 through I-SW-05 producers.

The authoritative software/subscription add-on has no numeric thresholds.  This
module therefore evaluates the exact disclosed domains and their comparable
periods; it never turns a keyword, company name, broad industry code, current
feed absence, or caller completion boolean into a conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.history_context import HistoricalContextAssessment
from company_quality.identity import CompanyIdentity

SoftwareAIFactType = Literal[
    "recurring_revenue",
    "renewal",
    "churn",
    "arpu",
    "contract_liability",
    "deferred_revenue",
    "revenue_conversion",
    "contract_acquisition_cost",
    "development_cost_capitalization",
    "cloud_cost",
    "service_cost",
    "gross_margin",
    "share_based_payment_cost",
    "dilution",
]
SoftwareAISignal = Literal["risk", "counterevidence"]
EvidenceRole = Literal["substantive", "context"]
SoftwareAIRoute = Literal["software_ai", "not_applicable", "unresolved"]

_FACT_TYPES = frozenset(SoftwareAIFactType.__args__)  # type: ignore[attr-defined]
_REQUIREMENTS: Mapping[str, tuple[SoftwareAIFactType, ...]] = {
    "I-SW-01": ("recurring_revenue", "renewal", "churn", "arpu"),
    "I-SW-02": ("contract_liability", "deferred_revenue", "revenue_conversion"),
    "I-SW-03": ("contract_acquisition_cost", "development_cost_capitalization"),
    "I-SW-04": ("cloud_cost", "service_cost", "gross_margin"),
    "I-SW-05": ("share_based_payment_cost", "dilution"),
}
_TREND_ROWS = frozenset({"I-SW-01", "I-SW-02", "I-SW-04", "I-SW-05"})
_MONITORING: Mapping[str, tuple[str, ...]] = {
    "I-SW-01": ("經常性收入", "續約率", "流失率", "每戶收入 ARPU"),
    "I-SW-02": ("合約負債", "遞延收入", "遞延收入轉收入金額與期間"),
    "I-SW-03": ("取得合約成本", "開發成本資本化", "攤銷與減損"),
    "I-SW-04": ("雲端成本", "服務成本", "毛利率"),
    "I-SW-05": ("股份基礎給付費用", "基本／稀釋股數", "基本／稀釋 EPS"),
}
_MECHANISMS: Mapping[str, str] = {
    "I-SW-01": "經常性收入須由續約、流失與每戶收入共同解釋；單看收入總額不能證明訂閱品質。",
    "I-SW-02": "合約負債與遞延收入只有按履約轉為收入後才形成已實現營收，轉換時點會影響能見度。",
    "I-SW-03": "取得合約成本與開發成本資本化會把現期支出遞延至後續期間，影響當期獲利與未來攤銷／減損。",
    "I-SW-04": "雲端與服務交付成本會直接傳導至服務毛利；營收成長不代表單位經濟改善。",
    "I-SW-05": "股份基礎給付同時形成真實人事成本與潛在股權稀釋，須與稀釋股數及每股結果共同觀察。",
}


class SoftwareAIEvidenceError(ValueError):
    """Raised when software/AI evidence violates identity, source or PIT rules."""


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise SoftwareAIEvidenceError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise SoftwareAIEvidenceError(f"{field} must be timezone-aware")
    return result


@dataclass(frozen=True, slots=True)
class SoftwareAIEvidenceFact:
    issuer_id: str
    fact_type: SoftwareAIFactType
    value: str
    period: str
    scope: str
    signal: SoftwareAISignal
    evidence_role: EvidenceRole
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if not self.issuer_id.strip():
            raise SoftwareAIEvidenceError("software fact requires issuer identity")
        if self.fact_type not in _FACT_TYPES:
            raise SoftwareAIEvidenceError(f"unsupported software fact: {self.fact_type}")
        if self.signal not in {"risk", "counterevidence"}:
            raise SoftwareAIEvidenceError("invalid software signal")
        if self.evidence_role not in {"substantive", "context"}:
            raise SoftwareAIEvidenceError("invalid software evidence role")
        if not self.value.strip() or not self.period.strip() or not self.scope.strip():
            raise SoftwareAIEvidenceError("software fact requires value, period and scope")
        if self.citation.period != self.period:
            raise SoftwareAIEvidenceError("software fact period must match citation period")
        if self.citation.source_tier not in {"official", "issuer_primary"}:
            raise SoftwareAIEvidenceError(
                "software facts require official or issuer-primary citations"
            )
        if not self.citation.verbatim_excerpt.strip():
            raise SoftwareAIEvidenceError("software fact requires verbatim evidence")
        _instant(self.citation.available_at, "citation available_at")


@dataclass(frozen=True, slots=True)
class SoftwareAIAssessment:
    issuer_id: str
    as_of: str
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    context_evidence_ids: tuple[str, ...]
    excluded_post_as_of_evidence_ids: tuple[str, ...]
    schema_version: Literal["SoftwareAIAssessment.v1"] = "SoftwareAIAssessment.v1"

    def check(self, check_id: str) -> ChecklistCheckResult:
        try:
            return next(item for item in self.checks if item.check_id == check_id)
        except StopIteration as exc:
            raise KeyError(check_id) from exc

    @property
    def by_check_id(self) -> Mapping[str, ChecklistCheckResult]:
        return {item.check_id: item for item in self.checks}


@dataclass(frozen=True, slots=True)
class SoftwareAIRouteDecision:
    route: SoftwareAIRoute
    status: Literal["routed", "not_applicable", "blocked"]
    reason: str | None
    issuer_id: str
    official_industry_code: str | None
    evidence_ids: tuple[str, ...]
    as_of: str | None
    schema_version: Literal["SoftwareAIRouteDecision.v1"] = "SoftwareAIRouteDecision.v1"


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def resolve_software_ai_route(
    *,
    identity: CompanyIdentity,
    context: HistoricalContextAssessment | None,
) -> SoftwareAIRouteDecision:
    """Route official industry 30 only after issuer-level model/product evidence.

    The official industry code is the first router, but code 30 is intentionally
    not sufficient by itself.  The same official issuer must also have admitted
    issuer-primary business-model and products/services claims from the #131
    historical-context contract.  Claim text and company names are never parsed
    for route keywords.
    """

    identity_evidence = (f"identity:{identity.security_id}",)
    if identity.industry_code != "30":
        return SoftwareAIRouteDecision(
            route="not_applicable",
            status="not_applicable",
            reason=None,
            issuer_id=identity.issuer_id,
            official_industry_code=identity.industry_code,
            evidence_ids=identity_evidence,
            as_of=context.as_of if context is not None else None,
        )
    if context is None:
        return SoftwareAIRouteDecision(
            route="unresolved",
            status="blocked",
            reason="company_level_business_evidence_missing",
            issuer_id=identity.issuer_id,
            official_industry_code=identity.industry_code,
            evidence_ids=identity_evidence,
            as_of=None,
        )
    if context.issuer_id != identity.issuer_id:
        raise SoftwareAIEvidenceError("software route issuer mismatch")
    by_axis = {
        axis: tuple(item for item in context.business_claims if item.axis == axis)
        for axis in ("business_model", "products_services")
    }
    admitted_ids = _unique(
        tuple(item.evidence_id for claims in by_axis.values() for item in claims)
    )
    if any(not claims for claims in by_axis.values()):
        return SoftwareAIRouteDecision(
            route="unresolved",
            status="blocked",
            reason="company_level_business_evidence_incomplete",
            issuer_id=identity.issuer_id,
            official_industry_code=identity.industry_code,
            evidence_ids=(*identity_evidence, *admitted_ids),
            as_of=context.as_of,
        )
    return SoftwareAIRouteDecision(
        route="software_ai",
        status="routed",
        reason=None,
        issuer_id=identity.issuer_id,
        official_industry_code=identity.industry_code,
        evidence_ids=(*identity_evidence, *admitted_ids),
        as_of=context.as_of,
    )


def _missing_domains(
    check_id: str,
    substantive: Sequence[SoftwareAIEvidenceFact],
) -> tuple[str, ...]:
    requirements = _REQUIREMENTS[check_id]
    present = {item.fact_type for item in substantive}
    missing = [item for item in requirements if item not in present]
    if check_id in _TREND_ROWS:
        periods_by_scope_type: dict[tuple[str, str], set[str]] = {}
        for item in substantive:
            periods_by_scope_type.setdefault((item.scope, item.fact_type), set()).add(item.period)
        comparable_scope = any(
            all(len(periods_by_scope_type.get((scope, fact_type), set())) >= 2 for fact_type in requirements)
            for scope in {item.scope for item in substantive}
        )
        if not comparable_scope:
            missing.append("同一範圍至少兩期的可比較證據")
    if substantive and not any(item.signal == "counterevidence" for item in substantive):
        missing.append("反證／緩衝證據")
    return _unique(missing)


def _build_row(
    check_id: str,
    facts: Sequence[SoftwareAIEvidenceFact],
) -> ChecklistCheckResult:
    required = set(_REQUIREMENTS[check_id])
    relevant = tuple(item for item in facts if item.fact_type in required)
    substantive = tuple(item for item in relevant if item.evidence_role == "substantive")
    missing = _missing_domains(check_id, substantive)
    risk = tuple(item for item in substantive if item.signal == "risk")
    counter = tuple(item for item in substantive if item.signal == "counterevidence")
    evidence_ids = _unique(tuple(item.citation.evidence_id for item in relevant))
    observations = _unique(tuple(item.value for item in relevant))
    periods = sorted({item.period for item in substantive})
    triggered = bool(risk)

    if missing:
        reason = (
            "未取得本題任何claim-specific官方／公司原始證據；資料缺口不得解讀為沒有風險。"
            if not relevant
            else "已保留部分官方／公司原始證據；尚缺：" + "、".join(missing) + "。"
        )
        return ChecklistCheckResult(
            check_id=check_id,
            domain="industry",
            applicability="triggered" if triggered else "unresolved",
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
                "同一官方發行人 → claim-specific期間與範圍 → 軟體／訂閱清單必要領域 → 尚未完成",
            ),
            mechanism=_MECHANISMS[check_id],
            leading_warnings=_MONITORING[check_id],
            buffers=_unique(tuple(item.value for item in counter)),
            monitoring_metrics=_MONITORING[check_id],
            monitoring_date=None,
            invalidation_or_resolution_conditions=(
                "補齊缺少領域、反證、期間與範圍後重新評估。",
            ),
            severity="medium" if triggered else "not_applicable",
            confidence="low",
            unresolved_reasons=(reason,),
        )

    return ChecklistCheckResult(
        check_id=check_id,
        domain="industry",
        applicability="triggered" if triggered else "not_triggered",
        status="evaluated",
        first_detectable_at=min(item.citation.available_at for item in substantive),
        financial_period="/".join(periods),
        observations=observations,
        evidence_ids=evidence_ids,
        supporting_evidence=_unique(tuple(item.value for item in risk)),
        counterevidence=_unique(tuple(item.value for item in counter)),
        inference_chain=(
            "同一官方發行人 → claim-specific期間與範圍 → 完整軟體／訂閱領域 → 風險與反證分列",
        ),
        mechanism=_MECHANISMS[check_id],
        leading_warnings=_MONITORING[check_id],
        buffers=_unique(tuple(item.value for item in counter)),
        monitoring_metrics=_MONITORING[check_id],
        monitoring_date=None,
        invalidation_or_resolution_conditions=("新一期同範圍證據或揭露政策更新目前判定。",),
        severity="high" if triggered else "low",
        confidence="high",
        unresolved_reasons=(),
    )


def build_software_ai_assessment(
    *,
    issuer_id: str,
    as_of: str,
    facts: Sequence[SoftwareAIEvidenceFact],
) -> SoftwareAIAssessment:
    """Assess I-SW-01..05 from admitted evidence contents and PIT availability."""

    if not issuer_id.strip():
        raise SoftwareAIEvidenceError("software assessment requires issuer identity")
    cutoff = _instant(as_of, "as_of")
    for item in facts:
        if item.issuer_id != issuer_id:
            raise SoftwareAIEvidenceError("software fact issuer mismatch")
    admitted = tuple(
        item for item in facts
        if _instant(item.citation.available_at, "citation available_at") <= cutoff
    )
    excluded = tuple(
        item for item in facts
        if _instant(item.citation.available_at, "citation available_at") > cutoff
    )
    citations = tuple(
        {item.citation.evidence_id: item.citation for item in admitted}.values()
    )
    return SoftwareAIAssessment(
        issuer_id=issuer_id,
        as_of=as_of,
        checks=tuple(_build_row(check_id, admitted) for check_id in _REQUIREMENTS),
        citations=citations,
        context_evidence_ids=_unique(tuple(
            item.citation.evidence_id for item in admitted if item.evidence_role == "context"
        )),
        excluded_post_as_of_evidence_ids=_unique(tuple(
            item.citation.evidence_id for item in excluded
        )),
    )


__all__ = [
    "SoftwareAIAssessment",
    "SoftwareAIEvidenceError",
    "SoftwareAIEvidenceFact",
    "SoftwareAIRouteDecision",
    "build_software_ai_assessment",
    "resolve_software_ai_route",
]
