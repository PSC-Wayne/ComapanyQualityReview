"""Non-publishable, executable candidate scoring policies for the PIT lab."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import re
from typing import Any, Literal, Mapping, Sequence, cast

from company_quality.audit.gates import AuditGateDecision
from company_quality.audit.reliability import Pillar1AuditReliabilityCandidate
from company_quality.business.moat import BusinessMoatCandidate
from company_quality.downside.diagnostic import DownsideStressDiagnostic
from company_quality.governance.people_adaptability import GovernancePeopleCandidate
from company_quality.industry.peer_outlook import PeerOutlookEvidence
from company_quality.scoring.cash_balance import CashBalanceAllocationCandidate
from company_quality.scoring.earnings import EarningsCapitalEfficiencyCandidate
from company_quality.valuation.diagnostic import ValuationUpsideDiagnostic


class CandidatePolicyError(RuntimeError):
    pass


Component = Literal[
    "audit_reliability", "earnings_capital_efficiency", "cash_balance_allocation",
    "business_moat", "governance", "people_adaptability",
    "maximum_drawdown_vulnerability", "permanent_capital_loss_vulnerability",
    "material_adverse_event_vulnerability", "hard_gate_only",
]
ScoredComponent = Literal[
    "audit_reliability", "earnings_capital_efficiency", "cash_balance_allocation",
    "business_moat", "governance", "people_adaptability",
    "maximum_drawdown_vulnerability", "permanent_capital_loss_vulnerability",
    "material_adverse_event_vulnerability",
]


@dataclass(frozen=True, slots=True)
class PillarWeights:
    audit_reliability: Decimal = Decimal("0.10")
    earnings_capital_efficiency: Decimal = Decimal("0.25")
    cash_balance_allocation: Decimal = Decimal("0.25")
    business_moat: Decimal = Decimal("0.25")
    governance: Decimal = Decimal("0.05")
    people_adaptability: Decimal = Decimal("0.10")
    sum: Decimal = Decimal("1")


@dataclass(frozen=True, slots=True)
class QualityBand:
    lower: Decimal
    upper: Decimal
    label: str


@dataclass(frozen=True, slots=True)
class QualityPolicy:
    normalisation: Literal["winsor_rank"]
    winsor_lower_quantile: Decimal
    winsor_upper_quantile: Decimal
    cohort_locator: Literal["PeerOutlookEvidence.peer_ids+issuer_id"]
    minimum_cohort_size: Literal[5]
    tie_method: Literal["average_percentile_rank"]
    insufficient_cohort_disposition: Literal["NULL_BLOCKED_NO_FALLBACK"]
    bands: tuple[QualityBand, ...]


@dataclass(frozen=True, slots=True)
class UpsideBucketPolicy:
    horizon_months: Literal[12]
    sensitivity_horizons_months: tuple[Literal[24], Literal[36]]
    return_unit: Literal["decimal_return"]
    thresholds: tuple[Decimal, Decimal, Decimal, Decimal]
    audit_gate_contract: Literal["AuditGateDecision.v1"]


@dataclass(frozen=True, slots=True)
class DownsideComponentWeights:
    maximum_drawdown_vulnerability: Decimal
    permanent_capital_loss_vulnerability: Decimal
    material_adverse_event_vulnerability: Decimal
    sum: Decimal


@dataclass(frozen=True, slots=True)
class DownsideBucketPolicy:
    horizon_months: Literal[12]
    component_weights: DownsideComponentWeights
    composite_thresholds: tuple[Decimal, Decimal, Decimal, Decimal]
    construct_names: tuple[
        Literal["maximum_drawdown_vulnerability"],
        Literal["permanent_capital_loss_vulnerability"],
        Literal["material_adverse_event_vulnerability"],
    ]


@dataclass(frozen=True, slots=True)
class EvidenceFamilyOwnership:
    evidence_family_id: str
    primary_component: Component
    excluded_from: tuple[ScoredComponent, ...]
    disposition: Literal["single_owner", "excluded_hard_gate", "excluded_duplicate"]
    policy_rule_id: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AntiDoubleCountPolicy:
    version: Literal["1.0.0"]
    evidence_family_policy_locator: Literal[
        "AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership"
    ]
    evidence_family_policy_canonicalization: Literal["RFC8785_JCS"]
    evidence_family_policy_sha256: str
    evidence_family_ownership: tuple[EvidenceFamilyOwnership, ...]


@dataclass(frozen=True, slots=True)
class BombPolicy:
    allowed_event_types: tuple[
        Literal["formal_adverse_opinion"], Literal["formal_disclaimer"],
        Literal["confirmed_fraud"], Literal["default"], Literal["insolvency"],
        Literal["major_regulatory_action"], Literal["other_governed"],
    ]
    requires_authoritative: Literal[True]
    requires_material: Literal[True]
    requires_current_relevance: Literal[True]


@dataclass(frozen=True, slots=True)
class CandidatePolicyBundle:
    pillar_weights: PillarWeights
    quality_policy: QualityPolicy
    upside_bucket_policy: UpsideBucketPolicy
    downside_bucket_policy: DownsideBucketPolicy
    anti_double_count_policy: AntiDoubleCountPolicy
    bomb_policy: BombPolicy
    champion_id: str
    challenger_ids: tuple[str, ...]
    policy_version: str
    publishable: Literal[False]
    policy_coverage: Decimal
    failure_reasons: dict[str, str]
    input_producer_shas: dict[str, str]
    available_at: str
    generation_id: str
    producer_candidate_sha: str
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["CandidatePolicyBundle.v1"] = "CandidatePolicyBundle.v1"
    source_version: Literal[
        "AuditGateDecision.v1+EarningsCapitalEfficiencyCandidate.v1+CashBalanceAllocationCandidate.v1+PeerOutlookEvidence.v1+BusinessMoatCandidate.v1+GovernancePeopleCandidate.v1+Pillar1AuditReliabilityCandidate.v1+ValuationUpsideDiagnostic.v1+DownsideStressDiagnostic.v1"
    ] = "AuditGateDecision.v1+EarningsCapitalEfficiencyCandidate.v1+CashBalanceAllocationCandidate.v1+PeerOutlookEvidence.v1+BusinessMoatCandidate.v1+GovernancePeopleCandidate.v1+Pillar1AuditReliabilityCandidate.v1+ValuationUpsideDiagnostic.v1+DownsideStressDiagnostic.v1"
    formula_version: Literal["candidate-policy-owned-families-jcs.v1"] = (
        "candidate-policy-owned-families-jcs.v1"
    )
    model_version: Literal["winsor-rank-peer-cohort-v1"] = (
        "winsor-rank-peer-cohort-v1"
    )


_SHA = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_ALL_SCORED: tuple[ScoredComponent, ...] = (
    "audit_reliability", "earnings_capital_efficiency", "cash_balance_allocation",
    "business_moat", "governance", "people_adaptability",
    "maximum_drawdown_vulnerability", "permanent_capital_loss_vulnerability",
    "material_adverse_event_vulnerability",
)


def jcs_canonicalize(value: Any) -> bytes:
    """RFC8785 canonical bytes for the JSON-only policy slice used by T19.

    The policy slice contains objects, arrays, strings and booleans only.  JCS
    number serialization is intentionally outside this transform's accepted domain.
    """
    def validate(item: Any) -> None:
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise CandidatePolicyError("JCS rejects lone surrogate code points")
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                validate(child)
            return
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise CandidatePolicyError("JCS object keys must be strings")
            for key, child in item.items():
                validate(key)
                validate(child)
            return
        raise CandidatePolicyError("JCS policy slice contains unsupported type")

    validate(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def evidence_family_policy_sha256(
    ownership: Sequence[EvidenceFamilyOwnership] | Sequence[Mapping[str, Any]],
) -> str:
    value = [asdict(item) if isinstance(item, EvidenceFamilyOwnership) else dict(item) for item in ownership]
    return sha256(jcs_canonicalize(value)).hexdigest()


def validate_evidence_family_policy_hash(
    ownership: Sequence[EvidenceFamilyOwnership] | Sequence[Mapping[str, Any]],
    claimed_sha256: str,
) -> None:
    if evidence_family_policy_sha256(ownership) != claimed_sha256:
        raise CandidatePolicyError("evidence family policy slice hash mismatch")


def _instant(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CandidatePolicyError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CandidatePolicyError(f"{field} must be timezone-aware")
    return result


def _primary(family: str) -> ScoredComponent:
    if family.startswith("audit:"):
        return "audit_reliability"
    if family in {"earnings_outcomes", "capital_efficiency"}:
        return "earnings_capital_efficiency"
    if family in {"cash_conversion", "balance_sheet", "capital_allocation", "high_risk_notes"}:
        return "cash_balance_allocation"
    if family.startswith("business:") or family == "industry:peer_outlook":
        return "business_moat"
    if family.startswith("governance:"):
        return "governance"
    if family.startswith(("people:", "adaptability:", "management:")):
        return "people_adaptability"
    if family in {
        "maximum_drawdown_vulnerability", "permanent_capital_loss_vulnerability",
        "material_adverse_event_vulnerability",
    }:
        return cast(ScoredComponent, family)
    raise CandidatePolicyError(f"BLOCKED_CONTRACT: no owner for evidence family {family}")


def _policy_evidence_id(family: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", family)
    value = f"policy:T19:single-owner:{safe}"
    if len(value) <= 128:
        return value
    return f"{value[:111]}:{sha256(family.encode('utf-8')).hexdigest()[:16]}"


def _ownership(
    gate: AuditGateDecision,
    earnings: EarningsCapitalEfficiencyCandidate,
    cash: CashBalanceAllocationCandidate,
    business: BusinessMoatCandidate,
    governance: GovernancePeopleCandidate,
    audit: Pillar1AuditReliabilityCandidate,
    downside: DownsideStressDiagnostic,
) -> tuple[EvidenceFamilyOwnership, ...]:
    memberships: dict[str, set[ScoredComponent]] = {}
    sources = (
        ("audit_reliability", audit.evidence_family_ids),
        ("earnings_capital_efficiency", earnings.evidence_family_ids),
        ("cash_balance_allocation", cash.evidence_family_ids),
        ("business_moat", business.evidence_family_ids),
        ("governance", tuple(f for f in governance.evidence_family_ids if f.startswith("governance:"))),
        ("people_adaptability", tuple(f for f in governance.evidence_family_ids if not f.startswith("governance:") and f != "governance_people:uncovered")),
        ("maximum_drawdown_vulnerability", ("maximum_drawdown_vulnerability",)),
        ("permanent_capital_loss_vulnerability", ("permanent_capital_loss_vulnerability",)),
        ("material_adverse_event_vulnerability", ("material_adverse_event_vulnerability",)),
    )
    for component, families in sources:
        if len(set(families)) != len(families):
            raise CandidatePolicyError(
                f"duplicate evidence family ID in {component}"
            )
        for family in families:
            if not family or len(family) > 128:
                raise CandidatePolicyError("invalid evidence family ID")
            memberships.setdefault(family, set()).add(cast(ScoredComponent, component))

    rows: list[EvidenceFamilyOwnership] = []
    for family in sorted(memberships):
        primary = _primary(family)
        excluded = cast(
            tuple[ScoredComponent, ...],
            tuple(
                component
                for component in _ALL_SCORED
                if component in memberships[family] and component != primary
            ),
        )
        rows.append(EvidenceFamilyOwnership(
            evidence_family_id=family,
            primary_component=primary,
            excluded_from=excluded,
            disposition="excluded_duplicate" if excluded else "single_owner",
            policy_rule_id=f"T19.owner.{family}"[:128],
            evidence_ids=(_policy_evidence_id(family),),
        ))

    if gate.hard_gate_evidence_ids:
        if any(not evidence or len(evidence) > 128 for evidence in gate.hard_gate_evidence_ids):
            raise CandidatePolicyError("hard-gate evidence ID exceeds policy contract")
        rows.append(EvidenceFamilyOwnership(
            evidence_family_id="audit:hard_gate",
            primary_component="hard_gate_only",
            excluded_from=_ALL_SCORED,
            disposition="excluded_hard_gate",
            policy_rule_id="T19.owner.audit-hard-gate",
            evidence_ids=tuple(gate.hard_gate_evidence_ids),
        ))
    rows.sort(key=lambda row: row.evidence_family_id)
    if not rows or len(rows) > 256:
        raise CandidatePolicyError("evidence family ownership count must be 1..256")
    if len({row.evidence_family_id for row in rows}) != len(rows):
        raise CandidatePolicyError("duplicate evidence family ID")
    for row in rows:
        if row.primary_component in row.excluded_from:
            raise CandidatePolicyError("primary component cannot be excluded")
        expected = (
            "excluded_hard_gate" if row.primary_component == "hard_gate_only"
            else "excluded_duplicate" if row.excluded_from else "single_owner"
        )
        if row.disposition != expected:
            raise CandidatePolicyError("ownership disposition mismatch")
    return tuple(rows)


def _validate_inputs(
    gate: AuditGateDecision,
    earnings: EarningsCapitalEfficiencyCandidate,
    cash: CashBalanceAllocationCandidate,
    peers: PeerOutlookEvidence,
    business: BusinessMoatCandidate,
    governance: GovernancePeopleCandidate,
    audit: Pillar1AuditReliabilityCandidate,
    valuation: ValuationUpsideDiagnostic,
    downside: DownsideStressDiagnostic,
    producer_shas: Mapping[str, str],
) -> None:
    expected = (
        (gate.schema_version, "AuditGateDecision.v1"),
        (earnings.schema_version, "EarningsCapitalEfficiencyCandidate.v1"),
        (cash.schema_version, "CashBalanceAllocationCandidate.v1"),
        (peers.schema_version, "PeerOutlookEvidence.v1"),
        (business.schema_version, "BusinessMoatCandidate.v1"),
        (governance.schema_version, "GovernancePeopleCandidate.v1"),
        (audit.schema_version, "Pillar1AuditReliabilityCandidate.v1"),
        (valuation.schema_version, "ValuationUpsideDiagnostic.v1"),
        (downside.schema_version, "DownsideStressDiagnostic.v1"),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise CandidatePolicyError("BLOCKED_CONTRACT: producer schema mismatch")
    required = {"T07", "T09", "T10", "T12", "T13", "T14", "T16", "T17", "T18"}
    if set(producer_shas) != required or any(not _SHA.fullmatch(value) for value in producer_shas.values()):
        raise CandidatePolicyError("BLOCKED_CONTRACT: exact input producer SHAs required")
    bound = {
        "T12": peers.producer_candidate_sha,
        "T13": business.producer_candidate_sha,
        "T14": governance.producer_candidate_sha,
    }
    if any(producer_shas[ticket] != value for ticket, value in bound.items()):
        raise CandidatePolicyError("BLOCKED_CONTRACT: producer SHA binding mismatch")
    if peers.status != "available" or peers.issuer_id != business.issuer_id or tuple(peers.peer_ids) != tuple(business.peer_ids):
        raise CandidatePolicyError("BLOCKED_CONTRACT: T12/T13 issuer or peer mismatch")
    if valuation.rating_disposition != "NO_RATING_NOT_APPLICABLE" or downside.rating_disposition != "NO_RATING_NOT_APPLICABLE":
        raise CandidatePolicyError("BLOCKED_CONTRACT: upstream rating disposition mismatch")


def build_candidate_policy_bundle(
    gate: AuditGateDecision,
    earnings: EarningsCapitalEfficiencyCandidate,
    cash: CashBalanceAllocationCandidate,
    peers: PeerOutlookEvidence,
    business: BusinessMoatCandidate,
    governance: GovernancePeopleCandidate,
    audit: Pillar1AuditReliabilityCandidate,
    valuation: ValuationUpsideDiagnostic,
    downside: DownsideStressDiagnostic,
    *,
    producer_shas: Mapping[str, str],
    generation_id: str,
    producer_candidate_sha: str,
) -> CandidatePolicyBundle:
    _validate_inputs(gate, earnings, cash, peers, business, governance, audit, valuation, downside, producer_shas)
    if not generation_id or not _SHA.fullmatch(producer_candidate_sha):
        raise CandidatePolicyError("generation ID and producer candidate SHA required")

    ownership = _ownership(gate, earnings, cash, business, governance, audit, downside)
    policy_hash = evidence_family_policy_sha256(ownership)
    anti = AntiDoubleCountPolicy(
        version="1.0.0",
        evidence_family_policy_locator="AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership",
        evidence_family_policy_canonicalization="RFC8785_JCS",
        evidence_family_policy_sha256=policy_hash,
        evidence_family_ownership=ownership,
    )
    coverages = (
        gate.coverage, earnings.coverage, cash.coverage, peers.coverage,
        business.coverage, governance.coverage, audit.coverage,
        valuation.coverage, downside.coverage,
    )
    if any(not Decimal("0") <= value <= Decimal("1") for value in coverages):
        raise CandidatePolicyError("upstream coverage outside 0..1")
    available_values = (
        gate.available_at, earnings.available_at, cash.available_at, peers.available_at,
        business.available_at, governance.available_at, audit.available_at,
        valuation.available_at, downside.available_at,
    )
    instants = tuple(_instant(value, "upstream available_at") for value in available_values)
    if any(value is None for value in instants):
        raise CandidatePolicyError("BLOCKED_CONTRACT: all producer available_at values required")
    available = max(cast(datetime, value) for value in instants)

    return CandidatePolicyBundle(
        pillar_weights=PillarWeights(),
        quality_policy=QualityPolicy(
            normalisation="winsor_rank",
            winsor_lower_quantile=Decimal("0.025"),
            winsor_upper_quantile=Decimal("0.975"),
            cohort_locator="PeerOutlookEvidence.peer_ids+issuer_id",
            minimum_cohort_size=5,
            tie_method="average_percentile_rank",
            insufficient_cohort_disposition="NULL_BLOCKED_NO_FALLBACK",
            bands=tuple(
                QualityBand(Decimal(lower), Decimal(upper), label)
                for lower, upper, label in (
                    ("0", "20", "very_weak"), ("20", "40", "weak"),
                    ("40", "60", "neutral"), ("60", "80", "strong"),
                    ("80", "100", "very_strong"),
                )
            ),
        ),
        upside_bucket_policy=UpsideBucketPolicy(
            horizon_months=12,
            sensitivity_horizons_months=(24, 36),
            return_unit="decimal_return",
            thresholds=(Decimal("-0.20"), Decimal("0"), Decimal("0.15"), Decimal("0.30")),
            audit_gate_contract="AuditGateDecision.v1",
        ),
        downside_bucket_policy=DownsideBucketPolicy(
            horizon_months=12,
            component_weights=DownsideComponentWeights(
                Decimal("0.30"), Decimal("0.40"), Decimal("0.30"), Decimal("1")
            ),
            composite_thresholds=(Decimal("20"), Decimal("40"), Decimal("60"), Decimal("80")),
            construct_names=(
                "maximum_drawdown_vulnerability",
                "permanent_capital_loss_vulnerability",
                "material_adverse_event_vulnerability",
            ),
        ),
        anti_double_count_policy=anti,
        bomb_policy=BombPolicy(
            allowed_event_types=(
                "formal_adverse_opinion", "formal_disclaimer", "confirmed_fraud",
                "default", "insolvency", "major_regulatory_action", "other_governed",
            ),
            requires_authoritative=True,
            requires_material=True,
            requires_current_relevance=True,
        ),
        champion_id="winsor-rank-peer-cohort-v1",
        challenger_ids=("robust-z-candidate-v1",),
        policy_version="1.0.0",
        publishable=False,
        policy_coverage=min(coverages),
        failure_reasons={},
        input_producer_shas=dict(sorted(producer_shas.items())),
        available_at=available.isoformat(),
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
    )


__all__ = [
    "CandidatePolicyBundle", "CandidatePolicyError", "EvidenceFamilyOwnership",
    "build_candidate_policy_bundle", "evidence_family_policy_sha256",
    "jcs_canonicalize", "validate_evidence_family_policy_hash",
]
