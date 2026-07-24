import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from company_quality.business.evidence import (
    BusinessObservation,
    BusinessSource,
    IssuerBusinessEvidenceError,
    build_issuer_business_evidence,
)
from company_quality.industry.routing import IndustryRoute

PDF_SHA = "a" * 64


def route(**changes):
    value = IndustryRoute(
        status="routed", reason=None, issuer_id="22099131",
        sector_code="electronics", industry_code="24",
        business_model_tags=("general_operating_company", "sector:electronics"),
        cyclicality="moderate", peer_rule_id="same-market-exact-official-industry.v1",
        route_version="1.0.0", evidence_ids=("identity:TWSE:2330",),
        route_coverage=Decimal("1"), decision_time="2026-07-24T12:00:00+08:00",
        authority_url="https://official.example/list", authority_sha256="b" * 64,
        available_at="2026-07-23T00:00:00+08:00",
        retrieved_at="2026-07-24T10:00:00+08:00",
    )
    return replace(value, **changes)


def annual(**changes):
    values = dict(
        issuer_id="22099131", available_at="2026-04-15T00:00:00+08:00",
        pdf_source_url="https://mops.example/2330-annual.pdf", pdf_sha256=PDF_SHA,
        retrieved_at="2026-07-24T10:00:00+08:00",
        schema_version="AuditFilingInventory.v1",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def source(source_id="annual", tier="official", sha=PDF_SHA, url=None):
    return BusinessSource(
        source_id=source_id, source_tier=tier,
        url=url or ("https://mops.example/2330-annual.pdf" if source_id == "annual" else f"https://example.com/{source_id}"),
        content_sha256=sha, available_at="2026-04-15T00:00:00+08:00",
        retrieved_at="2026-07-24T10:00:00+08:00",
    )


def obs(evidence_id="revenue", category="revenue_driver", *, source_id="annual", claim=None,
        value=Decimal("80"), direction="context", available="2026-04-15T00:00:00+08:00"):
    return BusinessObservation(
        evidence_id=evidence_id, source_id=source_id, claim_key=claim or evidence_id,
        category=category, name="advanced process", statement=f"Grounded {evidence_id}",
        direction=direction, numeric_value=value, period_end="2025-12-31",
        available_at=available,
    )


def build(*, sources=None, observations=None, industry_route=None, report=None):
    return build_issuer_business_evidence(
        industry_route or route(), report or annual(),
        tuple(sources or (source(),)), tuple(observations or (obs(),)),
        generation_id="gen-001", producer_candidate_sha="c" * 40,
    )


def test_admits_official_revenue_and_moat_counter_evidence() -> None:
    result = build(observations=(
        obs(),
        obs("switch", "switching_cost", value=Decimal("0.7"), direction="support"),
        obs("competition", "competition", value=None, direction="counter"),
    ))
    assert result.issuer_id == "22099131"
    assert result.counter_evidence_ids == ("competition",)
    assert result.confidence == 1
    assert result.publication_status == "NON_PUBLISHABLE_CANDIDATE"
    assert result.observations[0].source_tier == "official"


def test_official_claim_wins_over_secondary_and_secondary_only_is_discounted() -> None:
    secondary = source("research", "trusted_secondary", "d" * 64)
    official = obs(claim="mix")
    weaker = replace(official, evidence_id="secondary", source_id="research")
    preferred = build(sources=(source(), secondary), observations=(official, weaker))
    assert preferred.observations[0].evidence_id == "revenue"
    secondary_only = build(
        sources=(source(), secondary),
        observations=(replace(obs(), source_id="research"),),
    )
    assert secondary_only.confidence == Decimal("0.75")
    assert secondary_only.coverage < preferred.coverage


def test_future_observation_is_excluded() -> None:
    result = build(observations=(obs(), obs("future", available="2026-07-25T00:00:00+08:00")))
    assert tuple(item.evidence_id for item in result.observations) == ("revenue",)


def test_missing_revenue_driver_or_annual_binding_blocks() -> None:
    with pytest.raises(IssuerBusinessEvidenceError, match="revenue-driver"):
        build(observations=(obs("switch", "switching_cost", value=Decimal("0.5")),))
    with pytest.raises(IssuerBusinessEvidenceError, match="bind"):
        build(sources=(source(sha="e" * 64),))


def test_same_rank_conflict_blocks() -> None:
    conflict = replace(obs(claim="mix"), evidence_id="other", statement="Contradiction")
    with pytest.raises(IssuerBusinessEvidenceError, match="conflict"):
        build(observations=(obs(claim="mix"), conflict))


def test_numeric_ranges_and_unknown_are_typed() -> None:
    result = build(observations=(replace(obs(), numeric_value=None),))
    assert result.observations[0].numeric_value is None
    with pytest.raises(IssuerBusinessEvidenceError, match="percentage"):
        build(observations=(replace(obs(), numeric_value=Decimal("101")),))
    with pytest.raises(IssuerBusinessEvidenceError, match="moat"):
        build(observations=(obs("switch", "switching_cost", value=Decimal("2")), obs()))


def test_llm_observation_requires_and_preserves_execution_id() -> None:
    llm = replace(obs(), extraction_method="llm", ai_execution_id="llm-run-1")
    assert build(observations=(llm,)).ai_execution_ids == ("llm-run-1",)
    with pytest.raises(IssuerBusinessEvidenceError, match="execution"):
        build(observations=(replace(llm, ai_execution_id=None),))


def test_identity_pit_and_producer_contract_fail_closed() -> None:
    with pytest.raises(IssuerBusinessEvidenceError, match="issuer"):
        build(report=annual(issuer_id="other"))
    with pytest.raises(IssuerBusinessEvidenceError, match="PIT"):
        build(report=annual(available_at="2026-07-25T00:00:00+08:00"))
    with pytest.raises(IssuerBusinessEvidenceError, match="AuditFilingInventory.v1"):
        build(report=annual(schema_version="AuditFilingInventory.v2"))


def test_json_contract_is_closed_and_matches_output() -> None:
    path = Path(__file__).parents[3] / "src/company_quality/business/evidence/contracts/IssuerBusinessEvidence.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    payload = json.loads(json.dumps(asdict(build()), default=float))
    Draft202012Validator(schema).validate(payload)
    assert schema["additionalProperties"] is False
    assert schema["$id"] == "IssuerBusinessEvidence.v1"
