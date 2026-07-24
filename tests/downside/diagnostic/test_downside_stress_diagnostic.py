import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from company_quality.downside.diagnostic import (
    DownsideDiagnosticError,
    build_downside_stress_diagnostic,
)


def inputs(*, bomb=True, opinion="unmodified") -> tuple[Any, ...]:
    constructs = tuple(
        SimpleNamespace(
            name=name,
            raw_value=Decimal(raw),
            evidence_ids=(f"evidence-{name}",),
            state="present",
        )
        for name, raw in (
            ("maximum_drawdown_vulnerability", "0.4"),
            ("permanent_capital_loss_vulnerability", "0.2"),
            ("material_adverse_event_vulnerability", "0.3"),
        )
    )
    risk_items = (
        SimpleNamespace(
            cause="demand contraction",
            exposure="revenue concentration",
            transmission_path="lower utilisation reduces margin",
            buffer="net cash",
            indicator="monthly revenue growth",
            severity="high",
            trigger="three negative months",
            threshold=Decimal("-0.15"),
            evidence_id="risk-evidence",
            fact_id="risk-fact",
        ),
    )
    stress = tuple(
        SimpleNamespace(
            scenario=name,
            assumption_ids=(f"assumption-{name}",),
            equity_value_change_pct=Decimal(change),
            liquidity_state=liquidity,
            fact_id=f"stress-{name}",
        )
        for name, change, liquidity in (
            ("bear", "-40", "tight"),
            ("base", "5", "adequate"),
            ("bull", "30", "adequate"),
        )
    )
    event = None
    if bomb:
        event_type = {
            "adverse": "formal_adverse_opinion",
            "disclaimer": "formal_disclaimer",
        }.get(opinion, "default")
        event = SimpleNamespace(
            event_id="event-1",
            event_type=event_type,
            authoritative=True,
            material=True,
            current_relevance=True,
            authority_source_id="official-event-source",
            effective_at="2026-02-01T00:00:00+08:00",
            expires_at=None,
            evidence_ids=("bomb-evidence",),
        )
    assumptions = SimpleNamespace(
        schema_version="DownsideAssumptionBundle.v1",
        status="ready",
        constructs=constructs,
        risk_items=risk_items,
        stress_assumptions=stress,
        bomb_event=event,
        coverage=Decimal("0.9"),
        available_at="2026-03-03T19:00:00+08:00",
    )
    financials = SimpleNamespace(
        schema_version="CanonicalFinancialFacts.v1",
        facts=(SimpleNamespace(available_at="2026-03-01T10:00:00+08:00"),),
        fact_coverage=Decimal("0.95"),
    )
    gate = SimpleNamespace(
        schema_version="AuditGateDecision.v1",
        opinion_type=opinion,
        coverage=Decimal("1"),
        available_at="2026-03-01T11:00:00+08:00",
    )
    notes = SimpleNamespace(
        schema_version="HighRiskNoteRegister.v1",
        coverage=Decimal("0.8"),
        available_at="2026-03-01T12:00:00+08:00",
    )
    cash = SimpleNamespace(
        schema_version="CashBalanceAllocationCandidate.v1",
        coverage=Decimal("0.85"),
        available_at="2026-03-01T13:00:00+08:00",
    )
    peers = SimpleNamespace(
        schema_version="PeerOutlookEvidence.v1",
        status="available",
        issuer_id="issuer-1",
        peer_ids=("peer-a",),
        coverage=Decimal("0.9"),
        available_at="2026-03-01T14:00:00+08:00",
    )
    business = SimpleNamespace(
        schema_version="BusinessMoatCandidate.v1",
        issuer_id="issuer-1",
        peer_ids=("peer-a",),
        coverage=Decimal("0.75"),
        available_at="2026-03-01T15:00:00+08:00",
    )
    governance = SimpleNamespace(
        schema_version="GovernancePeopleCandidate.v1",
        coverage=Decimal("0.7"),
        available_at=None,
    )
    return assumptions, financials, gate, notes, cash, peers, business, governance


