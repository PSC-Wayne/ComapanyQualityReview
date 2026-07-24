import json
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from company_quality.policies.candidate import (
    CandidatePolicyError,
    build_candidate_policy_bundle,
    evidence_family_policy_sha256,
    jcs_canonicalize,
    validate_evidence_family_policy_hash,
)


def digest(char: str) -> str:
    return char * 64


def inputs(*, hard_gate=False) -> tuple[Any, ...]:
    gate = SimpleNamespace(
        schema_version="AuditGateDecision.v1",
        evidence_ids=("audit-lineage",),
        hard_gate_evidence_ids=("actual-gate-trigger",) if hard_gate else (),
        coverage=Decimal("1"),
        available_at="2026-03-01T10:00:00+08:00",
    )
    earnings = SimpleNamespace(
        schema_version="EarningsCapitalEfficiencyCandidate.v1",
        evidence_family_ids=("earnings_outcomes", "cash_conversion", "capital_efficiency"),
        coverage=Decimal("0.90"),
        available_at="2026-03-01T11:00:00+08:00",
    )
    cash = SimpleNamespace(
        schema_version="CashBalanceAllocationCandidate.v1",
        evidence_family_ids=("cash_conversion", "balance_sheet", "capital_allocation", "high_risk_notes"),
        coverage=Decimal("0.80"),
        available_at="2026-03-01T12:00:00+08:00",
    )
    peers = SimpleNamespace(
        schema_version="PeerOutlookEvidence.v1",
        status="available",
        issuer_id="issuer-1",
        peer_ids=("peer-a", "peer-b", "peer-c", "peer-d"),
        producer_candidate_sha=digest("c"),
        coverage=Decimal("0.75"),
        available_at="2026-03-01T13:00:00+08:00",
    )
    business = SimpleNamespace(
        schema_version="BusinessMoatCandidate.v1",
        issuer_id="issuer-1",
        peer_ids=("peer-a", "peer-b", "peer-c", "peer-d"),
        evidence_family_ids=("business:revenue_driver", "industry:peer_outlook"),
        producer_candidate_sha=digest("d"),
        coverage=Decimal("0.70"),
        available_at="2026-03-01T14:00:00+08:00",
    )
    governance = SimpleNamespace(
        schema_version="GovernancePeopleCandidate.v1",
        evidence_family_ids=("governance:board", "people:key_people", "adaptability:rd"),
        producer_candidate_sha=digest("e"),
        coverage=Decimal("0.65"),
        available_at="2026-03-01T15:00:00+08:00",
    )
    audit = SimpleNamespace(
        schema_version="Pillar1AuditReliabilityCandidate.v1",
        evidence_family_ids=("audit:filing_completeness", "audit:filing_timeliness"),
        coverage=Decimal("0.95"),
        available_at="2026-03-01T16:00:00+08:00",
    )
    valuation = SimpleNamespace(
        schema_version="ValuationUpsideDiagnostic.v1",
        rating_disposition="NO_RATING_NOT_APPLICABLE",
        coverage=Decimal("0.85"),
        available_at="2026-03-01T17:00:00+08:00",
    )
    downside = SimpleNamespace(
        schema_version="DownsideStressDiagnostic.v1",
        rating_disposition="NO_RATING_NOT_APPLICABLE",
        coverage=Decimal("0.60"),
        available_at="2026-03-01T18:00:00+08:00",
    )
    return gate, earnings, cash, peers, business, governance, audit, valuation, downside


def producer_shas() -> dict[str, str]:
    tickets = ("T07", "T09", "T10", "T12", "T13", "T14", "T16", "T17", "T18")
    hex_chars = "012345678"
    values = {
        ticket: digest(hex_chars[index])
        for index, ticket in enumerate(tickets)
    }
    values["T12"] = digest("c")
    values["T13"] = digest("d")
    values["T14"] = digest("e")
    return values


def build(*, hard_gate=False):
    return build_candidate_policy_bundle(
        *inputs(hard_gate=hard_gate),
        producer_shas=producer_shas(),
        generation_id="r9-generation",
        producer_candidate_sha=digest("f"),
    )


def row(bundle, family):
    return next(
        item for item in bundle.anti_double_count_policy.evidence_family_ownership
        if item.evidence_family_id == family
    )


def test_frozen_candidate_policies_are_directly_executable_and_non_publishable() -> None:
    result = build()

    assert asdict(result.pillar_weights) == {
        "audit_reliability": Decimal("0.10"),
        "earnings_capital_efficiency": Decimal("0.25"),
        "cash_balance_allocation": Decimal("0.25"),
        "business_moat": Decimal("0.25"),
        "governance": Decimal("0.05"),
        "people_adaptability": Decimal("0.10"),
        "sum": Decimal("1"),
    }
    quality = result.quality_policy
    assert quality.normalisation == "winsor_rank"
    assert (quality.winsor_lower_quantile, quality.winsor_upper_quantile) == (
        Decimal("0.025"), Decimal("0.975")
    )
    assert quality.cohort_locator == "PeerOutlookEvidence.peer_ids+issuer_id"
    assert quality.minimum_cohort_size == 5
    assert quality.tie_method == "average_percentile_rank"
    assert [item.label for item in quality.bands] == [
        "very_weak", "weak", "neutral", "strong", "very_strong"
    ]
    assert result.upside_bucket_policy.return_unit == "decimal_return"
    assert result.upside_bucket_policy.sensitivity_horizons_months == (24, 36)
    assert result.upside_bucket_policy.thresholds == (
        Decimal("-0.20"), Decimal("0"), Decimal("0.15"), Decimal("0.30")
    )
    assert asdict(result.downside_bucket_policy.component_weights) == {
        "maximum_drawdown_vulnerability": Decimal("0.30"),
        "permanent_capital_loss_vulnerability": Decimal("0.40"),
        "material_adverse_event_vulnerability": Decimal("0.30"),
        "sum": Decimal("1"),
    }
    assert result.downside_bucket_policy.composite_thresholds == (
        Decimal("20"), Decimal("40"), Decimal("60"), Decimal("80")
    )
    assert result.publishable is False
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"
    assert result.policy_coverage == Decimal("0.60")
    assert result.available_at == "2026-03-01T18:00:00+08:00"


