"""PIT exact-industry routing and sample eligibility for Spec #70."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from company_quality.industry.routing import IndustryAuthority


Market = Literal["TWSE", "TPEx"]
RouteStatus = Literal[
    "eligible",
    "industry_sample_insufficient",
    "classification_unverified",
    "financial_separate_model",
]
_TAIPEI = ZoneInfo("Asia/Taipei")
_BENCHMARKS: dict[Market, str] = {
    "TWSE": "https://openapi.twse.com.tw/v1/indicesReport/MFI94U",
    "TPEx": "https://www.tpex.org.tw/openapi/v1/tpex_reward_index",
}


class IndustryModelRouteError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EffectiveIndustryClassification:
    market: Market
    issuer_id: str
    security_code: str
    industry_code: str
    effective_from: str
    effective_to: str | None
    available_at: str
    classification_version: str
    authority_url: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class IndustryModelRoute:
    generation_id: str
    issuer_id: str
    security_code: str
    market: Market
    decision_date: str
    status: RouteStatus
    reason: str | None
    industry_code: str | None
    classification_effective_from: str | None
    classification_effective_to: str | None
    classification_version: str | None
    classification_authority_url: str | None
    classification_evidence_id: str | None
    candidate_model_id: str | None
    train_observations: int | None
    final_oos_observations: int | None
    official_benchmark_source_ref: str
    pit_value_chain_tags: list[str]
    financial_subtype: Literal["bank", "life_insurer", "securities"] | None
    stars_eligible: bool
    all_market_fallback_model_id: None = None
    schema_version: Literal["IndustryModelRoute.v1"] = "IndustryModelRoute.v1"


def _aware(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise IndustryModelRouteError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise IndustryModelRouteError(f"{field} must be timezone-aware")
    return result


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise IndustryModelRouteError(f"invalid {field}") from exc


def records_from_current_authority(
    authority: IndustryAuthority,
) -> tuple[EffectiveIndustryClassification, ...]:
    """Make current classifications valid only from their official availability day."""
    available = _aware(authority.available_at, "authority available_at")
    effective_from = available.astimezone(_TAIPEI).date().isoformat()
    return tuple(
        EffectiveIndustryClassification(
            market=authority.market,
            issuer_id=str(row.get("issuer_id", "")).strip(),
            security_code=str(row.get("security_code", "")).strip(),
            industry_code=str(row.get("industry_code", "")).strip(),
            effective_from=effective_from,
            effective_to=None,
            available_at=authority.available_at,
            classification_version=f"current-company-list:{authority.content_sha256}",
            authority_url=authority.url,
            evidence_id=f"authority:{authority.content_sha256}",
        )
        for row in authority.rows
    )


def route_industry_model(
    *,
    generation_id: str,
    issuer_id: str,
    security_code: str,
    market: Market,
    decision_date: str,
    classifications: Sequence[EffectiveIndustryClassification],
    sample_counts: Mapping[tuple[str, str], tuple[int, int]],
    pit_value_chain_tags: Sequence[str] = (),
    financial_subtype: Literal["bank", "life_insurer", "securities"] | None = None,
) -> IndustryModelRoute:
    """Resolve one PIT exact-industry route; never use latest or all-market fallback."""
    decision = _day(decision_date, "decision_date")
    decision_end = datetime(
        decision.year, decision.month, decision.day, 23, 59, 59, tzinfo=_TAIPEI
    )
    matching: list[EffectiveIndustryClassification] = []
    for item in classifications:
        if (
            item.market != market
            or item.issuer_id != issuer_id
            or item.security_code != security_code
        ):
            continue
        effective_from = _day(item.effective_from, "classification effective_from")
        effective_to = (
            _day(item.effective_to, "classification effective_to")
            if item.effective_to is not None
            else None
        )
        available = _aware(item.available_at, "classification available_at")
        if available > decision_end:
            continue
        if effective_from <= decision and (
            effective_to is None or decision < effective_to
        ):
            matching.append(item)

    benchmark = _BENCHMARKS[market]
    tags = sorted(set(str(item) for item in pit_value_chain_tags if str(item)))
    if not matching:
        return IndustryModelRoute(
            generation_id=generation_id,
            issuer_id=issuer_id,
            security_code=security_code,
            market=market,
            decision_date=decision_date,
            status="classification_unverified",
            reason="no_official_classification_provable_at_decision_time",
            industry_code=None,
            classification_effective_from=None,
            classification_effective_to=None,
            classification_version=None,
            classification_authority_url=None,
            classification_evidence_id=None,
            candidate_model_id=None,
            train_observations=None,
            final_oos_observations=None,
            official_benchmark_source_ref=benchmark,
            pit_value_chain_tags=tags,
            financial_subtype=None,
            stars_eligible=False,
        )
    signatures = {
        (
            item.industry_code,
            item.effective_from,
            item.effective_to,
            item.classification_version,
        )
        for item in matching
    }
    if len(signatures) != 1:
        raise IndustryModelRouteError("conflicting effective official classifications")
    item = matching[0]
    if not item.industry_code:
        raise IndustryModelRouteError("official industry code required")
    if item.industry_code == "17":
        status: RouteStatus = "financial_separate_model"
        train_count = None
        oos_count = None
        candidate = (
            f"financial-candidate:{market}:{financial_subtype}"
            if financial_subtype is not None
            else f"financial-candidate:{market}:17"
        )
        reason = "financial_model_required"
    else:
        if financial_subtype is not None:
            raise IndustryModelRouteError(
                "financial subtype is only valid for official industry 17"
            )
        train_count, oos_count = sample_counts.get(
            (market, item.industry_code), (0, 0)
        )
        if train_count < 0 or oos_count < 0:
            raise IndustryModelRouteError("sample counts cannot be negative")
        candidate = f"industry-candidate:{market}:{item.industry_code}"
        if train_count >= 500 and oos_count >= 100:
            status = "eligible"
            reason = None
        else:
            status = "industry_sample_insufficient"
            reason = "requires_500_train_and_100_final_oos"
    return IndustryModelRoute(
        generation_id=generation_id,
        issuer_id=issuer_id,
        security_code=security_code,
        market=market,
        decision_date=decision_date,
        status=status,
        reason=reason,
        industry_code=item.industry_code,
        classification_effective_from=item.effective_from,
        classification_effective_to=item.effective_to,
        classification_version=item.classification_version,
        classification_authority_url=item.authority_url,
        classification_evidence_id=item.evidence_id,
        candidate_model_id=candidate,
        train_observations=train_count,
        final_oos_observations=oos_count,
        official_benchmark_source_ref=benchmark,
        pit_value_chain_tags=tags,
        financial_subtype=financial_subtype if item.industry_code == "17" else None,
        stars_eligible=status == "eligible",
    )


__all__ = [
    "EffectiveIndustryClassification",
    "IndustryModelRoute",
    "IndustryModelRouteError",
    "records_from_current_authority",
    "route_industry_model",
]
