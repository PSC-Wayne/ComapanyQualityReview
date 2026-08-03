"""Shared official-disclosure policy for quality, upside and downside ratings.

Detailed checklist research may retain unresolved questions.  Rating eligibility,
however, depends only on point-in-time formal disclosures.  Information that is
not publicly disclosed is recorded for transparency and otherwise ignored.
Verified supplemental information may add explicit extra points, but can never
deduct from or make a core rating eligible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Sequence

from company_quality.company_analysis.contracts import EvidenceCitation


RatingDimension = Literal["quality", "upside", "downside"]
CoreDisclosureKind = Literal[
    "financial_statement",
    "financial_note",
    "auditor_report",
    "kam",
    "exchange_or_mops_disclosure",
    "official_material_event",
]
DisclosureKind = Literal[
    "financial_statement",
    "financial_note",
    "auditor_report",
    "kam",
    "exchange_or_mops_disclosure",
    "official_material_event",
    "verified_supplemental",
]
EvidenceRole = Literal["core", "extra"]
UnavailableReason = Literal[
    "not_formally_disclosed",
    "oral_claim_not_formally_disclosed",
    "contract_terms_not_public",
    "supplemental_counterevidence_missing",
    "supplemental_source_unavailable",
]

_CORE_KINDS: frozenset[str] = frozenset(
    {
        "financial_statement",
        "financial_note",
        "auditor_report",
        "kam",
        "exchange_or_mops_disclosure",
        "official_material_event",
    }
)
_CORE_SOURCE_TIERS = frozenset({"official", "issuer_primary"})


class RatingEvidencePolicyError(ValueError):
    """Raised when evidence violates the common rating-source policy."""


@dataclass(frozen=True, slots=True)
class RatingEvidenceInput:
    issuer_id: str
    disclosure_kind: DisclosureKind
    role: EvidenceRole
    citation: EvidenceCitation
    extra_points: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class UnavailableRatingInput:
    input_id: str
    reason: UnavailableReason


@dataclass(frozen=True, slots=True)
class RatingEvidenceDecision:
    dimension: RatingDimension
    issuer_id: str
    as_of: str
    core_rating_eligible: bool
    ineligibility_reason: Literal["official_primary_disclosure_missing"] | None
    core_evidence_ids: tuple[str, ...]
    core_disclosure_kinds: tuple[CoreDisclosureKind, ...]
    supplemental_evidence_ids: tuple[str, ...]
    extra_points: Decimal
    unavailable_inputs: tuple[str, ...]
    checklist_unresolved_ids: tuple[str, ...]
    policy_version: Literal["OfficialDisclosureRatingPolicy.v1"] = (
        "OfficialDisclosureRatingPolicy.v1"
    )


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RatingEvidencePolicyError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise RatingEvidencePolicyError(f"{field} must be timezone-aware")
    return result


def _unique(values: Sequence[str], field: str) -> tuple[str, ...]:
    result = tuple(values)
    if any(not item for item in result):
        raise RatingEvidencePolicyError(f"{field} cannot contain empty values")
    if len(set(result)) != len(result):
        raise RatingEvidencePolicyError(f"{field} must be unique")
    return result


def admit_rating_evidence(
    *,
    dimension: RatingDimension,
    issuer_id: str,
    as_of: str,
    evidence: Sequence[RatingEvidenceInput],
    unavailable: Sequence[UnavailableRatingInput] = (),
    checklist_unresolved_ids: Sequence[str] = (),
) -> RatingEvidenceDecision:
    """Classify rating evidence without treating unavailable extras as negatives."""

    if dimension not in {"quality", "upside", "downside"}:
        raise RatingEvidencePolicyError("invalid rating dimension")
    if not issuer_id:
        raise RatingEvidencePolicyError("issuer_id required")
    decision_time = _instant(as_of, "rating as_of")

    core_ids: list[str] = []
    core_kinds: list[CoreDisclosureKind] = []
    supplemental_ids: list[str] = []
    extra_points = Decimal("0")
    seen_evidence: set[str] = set()

    for item in evidence:
        if item.issuer_id != issuer_id:
            raise RatingEvidencePolicyError("rating evidence issuer mismatch")
        citation = item.citation
        if not citation.evidence_id or citation.evidence_id in seen_evidence:
            raise RatingEvidencePolicyError("rating evidence_id must be non-empty and unique")
        seen_evidence.add(citation.evidence_id)
        if _instant(citation.available_at, "evidence available_at") > decision_time:
            raise RatingEvidencePolicyError("rating evidence available after rating as_of")
        if not item.extra_points.is_finite() or item.extra_points < 0:
            raise RatingEvidencePolicyError("extra points must be finite and non-negative")

        if item.disclosure_kind in _CORE_KINDS:
            if item.role != "core":
                raise RatingEvidencePolicyError("formal disclosure must use core role")
            if citation.source_tier not in _CORE_SOURCE_TIERS:
                raise RatingEvidencePolicyError(
                    "core disclosure requires official or issuer-primary evidence"
                )
            if item.extra_points != 0:
                raise RatingEvidencePolicyError("core disclosure cannot carry extra points")
            core_ids.append(citation.evidence_id)
            core_kinds.append(item.disclosure_kind)  # type: ignore[arg-type]
            continue

        if item.disclosure_kind != "verified_supplemental" or item.role != "extra":
            raise RatingEvidencePolicyError(
                "supplemental information must use verified_supplemental extra role"
            )
        supplemental_ids.append(citation.evidence_id)
        extra_points += item.extra_points

    unavailable_ids = _unique(
        tuple(item.input_id for item in unavailable), "unavailable input IDs"
    )
    unresolved_ids = _unique(
        tuple(checklist_unresolved_ids), "checklist unresolved IDs"
    )
    eligible = bool(core_ids)
    return RatingEvidenceDecision(
        dimension=dimension,
        issuer_id=issuer_id,
        as_of=as_of,
        core_rating_eligible=eligible,
        ineligibility_reason=(
            None if eligible else "official_primary_disclosure_missing"
        ),
        core_evidence_ids=tuple(core_ids),
        core_disclosure_kinds=tuple(dict.fromkeys(core_kinds)),
        supplemental_evidence_ids=tuple(supplemental_ids),
        extra_points=extra_points,
        unavailable_inputs=unavailable_ids,
        checklist_unresolved_ids=unresolved_ids,
    )


__all__ = [
    "CoreDisclosureKind",
    "DisclosureKind",
    "EvidenceRole",
    "RatingDimension",
    "RatingEvidenceDecision",
    "RatingEvidenceInput",
    "RatingEvidencePolicyError",
    "UnavailableRatingInput",
    "UnavailableReason",
    "admit_rating_evidence",
]
