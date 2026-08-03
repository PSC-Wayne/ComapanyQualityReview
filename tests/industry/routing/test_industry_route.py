import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from company_quality.identity import CompanyIdentity, IdentityResolution
from company_quality.industry.routing import (
    IndustryAuthority,
    IndustryRouteError,
    fetch_industry_authority,
    route_industry,
)


def identity(code="2330", issuer="22099131", market="TWSE"):
    return IdentityResolution(
        identifier=code,
        requested_market=market,
        decision_time="2026-07-24T12:00:00+08:00",
        status="resolved",
        identity=CompanyIdentity(
            security_id=f"{market}:{code}", security_code=code,
            issuer_id=issuer, company_name="台灣積體電路製造股份有限公司",
            short_name="台積電", market=market,
            valid_from="1994-09-05T00:00:00+08:00",
        ),
        evidence_urls=("https://official.example/identity",),
    )


def authority(code="2330", industry="24", issuer="22099131", market="TWSE"):
    raw = json.dumps({"code": code, "industry": industry}, sort_keys=True).encode()
    return IndustryAuthority(
        market=market,
        url="https://official.example/company-list",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        available_at="2026-07-24T00:00:00+08:00",
        retrieved_at="2026-07-24T11:00:00+08:00",
        rows=({
            "security_code": code, "issuer_id": issuer,
            "company_name": "台灣積體電路製造股份有限公司",
            "short_name": "台積電", "industry_code": industry,
        },),
    )


def test_routes_general_company_by_exact_official_industry() -> None:
    result = route_industry(identity(), authority())
    assert result.status == "routed"
    assert result.issuer_id == "22099131"
    assert result.sector_code == "electronics"
    assert result.industry_code == "24"
    assert result.business_model_tags == ("general_operating_company", "sector:electronics")
    assert result.cyclicality == "moderate"
    assert result.peer_rule_id == "same-market-exact-official-industry.v1"
    assert result.route_coverage == 1
    assert result.reason is None


@pytest.mark.parametrize("industry", ["14", "15", "17"])
def test_owner_excluded_industries_are_unsupported(industry) -> None:
    result = route_industry(identity(), authority(industry=industry))
    assert result.status == "unsupported_scope"
    assert result.reason == "owner_excluded_v1_industry"
    assert result.peer_rule_id == "unsupported-scope.v1"
    assert result.route_coverage == 1


def test_remaining_industries_receive_explicit_cyclicality() -> None:
    assert route_industry(identity(), authority(industry="10")).cyclicality == "deep_cyclical"
    assert route_industry(identity(), authority(industry="16")).cyclicality == "cyclical"
    assert route_industry(identity(), authority(industry="02")).cyclicality == "defensive"
    assert route_industry(identity(), authority(industry="34")).cyclicality == "moderate"


def test_authority_after_decision_time_blocks_route_not_identity() -> None:
    result = route_industry(
        identity(), replace(authority(), available_at="2026-07-25T00:00:00+08:00")
    )
    assert result.status == "blocked"
    assert result.reason == "industry_authority_not_available_at_decision_time"
    assert result.issuer_id == "22099131"
    assert result.route_coverage == 0


def test_market_identity_or_same_rank_conflict_blocks() -> None:
    with pytest.raises(IndustryRouteError, match="market"):
        route_industry(identity(), authority(market="TPEx"))
    conflict = replace(authority(), rows=(
        authority().rows[0],
        {**authority().rows[0], "industry_code": "25"},
    ))
    result = route_industry(identity(), conflict)
    assert result.status == "blocked"
    assert result.reason == "conflicting_official_industry_routes"


def test_unresolved_identity_cannot_be_routed() -> None:
    unresolved = replace(identity(), status="not_found", identity=None)
    with pytest.raises(IndustryRouteError, match="resolved identity"):
        route_industry(unresolved, authority())


def test_unknown_industry_code_blocks_instead_of_general_fallback() -> None:
    result = route_industry(identity(), authority(industry="99"))
    assert result.status == "blocked"
    assert result.reason == "unsupported_official_industry_code"
    assert result.sector_code == "unknown"


def test_json_schema_is_closed_and_valid() -> None:
    path = Path(__file__).parents[3] / "src/company_quality/industry/routing/contracts/IndustryRoute.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "IndustryRoute.v1"
    assert schema["additionalProperties"] is False


@pytest.mark.authority_probe
def test_live_official_industry_authority_probe() -> None:
    source = fetch_industry_authority("TWSE")
    row = next(item for item in source.rows if item["security_code"] == "2330")
    assert row["industry_code"] == "24"
    assert row["issuer_id"] == "22099131"
    assert len(source.content_sha256) == 64
