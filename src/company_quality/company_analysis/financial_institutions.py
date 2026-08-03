"""Fail-closed financial-institution routing and I-FIN checklist producers.

The route uses the official financial-industry identity plus claim-specific,
company-level regulated-business evidence.  Company names are intentionally not
accepted.  Each subtype owns one disjoint metric family; no generic-company
quantitative metric or threshold is used here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult, CompanyRoute
from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.identity import CompanyIdentity

FinancialSubtype = Literal["bank", "life_insurer", "property_insurer", "securities_firm"]
RouteStatus = Literal["routed", "blocked", "not_applicable"]
RouteClaimPart = Literal[
    "regulated_license",
    "deposit_taking",
    "lending",
    "life_insurance_underwriting",
    "long_term_policy_obligations",
    "property_casualty_underwriting",
    "claims_obligations",
    "securities_brokerage_dealing",
    "securities_regulatory_capital",
]
FinancialFactType = Literal[
    "net_interest_margin",
    "nonperforming_loan_ratio",
    "common_equity_tier1_ratio",
    "contractual_service_margin",
    "solvency_ratio",
    "insurance_contract_reserve",
    "asset_liability_mismatch",
    "combined_ratio",
    "loss_ratio",
    "brokerage_revenue",
    "trading_income",
    "capital_adequacy_ratio",
]
EvidenceSignal = Literal["risk", "counterevidence"]
EvidenceRole = Literal["substantive", "context"]

_ROUTE_REQUIREMENTS: Mapping[FinancialSubtype, tuple[RouteClaimPart, ...]] = {
    "bank": ("regulated_license", "deposit_taking", "lending"),
    "life_insurer": (
        "regulated_license",
        "life_insurance_underwriting",
        "long_term_policy_obligations",
    ),
    "property_insurer": (
        "regulated_license",
        "property_casualty_underwriting",
        "claims_obligations",
    ),
    "securities_firm": (
        "regulated_license",
        "securities_brokerage_dealing",
        "securities_regulatory_capital",
    ),
}
_SUBTYPE_ROWS: Mapping[FinancialSubtype, str] = {
    "bank": "I-FIN-01",
    "life_insurer": "I-FIN-02",
    "property_insurer": "I-FIN-03",
    "securities_firm": "I-FIN-04",
}
_ROW_REQUIREMENTS: Mapping[str, tuple[FinancialFactType, ...]] = {
    "I-FIN-01": (
        "net_interest_margin",
        "nonperforming_loan_ratio",
        "common_equity_tier1_ratio",
    ),
    "I-FIN-02": (
        "contractual_service_margin",
        "solvency_ratio",
        "insurance_contract_reserve",
        "asset_liability_mismatch",
    ),
    "I-FIN-03": ("combined_ratio", "loss_ratio", "insurance_contract_reserve"),
    "I-FIN-04": ("brokerage_revenue", "trading_income", "capital_adequacy_ratio"),
}
_MONITORING: Mapping[str, tuple[str, ...]] = {
    "I-FIN-01": ("淨利差NIM", "逾放比NPL", "普通股權益第一類資本CET1"),
    "I-FIN-02": ("合約服務邊際CSM", "清償能力", "保險合約負債／準備", "資產負債期限與幣別錯配"),
    "I-FIN-03": ("綜合率", "損失率", "保險合約負債／準備"),
    "I-FIN-04": ("經紀業務收入", "交易損益", "資本適足／法定資本"),
}
_MECHANISMS: Mapping[str, str] = {
    "I-FIN-01": "銀行利差、資產品質與普通股核心資本須共同檢查；NIM、NPL與CET1不得被其他金融業指標替代。",
    "I-FIN-02": "壽險新契約服務邊際、清償能力、保險負債準備及資產負債錯配共同影響長期履約能力。",
    "I-FIN-03": "產險承保損益須以綜合率與損失率連同準備充足性檢查，不以壽險CSM替代。",
    "I-FIN-04": "證券商經紀與交易損益來源不同，必須連同法定資本承受交易及市場波動能力檢查。",
}


class FinancialInstitutionEvidenceError(ValueError):
    """Raised when financial route or fact evidence violates the contract."""


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise FinancialInstitutionEvidenceError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise FinancialInstitutionEvidenceError(f"{field} must be timezone-aware")
    return result


def _validate_citation(citation: EvidenceCitation, period: str) -> None:
    if citation.period != period:
        raise FinancialInstitutionEvidenceError("evidence period must match citation period")
    if citation.source_tier not in {"official", "issuer_primary"}:
        raise FinancialInstitutionEvidenceError("financial evidence requires official or issuer-primary source")
    if not citation.verbatim_excerpt.strip():
        raise FinancialInstitutionEvidenceError("verbatim financial evidence is required")
    _instant(citation.available_at, "citation available_at")


@dataclass(frozen=True, slots=True)
class FinancialSubtypeRouteClaim:
    issuer_id: str
    security_code: str
    financial_subtype: FinancialSubtype
    claim_part: RouteClaimPart
    value: str
    period: str
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if self.financial_subtype not in _ROUTE_REQUIREMENTS:
            raise FinancialInstitutionEvidenceError("unsupported financial subtype")
        if self.claim_part not in _ROUTE_REQUIREMENTS[self.financial_subtype]:
            raise FinancialInstitutionEvidenceError("route claim does not belong to subtype")
        if not self.issuer_id or not self.security_code or not self.value.strip() or not self.period.strip():
            raise FinancialInstitutionEvidenceError("route claim requires identity, value and period")
        _validate_citation(self.citation, self.period)


@dataclass(frozen=True, slots=True)
class FinancialInstitutionFact:
    issuer_id: str
    security_code: str
    fact_type: FinancialFactType
    value: str
    definition: str
    period: str
    scope: str
    signal: EvidenceSignal
    evidence_role: EvidenceRole
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if self.fact_type not in FinancialFactType.__args__:  # type: ignore[attr-defined]
            raise FinancialInstitutionEvidenceError(f"unsupported financial fact: {self.fact_type}")
        if not self.issuer_id or not self.security_code:
            raise FinancialInstitutionEvidenceError("financial fact requires issuer identity")
        if not self.value.strip() or not self.definition.strip():
            raise FinancialInstitutionEvidenceError("financial fact requires value and definition")
        if not self.period.strip() or not self.scope.strip():
            raise FinancialInstitutionEvidenceError("financial fact requires period and scope")
        if self.signal not in {"risk", "counterevidence"}:
            raise FinancialInstitutionEvidenceError("invalid financial evidence signal")
        if self.evidence_role not in {"substantive", "context"}:
            raise FinancialInstitutionEvidenceError("invalid financial evidence role")
        _validate_citation(self.citation, self.period)


@dataclass(frozen=True, slots=True)
class FinancialInstitutionAssessment:
    issuer_id: str
    security_code: str
    as_of: str
    financial_subtype: FinancialSubtype | Literal["unresolved", "not_applicable"]
    company_route: CompanyRoute
    route_status: RouteStatus
    route_evidence_ids: tuple[str, ...]
    route_unresolved_reasons: tuple[str, ...]
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    excluded_post_as_of_evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: Literal["FinancialInstitutionAssessment.v1"] = "FinancialInstitutionAssessment.v1"

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


def _not_applicable_row(check_id: str, subtype: FinancialSubtype) -> ChecklistCheckResult:
    return ChecklistCheckResult(
        check_id=check_id,
        domain="industry",
        applicability="not_applicable",
        status="evaluated",
        first_detectable_at=None,
        financial_period=None,
        observations=(f"本issuer已可靠分流為{subtype}；本列屬其他金融subtype。",),
        evidence_ids=(),
        supporting_evidence=(),
        counterevidence=(),
        inference_chain=("官方金融業身分 → 公司層級受監管業務證據 → subtype專用列",),
        mechanism=_MECHANISMS[check_id],
        leading_warnings=(),
        buffers=(),
        monitoring_metrics=(),
        monitoring_date=None,
        invalidation_or_resolution_conditions=("主管機關分類或公司主要受監管業務改變時重新分流。",),
        severity="not_applicable",
        confidence="not_applicable",
        unresolved_reasons=(),
    )


def _build_row(check_id: str, facts: Sequence[FinancialInstitutionFact]) -> ChecklistCheckResult:
    requirements = _ROW_REQUIREMENTS[check_id]
    relevant = tuple(item for item in facts if item.fact_type in requirements)
    substantive = tuple(item for item in relevant if item.evidence_role == "substantive")
    present = {item.fact_type for item in substantive}
    missing = tuple(item for item in requirements if item not in present)
    risk = tuple(item for item in substantive if item.signal == "risk")
    counter = tuple(item for item in substantive if item.signal == "counterevidence")
    periods = sorted({item.period for item in substantive})
    evidence_ids = _unique(tuple(item.citation.evidence_id for item in relevant))
    observations = _unique(tuple(item.value for item in relevant))
    definitions = _unique(tuple(item.definition for item in relevant))
    triggered = bool(risk)

    if missing:
        reason = (
            "未取得本subtype列任何claim-specific官方證據；資料缺口不得解讀為沒有風險。"
            if not relevant
            else "已保留部分subtype官方證據；尚缺：" + "、".join(missing) + "。"
        )
        return ChecklistCheckResult(
            check_id=check_id,
            domain="industry",
            applicability="triggered" if triggered else "unresolved",
            status="unresolved",
            first_detectable_at=min((item.citation.available_at for item in relevant), default=None),
            financial_period="/".join(periods) or None,
            observations=observations,
            evidence_ids=evidence_ids,
            supporting_evidence=_unique(tuple(item.value for item in risk)),
            counterevidence=_unique(tuple(item.value for item in counter)),
            inference_chain=definitions,
            mechanism=_MECHANISMS[check_id],
            leading_warnings=_MONITORING[check_id],
            buffers=_unique(tuple(item.value for item in counter)),
            monitoring_metrics=_MONITORING[check_id],
            monitoring_date=None,
            invalidation_or_resolution_conditions=("補齊同subtype缺少的原始定義與數值後重新評估。",),
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
        inference_chain=definitions,
        mechanism=_MECHANISMS[check_id],
        leading_warnings=_MONITORING[check_id],
        buffers=_unique(tuple(item.value for item in counter)),
        monitoring_metrics=_MONITORING[check_id],
        monitoring_date=None,
        invalidation_or_resolution_conditions=("新一期同定義監管數值取代目前判定。",),
        severity="high" if triggered else "low",
        confidence="high",
        unresolved_reasons=(),
    )


def build_financial_institution_assessment(
    *,
    identity: CompanyIdentity,
    route_claims: Sequence[FinancialSubtypeRouteClaim],
    facts: Sequence[FinancialInstitutionFact],
    as_of: str,
) -> FinancialInstitutionAssessment:
    """Resolve one financial subtype and produce only its exact I-FIN row."""

    decision_time = _instant(as_of, "as_of")
    if any(
        item.issuer_id != identity.issuer_id or item.security_code != identity.security_code
        for item in (*route_claims, *facts)
    ):
        raise FinancialInstitutionEvidenceError("financial evidence issuer identity mismatch")

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
    citations = tuple({
        item.citation.evidence_id: item.citation for item in (*admitted_claims, *admitted_facts)
    }.values())

    if identity.industry_code != "17":
        return FinancialInstitutionAssessment(
            issuer_id=identity.issuer_id,
            security_code=identity.security_code,
            as_of=as_of,
            financial_subtype="not_applicable",
            company_route="general_non_financial",
            route_status="not_applicable",
            route_evidence_ids=(),
            route_unresolved_reasons=(),
            checks=(),
            citations=citations,
            excluded_post_as_of_evidence_ids=excluded,
            limitations=("官方產業身分不是金融保險業；未套用I-FIN。",),
        )

    complete_subtypes: tuple[FinancialSubtype, ...] = tuple(
        subtype for subtype, requirements in _ROUTE_REQUIREMENTS.items()
        if set(requirements).issubset({
            item.claim_part for item in admitted_claims if item.financial_subtype == subtype
        })
    )
    route_ids = _unique(tuple(item.citation.evidence_id for item in admitted_claims))
    if len(complete_subtypes) != 1:
        if len(complete_subtypes) > 1:
            reasons = ("conflicting complete regulated financial subtype routes",)
        elif not admitted_claims:
            reasons = ("missing point-in-time company-level regulated-business route evidence",)
        else:
            missing = tuple(
                f"{subtype}:{part}"
                for subtype, requirements in _ROUTE_REQUIREMENTS.items()
                for part in requirements
                if part not in {
                    item.claim_part for item in admitted_claims if item.financial_subtype == subtype
                }
            )
            reasons = ("incomplete regulated financial subtype route claims: " + ",".join(missing),)
        return FinancialInstitutionAssessment(
            issuer_id=identity.issuer_id,
            security_code=identity.security_code,
            as_of=as_of,
            financial_subtype="unresolved",
            company_route="financial_institution_unrouted",
            route_status="blocked",
            route_evidence_ids=route_ids,
            route_unresolved_reasons=reasons,
            checks=(),
            citations=citations,
            excluded_post_as_of_evidence_ids=excluded,
            limitations=(
                "金融issuer subtype未可靠分流；維持blocked且不得進入一般公司量化模型。",
                *reasons,
            ),
        )

    subtype = complete_subtypes[0]
    selected_id = _SUBTYPE_ROWS[subtype]
    rows = tuple(
        _build_row(check_id, admitted_facts)
        if check_id == selected_id
        else _not_applicable_row(check_id, subtype)
        for check_id in _ROW_REQUIREMENTS
    )
    return FinancialInstitutionAssessment(
        issuer_id=identity.issuer_id,
        security_code=identity.security_code,
        as_of=as_of,
        financial_subtype=subtype,
        company_route=subtype,
        route_status="routed",
        route_evidence_ids=route_ids,
        route_unresolved_reasons=(),
        checks=rows,
        citations=citations,
        excluded_post_as_of_evidence_ids=excluded,
        limitations=(
            f"已分流{subtype}；僅I-FIN subtype專用語義可用，其他金融列為not_applicable。",
            "未設定清單未明示的數值門檻；每期依公司／主管機關原始定義與反證判讀。",
        ),
    )


__all__ = [
    "FinancialInstitutionAssessment",
    "FinancialInstitutionEvidenceError",
    "FinancialInstitutionFact",
    "FinancialSubtypeRouteClaim",
    "build_financial_institution_assessment",
]
