"""Annual-model research runtime with same-generation snapshot consumption."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from typing import Literal, Mapping, Sequence

import jsonschema

from company_quality.industry.model_route import IndustryModelRoute
from company_quality.research_snapshot import (
    CompanyResearchSnapshot,
    DownsideCoreResult,
    OfficialMaterialEvent,
    QualityCoreResult,
    UpsideCoreResult,
    build_company_research_snapshot,
)


_SNAPSHOT_SCHEMA = (
    Path(__file__).parents[1]
    / "research_snapshot/contracts/CompanyResearchSnapshot.schema.json"
)


@dataclass(frozen=True, slots=True)
class AnnualModelBundle:
    model_year: int
    trained_through: str
    quality_model_version: str
    upside_model_version: str
    downside_model_version: str


class AnnualModelRegistry:
    def __init__(self) -> None:
        self._models: dict[int, AnnualModelBundle] = {}

    def register(self, bundle: AnnualModelBundle) -> None:
        cutoff = date.fromisoformat(bundle.trained_through)
        if cutoff >= date(bundle.model_year, 1, 1):
            raise ValueError("annual model training cutoff must precede its model year")
        if not all((
            bundle.quality_model_version,
            bundle.upside_model_version,
            bundle.downside_model_version,
        )):
            raise ValueError("all annual model versions required")
        existing = self._models.get(bundle.model_year)
        if existing is not None and existing != bundle:
            raise ValueError("annual model is already frozen; intra-year retraining forbidden")
        self._models[bundle.model_year] = bundle

    def for_year(self, model_year: int) -> AnnualModelBundle:
        try:
            return self._models[model_year]
        except KeyError as exc:
            raise ValueError("annual model bundle is not registered") from exc


@dataclass(frozen=True, slots=True)
class RefreshData:
    generation_id: str
    issuer_id: str
    security_code: str
    market: Literal["TWSE", "TPEx"]
    generated_at: str
    latest_financial_available_at: str | None
    financial_statement_quarters: int
    price_date: str | None
    price_history_months: int
    current_price: float | None
    input_source_versions: dict[str, str]


@dataclass(frozen=True, slots=True)
class RefreshPredictions:
    quality_score: float
    quality_confidence: float
    positive_return_probability: float
    official_outperform_probability: float
    p10_return: float
    p50_return: float
    p90_return: float
    upside_confidence: float
    downside_risk_score: float
    downside_confidence: float


@dataclass(frozen=True, slots=True)
class RuntimeRefreshResult:
    generation_id: str
    data_state: str
    snapshot: CompanyResearchSnapshot
    stale_reference: CompanyResearchSnapshot | None
    snapshot_path: str
    runtime_metadata_path: str
    consumer_verified: bool
    schema_version: str = "ResearchRuntimeRefresh.v1"


@dataclass(frozen=True, slots=True)
class ConsumedResearchSnapshot:
    generation_id: str
    snapshot_payload: dict[str, object]
    runtime_metadata: dict[str, object]


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return result


def _stale_reference(snapshot: CompanyResearchSnapshot) -> CompanyResearchSnapshot:
    return replace(
        snapshot,
        status="stale_reference",
        quality=replace(snapshot.quality, status="stale_reference"),
        upside=replace(
            snapshot.upside,
            status="stale_reference",
            stars=None,
            p10_price=None,
            p50_price=None,
            p90_price=None,
        ),
        downside=replace(snapshot.downside, status="stale_reference", faces=None),
    )


def _price_ranges(
    current_price: float,
    returns: tuple[float, float, float],
) -> tuple[float | None, float | None, float | None]:
    p10, p50, p90 = returns
    values = (
        current_price * (1.0 + p10),
        current_price * (1.0 + p50),
        current_price * (1.0 + p90),
    )
    if any(value <= 0 for value in values):
        return None, None, None
    return values


def _data_state(
    data: RefreshData,
    generated: datetime,
    industry_route: IndustryModelRoute | None,
) -> str:
    if industry_route is None or industry_route.status == "classification_unverified":
        return "data_insufficient"
    if industry_route.status == "industry_sample_insufficient":
        return "industry_sample_insufficient"
    if data.financial_statement_quarters < 8 or data.price_history_months < 24:
        return "data_insufficient"
    if (
        data.latest_financial_available_at is None
        or data.price_date is None
        or data.current_price is None
        or data.current_price <= 0
    ):
        return "data_insufficient"
    financial_available = _instant(
        data.latest_financial_available_at, "latest_financial_available_at"
    )
    price_day = date.fromisoformat(data.price_date)
    if financial_available > generated or price_day > generated.date():
        raise ValueError("runtime source date cannot follow generation")
    if generated - financial_available > timedelta(days=180):
        return "data_insufficient"
    if generated.date() - price_day > timedelta(days=7):
        return "data_insufficient"
    return "research_only"


def run_research_refresh(
    *,
    registry: AnnualModelRegistry,
    data: RefreshData,
    predictions: RefreshPredictions | None,
    industry_route: IndustryModelRoute | None,
    output_root: Path,
    previous_snapshot: CompanyResearchSnapshot | None = None,
    official_events: Sequence[OfficialMaterialEvent] = (),
) -> RuntimeRefreshResult:
    generated = _instant(data.generated_at, "generated_at")
    bundle = registry.for_year(generated.year)
    state = _data_state(data, generated, industry_route)
    if industry_route is not None and (
        industry_route.generation_id != data.generation_id
        or industry_route.issuer_id != data.issuer_id
        or industry_route.security_code != data.security_code
        or industry_route.market != data.market
    ):
        raise ValueError("industry route must bind runtime generation and identity")
    if state == "research_only" and predictions is None:
        raise ValueError("fresh runtime data requires model predictions")

    data_as_of = generated.date().isoformat()
    if state == "research_only":
        assert predictions is not None
        assert data.current_price is not None
        quality = QualityCoreResult(
            data.generation_id, "research_only", predictions.quality_score,
            predictions.quality_confidence, bundle.quality_model_version, data_as_of,
        )
        prices = _price_ranges(
            float(data.current_price),
            (predictions.p10_return, predictions.p50_return, predictions.p90_return),
        )
        upside = UpsideCoreResult(
            data.generation_id, "research_only",
            predictions.positive_return_probability,
            predictions.official_outperform_probability,
            None,
            predictions.p10_return, predictions.p50_return, predictions.p90_return,
            *prices,
            None,
            predictions.upside_confidence,
            bundle.upside_model_version,
            data_as_of,
        )
        downside = DownsideCoreResult(
            data.generation_id, "research_only", predictions.downside_risk_score,
            None, predictions.downside_confidence, bundle.downside_model_version,
            data_as_of,
        )
    else:
        core_status = (
            "industry_sample_insufficient"
            if state == "industry_sample_insufficient"
            else "data_insufficient"
        )
        quality = QualityCoreResult(
            data.generation_id, core_status, None, None,
            bundle.quality_model_version, data_as_of,
        )
        upside = UpsideCoreResult(
            data.generation_id, core_status,
            None, None, None, None, None, None, None, None, None, None, None,
            bundle.upside_model_version, data_as_of,
        )
        downside = DownsideCoreResult(
            data.generation_id, core_status, None, None, None,
            bundle.downside_model_version, data_as_of,
        )

    source_versions = {
        **data.input_source_versions,
        "annual_quality_model": bundle.quality_model_version,
        "annual_upside_model": bundle.upside_model_version,
        "annual_downside_model": bundle.downside_model_version,
    }
    snapshot = build_company_research_snapshot(
        issuer_id=data.issuer_id,
        security_code=data.security_code,
        market=data.market,
        generated_at=data.generated_at,
        input_source_versions=source_versions,
        quality=quality,
        upside=upside,
        downside=downside,
        industry_route=industry_route,
        official_events=official_events,
    )
    if previous_snapshot is not None:
        if (
            previous_snapshot.issuer_id != data.issuer_id
            or previous_snapshot.security_code != data.security_code
            or previous_snapshot.market != data.market
            or previous_snapshot.generation_id == data.generation_id
            or _instant(previous_snapshot.generated_at, "previous generated_at") >= generated
        ):
            raise ValueError("stale reference must be an older generation of the same issuer")
        stale = _stale_reference(previous_snapshot)
    else:
        stale = None
    generation_dir = output_root / data.generation_id
    generation_dir.mkdir(parents=True, exist_ok=False)
    snapshot_path = generation_dir / "company_research_snapshot.json"
    metadata_path = generation_dir / "runtime_metadata.json"
    snapshot_payload = asdict(snapshot)
    schema = json.loads(_SNAPSHOT_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(snapshot_payload)
    snapshot_path.write_text(
        json.dumps(snapshot_payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "schema_version": "ResearchRuntimeMetadata.v1",
        "generation_id": data.generation_id,
        "model_year": bundle.model_year,
        "trained_through": bundle.trained_through,
        "quality_model_version": bundle.quality_model_version,
        "upside_model_version": bundle.upside_model_version,
        "downside_model_version": bundle.downside_model_version,
        "data_cutoff_time": data.latest_financial_available_at,
        "generated_at": data.generated_at,
        "price_date": data.price_date,
        "financial_statement_quarters": data.financial_statement_quarters,
        "price_history_months": data.price_history_months,
        "data_state": state,
        "formal_stars_authorized": False,
        "legacy_fallback": None,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    consumed = consume_successful_generation(output_root, data.generation_id)
    return RuntimeRefreshResult(
        generation_id=data.generation_id,
        data_state=state,
        snapshot=snapshot,
        stale_reference=stale,
        snapshot_path=str(snapshot_path),
        runtime_metadata_path=str(metadata_path),
        consumer_verified=consumed.generation_id == data.generation_id,
    )


def consume_successful_generation(
    output_root: Path,
    successful_generation_id: str,
) -> ConsumedResearchSnapshot:
    generation_dir = output_root / successful_generation_id
    snapshot_path = generation_dir / "company_research_snapshot.json"
    metadata_path = generation_dir / "runtime_metadata.json"
    if not snapshot_path.is_file() or not metadata_path.is_file():
        raise ValueError("successful generation artifacts are incomplete; no fallback allowed")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        snapshot.get("generation_id") != successful_generation_id
        or metadata.get("generation_id") != successful_generation_id
    ):
        raise ValueError("consumer generation mismatch")
    schema = json.loads(_SNAPSHOT_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(snapshot)
    return ConsumedResearchSnapshot(
        generation_id=successful_generation_id,
        snapshot_payload=snapshot,
        runtime_metadata=metadata,
    )


__all__ = [
    "AnnualModelBundle", "AnnualModelRegistry", "ConsumedResearchSnapshot",
    "RefreshData", "RefreshPredictions", "RuntimeRefreshResult",
    "consume_successful_generation", "run_research_refresh",
]
