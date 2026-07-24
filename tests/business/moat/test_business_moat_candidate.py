import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from company_quality.business.evidence import AdmittedBusinessObservation
from company_quality.business.moat import BusinessMoatError, build_business_moat_candidate


def observation(evidence_id, category, *, name="advanced process", value=None,
                direction="context", period="2025-12-31"):
    return AdmittedBusinessObservation(
        evidence_id=evidence_id, source_id="annual", source_tier="official",
        claim_key=evidence_id, category=category, name=name,
        statement=f"Grounded {evidence_id}", direction=direction,
        numeric_value=value, period_end=period,
        available_at="2026-04-15T00:00:00+08:00",
        extraction_method="deterministic", ai_execution_id=None,
    )


def business(**changes):
    values = dict(
        issuer_id="22099131", status="available",
        schema_version="IssuerBusinessEvidence.v1",
        observations=(
            observation("revenue", "revenue_driver", value=Decimal("80")),
            observation("customer-a", "customer_concentration", name="customer A", value=Decimal("12")),
            observation("customer-b", "customer_concentration", name="customer B", value=Decimal("8")),
            observation("switch-support", "switching_cost", value=Decimal("0.8"), direction="support"),
            observation("switch-counter", "switching_cost", value=Decimal("0.2"), direction="counter"),
        ),
        evidence_family_ids=("business:revenue_driver", "business:switching_cost"),
        coverage=Decimal("0.5"), confidence=Decimal("0.9"),
        available_at="2026-04-15T00:00:00+08:00",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def peer(**changes):
    values = dict(
        issuer_id="22099131", status="available",
        schema_version="PeerOutlookEvidence.v1", cyclicality="moderate",
        peer_ids=("peer-a", "peer-b"), outlook_evidence_ids=("outlook-a",),
        coverage=Decimal("0.8"), confidence=Decimal("0.75"),
        available_at="2026-07-24T09:00:00+08:00",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def build(**kwargs):
    return build_business_moat_candidate(
        kwargs.get("peer_outlook", peer()), kwargs.get("issuer_business", business()),
        generation_id="gen-001", producer_candidate_sha="a" * 40,
    )


def test_transforms_revenue_concentration_and_preserves_cyclicality() -> None:
    result = build()
    assert result.revenue_drivers[0].name == "advanced process"
    assert result.revenue_drivers[0].share_pct == Decimal("80")
    assert result.concentration_risks.customer_top1_pct == Decimal("12")
    assert result.concentration_risks.supplier_top1_pct is None
    assert result.cyclicality == "moderate"
    assert result.peer_ids == ("peer-a", "peer-b")
    assert result.outlook_evidence_ids == ("outlook-a",)
    assert result.coverage == Decimal("0.5")
    assert result.confidence == Decimal("0.75")


def test_moat_dimensions_and_score_remain_null_until_t23() -> None:
    result = build()
    assert asdict(result.moat_evidence) == {
        "switching_cost": None, "network_effect": None, "cost_advantage": None,
        "intangible_assets": None, "efficient_scale": None,
    }
    assert result.candidate_score is None
    assert result.unavailable_reasons["switching_cost"] == "calibration_pending_t23"
    assert result.unavailable_reasons["candidate_score"] == "calibration_pending_t23"
    assert result.status == "NON_PUBLISHABLE_CANDIDATE"


def test_moat_judgement_retains_support_counter_and_unknown() -> None:
    result = build()
    switching = next(item for item in result.moat_judgements if item.dimension == "switching_cost")
    assert switching.support_evidence_ids == ("switch-support",)
    assert switching.counter_evidence_ids == ("switch-counter",)
    assert switching.evidence_status == "evidence_present"
    network = next(item for item in result.moat_judgements if item.dimension == "network_effect")
    assert network.evidence_status == "unknown"
    assert network.support_evidence_ids == ()


def test_latest_period_drives_revenue_and_concentration() -> None:
    observations = business().observations + (
        observation("new-revenue", "revenue_driver", value=Decimal("85"), period="2026-03-31"),
        observation("new-customer", "customer_concentration", value=Decimal("15"), period="2026-03-31"),
    )
    result = build(issuer_business=business(observations=observations))
    assert result.revenue_drivers[0].share_pct == Decimal("85")
    assert result.concentration_risks.customer_top1_pct == Decimal("15")


def test_missing_concentrations_are_null_with_reasons_not_zero() -> None:
    minimal = business(observations=(observation("revenue", "revenue_driver", value=None),))
    result = build(issuer_business=minimal)
    assert result.revenue_drivers[0].share_pct is None
    assert result.concentration_risks.customer_top1_pct is None
    assert result.unavailable_reasons["customer_top1_pct"] == "missing_concentration_evidence"


def test_conflicting_latest_revenue_share_blocks() -> None:
    conflicting = (
        observation("a", "revenue_driver", value=Decimal("70")),
        observation("b", "revenue_driver", value=Decimal("80")),
    )
    with pytest.raises(BusinessMoatError, match="conflicting"):
        build(issuer_business=business(observations=conflicting))


def test_upstream_contract_status_and_issuer_binding_fail_closed() -> None:
    with pytest.raises(BusinessMoatError, match="issuer"):
        build(peer_outlook=peer(issuer_id="other"))
    with pytest.raises(BusinessMoatError, match="PeerOutlookEvidence.v1"):
        build(peer_outlook=peer(schema_version="PeerOutlookEvidence.v2"))
    with pytest.raises(BusinessMoatError, match="available"):
        build(issuer_business=business(status="blocked"))


def test_output_available_at_and_versions_are_bound() -> None:
    result = build()
    assert result.available_at == "2026-07-24T09:00:00+08:00"
    assert result.source_version == "PeerOutlookEvidence.v1+IssuerBusinessEvidence.v1"
    assert result.formula_version == "raw-evidence-no-moat-calibration.v1"
    assert "industry:peer_outlook" in result.evidence_family_ids


def test_closed_json_schema_validates_output() -> None:
    path = Path(__file__).parents[3] / "src/company_quality/business/moat/contracts/BusinessMoatCandidate.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    payload = json.loads(json.dumps(asdict(build()), default=float))
    Draft202012Validator(schema).validate(payload)
    assert schema["$id"] == "BusinessMoatCandidate.v1"
    assert schema["additionalProperties"] is False
