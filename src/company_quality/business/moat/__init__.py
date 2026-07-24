"""Transform PIT issuer evidence into a non-publishable business/moat candidate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from company_quality.business.evidence import (
    AdmittedBusinessObservation,
    IssuerBusinessEvidence,
)
from company_quality.industry.peer_outlook import PeerOutlookEvidence

_DIMENSIONS = (
    "switching_cost", "network_effect", "cost_advantage",
    "intangible_assets", "efficient_scale",
)
_CONCENTRATIONS = {
    "customer_top1_pct": "customer_concentration",
    "supplier_top1_pct": "supplier_concentration",
    "geography_top1_pct": "geography_concentration",
}


class BusinessMoatError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RevenueDriver:
    name: str
    share_pct: Decimal | None
    evidence_id: str


@dataclass(frozen=True, slots=True)
class MoatEvidence:
    switching_cost: None = None
    network_effect: None = None
    cost_advantage: None = None
    intangible_assets: None = None
    efficient_scale: None = None


@dataclass(frozen=True, slots=True)
class ConcentrationRisks:
    customer_top1_pct: Decimal | None
    supplier_top1_pct: Decimal | None
    geography_top1_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class MoatJudgement:
    dimension: str
    support_evidence_ids: tuple[str, ...]
    counter_evidence_ids: tuple[str, ...]
    context_evidence_ids: tuple[str, ...]
    evidence_status: Literal["evidence_present", "unknown"]
    calibration_status: Literal["PENDING_T23"] = "PENDING_T23"


@dataclass(frozen=True, slots=True)
class BusinessMoatCandidate:
    issuer_id: str
    peer_ids: tuple[str, ...]
    outlook_evidence_ids: tuple[str, ...]
    revenue_drivers: tuple[RevenueDriver, ...]
    moat_evidence: MoatEvidence
    moat_judgements: tuple[MoatJudgement, ...]
    concentration_risks: ConcentrationRisks
    cyclicality: Literal["defensive", "moderate", "cyclical", "deep_cyclical"]
    evidence_family_ids: tuple[str, ...]
    metric_lineage: dict[str, tuple[str, ...]]
    unavailable_reasons: dict[str, str]
    coverage: Decimal
    confidence: Decimal
    candidate_score: None
    available_at: str
    generation_id: str
    producer_candidate_sha: str
    status: Literal["NON_PUBLISHABLE_CANDIDATE"] = "NON_PUBLISHABLE_CANDIDATE"
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["BusinessMoatCandidate.v1"] = "BusinessMoatCandidate.v1"
    source_version: Literal["PeerOutlookEvidence.v1+IssuerBusinessEvidence.v1"] = (
        "PeerOutlookEvidence.v1+IssuerBusinessEvidence.v1"
    )
    formula_version: Literal["raw-evidence-no-moat-calibration.v1"] = (
        "raw-evidence-no-moat-calibration.v1"
    )
    model_version: Literal["business-moat-candidate-1.0.0"] = (
        "business-moat-candidate-1.0.0"
    )


def _instant(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BusinessMoatError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BusinessMoatError(f"{field} must be timezone-aware")
    return parsed


def build_business_moat_candidate(
    peer_outlook: PeerOutlookEvidence,
    business: IssuerBusinessEvidence,
    *,
    generation_id: str,
    producer_candidate_sha: str,
) -> BusinessMoatCandidate:
    """Build raw diagnostics; T23 owns moat calibration and scoring."""

    if peer_outlook.schema_version != "PeerOutlookEvidence.v1":
        raise BusinessMoatError("expected PeerOutlookEvidence.v1")
    if business.schema_version != "IssuerBusinessEvidence.v1":
        raise BusinessMoatError("expected IssuerBusinessEvidence.v1")
    if peer_outlook.status != "available" or business.status != "available":
        raise BusinessMoatError("both upstream evidence sections must be available")
    if peer_outlook.issuer_id != business.issuer_id:
        raise BusinessMoatError("upstream issuer binding mismatch")
    if not generation_id.strip() or len(generation_id) > 128:
        raise BusinessMoatError("invalid generation_id")
    if len(producer_candidate_sha) != 40 or any(c not in "0123456789abcdef" for c in producer_candidate_sha):
        raise BusinessMoatError("invalid producer_candidate_sha")

    revenue = [item for item in business.observations if item.category == "revenue_driver"]
    if not revenue:
        raise BusinessMoatError("revenue-driver evidence is required")
    by_name: dict[str, list[AdmittedBusinessObservation]] = {}
    for item in revenue:
        by_name.setdefault(item.name, []).append(item)
    drivers: list[RevenueDriver] = []
    lineage: dict[str, tuple[str, ...]] = {}
    for name in sorted(by_name):
        candidates = by_name[name]
        latest_period = max(item.period_end for item in candidates)
        latest = [item for item in candidates if item.period_end == latest_period]
        values = {item.numeric_value for item in latest}
        if len(values) != 1:
            raise BusinessMoatError("conflicting latest revenue-driver shares")
        chosen = min(latest, key=lambda item: item.evidence_id)
        drivers.append(RevenueDriver(name, chosen.numeric_value, chosen.evidence_id))
        lineage[f"revenue_driver:{name}"] = tuple(sorted(item.evidence_id for item in latest))
    if len(drivers) > 32:
        raise BusinessMoatError("revenue drivers exceed the 32-item limit")

    concentration_values: dict[str, Decimal | None] = {}
    reasons: dict[str, str] = {}
    for output_name, category in _CONCENTRATIONS.items():
        items = [item for item in business.observations if item.category == category]
        if not items:
            concentration_values[output_name] = None
            reasons[output_name] = "missing_concentration_evidence"
            continue
        latest_period = max(item.period_end for item in items)
        current = [item for item in items if item.period_end == latest_period]
        numeric = [item for item in current if item.numeric_value is not None]
        lineage[output_name] = tuple(sorted(item.evidence_id for item in current))
        if not numeric:
            concentration_values[output_name] = None
            reasons[output_name] = "concentration_denominator_or_value_unavailable"
        else:
            concentration_values[output_name] = max(
                item.numeric_value for item in numeric if item.numeric_value is not None
            )

    judgements: list[MoatJudgement] = []
    for dimension in _DIMENSIONS:
        items = [item for item in business.observations if item.category == dimension]
        support = tuple(sorted(item.evidence_id for item in items if item.direction == "support"))
        counter = tuple(sorted(item.evidence_id for item in items if item.direction == "counter"))
        context = tuple(sorted(item.evidence_id for item in items if item.direction == "context"))
        all_ids = tuple(sorted(item.evidence_id for item in items))
        lineage[dimension] = all_ids
        reasons[dimension] = "calibration_pending_t23"
        judgements.append(MoatJudgement(
            dimension=dimension,
            support_evidence_ids=support,
            counter_evidence_ids=counter,
            context_evidence_ids=context,
            evidence_status="evidence_present" if all_ids else "unknown",
        ))
    reasons["candidate_score"] = "calibration_pending_t23"

    return BusinessMoatCandidate(
        issuer_id=business.issuer_id,
        peer_ids=peer_outlook.peer_ids,
        outlook_evidence_ids=peer_outlook.outlook_evidence_ids,
        revenue_drivers=tuple(drivers),
        moat_evidence=MoatEvidence(),
        moat_judgements=tuple(judgements),
        concentration_risks=ConcentrationRisks(**concentration_values),
        cyclicality=peer_outlook.cyclicality,
        evidence_family_ids=tuple(sorted(set(business.evidence_family_ids) | {"industry:peer_outlook"})),
        metric_lineage=lineage,
        unavailable_reasons=reasons,
        coverage=min(business.coverage, peer_outlook.coverage),
        confidence=min(business.confidence, peer_outlook.confidence),
        candidate_score=None,
        available_at=max(
            _instant(business.available_at, "business available_at"),
            _instant(peer_outlook.available_at, "peer outlook available_at"),
        ).isoformat(),
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
    )
