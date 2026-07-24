"""PIT admission contract for issuer-level business and moat evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, Sequence

from company_quality.industry.routing import IndustryRoute

SourceTier = Literal["official", "issuer_primary", "trusted_secondary"]
Category = Literal[
    "revenue_driver", "customer_concentration", "supplier_concentration",
    "geography_concentration", "switching_cost", "network_effect",
    "cost_advantage", "intangible_assets", "efficient_scale", "competition",
]
Direction = Literal["support", "counter", "context"]
ExtractionMethod = Literal["deterministic", "llm"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_PERCENT_CATEGORIES = {
    "revenue_driver", "customer_concentration", "supplier_concentration",
    "geography_concentration",
}
_MOAT_CATEGORIES = {
    "switching_cost", "network_effect", "cost_advantage",
    "intangible_assets", "efficient_scale",
}


class IssuerBusinessEvidenceError(RuntimeError):
    pass


class AnnualReportArtifact(Protocol):
    issuer_id: str
    available_at: str
    pdf_source_url: str | None
    pdf_sha256: str | None
    retrieved_at: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class BusinessSource:
    source_id: str
    source_tier: SourceTier
    url: str
    content_sha256: str
    available_at: str
    retrieved_at: str


@dataclass(frozen=True, slots=True)
class BusinessObservation:
    evidence_id: str
    source_id: str
    claim_key: str
    category: Category
    name: str
    statement: str
    direction: Direction
    numeric_value: Decimal | None
    period_end: str
    available_at: str
    extraction_method: ExtractionMethod = "deterministic"
    ai_execution_id: str | None = None


@dataclass(frozen=True, slots=True)
class AdmittedBusinessObservation:
    evidence_id: str
    source_id: str
    source_tier: SourceTier
    claim_key: str
    category: Category
    name: str
    statement: str
    direction: Direction
    numeric_value: Decimal | None
    period_end: str
    available_at: str
    extraction_method: ExtractionMethod
    ai_execution_id: str | None


@dataclass(frozen=True, slots=True)
class BusinessSourceRecord:
    source_id: str
    source_tier: SourceTier
    url: str
    content_sha256: str
    available_at: str
    retrieved_at: str
    used: bool


@dataclass(frozen=True, slots=True)
class IssuerBusinessEvidence:
    issuer_id: str
    observations: tuple[AdmittedBusinessObservation, ...]
    source_records: tuple[BusinessSourceRecord, ...]
    evidence_family_ids: tuple[str, ...]
    counter_evidence_ids: tuple[str, ...]
    ai_execution_ids: tuple[str, ...]
    available_at: str
    coverage: Decimal
    confidence: Decimal
    generation_id: str
    producer_candidate_sha: str
    status: Literal["available"] = "available"
    reason: None = None
    publication_status: Literal["NON_PUBLISHABLE_CANDIDATE"] = (
        "NON_PUBLISHABLE_CANDIDATE"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["IssuerBusinessEvidence.v1"] = (
        "IssuerBusinessEvidence.v1"
    )
    source_version: Literal["T06+issuer-primary+trusted-secondary.v1"] = (
        "T06+issuer-primary+trusted-secondary.v1"
    )
    formula_version: Literal["official-first-claim-admission.v1"] = (
        "official-first-claim-admission.v1"
    )
    model_version: Literal["issuer-business-evidence-1.0.0"] = (
        "issuer-business-evidence-1.0.0"
    )


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise IssuerBusinessEvidenceError(f"invalid {field}")
    return value.strip()


def _instant(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise IssuerBusinessEvidenceError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IssuerBusinessEvidenceError(f"{field} must be timezone-aware")
    return parsed


def _validate_value(item: BusinessObservation) -> None:
    value = item.numeric_value
    if item.category in _PERCENT_CATEGORIES:
        if value is not None and not Decimal("0") <= value <= Decimal("100"):
            raise IssuerBusinessEvidenceError("percentage observation outside [0,100]")
    elif item.category in _MOAT_CATEGORIES:
        if value is not None and not Decimal("0") <= value <= Decimal("1"):
            raise IssuerBusinessEvidenceError("moat observation outside [0,1]")
    elif value is not None:
        raise IssuerBusinessEvidenceError("competition observation cannot carry a score")


def build_issuer_business_evidence(
    route: IndustryRoute,
    annual_report: AnnualReportArtifact,
    sources: Sequence[BusinessSource],
    observations: Sequence[BusinessObservation],
    *,
    generation_id: str,
    producer_candidate_sha: str,
) -> IssuerBusinessEvidence:
    """Admit source-bound issuer observations without deriving a moat score."""

    if route.schema_version != "IndustryRoute.v1" or route.status != "routed":
        raise IssuerBusinessEvidenceError("a routed IndustryRoute.v1 is required")
    if annual_report.schema_version != "AuditFilingInventory.v1":
        raise IssuerBusinessEvidenceError("expected AuditFilingInventory.v1")
    if annual_report.issuer_id != route.issuer_id:
        raise IssuerBusinessEvidenceError("annual report issuer conflicts with route")
    if annual_report.pdf_sha256 is None or annual_report.pdf_source_url is None:
        raise IssuerBusinessEvidenceError("official annual-report PDF authority is required")
    if _SHA256.fullmatch(annual_report.pdf_sha256) is None:
        raise IssuerBusinessEvidenceError("invalid annual-report PDF SHA256")
    _text(generation_id, "generation_id", 128)
    if _GIT_SHA.fullmatch(producer_candidate_sha) is None:
        raise IssuerBusinessEvidenceError("invalid producer_candidate_sha")
    decision_time = _instant(route.decision_time, "decision_time")
    if _instant(annual_report.available_at, "annual report available_at") > decision_time:
        raise IssuerBusinessEvidenceError("annual report is not PIT-admissible")

    source_map: dict[str, BusinessSource] = {}
    if not sources or len(sources) > 64:
        raise IssuerBusinessEvidenceError("one to 64 business sources are required")
    for source in sources:
        source_id = _text(source.source_id, "source_id", 128)
        if source_id in source_map:
            raise IssuerBusinessEvidenceError("duplicate source_id")
        if source.source_tier not in ("official", "issuer_primary", "trusted_secondary"):
            raise IssuerBusinessEvidenceError("invalid source tier")
        _text(source.url, "source URL", 4096)
        if _SHA256.fullmatch(source.content_sha256) is None:
            raise IssuerBusinessEvidenceError("invalid source SHA256")
        available = _instant(source.available_at, "source available_at")
        if available > decision_time:
            continue
        _instant(source.retrieved_at, "source retrieved_at")
        source_map[source_id] = source
    annual_sources = tuple(
        source for source in source_map.values()
        if source.content_sha256 == annual_report.pdf_sha256
        and source.url == annual_report.pdf_source_url
        and source.source_tier in ("official", "issuer_primary")
    )
    if len(annual_sources) != 1:
        raise IssuerBusinessEvidenceError("exactly one source must bind the T06 annual report")

    valid: list[BusinessObservation] = []
    seen_ids: set[str] = set()
    for item in observations:
        evidence_id = _text(item.evidence_id, "evidence_id", 128)
        available = _instant(item.available_at, "observation available_at")
        if available > decision_time:
            continue
        if evidence_id in seen_ids:
            raise IssuerBusinessEvidenceError("duplicate evidence_id")
        seen_ids.add(evidence_id)
        source = source_map.get(_text(item.source_id, "observation source_id", 128))
        if source is None:
            raise IssuerBusinessEvidenceError("observation has no PIT-admitted source")
        if available < _instant(source.available_at, "source available_at"):
            raise IssuerBusinessEvidenceError("observation predates its source")
        _text(item.claim_key, "claim_key", 128)
        _text(item.name, "observation name", 128)
        _text(item.statement, "observation statement", 512)
        if item.category not in _PERCENT_CATEGORIES | _MOAT_CATEGORIES | {"competition"}:
            raise IssuerBusinessEvidenceError("invalid observation category")
        if item.direction not in ("support", "counter", "context"):
            raise IssuerBusinessEvidenceError("invalid observation direction")
        _validate_value(item)
        try:
            datetime.fromisoformat(item.period_end)
        except ValueError as exc:
            raise IssuerBusinessEvidenceError("invalid observation period_end") from exc
        if item.extraction_method == "llm":
            _text(item.ai_execution_id, "AI execution_id", 128)
        elif item.extraction_method != "deterministic" or item.ai_execution_id is not None:
            raise IssuerBusinessEvidenceError("invalid extraction provenance")
        valid.append(item)

    by_claim: dict[str, list[BusinessObservation]] = {}
    for item in valid:
        by_claim.setdefault(item.claim_key, []).append(item)
    selected: list[BusinessObservation] = []
    rank = {"official": 0, "issuer_primary": 0, "trusted_secondary": 1}
    for claim_key in sorted(by_claim):
        candidates = by_claim[claim_key]
        best_rank = min(rank[source_map[item.source_id].source_tier] for item in candidates)
        best = [item for item in candidates if rank[source_map[item.source_id].source_tier] == best_rank]
        signatures = {
            (item.category, item.name, item.statement, item.direction, item.numeric_value,
             item.period_end)
            for item in best
        }
        if len(signatures) != 1:
            raise IssuerBusinessEvidenceError("unresolved same-rank claim conflict")
        selected.append(min(best, key=lambda item: (item.available_at, item.evidence_id)))
    if not selected:
        raise IssuerBusinessEvidenceError("at least one PIT business observation is required")
    if len(selected) > 128:
        raise IssuerBusinessEvidenceError("business observations exceed the 128-item limit")
    if not any(item.category == "revenue_driver" for item in selected):
        raise IssuerBusinessEvidenceError("at least one revenue-driver observation is required")

    selected.sort(key=lambda item: (item.category, item.claim_key, item.evidence_id))
    used_ids = {item.source_id for item in selected} | {annual_sources[0].source_id}
    admitted = tuple(AdmittedBusinessObservation(
        evidence_id=item.evidence_id,
        source_id=item.source_id,
        source_tier=source_map[item.source_id].source_tier,
        claim_key=item.claim_key,
        category=item.category,
        name=item.name,
        statement=item.statement,
        direction=item.direction,
        numeric_value=item.numeric_value,
        period_end=item.period_end,
        available_at=item.available_at,
        extraction_method=item.extraction_method,
        ai_execution_id=item.ai_execution_id,
    ) for item in selected)
    records = tuple(BusinessSourceRecord(
        source_id=source.source_id,
        source_tier=source.source_tier,
        url=source.url,
        content_sha256=source.content_sha256,
        available_at=source.available_at,
        retrieved_at=source.retrieved_at,
        used=source.source_id in used_ids,
    ) for source in sorted(source_map.values(), key=lambda value: value.source_id))
    secondary_used = any(item.source_tier == "trusted_secondary" for item in admitted)
    covered_categories = {item.category for item in admitted}
    coverage = Decimal(len(covered_categories)) / Decimal(len(_PERCENT_CATEGORIES | _MOAT_CATEGORIES | {"competition"}))
    if secondary_used:
        coverage *= Decimal("0.8")
    return IssuerBusinessEvidence(
        issuer_id=route.issuer_id,
        observations=admitted,
        source_records=records,
        evidence_family_ids=tuple(sorted({f"business:{item.category}" for item in admitted})),
        counter_evidence_ids=tuple(item.evidence_id for item in admitted if item.direction == "counter"),
        ai_execution_ids=tuple(sorted({item.ai_execution_id for item in admitted if item.ai_execution_id is not None})),
        available_at=max(
            [_instant(annual_report.available_at, "annual report available_at"),
             *(_instant(item.available_at, "observation available_at") for item in admitted)]
        ).isoformat(),
        coverage=coverage,
        confidence=Decimal("0.75") if secondary_used else Decimal("1"),
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
    )