def test_single_owner_duplicate_exclusion_and_downside_ownership() -> None:
    result = build()

    earnings = row(result, "earnings_outcomes")
    assert earnings.primary_component == "earnings_capital_efficiency"
    assert earnings.excluded_from == ()
    assert earnings.disposition == "single_owner"

    conversion = row(result, "cash_conversion")
    assert conversion.primary_component == "cash_balance_allocation"
    assert conversion.excluded_from == ("earnings_capital_efficiency",)
    assert conversion.disposition == "excluded_duplicate"

    downside = row(result, "permanent_capital_loss_vulnerability")
    assert downside.primary_component == "permanent_capital_loss_vulnerability"
    assert downside.excluded_from == ()
    assert downside.disposition == "single_owner"


def test_actual_t07_trigger_only_creates_hard_gate_exclusion() -> None:
    clear = build()
    assert all(
        item.evidence_family_id != "audit:hard_gate"
        for item in clear.anti_double_count_policy.evidence_family_ownership
    )

    triggered = build(hard_gate=True)
    hard = row(triggered, "audit:hard_gate")
    assert hard.primary_component == "hard_gate_only"
    assert hard.excluded_from == (
        "audit_reliability", "earnings_capital_efficiency", "cash_balance_allocation",
        "business_moat", "governance", "people_adaptability",
        "maximum_drawdown_vulnerability", "permanent_capital_loss_vulnerability",
        "material_adverse_event_vulnerability",
    )
    assert hard.disposition == "excluded_hard_gate"
    assert hard.evidence_ids == ("actual-gate-trigger",)


def test_jcs_hash_is_semantic_slice_hash_not_raw_or_parent_bytes() -> None:
    first = json.loads('[{"policy_rule_id":"x\\n","evidence_family_id":"caf\\u00e9"}]')
    second = json.loads('[ { "evidence_family_id" : "café", "policy_rule_id" : "x\\n" } ]')
    assert evidence_family_policy_sha256(first) == evidence_family_policy_sha256(second)

    reordered = [second[0], {"evidence_family_id": "second", "policy_rule_id": "y"}]
    reversed_list = list(reversed(reordered))
    assert evidence_family_policy_sha256(reordered) != evidence_family_policy_sha256(reversed_list)
    changed = [{**second[0], "policy_rule_id": "changed"}]
    assert evidence_family_policy_sha256(second) != evidence_family_policy_sha256(changed)

    claimed = evidence_family_policy_sha256(second)
    validate_evidence_family_policy_hash(second, claimed)
    parent_sha = sha256(jcs_canonicalize({"parent": second})).hexdigest()
    with pytest.raises(CandidatePolicyError, match="slice hash mismatch"):
        validate_evidence_family_policy_hash(second, parent_sha)


def test_unknown_duplicate_family_and_missing_sha_fail_closed() -> None:
    values = list(inputs())
    values[1].evidence_family_ids = ("earnings_outcomes", "earnings_outcomes")
    with pytest.raises(CandidatePolicyError, match="duplicate evidence family"):
        build_candidate_policy_bundle(
            *values, producer_shas=producer_shas(), generation_id="g",
            producer_candidate_sha=digest("f")
        )

    values = list(inputs())
    values[4].evidence_family_ids = ("mystery-family",)
    with pytest.raises(CandidatePolicyError, match="no owner"):
        build_candidate_policy_bundle(
            *values, producer_shas=producer_shas(), generation_id="g",
            producer_candidate_sha=digest("f")
        )

    shas = producer_shas()
    shas.pop("T17")
    with pytest.raises(CandidatePolicyError, match="producer SHAs"):
        build_candidate_policy_bundle(
            *inputs(), producer_shas=shas, generation_id="g",
            producer_candidate_sha=digest("f")
        )


def test_closed_schema_accepts_output_and_rejects_ownership_violations() -> None:
    result = build(hard_gate=True)
    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/policies/candidate/contracts/CandidatePolicyBundle.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(result), default=float))
    validator.validate(payload)

    ownership = payload["anti_double_count_policy"]["evidence_family_ownership"]
    single = next(item for item in ownership if item["disposition"] == "single_owner")
    single["excluded_from"] = ["governance"]
    assert next(validator.iter_errors(payload)).validator in {"const", "enum"}

    payload = json.loads(json.dumps(asdict(result), default=float))
    hard = next(item for item in payload["anti_double_count_policy"]["evidence_family_ownership"] if item["primary_component"] == "hard_gate_only")
    hard["excluded_from"] = []
    assert next(validator.iter_errors(payload)).validator == "minItems"

    payload = json.loads(json.dumps(asdict(result), default=float))
    conversion = next(item for item in payload["anti_double_count_policy"]["evidence_family_ownership"] if item["evidence_family_id"] == "cash_conversion")
    conversion["excluded_from"] = ["cash_balance_allocation"]
    assert next(validator.iter_errors(payload)).validator == "not"

    payload = json.loads(json.dumps(asdict(result), default=float))
    payload["anti_double_count_policy"]["evidence_family_ownership"][0]["secondary_component"] = "governance"
    assert next(validator.iter_errors(payload)).validator == "additionalProperties"