def test_maps_governed_constructs_risks_and_stress_without_normalisation() -> None:
    result = build_downside_stress_diagnostic(*inputs(bomb=False))

    assert result.horizon_months == 12
    assert result.constructs.maximum_drawdown_vulnerability.raw_value == Decimal("0.4")
    assert result.constructs.maximum_drawdown_vulnerability.normalised_score is None
    assert result.constructs.permanent_capital_loss_vulnerability.normalised_score is None
    assert result.constructs.material_adverse_event_vulnerability.normalised_score is None
    assert result.risk_items[0].cause == "demand contraction"
    assert result.stress_pack.bear.equity_value_change_pct == Decimal("-40")
    assert result.stress_pack.base.liquidity_state == "adequate"
    assert result.bomb_candidate is None
    assert result.coverage == Decimal("0.7")
    assert result.available_at == "2026-03-03T19:00:00+08:00"


def test_authoritative_material_current_event_becomes_candidate_only() -> None:
    result = build_downside_stress_diagnostic(*inputs(bomb=True))
    assert result.bomb_candidate.event_type == "default"
    assert result.bomb_candidate.authoritative is True
    assert result.publication_status == "NON_PUBLISHABLE_CANDIDATE"
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"

    values = list(inputs(bomb=True))
    values[0].bomb_event.current_relevance = False
    result = build_downside_stress_diagnostic(*values)
    assert result.bomb_candidate is None


def test_t07_formal_opinion_requires_matching_formal_bomb_event() -> None:
    with pytest.raises(DownsideDiagnosticError, match="matching Bomb"):
        build_downside_stress_diagnostic(*inputs(bomb=False, opinion="adverse"))

    result = build_downside_stress_diagnostic(*inputs(bomb=True, opinion="adverse"))
    assert result.bomb_candidate.event_type == "formal_adverse_opinion"

    values = list(inputs(bomb=True, opinion="adverse"))
    values[0].bomb_event.authoritative = False
    with pytest.raises(
        DownsideDiagnosticError, match="authoritative, material and current"
    ):
        build_downside_stress_diagnostic(*values)

    values = list(inputs(bomb=True, opinion="unmodified"))
    values[0].bomb_event.event_type = "formal_disclaimer"
    with pytest.raises(DownsideDiagnosticError, match="conflicts with T07"):
        build_downside_stress_diagnostic(*values)


def test_blocked_or_incomplete_assumptions_fail_closed() -> None:
    values = list(inputs())
    values[0].status = "blocked"
    with pytest.raises(DownsideDiagnosticError, match="not ready"):
        build_downside_stress_diagnostic(*values)

    values = list(inputs())
    values[0].constructs[0].evidence_ids = ()
    with pytest.raises(DownsideDiagnosticError, match="constructs"):
        build_downside_stress_diagnostic(*values)

    values = list(inputs())
    values[0].stress_assumptions = values[0].stress_assumptions[:2]
    with pytest.raises(DownsideDiagnosticError, match="stress pack"):
        build_downside_stress_diagnostic(*values)


def test_issuer_schema_and_coverage_conflicts_fail_closed() -> None:
    values = list(inputs())
    values[6].issuer_id = "issuer-2"
    with pytest.raises(DownsideDiagnosticError, match="issuer"):
        build_downside_stress_diagnostic(*values)

    values = list(inputs())
    values[5].schema_version = "PeerOutlookEvidence.v2"
    with pytest.raises(DownsideDiagnosticError, match="producer schema"):
        build_downside_stress_diagnostic(*values)

    values = list(inputs())
    values[7].coverage = Decimal("1.1")
    with pytest.raises(DownsideDiagnosticError, match="coverage"):
        build_downside_stress_diagnostic(*values)


def test_closed_schema_accepts_output() -> None:
    result = build_downside_stress_diagnostic(*inputs())
    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/downside/diagnostic/contracts/DownsideStressDiagnostic.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(result), default=float))
    validator.validate(payload)
    assert next(validator.iter_errors(payload | {"stars": 5})).validator == (
        "additionalProperties"
    )
