"""Deterministic, monotonic hard gates for formal audit evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from company_quality.audit.inventory import AuditFilingInventory, OpinionType

GateState = Literal["clear", "cap", "no_rating", "blocked"]
NoRatingReason = Literal[
    "formal_disclaimer",
    "formal_adverse",
    "missing_mandatory_evidence",
    "authority_conflict",
]


class AuditGatePolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuditGatePolicy:
    version: str
    adverse_quality_cap: int
    qualified_quality_cap: int
    severe_qualified_quality_cap: int
    integrity_event_quality_cap: int

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise AuditGatePolicyError("policy version is required")
        if not 20 <= self.adverse_quality_cap <= 30:
            raise AuditGatePolicyError("adverse quality cap must be within 20..30")
        if not 0 <= self.qualified_quality_cap <= 60:
            raise AuditGatePolicyError("qualified quality cap must be within 0..60")
        if not 0 <= self.severe_qualified_quality_cap <= self.qualified_quality_cap:
            raise AuditGatePolicyError(
                "severe qualified cap cannot exceed qualified quality cap"
            )
        if not 30 <= self.integrity_event_quality_cap <= 40:
            raise AuditGatePolicyError("integrity event quality cap must be within 30..40")


@dataclass(frozen=True, slots=True)
class AuditGateDecision:
    gate_state: GateState
    opinion_type: OpinionType | None
    going_concern: bool | None
    restatement: bool | None
    confirmed_fraud: bool | None
    key_audit_matter_first_occurrence: bool | None
    emphasis_matter_first_occurrence: bool | None
    auditor_change: bool | None
    cap_value: int | None
    upside_star_cap: int | None
    floor_value: int | None
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    available_at: str
    coverage: Decimal
    no_rating_reason: NoRatingReason | None
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["AuditGateDecision.v1"] = "AuditGateDecision.v1"
    source_version: str = "AuditFilingInventory.v1"
    formula_version: Literal["audit-hard-gate.v1"] = "audit-hard-gate.v1"
    model_version: str = ""


def apply_ceiling(value: int | None, ceiling: int | None) -> int | None:
    if value is None or ceiling is None:
        return value
    return min(value, ceiling)


def apply_floor(value: int | None, floor: int | None) -> int | None:
    if value is None or floor is None:
        return value
    return max(value, floor)


def _stricter_ceiling(current: int | None, candidate: int) -> int:
    return candidate if current is None else min(current, candidate)


def _stricter_floor(current: int | None, candidate: int) -> int:
    return candidate if current is None else max(current, candidate)


def _valid_available_at(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("available_at must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("available_at must be timezone-aware")


def evaluate_audit_gate(
    inventory: AuditFilingInventory,
    policy: AuditGatePolicy,
    *,
    going_concern: bool | None = None,
    restatement: bool | None = None,
    confirmed_fraud: bool | None = None,
    key_audit_matter_first_occurrence: bool | None = None,
    emphasis_matter_first_occurrence: bool | None = None,
    auditor_change: bool | None = None,
    statements_reliable: bool | None = None,
    qualified_pervasive_or_core: bool | None = None,
    authority_conflict: bool = False,
    additional_evidence_ids: tuple[str, ...] = (),
) -> AuditGateDecision:
    _valid_available_at(inventory.available_at)
    if not Decimal("0") <= inventory.coverage <= Decimal("1"):
        raise ValueError("coverage must be within 0..1")
    supplemental_formal_fact = any(
        value is not None
        for value in (
            going_concern,
            restatement,
            confirmed_fraud,
            statements_reliable,
            qualified_pervasive_or_core,
            key_audit_matter_first_occurrence,
            emphasis_matter_first_occurrence,
            auditor_change,
        )
    )
    if supplemental_formal_fact and not additional_evidence_ids:
        raise ValueError("supplemental formal audit facts require evidence IDs")
    evidence_ids = tuple(dict.fromkeys((*inventory.evidence_ids, *additional_evidence_ids)))
    if not evidence_ids:
        raise ValueError("at least one evidence ID is required")

    reasons: list[str] = []
    quality_cap: int | None = None
    star_cap: int | None = None
    downside_floor: int | None = None
    no_rating_reason: NoRatingReason | None = None

    if inventory.schema_version != "AuditFilingInventory.v1":
        authority_conflict = True
        reasons.append("unsupported_audit_inventory_schema")
    if inventory.mandatory_evidence_gaps:
        reasons.extend(inventory.mandatory_evidence_gaps)
    if inventory.opinion_type is None and not inventory.mandatory_evidence_gaps:
        authority_conflict = True
        reasons.append("formal_opinion_missing_without_coverage_gap")

    if inventory.opinion_type == "disclaimer":
        no_rating_reason = "formal_disclaimer"
        downside_floor = _stricter_floor(downside_floor, 5)
        reasons.append("formal_disclaimer_of_opinion")
    elif inventory.opinion_type == "adverse":
        quality_cap = _stricter_ceiling(quality_cap, policy.adverse_quality_cap)
        star_cap = _stricter_ceiling(star_cap, 1)
        downside_floor = _stricter_floor(downside_floor, 5)
        reasons.append("formal_adverse_opinion")
    elif inventory.opinion_type == "qualified":
        cap = (
            policy.qualified_quality_cap
            if qualified_pervasive_or_core is False
            else policy.severe_qualified_quality_cap
        )
        quality_cap = _stricter_ceiling(quality_cap, cap)
        reasons.append(
            "formal_qualified_opinion_severe"
            if qualified_pervasive_or_core is not False
            else "formal_qualified_opinion"
        )

    if going_concern is True:
        quality_cap = _stricter_ceiling(quality_cap, 40)
        star_cap = _stricter_ceiling(star_cap, 2)
        downside_floor = _stricter_floor(downside_floor, 4)
        reasons.append("going_concern_material_uncertainty")

    if restatement is True:
        quality_cap = _stricter_ceiling(
            quality_cap, policy.integrity_event_quality_cap
        )
        downside_floor = _stricter_floor(downside_floor, 4)
        reasons.append("major_correction_or_restatement")

    if confirmed_fraud is True:
        quality_cap = _stricter_ceiling(
            quality_cap, policy.integrity_event_quality_cap
        )
        downside_floor = _stricter_floor(downside_floor, 4)
        reasons.append("confirmed_fraud_or_integrity_failure")

    if key_audit_matter_first_occurrence is True:
        reasons.append("first_occurrence_key_audit_matter_negative_evidence")
    if emphasis_matter_first_occurrence is True:
        reasons.append("first_occurrence_emphasis_matter_negative_evidence")
    if auditor_change is True:
        reasons.append("auditor_change_negative_evidence")

    if statements_reliable is False:
        no_rating_reason = "authority_conflict"
        reasons.append("financial_statements_unreliable")

    if authority_conflict:
        gate_state: GateState = "blocked"
        no_rating_reason = "authority_conflict"
        reasons.append("audit_authority_conflict")
    elif no_rating_reason is not None:
        gate_state = "no_rating"
        quality_cap = None
        star_cap = None
    elif any(value is not None for value in (quality_cap, star_cap, downside_floor)):
        gate_state = "cap"
    else:
        gate_state = "clear"

    if not reasons:
        reasons.append("no_audit_hard_gate_triggered")

    return AuditGateDecision(
        gate_state=gate_state,
        opinion_type=inventory.opinion_type,
        going_concern=going_concern,
        restatement=restatement,
        confirmed_fraud=confirmed_fraud,
        key_audit_matter_first_occurrence=key_audit_matter_first_occurrence,
        emphasis_matter_first_occurrence=emphasis_matter_first_occurrence,
        auditor_change=auditor_change,
        cap_value=quality_cap,
        upside_star_cap=star_cap,
        floor_value=downside_floor,
        reasons=tuple(dict.fromkeys(reasons)),
        evidence_ids=evidence_ids,
        available_at=inventory.available_at,
        coverage=inventory.coverage,
        no_rating_reason=no_rating_reason,
        source_version=inventory.schema_version,
        model_version=policy.version,
    )
