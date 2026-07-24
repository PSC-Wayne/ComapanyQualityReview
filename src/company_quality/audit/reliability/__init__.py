"""Ordinary audit-pillar diagnostics kept separate from audit hard gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from company_quality.audit.gates import AuditGateDecision
from company_quality.audit.high_risk_notes import HighRiskNoteRegister
from company_quality.audit.inventory import AuditFilingInventory


class AuditReliabilityError(RuntimeError):
    """Raised when bounded producer contracts cannot be safely combined."""


@dataclass(frozen=True, slots=True)
class Pillar1AuditReliabilityCandidate:
    ordinary_score: None
    ordinary_weight: Decimal
    completeness: Decimal
    timeliness: Decimal
    consistency: Decimal
    evidence_family_ids: tuple[str, ...]
    hard_gate_excluded_evidence_ids: tuple[str, ...]
    coverage: Decimal
    metric_lineage: dict[str, tuple[str, ...]]
    reasons: dict[str, str]
    available_at: str
    publication_status: Literal["NON_PUBLISHABLE_CANDIDATE"] = (
        "NON_PUBLISHABLE_CANDIDATE"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["Pillar1AuditReliabilityCandidate.v1"] = (
        "Pillar1AuditReliabilityCandidate.v1"
    )
    source_version: Literal[
        "AuditFilingInventory.v1+AuditGateDecision.v1+HighRiskNoteRegister.v1"
    ] = "AuditFilingInventory.v1+AuditGateDecision.v1+HighRiskNoteRegister.v1"
    formula_version: Literal["audit-reliability-diagnostics.v1"] = (
        "audit-reliability-diagnostics.v1"
    )
    model_version: Literal["calibration-pending-t23"] = "calibration-pending-t23"


def _instant(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise AuditReliabilityError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuditReliabilityError(f"{field} must be timezone-aware")
    return parsed


def _validate_coverage(value: Decimal, field: str) -> None:
    if not Decimal("0") <= value <= Decimal("1"):
        raise AuditReliabilityError(f"{field} must be within 0..1")


def _validate_inputs(
    inventory: AuditFilingInventory,
    gate: AuditGateDecision,
    notes: HighRiskNoteRegister,
) -> None:
    if inventory.schema_version != "AuditFilingInventory.v1":
        raise AuditReliabilityError("BLOCKED_CONTRACT: expected AuditFilingInventory.v1")
    if gate.schema_version != "AuditGateDecision.v1":
        raise AuditReliabilityError("BLOCKED_CONTRACT: expected AuditGateDecision.v1")
    if notes.schema_version != "HighRiskNoteRegister.v1":
        raise AuditReliabilityError("BLOCKED_CONTRACT: expected HighRiskNoteRegister.v1")
    if gate.source_version != "AuditFilingInventory.v1":
        raise AuditReliabilityError("BLOCKED_CONTRACT: gate source version mismatch")
    if notes.source_version != "CanonicalFinancialFacts.v1+AuditFilingInventory.v1":
        raise AuditReliabilityError("BLOCKED_CONTRACT: note source version mismatch")
    if gate.opinion_type != inventory.opinion_type:
        raise AuditReliabilityError("BLOCKED_CONTRACT: gate opinion conflicts with inventory")
    if any(item.period != inventory.period for item in notes.items):
        raise AuditReliabilityError("BLOCKED_CONTRACT: note period conflicts with inventory")
    for field, value in (
        ("inventory coverage", inventory.coverage),
        ("gate coverage", gate.coverage),
        ("note coverage", notes.coverage),
    ):
        _validate_coverage(value, field)
    if not inventory.evidence_ids:
        raise AuditReliabilityError("BLOCKED_CONTRACT: inventory evidence IDs are required")
    if not set(gate.evidence_ids).issuperset(inventory.evidence_ids):
        raise AuditReliabilityError(
            "BLOCKED_CONTRACT: gate does not bind inventory evidence"
        )


def build_audit_reliability_candidate(
    inventory: AuditFilingInventory | None,
    gate: AuditGateDecision | None,
    notes: HighRiskNoteRegister | None,
) -> Pillar1AuditReliabilityCandidate:
    """Build unscored diagnostics without reusing hard-gate evidence as a score."""

    if inventory is None or gate is None or notes is None:
        raise AuditReliabilityError(
            "BLOCKED_CONTRACT: all T06/T07/T08 inputs are required"
        )
    _validate_inputs(inventory, gate, notes)
    filed_at = _instant(inventory.official_filed_at, "official_filed_at")
    due_at = _instant(inventory.statutory_due_at, "statutory_due_at")
    available = max(
        _instant(inventory.available_at, "inventory available_at"),
        _instant(gate.available_at, "gate available_at"),
        _instant(notes.available_at, "notes available_at"),
    )

    completeness = min(inventory.coverage, notes.coverage)
    timeliness = Decimal("1") if filed_at <= due_at else Decimal("0")
    consistency = (
        Decimal("0")
        if inventory.corrected is True or gate.restatement is True
        else Decimal("1")
    )
    no_trigger = gate.reasons == ("no_audit_hard_gate_triggered",)
    excluded = () if no_trigger else tuple(dict.fromkeys(gate.evidence_ids))

    note_evidence = tuple(
        item.evidence_id for item in notes.items if item.evidence_id is not None
    )
    lineage = {
        "completeness": tuple(
            dict.fromkeys((*inventory.evidence_ids, *note_evidence))
        ),
        "timeliness": tuple(inventory.evidence_ids),
        "consistency": tuple(
            dict.fromkeys((*inventory.evidence_ids, *gate.evidence_ids))
        ),
        "ordinary_score": (),
    }
    reasons = {
        "ordinary_score": "calibration_pending_t23",
        "hard_gate_exclusion": (
            "no_hard_gate_evidence_excluded"
            if no_trigger
            else "t07_trigger_evidence_excluded_from_ordinary_score"
        ),
    }
    if inventory.mandatory_evidence_gaps:
        reasons["completeness"] = "mandatory_audit_evidence_gap_present"
    if timeliness == 0:
        reasons["timeliness"] = "official_filing_after_statutory_due_at"
    if consistency == 0:
        reasons["consistency"] = "correction_or_restatement_present"

    return Pillar1AuditReliabilityCandidate(
        ordinary_score=None,
        ordinary_weight=Decimal("0.10"),
        completeness=completeness,
        timeliness=timeliness,
        consistency=consistency,
        evidence_family_ids=(
            "audit:filing_completeness",
            "audit:high_risk_note_coverage",
            "audit:filing_timeliness",
            "audit:filing_consistency",
        ),
        hard_gate_excluded_evidence_ids=excluded,
        coverage=min(inventory.coverage, gate.coverage, notes.coverage),
        metric_lineage=lineage,
        reasons=reasons,
        available_at=available.isoformat(),
    )


__all__ = [
    "AuditReliabilityError",
    "Pillar1AuditReliabilityCandidate",
    "build_audit_reliability_candidate",
]
