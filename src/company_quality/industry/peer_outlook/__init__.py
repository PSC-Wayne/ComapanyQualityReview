"""Deterministic, point-in-time peer and industry-outlook evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Mapping, Sequence

from company_quality.industry.routing import IndustryRoute

AuthorityTier = Literal["official", "trusted_secondary"]
Direction = Literal["positive", "negative", "mixed"]
Scenario = Literal["bear", "base", "bull"]
InclusionReasonCode = Literal[
    "industry_match", "revenue_mix_match", "market_match", "business_model_match"
]
ExclusionReasonCode = Literal[
    "financial_sector", "wrong_market", "insufficient_history", "business_model_mismatch"
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SCENARIOS: tuple[Scenario, ...] = ("bear", "base", "bull")


class PeerOutlookError(RuntimeError):
    """Raised when T12 cannot produce source-complete, PIT-safe evidence."""


@dataclass(frozen=True, slots=True)
class PeerAuthority:
    """Injected company-list or outlook authority snapshot."""

    source_id: str
    source_tier: AuthorityTier
    url: str
    content_sha256: str
    available_at: str
    retrieved_at: str
    rows: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class OutlookObservation:
    """A verbatim outlook observation bound to one injected authority."""

    evidence_id: str
    authority_id: str
    claim_key: str
    statement: str
    driver: str
    direction: Direction
    horizon_months: Literal[12]
    scenario: Scenario
    available_at: str
    is_counter_evidence: bool
    cycle_normalized: bool
    extraction_method: Literal["deterministic", "llm"] = "deterministic"
    ai_execution_id: str | None = None


@dataclass(frozen=True, slots=True)
class PeerInclusionReason:
    peer_id: str
    reason_code: InclusionReasonCode
    evidence_id: str


@dataclass(frozen=True, slots=True)
class PeerExclusionReason:
    issuer_id: str
    reason_code: ExclusionReasonCode
    evidence_id: str


@dataclass(frozen=True, slots=True)
class SectorDriver:
    driver: str
    direction: Direction
    horizon_months: Literal[12]
    evidence_id: str


@dataclass(frozen=True, slots=True)
class ScenarioEvidenceIds:
    bear: tuple[str, ...]
    base: tuple[str, ...]
    bull: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CycleNormalizationGate:
    required: bool
    satisfied: bool
    reason: str | None
    normalization_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthorityRecord:
    source_id: str
    source_tier: AuthorityTier
    url: str
    content_sha256: str
    available_at: str
    retrieved_at: str
    used: bool


@dataclass(frozen=True, slots=True)
class PeerOutlookEvidence:
    issuer_id: str
    status: Literal["available", "blocked"]
    reason: str | None
    peer_ids: tuple[str, ...]
    inclusion_reasons: tuple[PeerInclusionReason, ...]
    exclusion_reasons: tuple[PeerExclusionReason, ...]
    sector_drivers: tuple[SectorDriver, ...]
    outlook_evidence_ids: tuple[str, ...]
    counter_evidence_ids: tuple[str, ...]
    ai_execution_ids: tuple[str, ...]
    scenario_assumptions: dict[str, tuple[str, ...]]
    scenario_evidence_ids: ScenarioEvidenceIds
    cycle_normalization_gate: CycleNormalizationGate
    authority_records: tuple[AuthorityRecord, ...]
    available_at: str
    coverage: Decimal
    confidence: Decimal
    generation_id: str
    producer_candidate_sha: str
    publication_status: Literal["NON_PUBLISHABLE_CANDIDATE"] = (
        "NON_PUBLISHABLE_CANDIDATE"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["PeerOutlookEvidence.v1"] = "PeerOutlookEvidence.v1"
    source_version: Literal[
        "IndustryRoute.v1+official-company-list.v1+OutlookObservation.v1"
    ] = "IndustryRoute.v1+official-company-list.v1+OutlookObservation.v1"
    formula_version: Literal[
        "same-market-official-industry-hybrid-outlook.v1"
    ] = "same-market-official-industry-hybrid-outlook.v1"
    model_version: Literal["peer-outlook-deterministic-1.0.0"] = (
        "peer-outlook-deterministic-1.0.0"
    )


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise PeerOutlookError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PeerOutlookError(f"{field} must be timezone-aware")
    return result


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise PeerOutlookError(f"invalid {field}")
    return value.strip()


def _validate_authorities(
    authorities: Sequence[PeerAuthority], decision_time: datetime
) -> dict[str, PeerAuthority]:
    if not authorities or len(authorities) > 64:
        raise PeerOutlookError("one to 64 source authorities are required")
    by_id: dict[str, PeerAuthority] = {}
    for authority in authorities:
        source_id = _bounded_text(authority.source_id, "authority source_id", 128)
        if source_id in by_id:
            raise PeerOutlookError("duplicate authority source_id")
        if authority.source_tier not in ("official", "trusted_secondary"):
            raise PeerOutlookError("unsupported authority source tier")
        _bounded_text(authority.url, "authority source URL", 4096)
        if _SHA256.fullmatch(authority.content_sha256) is None:
            raise PeerOutlookError("invalid authority content SHA256")
        available = _instant(authority.available_at, "authority available_at")
        if available > decision_time:
            continue
        _instant(authority.retrieved_at, "authority retrieved_at")
        by_id[source_id] = authority
    return by_id


def _peer_authority(
    route: IndustryRoute, authorities: Mapping[str, PeerAuthority]
) -> PeerAuthority:
    candidates = tuple(
        authority
        for authority in authorities.values()
        if authority.source_tier == "official"
        and authority.content_sha256 == route.authority_sha256
    )
    if not candidates:
        raise PeerOutlookError("official peer authority does not bind IndustryRoute.v1")
    if len(candidates) != 1:
        raise PeerOutlookError("conflicting official peer authorities")
    return candidates[0]


def _peer_set(
    route: IndustryRoute, authority: PeerAuthority
) -> tuple[
    tuple[str, ...],
    tuple[PeerInclusionReason, ...],
    tuple[PeerExclusionReason, ...],
    bool,
]:
    rows: dict[str, Mapping[str, str]] = {}
    for row in authority.rows:
        issuer_id = _bounded_text(row.get("issuer_id"), "official peer issuer_id", 64)
        previous = rows.get(issuer_id)
        normalized = {str(key): str(value).strip() for key, value in row.items()}
        if previous is not None:
            route_fields = ("market", "industry_code", "history_years", "business_model")
            if any(previous.get(key, "").strip() != normalized.get(key, "") for key in route_fields):
                raise PeerOutlookError("conflicting official rows for peer issuer")
            if normalized.get("security_code", "") < previous.get("security_code", ""):
                rows[issuer_id] = normalized
            continue
        rows[issuer_id] = normalized

    target = rows.get(route.issuer_id)
    if target is None:
        raise PeerOutlookError("target issuer is absent from official peer authority")
    target_market = _bounded_text(target.get("market"), "target market", 64)
    if target.get("industry_code", "").strip() != route.industry_code:
        raise PeerOutlookError("official target industry conflicts with IndustryRoute.v1")

    evidence_id = f"authority:{authority.content_sha256}"
    peers: list[str] = []
    exclusions: list[PeerExclusionReason] = []
    expected_models = {
        tag for tag in route.business_model_tags if not tag.startswith("sector:")
    }
    for issuer_id in sorted(rows):
        if issuer_id == route.issuer_id:
            continue
        row = rows[issuer_id]
        market = row.get("market", "").strip()
        industry = row.get("industry_code", "").strip()
        business_model = row.get("business_model", "").strip()
        history_raw = row.get("history_years", "").strip()
        try:
            history_years = Decimal(history_raw) if history_raw else None
        except Exception as exc:
            raise PeerOutlookError("invalid official peer history_years") from exc

        reason: ExclusionReasonCode | None = None
        if market != target_market:
            reason = "wrong_market"
        elif industry == "17":
            reason = "financial_sector"
        elif industry != route.industry_code:
            reason = "business_model_mismatch"
        elif history_years is not None and history_years < Decimal("3"):
            reason = "insufficient_history"
        elif expected_models and business_model and business_model not in expected_models:
            reason = "business_model_mismatch"

        if reason is None:
            peers.append(issuer_id)
        else:
            exclusions.append(PeerExclusionReason(issuer_id, reason, evidence_id))

    selected = tuple(peers[:50])
    if not selected:
        raise PeerOutlookError("no eligible exact-industry same-market peers")
    inclusion = tuple(
        PeerInclusionReason(peer_id, "industry_match", evidence_id)
        for peer_id in selected
    )
    return selected, inclusion, tuple(exclusions[:100]), len(peers) > 50


def _select_observations(
    observations: Sequence[OutlookObservation],
    authorities: Mapping[str, PeerAuthority],
    decision_time: datetime,
) -> tuple[tuple[OutlookObservation, ...], bool]:
    validated: list[OutlookObservation] = []
    evidence_ids: set[str] = set()
    for item in observations:
        _bounded_text(item.evidence_id, "outlook evidence_id", 4096)
        available = _instant(item.available_at, "outlook available_at")
        if available > decision_time:
            continue
        _bounded_text(item.authority_id, "outlook source authority_id", 128)
        _bounded_text(item.claim_key, "outlook claim_key", 128)
        _bounded_text(item.statement, "outlook statement", 256)
        _bounded_text(item.driver, "outlook driver", 256)
        if item.evidence_id in evidence_ids:
            raise PeerOutlookError("duplicate outlook evidence_id")
        evidence_ids.add(item.evidence_id)
        authority = authorities.get(item.authority_id)
        if authority is None:
            raise PeerOutlookError("outlook observation has no source authority")
        if item.direction not in ("positive", "negative", "mixed"):
            raise PeerOutlookError("invalid outlook direction")
        if item.horizon_months != 12 or item.scenario not in _SCENARIOS:
            raise PeerOutlookError("invalid outlook horizon or scenario")
        if item.extraction_method not in ("deterministic", "llm"):
            raise PeerOutlookError("invalid outlook extraction method")
        if item.extraction_method == "llm":
            _bounded_text(item.ai_execution_id, "AI execution_id", 128)
        elif item.ai_execution_id is not None:
            raise PeerOutlookError("deterministic observation cannot carry AI execution_id")
        if available < _instant(authority.available_at, "authority available_at"):
            raise PeerOutlookError("outlook evidence predates its source authority")
        validated.append(item)

    by_claim: dict[str, list[OutlookObservation]] = {}
    for item in validated:
        by_claim.setdefault(item.claim_key, []).append(item)

    selected: list[OutlookObservation] = []
    used_secondary = False
    for claim_key in sorted(by_claim):
        candidates = by_claim[claim_key]
        official = [
            item
            for item in candidates
            if authorities[item.authority_id].source_tier == "official"
        ]
        chosen_pool = official or [
            item
            for item in candidates
            if authorities[item.authority_id].source_tier == "trusted_secondary"
        ]
        if not chosen_pool:
            raise PeerOutlookError("outlook claim has no allowed source authority")
        signatures = {
            (item.statement, item.driver, item.direction, item.scenario, item.is_counter_evidence)
            for item in chosen_pool
        }
        if len(signatures) != 1:
            raise PeerOutlookError("unresolved same-rank outlook claim conflict")
        chosen = min(chosen_pool, key=lambda item: (item.available_at, item.evidence_id))
        selected.append(chosen)
        used_secondary |= authorities[chosen.authority_id].source_tier == "trusted_secondary"

    if not selected:
        raise PeerOutlookError("outlook observations are required")
    selected.sort(key=lambda item: (item.scenario, item.claim_key, item.evidence_id))
    if len(selected) > 64:
        raise PeerOutlookError("outlook evidence exceeds the 64-item contract limit")
    return tuple(selected), used_secondary


def build_peer_outlook_evidence(
    route: IndustryRoute,
    authorities: Sequence[PeerAuthority],
    observations: Sequence[OutlookObservation],
    *,
    generation_id: str,
    producer_candidate_sha: str,
) -> PeerOutlookEvidence:
    """Build ``PeerOutlookEvidence.v1`` without producing source-free prose."""

    if route.schema_version != "IndustryRoute.v1":
        raise PeerOutlookError("expected IndustryRoute.v1")
    if route.status != "routed":
        raise PeerOutlookError(f"industry route is {route.status}: {route.reason}")
    _bounded_text(generation_id, "generation_id", 128)
    if _GIT_SHA.fullmatch(producer_candidate_sha) is None:
        raise PeerOutlookError("producer_candidate_sha must be a 40-character lowercase SHA")
    decision_time = _instant(route.decision_time, "route decision_time")
    authority_map = _validate_authorities(authorities, decision_time)
    official_peer_source = _peer_authority(route, authority_map)
    peer_ids, inclusion, exclusion, peer_cap_applied = _peer_set(
        route, official_peer_source
    )
    selected, used_secondary = _select_observations(
        observations, authority_map, decision_time
    )

    scenarios: dict[str, list[OutlookObservation]] = {
        scenario: [item for item in selected if item.scenario == scenario]
        for scenario in _SCENARIOS
    }
    if any(not values for values in scenarios.values()):
        raise PeerOutlookError("bear, base, and bull scenarios all require evidence")
    if any(len(values) > 16 for values in scenarios.values()):
        raise PeerOutlookError("scenario evidence exceeds the 16-item limit")
    for values in scenarios.values():
        if len({item.statement.strip() for item in values}) != len(values):
            raise PeerOutlookError("duplicate scenario statements are not allowed")

    cycle_required = route.cyclicality in ("cyclical", "deep_cyclical")
    normalized_ids = tuple(
        item.evidence_id for item in selected if item.cycle_normalized
    )
    if cycle_required and len(normalized_ids) != len(selected):
        raise PeerOutlookError("cyclical route requires cycle normalization evidence")
    cycle_gate = CycleNormalizationGate(
        required=cycle_required,
        satisfied=(not cycle_required or len(normalized_ids) == len(selected)),
        reason=(
            "deep_cyclical_normalization_satisfied"
            if route.cyclicality == "deep_cyclical"
            else "cyclical_normalization_satisfied"
            if route.cyclicality == "cyclical"
            else "cycle_normalization_not_required"
        ),
        normalization_evidence_ids=normalized_ids if cycle_required else (),
    )

    used_authority_ids = {official_peer_source.source_id} | {
        item.authority_id for item in selected
    }
    authority_records = tuple(
        AuthorityRecord(
            source_id=authority.source_id,
            source_tier=authority.source_tier,
            url=authority.url,
            content_sha256=authority.content_sha256,
            available_at=authority.available_at,
            retrieved_at=authority.retrieved_at,
            used=authority.source_id in used_authority_ids,
        )
        for authority in sorted(authority_map.values(), key=lambda item: item.source_id)
    )
    sector_drivers = tuple(
        SectorDriver(item.driver.strip(), item.direction, 12, item.evidence_id)
        for item in selected
    )
    if len(sector_drivers) > 32:
        raise PeerOutlookError("sector drivers exceed the 32-item limit")

    coverage = Decimal("0.80") if used_secondary else Decimal("1")
    confidence = Decimal("0.75") if used_secondary else Decimal("1")
    if peer_cap_applied:
        coverage -= Decimal("0.05")
    available_at = max(
        [
            _instant(official_peer_source.available_at, "peer authority available_at"),
            *(_instant(item.available_at, "outlook available_at") for item in selected),
        ]
    ).isoformat()
    scenario_assumptions = {
        scenario: tuple(item.statement.strip() for item in scenarios[scenario])
        for scenario in _SCENARIOS
    }
    scenario_ids = ScenarioEvidenceIds(
        bear=tuple(item.evidence_id for item in scenarios["bear"]),
        base=tuple(item.evidence_id for item in scenarios["base"]),
        bull=tuple(item.evidence_id for item in scenarios["bull"]),
    )
    return PeerOutlookEvidence(
        issuer_id=route.issuer_id,
        status="available",
        reason=None,
        peer_ids=peer_ids,
        inclusion_reasons=inclusion,
        exclusion_reasons=exclusion,
        sector_drivers=sector_drivers,
        outlook_evidence_ids=tuple(item.evidence_id for item in selected),
        counter_evidence_ids=tuple(
            item.evidence_id for item in selected if item.is_counter_evidence
        ),
        ai_execution_ids=tuple(sorted({
            item.ai_execution_id
            for item in selected
            if item.ai_execution_id is not None
        })),
        scenario_assumptions=scenario_assumptions,
        scenario_evidence_ids=scenario_ids,
        cycle_normalization_gate=cycle_gate,
        authority_records=authority_records,
        available_at=available_at,
        coverage=coverage,
        confidence=confidence,
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
    )
