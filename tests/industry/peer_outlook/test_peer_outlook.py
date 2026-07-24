import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from company_quality.industry.peer_outlook import (
    OutlookObservation,
    PeerAuthority,
    PeerOutlookError,
    build_peer_outlook_evidence,
)
from company_quality.industry.routing import IndustryRoute
from company_quality.industry.routing import fetch_industry_authority


DECISION_TIME = "2026-07-24T12:00:00+08:00"
OFFICIAL_SHA = "a" * 64
SECONDARY_SHA = "b" * 64


def route(**changes) -> IndustryRoute:
    value = IndustryRoute(
        status="routed",
        reason=None,
        issuer_id="22099131",
        sector_code="electronics",
        industry_code="24",
        business_model_tags=("general_operating_company", "sector:electronics"),
        cyclicality="moderate",
        peer_rule_id="same-market-exact-official-industry.v1",
        route_version="1.0.0",
        evidence_ids=("identity:TWSE:2330", "authority:" + OFFICIAL_SHA),
        route_coverage=Decimal("1"),
        decision_time=DECISION_TIME,
        authority_url="https://official.example/company-list",
        authority_sha256=OFFICIAL_SHA,
        available_at="2026-07-23T00:00:00+08:00",
        retrieved_at="2026-07-24T10:00:00+08:00",
    )
    return replace(value, **changes)


def peer_row(
    issuer_id: str,
    *,
    security_code: str,
    market: str = "TWSE",
    industry_code: str = "24",
    history_years: str = "5",
    business_model: str = "general_operating_company",
) -> dict[str, str]:
    return {
        "issuer_id": issuer_id,
        "security_code": security_code,
        "market": market,
        "industry_code": industry_code,
        "history_years": history_years,
        "business_model": business_model,
    }


def authority(
    *,
    source_id: str = "official-company-list",
    source_tier: str = "official",
    rows=None,
) -> PeerAuthority:
    if rows is None:
        rows = (
            peer_row("22099131", security_code="2330"),
            peer_row("peer-b", security_code="2454"),
            peer_row("peer-a", security_code="2303"),
        )
    return PeerAuthority(
        source_id=source_id,
        source_tier=source_tier,
        url=f"https://{source_tier}.example/{source_id}",
        content_sha256=OFFICIAL_SHA if source_tier == "official" else SECONDARY_SHA,
        available_at="2026-07-23T00:00:00+08:00",
        retrieved_at="2026-07-24T10:00:00+08:00",
        rows=tuple(rows),
    )


def observation(
    evidence_id: str,
    scenario: str,
    *,
    authority_id: str = "official-company-list",
    claim_key: str | None = None,
    direction: str = "positive",
    available_at: str = "2026-07-24T09:00:00+08:00",
    is_counter_evidence: bool = False,
    cycle_normalized: bool = True,
) -> OutlookObservation:
    return OutlookObservation(
        evidence_id=evidence_id,
        authority_id=authority_id,
        claim_key=claim_key or f"claim:{evidence_id}",
        statement=f"Grounded {scenario} assumption for {evidence_id}",
        driver="advanced-node demand",
        direction=direction,
        horizon_months=12,
        scenario=scenario,
        available_at=available_at,
        is_counter_evidence=is_counter_evidence,
        cycle_normalized=cycle_normalized,
    )


def outlook_observations(*, authority_id="official-company-list", normalized=True):
    return (
        observation("ev-bear", "bear", authority_id=authority_id, direction="negative", cycle_normalized=normalized),
        observation("ev-base", "base", authority_id=authority_id, cycle_normalized=normalized),
        observation("ev-bull", "bull", authority_id=authority_id, cycle_normalized=normalized),
        observation(
            "ev-counter", "base", authority_id=authority_id, direction="negative",
            is_counter_evidence=True, cycle_normalized=normalized,
        ),
    )


def build(*, industry_route=None, authorities=None, observations=None):
    return build_peer_outlook_evidence(
        industry_route or route(),
        tuple(authorities or (authority(),)),
        tuple(observations or outlook_observations()),
        generation_id="generation-20260724-001",
        producer_candidate_sha="c" * 40,
    )


