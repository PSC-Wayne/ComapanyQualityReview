"""Fail-closed manufacturing evidence producers for I-MFG-01 through I-MFG-06.

The producer accepts cited, claim-specific facts rather than caller completion
booleans.  Context records (headings, keywords, ESG metrics and feed-absence
receipts) are retained but never satisfy a domain requirement.  A row is
complete only when all of its authority-defined domains are present and at
least two independent source documents support the chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation

ManufacturingFactType = Literal[
    "capacity",
    "utilization",
    "yield",
    "depreciation_burden",
    "raw_materials",
    "work_in_process",
    "finished_goods",
    "inventory_aging",
    "inventory_write_down",
    "subsequent_sales_realization",
    "signed_purchase_commitment",
    "long_term_term",
    "non_cancellable_term",
    "prepayment",
    "cancellation_term",
    "demand_support",
    "end_application_distribution",
    "customer_substitution",
    "customer_certification",
    "design_win",
    "mass_production",
    "mass_production_revenue",
    "fx_revenue_impact",
    "fx_gross_margin_impact",
    "fx_non_operating_impact",
    "fx_currency",
    "fx_exposure",
    "fx_hedge",
]
ManufacturingSignal = Literal["risk", "counterevidence"]
EvidenceRole = Literal["substantive", "context"]

_FACT_TYPES = frozenset(ManufacturingFactType.__args__)  # type: ignore[attr-defined]
_REQUIREMENTS: Mapping[str, tuple[ManufacturingFactType, ...]] = {
    "I-MFG-01": ("capacity", "utilization", "yield", "depreciation_burden"),
    "I-MFG-02": (
        "raw_materials",
        "work_in_process",
        "finished_goods",
        "inventory_aging",
        "inventory_write_down",
        "subsequent_sales_realization",
    ),
    "I-MFG-03": (
        "signed_purchase_commitment",
        "long_term_term",
        "non_cancellable_term",
        "prepayment",
        "cancellation_term",
        "demand_support",
    ),
    "I-MFG-04": ("end_application_distribution", "customer_substitution"),
    "I-MFG-05": (
        "customer_certification",
        "design_win",
        "mass_production",
        "mass_production_revenue",
    ),
    "I-MFG-06": (
        "fx_revenue_impact",
        "fx_gross_margin_impact",
        "fx_non_operating_impact",
        "fx_currency",
        "fx_exposure",
        "fx_hedge",
    ),
}
_TREND_ROWS = frozenset({"I-MFG-01", "I-MFG-02", "I-MFG-06"})
_MONITORING: Mapping[str, tuple[str, ...]] = {
    "I-MFG-01": ("產能", "稼動率", "良率", "折舊負擔"),
    "I-MFG-02": ("原料／在製品／製成品", "庫齡", "跌價", "期後銷售實現"),
    "I-MFG-03": ("簽署採購承諾", "長約與不可取消金額", "預付款", "取消條款", "需求支持"),
    "I-MFG-04": ("終端應用分布", "客戶流失情境", "替代客戶與轉換期間"),
    "I-MFG-05": ("客戶認證", "design-win", "量產", "量產收入"),
    "I-MFG-06": ("交易幣別", "曝險期間", "避險期間", "營收／毛利／業外匯率影響"),
}
_MECHANISMS: Mapping[str, str] = {
    "I-MFG-01": "產能、稼動率與良率共同決定固定折舊吸收及單位製造成本。",
    "I-MFG-02": "存貨組成、庫齡與跌價須由期後銷售實現交叉驗證，避免把備貨直接視為安全。",
    "I-MFG-03": "簽署長約、不可取消採購與預付款會把需求變化傳導為固定採購及現金義務。",
    "I-MFG-04": "終端應用衰退或客戶流失若缺少可替代客戶，會傳導至營收、毛利與收款。",
    "I-MFG-05": "認證與design-win只有轉為量產及可辨識收入後，才形成已實現成長。",
    "I-MFG-06": "外幣曝險會分層影響收入換算、製造毛利及業外匯兌，避險期間可能改變各層時點。",
}


class ManufacturingEvidenceError(ValueError):
    """Raised when manufacturing input violates the evidence contract."""


@dataclass(frozen=True, slots=True)
class ManufacturingEvidenceFact:
    fact_type: ManufacturingFactType
    value: str
    period: str
    scope: str
    signal: ManufacturingSignal
    evidence_role: EvidenceRole
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if self.fact_type not in _FACT_TYPES:
            raise ManufacturingEvidenceError(f"unsupported manufacturing fact: {self.fact_type}")
        if self.signal not in {"risk", "counterevidence"}:
            raise ManufacturingEvidenceError("invalid manufacturing signal")
        if self.evidence_role not in {"substantive", "context"}:
            raise ManufacturingEvidenceError("invalid manufacturing evidence role")
        if not self.value.strip() or not self.period.strip() or not self.scope.strip():
            raise ManufacturingEvidenceError("manufacturing fact requires value, period and scope")
        if self.citation.period != self.period:
            raise ManufacturingEvidenceError("manufacturing fact period must match citation period")
        if self.citation.source_tier not in {"official", "issuer_primary"}:
            raise ManufacturingEvidenceError(
                "manufacturing facts require official or issuer-primary citations"
            )
        if not self.citation.verbatim_excerpt.strip():
            raise ManufacturingEvidenceError("manufacturing fact requires verbatim evidence")


@dataclass(frozen=True, slots=True)
class ManufacturingAssessment:
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    context_evidence_ids: tuple[str, ...]
    schema_version: Literal["ManufacturingAssessment.v1"] = "ManufacturingAssessment.v1"

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


def _row_facts(
    facts: Sequence[ManufacturingEvidenceFact],
    requirements: Sequence[ManufacturingFactType],
) -> tuple[ManufacturingEvidenceFact, ...]:
    required = set(requirements)
    return tuple(item for item in facts if item.fact_type in required)


def _missing_domains(
    check_id: str,
    substantive: Sequence[ManufacturingEvidenceFact],
) -> tuple[str, ...]:
    requirements = _REQUIREMENTS[check_id]
    present = {item.fact_type for item in substantive}
    missing = [item for item in requirements if item not in present]
    if check_id in _TREND_ROWS:
        by_scope_type: dict[tuple[str, str], set[str]] = {}
        for item in substantive:
            by_scope_type.setdefault((item.scope, item.fact_type), set()).add(item.period)
        comparable_scopes = {
            scope
            for scope in {item.scope for item in substantive}
            if all(len(by_scope_type.get((scope, fact_type), set())) >= 2 for fact_type in requirements)
        }
        if not comparable_scopes:
            missing.append("同一範圍至少兩期的可比較證據")
    source_ids = {item.citation.source_id for item in substantive}
    if len(source_ids) < 2:
        missing.append("至少兩個獨立來源文件（單一來源文件不得完成本題）")
    return _unique(missing)


def _build_row(
    check_id: str,
    facts: Sequence[ManufacturingEvidenceFact],
) -> ChecklistCheckResult:
    requirements = _REQUIREMENTS[check_id]
    relevant = _row_facts(facts, requirements)
    substantive = tuple(item for item in relevant if item.evidence_role == "substantive")
    missing = _missing_domains(check_id, substantive)
    evidence_ids = _unique(tuple(item.citation.evidence_id for item in relevant))
    observations = _unique(tuple(item.value for item in relevant))
    risk = tuple(item for item in substantive if item.signal == "risk")
    counter = tuple(item for item in substantive if item.signal == "counterevidence")
    periods = sorted({item.period for item in substantive})
    triggered = bool(risk)

    if missing:
        reason = (
            "未取得本題任何claim-specific官方證據；資料缺口不得解讀為沒有風險。"
            if not relevant
            else "已保留部分官方證據；尚缺：" + "、".join(missing) + "。"
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
                "claim-specific官方／公司原始證據 → 範圍與期間 → 清單必要領域 → 尚未完成",
            ),
            mechanism=_MECHANISMS[check_id],
            leading_warnings=_MONITORING[check_id],
            buffers=_unique(tuple(item.value for item in counter)),
            monitoring_metrics=_MONITORING[check_id],
            monitoring_date=None,
            invalidation_or_resolution_conditions=(
                "補齊缺少領域、獨立來源、期間與範圍後重新評估。",
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
            "claim-specific官方／公司原始證據 → 範圍與期間 → 完整製造業領域 → 風險與反證分列",
        ),
        mechanism=_MECHANISMS[check_id],
        leading_warnings=_MONITORING[check_id],
        buffers=_unique(tuple(item.value for item in counter)),
        monitoring_metrics=_MONITORING[check_id],
        monitoring_date=None,
        invalidation_or_resolution_conditions=("新一期同範圍證據或條款更新目前判定。",),
        severity="high" if triggered else "low",
        confidence="high",
        unresolved_reasons=(),
    )


def build_manufacturing_assessment(
    facts: Sequence[ManufacturingEvidenceFact],
) -> ManufacturingAssessment:
    """Assess I-MFG-01..06 from evidence contents, never caller booleans."""

    evidence_ids: set[str] = set()
    for item in facts:
        if item.citation.evidence_id in evidence_ids:
            # One document may support several domains; duplicate fact references are
            # allowed, but the final citation collection remains unique.
            continue
        evidence_ids.add(item.citation.evidence_id)
    citations = tuple(
        {item.citation.evidence_id: item.citation for item in facts}.values()
    )
    return ManufacturingAssessment(
        checks=tuple(_build_row(check_id, facts) for check_id in _REQUIREMENTS),
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
    "ManufacturingAssessment",
    "ManufacturingEvidenceError",
    "ManufacturingEvidenceFact",
    "build_manufacturing_assessment",
]
