import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from company_quality.pit import AdmittedFactSet, FactAdmission
from company_quality.valuation.diagnostic import (
    ValuationDiagnosticError,
    build_valuation_upside_diagnostic,
)


def fact(fact_id: str, fact_type: str, value: object, *, effective_at=None):
    timestamp = effective_at or "2026-03-03T14:00:00+08:00"
    return FactAdmission(
        fact_id=fact_id,
        fact_type=fact_type,
        value=value,
        unit=None,
        effective_at=timestamp,
        announced_at=None,
        available_at="2026-03-03T15:00:00+08:00",
        retrieved_at="2026-03-03T16:00:00+08:00",
        valid_from="2026-03-03T15:00:00+08:00",
        valid_to=None,
        authority_rank=1,
        append_sequence=1,
        version_id="v1",
        source_id="official",
        disposition="admitted",
        failure_reason=None,
        admission_coverage=1.0,
    )


def valuation_facts(*, include_dcf=True, include_relative=True):
    facts = [
        fact(
            "price-1",
            "official_close_price",
            {
                "value": "100",
                "currency": "TWD",
                "price_time": "2026-03-03T13:30:00+08:00",
            },
        ),
        fact(
            "scenario-bear",
            "valuation.scenario.bear",
            {"value": "80", "assumption_ids": ["out-bear"]},
        ),
        fact(
            "scenario-base",
            "valuation.scenario.base",
            {"value": "110", "assumption_ids": ["out-base"]},
        ),
        fact(
            "scenario-bull",
            "valuation.scenario.bull",
            {"value": "140", "assumption_ids": ["out-bull"]},
        ),
    ]
    if include_relative:
        facts.append(
            fact(
                "relative-1",
                "valuation.relative",
                {
                    "peer_ids": ["peer-a", "peer-b"],
                    "multiple": "pe",
                    "issuer_multiple": "10",
                    "peer_median": "12",
                    "implied_value": "120",
                },
            )
        )
    if include_dcf:
        facts.append(
            fact(
                "dcf-1",
                "valuation.dcf",
                {
                    "forecast_years": 5,
                    "revenue_growth": ["0.05"] * 5,
                    "operating_margin": ["0.1"] * 5,
                    "wacc": "0.08",
                    "terminal_growth": "0.02",
                    "net_debt": "1000",
                    "shares": "100",
                    "implied_value": "80",
                },
            )
        )
    return facts


def producers(facts=None) -> tuple[AdmittedFactSet, Any, Any, Any, Any, Any]:
    admitted = AdmittedFactSet(
        decision_time="2026-03-03T23:00:00+08:00",
        facts=tuple(facts if facts is not None else valuation_facts()),
    )
    financials = SimpleNamespace(
        schema_version="CanonicalFinancialFacts.v1", facts=(object(),)
    )
    earnings = SimpleNamespace(
        schema_version="EarningsCapitalEfficiencyCandidate.v1"
    )
    cash = SimpleNamespace(schema_version="CashBalanceAllocationCandidate.v1")
    peers = SimpleNamespace(
        schema_version="PeerOutlookEvidence.v1",
        status="available",
        issuer_id="issuer-1",
        peer_ids=("peer-a", "peer-b"),
        outlook_evidence_ids=("out-bear", "out-base", "out-bull"),
        available_at="2026-03-03T17:00:00+08:00",
    )
    business = SimpleNamespace(
        schema_version="BusinessMoatCandidate.v1",
        issuer_id="issuer-1",
        peer_ids=("peer-a", "peer-b"),
        outlook_evidence_ids=("out-bear", "out-base", "out-bull"),
        available_at="2026-03-03T18:00:00+08:00",
    )
    return admitted, financials, earnings, cash, peers, business


def test_recomputes_upside_route_scenarios_and_model_disagreement() -> None:
    result = build_valuation_upside_diagnostic(*producers())

    assert result.current_price.value == Decimal("100")
    assert result.route == "multi_model"
    assert result.relative_value.implied_value == Decimal("120")
    assert result.relative_value.upside_pct == Decimal("0.2")
    assert result.dcf.implied_value == Decimal("80")
    assert result.dcf.upside_pct == Decimal("-0.2")
    assert result.scenarios.bear.upside_pct == Decimal("-0.2")
    assert result.scenarios.base.upside_pct == Decimal("0.1")
    assert result.scenarios.bull.upside_pct == Decimal("0.4")
    assert result.model_disagreement.range_pct == Decimal("40.0")
    assert result.model_disagreement.max_model == "relative"
    assert result.model_disagreement.min_model == "dcf"
    assert result.horizon_months == 12
    assert result.coverage == Decimal("0.8")


