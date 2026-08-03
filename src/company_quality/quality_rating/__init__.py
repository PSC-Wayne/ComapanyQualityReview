"""Formal descriptive company-quality rating from official financial evidence.

The model compares disclosed financial metrics within a same-date market/industry
cohort.  It does not predict price returns or adverse events.  Detailed checklist
gaps remain visible but do not enter the score denominator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Sequence, cast

from company_quality.company_analysis.rating_evidence_policy import RatingEvidenceDecision

QualityPillar = Literal[
    "earnings_quality",
    "financial_reliability",
    "cash_balance",
    "capital_efficiency",
    "industry_financial",
]
MetricDirection = Literal["high_good", "low_good"]
Market = Literal["TWSE", "TPEx"]
QualityStatus = Literal["formal", "research_only"]
DriverDirection = Literal["positive", "negative", "context"]

PILLARS: tuple[QualityPillar, ...] = (
    "earnings_quality",
    "financial_reliability",
    "cash_balance",
    "capital_efficiency",
    "industry_financial",
)
_Q = Decimal("0.000001")


class QualityRatingError(RuntimeError):
    """Raised when official quality inputs violate the closed rating contract."""


@dataclass(frozen=True, slots=True)
class OfficialQualityMetric:
    issuer_id: str
    security_code: str
    market: Market
    industry_code: str
    decision_date: str
    generation_id: str
    pillar: QualityPillar
    metric_id: str
    value: Decimal | None
    direction: MetricDirection
    evidence_ids: tuple[str, ...]
    available_at: str


@dataclass(frozen=True, slots=True)
class KamFocus:
    topic: str
    evidence_ids: tuple[str, ...]
    linked_metric_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityPillarResult:
    score: Decimal
    metric_scores: dict[str, Decimal]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityDriver:
    pillar: QualityPillar | None
    direction: DriverDirection
    summary: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompanyQualityRating:
    issuer_id: str
    security_code: str
    market: Market
    generation_id: str
    decision_date: str
    data_as_of: str
    status: QualityStatus
    score: Decimal | None
    base_score: Decimal | None
    extra_points: Decimal
    confidence: Decimal
    pillars: dict[QualityPillar, QualityPillarResult]
    missing_primary_pillars: tuple[QualityPillar, ...]
    drivers: tuple[QualityDriver, ...]
    kam_focuses: tuple[KamFocus, ...]
    official_source_ids: tuple[str, ...]
    extra_source_ids: tuple[str, ...]
    checklist_unresolved_ids: tuple[str, ...]
    cohort_issuer_count: int
    cohort_scope: str
    source_policy_version: str
    model_scope: Literal["descriptive_official_financial_quality"] = (
        "descriptive_official_financial_quality"
    )
    predicts_price_or_adverse_event: Literal[False] = False
    rating_disposition: Literal["FORMAL", "RESEARCH_ONLY"] = "RESEARCH_ONLY"
    schema_version: Literal["CompanyQualityRating.v1"] = "CompanyQualityRating.v1"
    model_version: Literal["official-peer-percentile-equal-pillar.v1"] = (
        "official-peer-percentile-equal-pillar.v1"
    )


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise QualityRatingError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise QualityRatingError(f"{field} must be timezone-aware")
    return result


def _percentile(value: Decimal, cohort: Sequence[Decimal], direction: MetricDirection) -> Decimal:
    ordered = sorted(cohort)
    if len(ordered) < 5:
        raise QualityRatingError("metric cohort requires at least five issuers")
    below = sum(item < value for item in ordered)
    equal = sum(item == value for item in ordered)
    rank = (Decimal(below) + Decimal(equal - 1) / Decimal(2)) / Decimal(len(ordered) - 1)
    score = rank * Decimal("100")
    if direction == "low_good":
        score = Decimal("100") - score
    return score.quantize(_Q, rounding=ROUND_HALF_UP)


def _drivers(
    pillars: dict[QualityPillar, QualityPillarResult],
    kam_focuses: tuple[KamFocus, ...],
) -> tuple[QualityDriver, ...]:
    ordered = sorted(pillars.items(), key=lambda item: (item[1].score, item[0]))
    result: list[QualityDriver] = []
    negative = ordered[: min(2, len(ordered))]
    positive = ordered[max(0, len(ordered) - 2) :]
    for pillar, item in negative:
        result.append(QualityDriver(
            pillar=pillar,
            direction="negative",
            summary=f"{pillar}為五柱中相對較弱項（{item.score}）。",
            evidence_ids=item.evidence_ids,
        ))
    for pillar, item in positive:
        if any(driver.pillar == pillar for driver in result):
            continue
        result.append(QualityDriver(
            pillar=pillar,
            direction="positive",
            summary=f"{pillar}為五柱中相對較強項（{item.score}）。",
            evidence_ids=item.evidence_ids,
        ))
    result.extend(
        QualityDriver(
            pillar=None,
            direction="context",
            summary=f"KAM重大判斷焦點：{focus.topic}；僅作正式揭露脈絡，不因KAM存在而扣分。",
            evidence_ids=focus.evidence_ids,
        )
        for focus in kam_focuses
    )
    return tuple(result)


def build_company_quality_rating(
    *,
    issuer_id: str,
    security_code: str,
    market: Market,
    generation_id: str,
    rating_as_of: str,
    observations: Sequence[OfficialQualityMetric],
    rating_evidence: RatingEvidenceDecision,
    kam_focuses: tuple[KamFocus, ...] = (),
) -> CompanyQualityRating:
    """Build an equal-pillar 0..100 descriptive rating from official inputs."""

    as_of = _instant(rating_as_of, "rating_as_of")
    if rating_evidence.dimension != "quality":
        raise QualityRatingError("quality evidence decision required")
    if rating_evidence.issuer_id != issuer_id:
        raise QualityRatingError("rating evidence issuer mismatch")
    if _instant(rating_evidence.as_of, "rating evidence as_of") > as_of:
        raise QualityRatingError("rating evidence is later than rating_as_of")
    if not observations:
        raise QualityRatingError("quality observations are required")

    target = [
        item
        for item in observations
        if item.issuer_id == issuer_id
        and item.security_code == security_code
        and item.market == market
        and item.generation_id == generation_id
    ]
    if not target:
        raise QualityRatingError("target issuer observations are required")
    decision_dates = {item.decision_date for item in target}
    industry_codes = {item.industry_code for item in target}
    if len(decision_dates) != 1 or len(industry_codes) != 1:
        raise QualityRatingError("target requires one decision date and industry")
    decision_date = next(iter(decision_dates))
    industry_code = next(iter(industry_codes))
    if len({item.metric_id for item in target}) != len(target):
        raise QualityRatingError("duplicate target quality metric")

    eligible_cohort = [
        item
        for item in observations
        if item.market == market
        and item.industry_code == industry_code
        and item.decision_date == decision_date
        and item.generation_id == generation_id
    ]
    if len({item.issuer_id for item in eligible_cohort}) < 5:
        raise QualityRatingError("same-date market/industry cohort requires five issuers")
    for item in eligible_cohort:
        available = _instant(item.available_at, "metric available_at")
        if available > as_of:
            raise QualityRatingError("quality metric is not PIT-admissible")
        if item.value is not None and not item.evidence_ids:
            raise QualityRatingError("present quality metric requires evidence")
        if not item.metric_id or item.pillar not in PILLARS:
            raise QualityRatingError("invalid quality metric identity")

    admitted_core = set(rating_evidence.core_evidence_ids)
    target_metric_ids = {item.metric_id for item in target}
    for item in target:
        if item.value is not None and not set(item.evidence_ids).issubset(admitted_core):
            raise QualityRatingError("target metric is not bound to official policy evidence")
    for focus in kam_focuses:
        if not focus.topic or not focus.evidence_ids:
            raise QualityRatingError("KAM focus requires topic and evidence")
        if not set(focus.evidence_ids).issubset(admitted_core):
            raise QualityRatingError("KAM focus is not bound to official policy evidence")
        if not set(focus.linked_metric_ids).issubset(target_metric_ids):
            raise QualityRatingError("KAM focus must link target financial metrics")

    pillar_metrics: dict[QualityPillar, dict[str, Decimal]] = {pillar: {} for pillar in PILLARS}
    pillar_evidence: dict[QualityPillar, list[str]] = {pillar: [] for pillar in PILLARS}
    for item in target:
        if item.value is None:
            continue
        matches = [
            peer
            for peer in eligible_cohort
            if peer.metric_id == item.metric_id and peer.value is not None
        ]
        pillars = {peer.pillar for peer in matches}
        directions = {peer.direction for peer in matches}
        if pillars != {item.pillar} or directions != {item.direction}:
            raise QualityRatingError("cohort metric pillar/direction conflict")
        issuer_values = {peer.issuer_id: cast(Decimal, peer.value) for peer in matches}
        if len(issuer_values) < 5:
            continue
        metric_score = _percentile(item.value, tuple(issuer_values.values()), item.direction)
        pillar_metrics[item.pillar][item.metric_id] = metric_score
        for evidence_id in item.evidence_ids:
            if evidence_id not in pillar_evidence[item.pillar]:
                pillar_evidence[item.pillar].append(evidence_id)

    pillar_results: dict[QualityPillar, QualityPillarResult] = {}
    for pillar in PILLARS:
        values = pillar_metrics[pillar]
        if not values:
            continue
        score = (sum(values.values()) / Decimal(len(values))).quantize(
            _Q, rounding=ROUND_HALF_UP
        )
        pillar_results[pillar] = QualityPillarResult(
            score=score,
            metric_scores=dict(sorted(values.items())),
            evidence_ids=tuple(pillar_evidence[pillar]),
        )

    missing: tuple[QualityPillar, ...] = tuple(
        cast(QualityPillar, pillar) for pillar in PILLARS if pillar not in pillar_results
    )
    confidence = (Decimal(len(pillar_results)) / Decimal(len(PILLARS))).quantize(
        _Q, rounding=ROUND_HALF_UP
    )
    formal = not missing and rating_evidence.core_rating_eligible
    if formal:
        base_score = (sum(item.score for item in pillar_results.values()) / Decimal(len(PILLARS))).quantize(
            _Q, rounding=ROUND_HALF_UP
        )
        extra = rating_evidence.extra_points.quantize(_Q, rounding=ROUND_HALF_UP)
        score = min(Decimal("100"), base_score + extra).quantize(
            _Q, rounding=ROUND_HALF_UP
        )
    else:
        base_score = None
        score = None
        extra = rating_evidence.extra_points.quantize(_Q, rounding=ROUND_HALF_UP)

    data_as_of = max(_instant(item.available_at, "metric available_at") for item in target)
    return CompanyQualityRating(
        issuer_id=issuer_id,
        security_code=security_code,
        market=market,
        generation_id=generation_id,
        decision_date=decision_date,
        data_as_of=data_as_of.isoformat(),
        status="formal" if formal else "research_only",
        score=score,
        base_score=base_score,
        extra_points=extra,
        confidence=confidence,
        pillars=pillar_results,
        missing_primary_pillars=missing,
        drivers=_drivers(pillar_results, kam_focuses),
        kam_focuses=kam_focuses,
        official_source_ids=rating_evidence.core_evidence_ids,
        extra_source_ids=rating_evidence.supplemental_evidence_ids,
        checklist_unresolved_ids=rating_evidence.checklist_unresolved_ids,
        cohort_issuer_count=len({item.issuer_id for item in eligible_cohort}),
        cohort_scope=f"{market}:{industry_code}:{decision_date}",
        source_policy_version=rating_evidence.policy_version,
        rating_disposition="FORMAL" if formal else "RESEARCH_ONLY",
    )


__all__ = [
    "CompanyQualityRating",
    "KamFocus",
    "OfficialQualityMetric",
    "PILLARS",
    "QualityDriver",
    "QualityPillarResult",
    "QualityRatingError",
    "build_company_quality_rating",
]