def test_selects_deterministic_exact_industry_same_market_peers_and_excludes_target() -> None:
    rows = (
        peer_row("peer-z", security_code="9999"),
        peer_row("22099131", security_code="2330"),
        peer_row("peer-a", security_code="1111"),
        peer_row("other-market", security_code="2222", market="TPEx"),
        peer_row("other-industry", security_code="3333", industry_code="25"),
        peer_row("too-new", security_code="4444", history_years="1"),
        peer_row("wrong-model", security_code="5555", business_model="distributor"),
        peer_row("financial", security_code="6666", industry_code="17"),
    )
    result = build(authorities=(authority(rows=rows),))

    assert result.peer_ids == ("peer-a", "peer-z")
    assert "22099131" not in result.peer_ids
    assert tuple(item.peer_id for item in result.inclusion_reasons) == result.peer_ids
    assert {item.reason_code for item in result.inclusion_reasons} == {"industry_match"}
    assert {(item.issuer_id, item.reason_code) for item in result.exclusion_reasons} == {
        ("other-market", "wrong_market"),
        ("other-industry", "business_model_mismatch"),
        ("too-new", "insufficient_history"),
        ("wrong-model", "business_model_mismatch"),
        ("financial", "financial_sector"),
    }


def test_peer_set_is_capped_at_fifty_in_stable_order() -> None:
    rows = (peer_row("22099131", security_code="2330"),) + tuple(
        peer_row(f"peer-{index:02d}", security_code=f"{index:04d}")
        for index in range(60, -1, -1)
    )
    result = build(authorities=(authority(rows=rows),))
    assert len(result.peer_ids) == 50
    assert result.peer_ids == tuple(f"peer-{index:02d}" for index in range(50))


def test_rejects_outlook_evidence_not_available_at_decision_time() -> None:
    future = observation(
        "future", "base", available_at="2026-07-24T12:00:01+08:00"
    )
    result = build(observations=outlook_observations() + (future,))
    assert "future" not in result.outlook_evidence_ids
    assert "future" not in result.scenario_evidence_ids.base


def test_official_claim_wins_over_same_claim_from_trusted_secondary() -> None:
    official = observation("official-demand", "base", claim_key="demand-2027")
    secondary = observation(
        "secondary-demand", "base", authority_id="trusted-research",
        claim_key="demand-2027",
    )
    result = build(
        authorities=(authority(), authority(source_id="trusted-research", source_tier="trusted_secondary")),
        observations=outlook_observations() + (secondary, official),
    )
    assert "official-demand" in result.outlook_evidence_ids
    assert "secondary-demand" not in result.outlook_evidence_ids


def test_secondary_only_evidence_has_explicit_tier_and_reduced_confidence_and_coverage() -> None:
    official_result = build()
    secondary_source = authority(source_id="trusted-research", source_tier="trusted_secondary")
    secondary_result = build(
        authorities=(authority(), secondary_source),
        observations=outlook_observations(authority_id="trusted-research"),
    )
    assert {item.source_tier for item in secondary_result.authority_records if item.used} == {
        "official", "trusted_secondary"
    }
    assert next(
        item for item in secondary_result.authority_records
        if item.source_id == "trusted-research"
    ).used is True
    assert secondary_result.confidence < official_result.confidence
    assert secondary_result.coverage < official_result.coverage


def test_source_free_statement_is_rejected() -> None:
    source_free = replace(observation("free", "base"), authority_id="")
    with pytest.raises(PeerOutlookError, match="source|authority"):
        build(observations=outlook_observations() + (source_free,))


def test_llm_observations_preserve_execution_id() -> None:
    llm_items = tuple(replace(
        item, extraction_method="llm", ai_execution_id="run-20260724-001"
    ) for item in outlook_observations())
    assert build(observations=llm_items).ai_execution_ids == ("run-20260724-001",)
    with pytest.raises(PeerOutlookError, match="execution"):
        build(observations=(replace(llm_items[0], ai_execution_id=None), *llm_items[1:]))