def test_single_relative_model_routes_relative_without_inventing_dcf() -> None:
    result = build_valuation_upside_diagnostic(
        *producers(valuation_facts(include_dcf=False))
    )
    assert result.route == "relative"
    assert result.dcf is None
    assert result.reverse_dcf is None
    assert result.model_disagreement.range_pct == 0


def test_missing_scenario_or_model_blocks_instead_of_inventing() -> None:
    missing_scenario = [
        item for item in valuation_facts() if item.fact_type != "valuation.scenario.bear"
    ]
    with pytest.raises(ValuationDiagnosticError, match="missing bear scenario"):
        build_valuation_upside_diagnostic(*producers(missing_scenario))

    no_models = [
        item for item in valuation_facts()
        if not item.fact_type.startswith("valuation.relative")
        and item.fact_type != "valuation.dcf"
    ]
    with pytest.raises(ValuationDiagnosticError, match="valuation model"):
        build_valuation_upside_diagnostic(*producers(no_models))


def test_unresolved_newer_price_conflict_cannot_fall_back_to_older_price() -> None:
    facts = valuation_facts()
    facts.append(
        FactAdmission(
            fact_id="price-conflict",
            fact_type="official_close_price",
            value=None,
            unit=None,
            effective_at="2026-03-03T14:30:00+08:00",
            announced_at=None,
            available_at="2026-03-03T15:00:00+08:00",
            retrieved_at="2026-03-03T16:00:00+08:00",
            valid_from="2026-03-03T15:00:00+08:00",
            valid_to=None,
            authority_rank=1,
            append_sequence=2,
            version_id="v2",
            source_id=None,
            disposition="blocked_conflict",
            failure_reason="same_rank_conflict",
            admission_coverage=0.0,
        )
    )
    with pytest.raises(ValuationDiagnosticError, match="unresolved conflict"):
        build_valuation_upside_diagnostic(*producers(facts))


def test_unbound_assumption_peer_and_issuer_conflicts_fail_closed() -> None:
    bad = valuation_facts()
    scenario = next(item for item in bad if item.fact_type == "valuation.scenario.base")
    bad[bad.index(scenario)] = fact(
        scenario.fact_id,
        scenario.fact_type,
        {"value": "110", "assumption_ids": ["unknown-future-claim"]},
    )
    with pytest.raises(ValuationDiagnosticError, match="unbound base"):
        build_valuation_upside_diagnostic(*producers(bad))

    values = list(producers())
    values[-1].issuer_id = "issuer-2"
    with pytest.raises(ValuationDiagnosticError, match="issuer binding"):
        build_valuation_upside_diagnostic(*values)

    bad_peer = valuation_facts()
    rel = next(item for item in bad_peer if item.fact_type == "valuation.relative")
    bad_peer[bad_peer.index(rel)] = fact(
        rel.fact_id,
        rel.fact_type,
        {**rel.value, "peer_ids": ["not-a-t12-peer"]},
    )
    with pytest.raises(ValuationDiagnosticError, match="peer_ids"):
        build_valuation_upside_diagnostic(*producers(bad_peer))


def test_future_price_and_non_monotonic_scenarios_fail_closed() -> None:
    future = valuation_facts()
    price = future[0]
    future[0] = fact(
        price.fact_id,
        price.fact_type,
        {**price.value, "price_time": "2026-03-04T13:30:00+08:00"},
    )
    with pytest.raises(ValuationDiagnosticError, match="later than decision"):
        build_valuation_upside_diagnostic(*producers(future))

    crossed = valuation_facts()
    bear = next(item for item in crossed if item.fact_type.endswith("bear"))
    crossed[crossed.index(bear)] = fact(
        bear.fact_id,
        bear.fact_type,
        {"value": "130", "assumption_ids": ["out-bear"]},
    )
    with pytest.raises(ValuationDiagnosticError, match="bear <= base <= bull"):
        build_valuation_upside_diagnostic(*producers(crossed))


def test_sensitivity_is_isolated_and_never_headline_eligible() -> None:
    facts = valuation_facts() + [
        fact(
            "sensitivity-1",
            "valuation.sensitivity_24_36",
            {
                "isolated": True,
                "month24_upside_pct": "30",
                "month36_upside_pct": "50",
                "headline_eligible": False,
            },
        )
    ]
    result = build_valuation_upside_diagnostic(*producers(facts))
    assert result.sensitivity_24_36.isolated is True
    assert result.sensitivity_24_36.headline_eligible is False
    assert result.horizon_months == 12


def test_closed_schema_accepts_output() -> None:
    result = build_valuation_upside_diagnostic(*producers())
    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/valuation/diagnostic/contracts/ValuationUpsideDiagnostic.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(result), default=float))
    validator.validate(payload)
    assert next(validator.iter_errors(payload | {"stars": 5})).validator == (
        "additionalProperties"
    )
