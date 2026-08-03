"""Closed same-generation contract for the three independent research outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Mapping, Sequence, cast

from company_quality.company_analysis.rating_evidence_policy import (
    RatingDimension,
    RatingEvidenceDecision,
    admit_rating_evidence,
)
from company_quality.industry.model_route import IndustryModelRoute
from company_quality.lab.outcome_labels import TwelveMonthReturnLabel


CoreStatus = Literal[
    "formal",
    "research_only",
    "stale_reference",
    "data_insufficient",
    "industry_sample_insufficient",
]


class CompanyResearchSnapshotError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class QualityCoreResult:
    generation_id: str
    status: CoreStatus
    score: float | None
    confidence: float | None
    model_version: str
    data_as_of: str


@dataclass(frozen=True, slots=True)
class UpsideCoreResult:
    generation_id: str
    status: CoreStatus
    positive_return_probability: float | None
    official_benchmark_outperform_probability: float | None
    secondary_market_median_outperform_probability: float | None
    p10_return: float | None
    p50_return: float | None
    p90_return: float | None
    p10_price: float | None
    p50_price: float | None
    p90_price: float | None
    stars: float | None
    confidence: float | None
    model_version: str
    data_as_of: str


@dataclass(frozen=True, slots=True)
class DownsideCoreResult:
    generation_id: str
    status: CoreStatus
    risk_score: float | None
    faces: float | None
    confidence: float | None
    model_version: str
    data_as_of: str


@dataclass(frozen=True, slots=True)
class OfficialMaterialEvent:
    generation_id: str
    issuer_id: str
    security_code: str
    market: Literal["TWSE", "TPEx"]
    event_id: str
    event_type: Literal[
        "material_announcement",
        "trading_suspension",
        "altered_trading",
        "delisting",
        "regulatory_violation",
        "filing_violation",
        "financial_restatement",
    ]
    title: str
    effective_date: str
    available_at: str
    official_reason: str
    source_authority: Literal["TWSE", "TPEx"]
    source_url: str
    evidence_id: str
    confirmation_status: Literal["confirmed", "unconfirmed_research"]
    downside_candidate_status: Literal[
        "eligible_for_validation",
        "display_only",
        "unconfirmed_research",
    ]


@dataclass(frozen=True, slots=True)
class RatingEvidenceSummary:
    dimension: RatingDimension
    core_rating_eligible: bool
    ineligibility_reason: str | None
    core_evidence_ids: list[str]
    core_disclosure_kinds: list[str]
    supplemental_evidence_ids: list[str]
    extra_points: float
    unavailable_inputs: list[str]
    checklist_unresolved_ids: list[str]
    policy_as_of: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class CompanyResearchSnapshot:
    issuer_id: str
    security_code: str | None
    market: Literal["TWSE", "TPEx"] | None
    generation_id: str
    generated_at: str
    status: CoreStatus
    ai_status: Literal["AI_unavailable"]
    input_source_versions: dict[str, str]
    quality: QualityCoreResult
    upside: UpsideCoreResult
    downside: DownsideCoreResult
    rating_evidence: dict[RatingDimension, RatingEvidenceSummary]
    twelve_month_return: TwelveMonthReturnLabel | None
    industry_route: IndustryModelRoute | None = None
    official_events: list[OfficialMaterialEvent] = field(default_factory=list)
    rating_disposition: Literal["FORMAL", "RESEARCH_ONLY"] = "RESEARCH_ONLY"
    schema_version: Literal["CompanyResearchSnapshot.v2"] = (
        "CompanyResearchSnapshot.v2"
    )


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CompanyResearchSnapshotError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CompanyResearchSnapshotError(f"{field} must be timezone-aware")
    return result


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CompanyResearchSnapshotError(f"invalid {field}") from exc


def _bounded(value: float | None, lower: float, upper: float, field: str) -> None:
    if value is not None and not lower <= value <= upper:
        raise CompanyResearchSnapshotError(f"{field} outside {lower}..{upper}")


def build_company_research_snapshot(
    *,
    issuer_id: str,
    security_code: str | None,
    market: Literal["TWSE", "TPEx"] | None,
    generated_at: str,
    input_source_versions: Mapping[str, str],
    quality: QualityCoreResult,
    upside: UpsideCoreResult,
    downside: DownsideCoreResult,
    twelve_month_return: TwelveMonthReturnLabel | None = None,
    industry_route: IndustryModelRoute | None = None,
    official_events: Sequence[OfficialMaterialEvent] = (),
    rating_evidence: Mapping[RatingDimension, RatingEvidenceDecision] | None = None,
) -> CompanyResearchSnapshot:
    """Bind independent existing results without recomputing or merging their values."""
    generations = {
        quality.generation_id,
        upside.generation_id,
        downside.generation_id,
    }
    if len(generations) != 1 or not next(iter(generations)):
        raise CompanyResearchSnapshotError(
            "all core results must bind the same successful generation"
        )
    generation_id = next(iter(generations))
    if rating_evidence is None:
        rating_evidence = {
            dimension: admit_rating_evidence(
                dimension=dimension,
                issuer_id=issuer_id,
                as_of=generated_at,
                evidence=(),
            )
            for dimension in ("quality", "upside", "downside")
        }
    if set(rating_evidence) != {"quality", "upside", "downside"}:
        raise CompanyResearchSnapshotError(
            "quality, upside and downside rating evidence required"
        )
    if twelve_month_return is not None and (
        twelve_month_return.generation_id != generation_id
        or twelve_month_return.market != market
    ):
        raise CompanyResearchSnapshotError(
            "12-month return label must bind the same generation and market"
        )
    if not issuer_id:
        raise CompanyResearchSnapshotError("issuer_id required")
    generated = _instant(generated_at, "generated_at")
    if industry_route is not None:
        if (
            industry_route.generation_id != generation_id
            or industry_route.issuer_id != issuer_id
            or industry_route.security_code != security_code
            or industry_route.market != market
        ):
            raise CompanyResearchSnapshotError(
                "industry route must bind snapshot identity, market and generation"
            )
        route_day = _day(industry_route.decision_date, "industry route decision_date")
        if route_day > generated.date():
            raise CompanyResearchSnapshotError(
                "industry route decision cannot follow snapshot generation"
            )
        if industry_route.all_market_fallback_model_id is not None:
            raise CompanyResearchSnapshotError("all-market industry fallback is forbidden")
        if not industry_route.stars_eligible and upside.stars is not None:
            raise CompanyResearchSnapshotError(
                "ineligible industry route cannot carry upside stars"
            )
        if industry_route.status == "industry_sample_insufficient":
            if upside.status != "industry_sample_insufficient" or upside.stars is not None:
                raise CompanyResearchSnapshotError(
                    "sample-insufficient industry must suppress upside stars"
                )
        if industry_route.status == "classification_unverified":
            if upside.status != "data_insufficient" or upside.stars is not None:
                raise CompanyResearchSnapshotError(
                    "unverified industry classification must suppress upside result"
                )
        if industry_route.status in {
            "eligible",
            "industry_sample_insufficient",
            "financial_separate_model",
        } and (
            not industry_route.industry_code
            or not industry_route.classification_version
            or not industry_route.classification_authority_url
            or not industry_route.classification_evidence_id
            or not industry_route.candidate_model_id
        ):
            raise CompanyResearchSnapshotError(
                "verified industry route requires classification evidence"
            )
    eligible_event_types = {
        "trading_suspension",
        "altered_trading",
        "delisting",
        "regulatory_violation",
        "filing_violation",
        "financial_restatement",
    }
    admitted_events: list[OfficialMaterialEvent] = []
    for event in official_events:
        if (
            event.generation_id != generation_id
            or event.issuer_id != issuer_id
            or event.security_code != security_code
            or event.market != market
        ):
            raise CompanyResearchSnapshotError(
                "official event must bind snapshot identity, market and generation"
            )
        available = _instant(event.available_at, "official event available_at")
        _day(event.effective_date, "official event effective_date")
        if available > generated:
            raise CompanyResearchSnapshotError(
                "official event was not available when snapshot was generated"
            )
        if (
            not event.event_id
            or not event.title
            or not event.official_reason
            or not event.evidence_id
            or not event.source_url.startswith("https://")
            or event.source_authority != event.market
        ):
            raise CompanyResearchSnapshotError("official event authority fields required")
        if event.confirmation_status == "unconfirmed_research":
            if event.downside_candidate_status != "unconfirmed_research":
                raise CompanyResearchSnapshotError(
                    "unconfirmed event cannot enter a core candidate"
                )
        elif event.downside_candidate_status == "eligible_for_validation":
            if event.event_type not in eligible_event_types:
                raise CompanyResearchSnapshotError(
                    "generic announcement cannot enter downside validation"
                )
        elif event.downside_candidate_status != "display_only":
            raise CompanyResearchSnapshotError("invalid confirmed event disposition")
        admitted_events.append(event)
    for name, result in (
        ("quality", quality),
        ("upside", upside),
        ("downside", downside),
    ):
        if not result.model_version:
            raise CompanyResearchSnapshotError(f"{name} model_version required")
        _day(result.data_as_of, f"{name} data_as_of")
        decision = rating_evidence[cast(RatingDimension, name)]
        if decision.dimension != name or decision.issuer_id != issuer_id:
            raise CompanyResearchSnapshotError(
                f"{name} rating evidence must bind snapshot dimension and issuer"
            )
        if _instant(decision.as_of, f"{name} rating evidence as_of") > generated:
            raise CompanyResearchSnapshotError(
                f"{name} rating evidence cannot follow snapshot generation"
            )
        if result.status == "formal" and not decision.core_rating_eligible:
            raise CompanyResearchSnapshotError(
                f"formal {name} requires official disclosure rating evidence"
            )
    if not input_source_versions or any(
        not key or not value for key, value in input_source_versions.items()
    ):
        raise CompanyResearchSnapshotError("input source versions required")

    _bounded(quality.score, 0, 100, "quality score")
    _bounded(quality.confidence, 0, 1, "quality confidence")
    _bounded(downside.risk_score, 0, 100, "downside risk_score")
    _bounded(downside.faces, 0, 5, "downside faces")
    _bounded(downside.confidence, 0, 1, "downside confidence")
    _bounded(upside.positive_return_probability, 0, 1, "upside positive probability")
    _bounded(
        upside.official_benchmark_outperform_probability,
        0,
        1,
        "upside official benchmark probability",
    )
    _bounded(
        upside.secondary_market_median_outperform_probability,
        0,
        1,
        "upside secondary median probability",
    )
    _bounded(upside.stars, 0, 5, "upside stars")
    _bounded(upside.confidence, 0, 1, "upside confidence")
    for values, field in (
        ((upside.p10_return, upside.p50_return, upside.p90_return), "return range"),
        ((upside.p10_price, upside.p50_price, upside.p90_price), "price range"),
    ):
        present = [value for value in values if value is not None]
        if present and (len(present) != 3 or list(values) != sorted(present)):
            raise CompanyResearchSnapshotError(f"complete ordered {field} required")

    status_priority: tuple[CoreStatus, ...] = (
        "data_insufficient",
        "industry_sample_insufficient",
        "stale_reference",
        "research_only",
        "formal",
    )
    statuses = {quality.status, upside.status, downside.status}
    status = cast(CoreStatus, next(item for item in status_priority if item in statuses))
    evidence_summaries: dict[RatingDimension, RatingEvidenceSummary] = {
        dimension: RatingEvidenceSummary(
            dimension=decision.dimension,
            core_rating_eligible=decision.core_rating_eligible,
            ineligibility_reason=decision.ineligibility_reason,
            core_evidence_ids=list(decision.core_evidence_ids),
            core_disclosure_kinds=list(decision.core_disclosure_kinds),
            supplemental_evidence_ids=list(decision.supplemental_evidence_ids),
            extra_points=float(decision.extra_points),
            unavailable_inputs=list(decision.unavailable_inputs),
            checklist_unresolved_ids=list(decision.checklist_unresolved_ids),
            policy_as_of=decision.as_of,
            policy_version=decision.policy_version,
        )
        for dimension, decision in rating_evidence.items()
    }
    source_versions = dict(input_source_versions)
    source_versions["rating_evidence_policy"] = "OfficialDisclosureRatingPolicy.v1"
    rating_disposition: Literal["FORMAL", "RESEARCH_ONLY"] = (
        "FORMAL" if statuses == {"formal"} else "RESEARCH_ONLY"
    )
    return CompanyResearchSnapshot(
        issuer_id=issuer_id,
        security_code=security_code,
        market=market,
        generation_id=generation_id,
        generated_at=generated_at,
        status=status,
        ai_status="AI_unavailable",
        input_source_versions=dict(sorted(source_versions.items())),
        quality=quality,
        upside=upside,
        downside=downside,
        rating_evidence=evidence_summaries,
        twelve_month_return=twelve_month_return,
        industry_route=industry_route,
        official_events=sorted(admitted_events, key=lambda item: item.available_at),
        rating_disposition=rating_disposition,
    )


__all__ = [
    "CompanyResearchSnapshot",
    "CompanyResearchSnapshotError",
    "DownsideCoreResult",
    "OfficialMaterialEvent",
    "QualityCoreResult",
    "RatingEvidenceSummary",
    "UpsideCoreResult",
    "build_company_research_snapshot",
]
