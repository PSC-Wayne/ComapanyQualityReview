from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Literal

import jsonschema
import pytest

from company_quality.industry.model_route import (
    EffectiveIndustryClassification,
    records_from_current_authority,
    route_industry_model,
)
from company_quality.industry.routing import IndustryAuthority
from company_quality.research_snapshot import (
    CompanyResearchSnapshotError,
    DownsideCoreResult,
    QualityCoreResult,
    UpsideCoreResult,
    build_company_research_snapshot,
)


ROOT = Path(__file__).parents[3]
GENERATION = "g1"


def _record(
    *,
    market: Literal["TWSE", "TPEx"] = "TWSE",
    code: str = "2330",
    issuer: str = "22099131",
    industry: str = "24",
    effective_from: str = "2020-01-01",
    effective_to: str | None = None,
    available_at: str = "2020-01-02T00:00:00+08:00",
    version: str = "official-history-2020",
):
    return EffectiveIndustryClassification(
        market=market,
        issuer_id=issuer,
        security_code=code,
        industry_code=industry,
        effective_from=effective_from,
        effective_to=effective_to,
        available_at=available_at,
        classification_version=version,
        authority_url=(
            "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
            if market == "TWSE"
            else "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
        ),
        evidence_id=f"{market}:{code}:{version}",
    )


def _route(
    decision: str,
    records,
    counts,
    *,
    market: Literal["TWSE", "TPEx"] = "TWSE",
    code: str = "2330",
    issuer: str = "22099131",
):
    return route_industry_model(
        generation_id=GENERATION,
        issuer_id=issuer,
        security_code=code,
        market=market,
        decision_date=decision,
        classifications=records,
        sample_counts=counts,
        pit_value_chain_tags=("semiconductor-foundry",),
    )


def test_routes_by_effective_history_without_latest_backfill() -> None:
    records = (
        _record(effective_to="2022-01-01"),
        _record(
            industry="31",
            effective_from="2022-01-01",
            available_at="2022-01-03T00:00:00+08:00",
            version="official-history-2022",
        ),
    )
    old = _route("2021-06-30", records, {("TWSE", "24"): (500, 100)})
    new = _route("2022-06-30", records, {("TWSE", "31"): (500, 100)})

    assert old.industry_code == "24"
    assert old.classification_effective_from == "2020-01-01"
    assert new.industry_code == "31"
    assert new.classification_effective_from == "2022-01-01"
    assert old.candidate_model_id == "industry-candidate:TWSE:24"
    assert new.candidate_model_id == "industry-candidate:TWSE:31"
    assert old.pit_value_chain_tags == ["semiconductor-foundry"]

    current_only = _record(
        industry="31",
        effective_from="2026-07-27",
        available_at="2026-07-27T00:00:00+08:00",
        version="current-only",
    )
    blocked = _route("2021-06-30", (current_only,), {})
    assert blocked.status == "classification_unverified"
    assert blocked.industry_code is None
    assert blocked.candidate_model_id is None
    assert blocked.all_market_fallback_model_id is None
    assert blocked.stars_eligible is False


def test_exact_industry_sample_thresholds_and_market_benchmarks() -> None:
    record = _record()
    insufficient = _route(
        "2021-06-30", (record,), {("TWSE", "24"): (499, 100)}
    )
    eligible = _route(
        "2021-06-30", (record,), {("TWSE", "24"): (500, 100)}
    )
    tpex_record = _record(
        market="TPEx", code="6488", issuer="29113265", industry="24"
    )
    tpex = _route(
        "2021-06-30",
        (tpex_record,),
        {("TPEx", "24"): (500, 100)},
        market="TPEx",
        code="6488",
        issuer="29113265",
    )

    assert insufficient.status == "industry_sample_insufficient"
    assert insufficient.stars_eligible is False
    assert insufficient.all_market_fallback_model_id is None
    assert eligible.status == "eligible"
    assert eligible.stars_eligible is True
    assert eligible.candidate_model_id != tpex.candidate_model_id
    assert eligible.official_benchmark_source_ref.endswith("/MFI94U")
    assert tpex.official_benchmark_source_ref.endswith("/tpex_reward_index")

    financial = _route(
        "2021-06-30",
        (_record(industry="17"),),
        {("TWSE", "17"): (9999, 9999)},
    )
    assert financial.status == "financial_separate_model"
    assert financial.candidate_model_id == "financial-candidate:TWSE:17"
    assert financial.stars_eligible is False


def test_current_authority_becomes_effective_only_when_officially_available() -> None:
    authority = IndustryAuthority(
        market="TWSE",
        url="https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        content_sha256="a" * 64,
        available_at="2026-07-27T00:00:00+08:00",
        retrieved_at="2026-07-27T12:00:00+08:00",
        rows=({
            "security_code": "2330",
            "issuer_id": "22099131",
            "industry_code": "24",
        },),
    )
    records = records_from_current_authority(authority)

    before = _route("2024-06-30", records, {})
    current = _route(
        "2026-07-27", records, {("TWSE", "24"): (500, 100)}
    )
    assert before.status == "classification_unverified"
    assert current.status == "eligible"
    assert records[0].effective_from == "2026-07-27"


def _snapshot(
    route,
    *,
    upside_status: Literal["industry_sample_insufficient", "research_only"] = (
        "industry_sample_insufficient"
    ),
):
    return build_company_research_snapshot(
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        generated_at="2022-07-01T12:00:00+08:00",
        input_source_versions={"industry_route": route.schema_version},
        quality=QualityCoreResult(
            GENERATION, "research_only", None, None, "quality.v1", "2022-06-30"
        ),
        upside=UpsideCoreResult(
            GENERATION,
            upside_status,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "upside.v1",
            "2022-06-30",
        ),
        downside=DownsideCoreResult(
            GENERATION, "research_only", None, None, None, "downside.v1", "2022-06-30"
        ),
        industry_route=route,
    )


def test_snapshot_records_route_and_suppresses_sample_insufficient_stars() -> None:
    route = _route(
        "2022-06-30",
        (_record(),),
        {("TWSE", "24"): (499, 100)},
    )
    snapshot = _snapshot(route)
    schema = json.loads(
        (ROOT / "src/company_quality/research_snapshot/contracts/CompanyResearchSnapshot.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(asdict(snapshot))

    assert snapshot.status == "industry_sample_insufficient"
    assert snapshot.upside.stars is None
    assert snapshot.industry_route == route
    with pytest.raises(CompanyResearchSnapshotError, match="sample-insufficient"):
        _snapshot(route, upside_status="research_only")