def test_counter_evidence_and_every_scenario_preserve_evidence_provenance() -> None:
    result = build()
    assert result.counter_evidence_ids == ("ev-counter",)
    assert set(result.scenario_assumptions) == {"bear", "base", "bull"}
    assert all(result.scenario_assumptions[name] for name in ("bear", "base", "bull"))
    assert result.scenario_evidence_ids.bear == ("ev-bear",)
    assert "ev-base" in result.scenario_evidence_ids.base
    assert result.scenario_evidence_ids.bull == ("ev-bull",)


def test_cyclical_routes_require_and_report_satisfied_normalization_gate() -> None:
    cyclical = route(cyclicality="cyclical")
    with pytest.raises(PeerOutlookError, match="cycle|cyclical|normalization"):
        build(industry_route=cyclical, observations=outlook_observations(normalized=False))

    result = build(industry_route=cyclical)
    assert result.cycle_normalization_gate.required is True
    assert result.cycle_normalization_gate.satisfied is True
    assert result.cycle_normalization_gate.normalization_evidence_ids


@pytest.mark.parametrize("route_status", ["unsupported_scope", "blocked"])
def test_unsupported_or_blocked_industry_route_cannot_produce_outlook(route_status) -> None:
    bad_route = route(status=route_status, reason="owner_excluded_v1_industry")
    with pytest.raises(PeerOutlookError, match="route|unsupported|blocked"):
        build(industry_route=bad_route)


def test_producer_schema_mismatch_blocks() -> None:
    with pytest.raises(PeerOutlookError, match="IndustryRoute.v1"):
        build(industry_route=route(schema_version="IndustryRoute.v2"))


def test_result_has_required_candidate_envelope_and_validates_closed_schema() -> None:
    result = build()
    assert result.status == "available"
    assert result.reason is None
    assert Decimal("0") < result.confidence <= Decimal("1")
    assert result.publication_status == "NON_PUBLISHABLE_CANDIDATE"
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"
    assert (
        result.schema_version,
        result.source_version,
        result.formula_version,
        result.model_version,
    ) == (
        "PeerOutlookEvidence.v1",
        "IndustryRoute.v1+official-company-list.v1+OutlookObservation.v1",
        "same-market-official-industry-hybrid-outlook.v1",
        "peer-outlook-deterministic-1.0.0",
    )
    assert result.generation_id == "generation-20260724-001"
    assert result.producer_candidate_sha == "c" * 40

    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/industry/peer_outlook/contracts/PeerOutlookEvidence.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(result), default=float))
    validator.validate(payload)
    invalid = payload | {"undeclared": True}
    assert next(validator.iter_errors(invalid)).validator == "additionalProperties"
    assert schema["$id"] == "PeerOutlookEvidence.v1"
    assert schema["additionalProperties"] is False


@pytest.mark.authority_probe
def test_live_official_authority_probe_accepts_t11_shaped_rows() -> None:
    live = fetch_industry_authority("TWSE")
    official = PeerAuthority(
        source_id="official-company-list",
        source_tier="official",
        url=live.url,
        content_sha256=live.content_sha256,
        available_at=live.available_at,
        retrieved_at=live.retrieved_at,
        rows=tuple({**row, "market": "TWSE"} for row in live.rows),
    )
    live_route = route(
        authority_sha256=live.content_sha256,
        authority_url=live.url,
        available_at=live.available_at,
        retrieved_at=live.retrieved_at,
        decision_time="2030-07-24T12:00:00+08:00",
    )
    live_observations = tuple(
        replace(item, available_at=live.available_at) for item in outlook_observations()
    )
    result = build(
        industry_route=live_route,
        authorities=(official,),
        observations=live_observations,
    )
    assert result.peer_ids
    assert "22099131" not in result.peer_ids
    record = next(item for item in result.authority_records if item.source_id == official.source_id)
    assert record.source_tier == "official"
    assert record.url == official.url
    assert record.content_sha256 == live.content_sha256
    assert record.available_at == official.available_at
    assert record.retrieved_at == official.retrieved_at
