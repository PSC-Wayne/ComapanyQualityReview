"""Closed same-generation contract for the three independent research outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Mapping, cast

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
    twelve_month_return: TwelveMonthReturnLabel | None
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["CompanyResearchSnapshot.v1"] = (
        "CompanyResearchSnapshot.v1"
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
    if twelve_month_return is not None and (
        twelve_month_return.generation_id != generation_id
        or twelve_month_return.market != market
    ):
        raise CompanyResearchSnapshotError(
            "12-month return label must bind the same generation and market"
        )
    if not issuer_id:
        raise CompanyResearchSnapshotError("issuer_id required")
    _instant(generated_at, "generated_at")
    for name, result in (
        ("quality", quality),
        ("upside", upside),
        ("downside", downside),
    ):
        if not result.model_version:
            raise CompanyResearchSnapshotError(f"{name} model_version required")
        _day(result.data_as_of, f"{name} data_as_of")
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
    return CompanyResearchSnapshot(
        issuer_id=issuer_id,
        security_code=security_code,
        market=market,
        generation_id=generation_id,
        generated_at=generated_at,
        status=status,
        ai_status="AI_unavailable",
        input_source_versions=dict(sorted(input_source_versions.items())),
        quality=quality,
        upside=upside,
        downside=downside,
        twelve_month_return=twelve_month_return,
    )


__all__ = [
    "CompanyResearchSnapshot",
    "CompanyResearchSnapshotError",
    "DownsideCoreResult",
    "QualityCoreResult",
    "UpsideCoreResult",
    "build_company_research_snapshot",
]
