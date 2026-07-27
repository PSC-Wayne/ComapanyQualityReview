from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from company_quality.industry.model_route import (
    EffectiveIndustryClassification,
    route_industry_model,
)
from company_quality.lab.research_runtime import (
    AnnualModelBundle,
    AnnualModelRegistry,
    RefreshData,
    RefreshPredictions,
    consume_successful_generation,
    run_research_refresh,
)


def _registry() -> AnnualModelRegistry:
    registry = AnnualModelRegistry()
    registry.register(AnnualModelBundle(
        model_year=2026,
        trained_through="2025-12-30",
        quality_model_version="quality-2026.v1",
        upside_model_version="upside-2026.v1",
        downside_model_version="downside-2026.v1",
    ))
    return registry


def _route(generation="g1"):
    record = EffectiveIndustryClassification(
        market="TWSE",
        issuer_id="issuer-2330",
        security_code="2330",
        industry_code="24",
        effective_from="2020-01-01",
        effective_to=None,
        available_at="2020-01-02T00:00:00+08:00",
        classification_version="official-history-v1",
        authority_url="https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        evidence_id="industry:2330:v1",
    )
    return route_industry_model(
        generation_id=generation,
        issuer_id="issuer-2330",
        security_code="2330",
        market="TWSE",
        decision_date="2026-07-27",
        classifications=(record,),
        sample_counts={("TWSE", "24"): (500, 100)},
    )


def _data(generation="g1") -> RefreshData:
    return RefreshData(
        generation_id=generation,
        issuer_id="issuer-2330",
        security_code="2330",
        market="TWSE",
        generated_at="2026-07-27T12:00:00+08:00",
        latest_financial_available_at="2026-06-15T18:00:00+08:00",
        financial_statement_quarters=8,
        price_date="2026-07-24",
        price_history_months=24,
        current_price=100.0,
        input_source_versions={"financials": "mops-pit.v1", "prices": "finlab.v1"},
    )


def _predictions() -> RefreshPredictions:
    return RefreshPredictions(
        quality_score=70.0,
        quality_confidence=0.8,
        positive_return_probability=0.7,
        official_outperform_probability=0.65,
        p10_return=-0.1,
        p50_return=0.2,
        p90_return=0.4,
        upside_confidence=0.75,
        downside_risk_score=30.0,
        downside_confidence=0.7,
    )


def test_annual_bundle_is_fixed_while_intra_year_data_refreshes(tmp_path: Path) -> None:
    registry = _registry()
    first = run_research_refresh(
        registry=registry,
        data=_data("g1"),
        predictions=_predictions(),
        industry_route=_route("g1"),
        output_root=tmp_path,
    )
    second = run_research_refresh(
        registry=registry,
        data=replace(_data("g2"), current_price=110.0),
        predictions=replace(_predictions(), p50_return=0.25),
        industry_route=_route("g2"),
        output_root=tmp_path,
    )

    assert first.consumer_verified is True
    assert first.snapshot.generation_id == "g1"
    assert first.snapshot.status == "research_only"
    assert first.snapshot.upside.stars is None
    assert (first.snapshot.upside.p10_price, first.snapshot.upside.p50_price, first.snapshot.upside.p90_price) == pytest.approx((90, 120, 140))
    assert second.snapshot.upside.p50_price == pytest.approx(137.5)
    assert first.snapshot.upside.model_version == second.snapshot.upside.model_version == "upside-2026.v1"
    consumed = consume_successful_generation(tmp_path, "g2")
    assert consumed.generation_id == "g2"
    assert consumed.snapshot_payload["generation_id"] == consumed.runtime_metadata["generation_id"]
    assert consumed.runtime_metadata["trained_through"] == "2025-12-30"
    assert consumed.runtime_metadata["price_date"] == "2026-07-24"
    assert consumed.runtime_metadata["formal_stars_authorized"] is False
    assert consumed.runtime_metadata["legacy_fallback"] is None

    with pytest.raises(ValueError, match="intra-year retraining forbidden"):
        registry.register(replace(
            registry.for_year(2026), upside_model_version="upside-2026.v2"
        ))


@pytest.mark.parametrize(
    "changed",
    [
        {"financial_statement_quarters": 7},
        {"price_history_months": 23},
        {"price_date": "2026-07-01"},
        {"latest_financial_available_at": "2025-12-01T12:00:00+08:00"},
        {"current_price": None},
    ],
)
def test_missing_or_stale_required_data_suppresses_current_outputs(
    tmp_path: Path, changed: dict[str, object]
) -> None:
    data = replace(_data(), **changed)
    result = run_research_refresh(
        registry=_registry(),
        data=data,
        predictions=None,
        industry_route=_route(),
        output_root=tmp_path,
    )

    assert result.data_state == "data_insufficient"
    assert result.snapshot.status == "data_insufficient"
    assert result.snapshot.upside.stars is None
    assert result.snapshot.upside.p10_price is None
    assert result.snapshot.upside.p50_price is None
    assert result.snapshot.upside.p90_price is None
    assert result.consumer_verified is True


def test_previous_generation_is_only_exposed_as_stale_reference(tmp_path: Path) -> None:
    registry = _registry()
    previous = run_research_refresh(
        registry=registry,
        data=replace(
            _data("old-generation"), generated_at="2026-07-27T10:00:00+08:00"
        ),
        predictions=_predictions(),
        industry_route=_route("old-generation"),
        output_root=tmp_path,
    ).snapshot
    current = run_research_refresh(
        registry=registry,
        data=replace(_data("new-generation"), financial_statement_quarters=7),
        predictions=None,
        industry_route=_route("new-generation"),
        output_root=tmp_path,
        previous_snapshot=previous,
    )

    assert current.snapshot.generation_id == "new-generation"
    assert current.snapshot.status == "data_insufficient"
    assert current.stale_reference is not None
    assert current.stale_reference.generation_id == "old-generation"
    assert current.stale_reference.status == "stale_reference"
    assert current.stale_reference.quality.status == "stale_reference"
    assert current.stale_reference.upside.status == "stale_reference"
    assert current.stale_reference.upside.stars is None
    assert current.stale_reference.upside.p50_price is None


def test_consumer_requires_exact_complete_success_generation_and_never_falls_back(
    tmp_path: Path,
) -> None:
    (tmp_path / "legacy_snapshot.json").write_text('{"generation_id":"legacy"}')
    with pytest.raises(ValueError, match="no fallback allowed"):
        consume_successful_generation(tmp_path, "missing-generation")

    result = run_research_refresh(
        registry=_registry(), data=_data(), predictions=_predictions(),
        industry_route=_route(), output_root=tmp_path,
    )
    metadata = Path(result.runtime_metadata_path)
    metadata.write_text(metadata.read_text().replace('"g1"', '"other"'))
    with pytest.raises(ValueError, match="generation mismatch"):
        consume_successful_generation(tmp_path, "g1")
