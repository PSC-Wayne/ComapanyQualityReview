import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from company_quality.downside.assumptions import (
    DownsideAssumptionError,
    build_downside_assumption_bundle,
)
from company_quality.pit import AdmittedFactSet, FactAdmission


SHA = "a" * 40


def fact(fact_id, fact_type, value, *, source_id="official-risk", disposition="admitted"):
    return FactAdmission(
        fact_id=fact_id,
        fact_type=fact_type,
        value=value,
        unit=None,
        effective_at="2026-03-03T12:00:00+08:00",
        announced_at=None,
        available_at="2026-03-03T13:00:00+08:00",
        retrieved_at="2026-03-03T14:00:00+08:00",
        valid_from="2026-03-03T13:00:00+08:00",
        valid_to=None,
        authority_rank=1,
        append_sequence=1,
        version_id="v1",
        source_id=source_id if disposition == "admitted" else None,
        disposition=disposition,
        failure_reason=None if disposition == "admitted" else "same_rank_conflict",
        admission_coverage=1.0 if disposition == "admitted" else 0.0,
    )


def facts(*, bomb=False):
    rows = [
        fact("evidence-risk", "downside.evidence", {"claim": "demand shock"}),
        fact("assumption-bear", "downside.evidence", {"claim": "bear"}),
        fact("assumption-base", "downside.evidence", {"claim": "base"}),
        fact("assumption-bull", "downside.evidence", {"claim": "bull"}),
    ]
    for name, raw in (
        ("maximum_drawdown_vulnerability", "0.4"),
        ("permanent_capital_loss_vulnerability", "0.2"),
        ("material_adverse_event_vulnerability", "0.3"),
    ):
        rows.append(
            fact(
                f"construct-{name}",
                f"downside.construct.{name}",
                {"raw_value": raw, "evidence_ids": ["evidence-risk"]},
            )
        )
    rows.append(
        fact(
            "risk-1",
            "downside.risk_item",
            {
                "cause": "customer demand contraction",
                "exposure": "concentrated revenue",
                "transmission_path": "lower utilisation reduces margin and cash flow",
                "buffer": "net cash",
                "indicator": "monthly revenue growth",
                "severity": "high",
                "trigger": "three consecutive negative months",
                "threshold": "-0.15",
                "evidence_id": "evidence-risk",
            },
        )
    )
    for scenario, change, liquidity in (
        ("bear", "-40", "tight"),
        ("base", "5", "adequate"),
        ("bull", "30", "adequate"),
    ):
        rows.append(
            fact(
                f"stress-{scenario}",
                f"downside.stress.{scenario}",
                {
                    "assumption_ids": [f"assumption-{scenario}"],
                    "equity_value_change_pct": change,
                    "liquidity_state": liquidity,
                },
            )
        )
    if bomb:
        rows.append(fact("bomb-evidence", "downside.evidence", {"claim": "default"}))
        rows.append(
            fact(
                "bomb-fact",
                "downside.bomb_event",
                {
                    "event_id": "event-default-1",
                    "event_type": "default",
                    "authoritative": True,
                    "material": True,
                    "current_relevance": True,
                    "authority_source_id": "official-risk",
                    "effective_at": "2026-02-01T00:00:00+08:00",
                    "expires_at": None,
                    "evidence_ids": ["bomb-evidence"],
                },
            )
        )
    return rows


def bundle(rows=None):
    admitted = AdmittedFactSet(
        decision_time="2026-03-03T23:00:00+08:00",
        facts=tuple(facts() if rows is None else rows),
    )
    return build_downside_assumption_bundle(
        admitted, generation_id="generation-18a", producer_candidate_sha=SHA
    )


def test_ready_bundle_governs_complete_explicit_assumptions() -> None:
    result = bundle()

    assert result.status == "ready"
    assert len(result.constructs) == 3
    assert all(item.state == "present" for item in result.constructs)
    assert result.constructs[0].raw_value is not None
    assert len(result.risk_items) == 1
    assert [item.scenario for item in result.stress_assumptions] == [
        "bear", "base", "bull"
    ]
    assert result.bomb_event is None
    assert result.coverage == Decimal("1")
    assert result.publication_status == "NON_PUBLISHABLE_CANDIDATE"


def test_missing_stress_blocks_bundle_without_inventing_replacement() -> None:
    rows = [item for item in facts() if item.fact_type != "downside.stress.bear"]
    result = bundle(rows)

    assert result.status == "blocked"
    assert len(result.stress_assumptions) == 2
    assert result.missing_reasons["stress.bear"] == "missing_explicit_pit_assumption"
    assert result.coverage < 1


def test_incomplete_risk_item_is_excluded_with_reason() -> None:
    rows = facts()
    rows.append(
        fact(
            "risk-incomplete",
            "downside.risk_item",
            {"cause": "unknown", "evidence_id": "evidence-risk"},
        )
    )
    result = bundle(rows)

    assert [item.fact_id for item in result.risk_items] == ["risk-1"]
    assert result.missing_reasons["risk.risk-incomplete"] == (
        "incomplete_or_invalid_causal_chain"
    )


def test_governed_bomb_event_preserves_authority_and_time() -> None:
    result = bundle(facts(bomb=True))

    assert result.bomb_event.event_type == "default"
    assert result.bomb_event.authoritative is True
    assert result.bomb_event.authority_source_id == "official-risk"
    assert result.bomb_event.evidence_ids == ("bomb-evidence",)


def test_unbound_stress_reference_and_authority_mismatch_fail_closed() -> None:
    rows = facts()
    bear = next(item for item in rows if item.fact_type == "downside.stress.bear")
    rows[rows.index(bear)] = fact(
        bear.fact_id,
        bear.fact_type,
        {
            "assumption_ids": ["unknown-assumption"],
            "equity_value_change_pct": "-40",
            "liquidity_state": "tight",
        },
    )
    with pytest.raises(DownsideAssumptionError, match="unbound bear"):
        bundle(rows)

    rows = facts(bomb=True)
    bomb = next(item for item in rows if item.fact_type == "downside.bomb_event")
    rows[rows.index(bomb)] = fact(
        bomb.fact_id,
        bomb.fact_type,
        {**bomb.value, "authority_source_id": "other-source"},
    )
    with pytest.raises(DownsideAssumptionError, match="authority source"):
        bundle(rows)


def test_conflicted_construct_does_not_fall_back() -> None:
    rows = facts()
    rows.append(
        fact(
            "construct-conflict",
            "downside.construct.maximum_drawdown_vulnerability",
            None,
            disposition="blocked_conflict",
        )
    )
    with pytest.raises(DownsideAssumptionError, match="unresolved conflict"):
        bundle(rows)


def test_closed_schema_accepts_ready_and_blocked_outputs() -> None:
    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/downside/assumptions/contracts/DownsideAssumptionBundle.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for result in (bundle(), bundle([])):
        payload = json.loads(json.dumps(asdict(result), default=float))
        validator.validate(payload)
    payload = json.loads(json.dumps(asdict(bundle()), default=float))
    assert next(validator.iter_errors(payload | {"bomb": True})).validator == (
        "additionalProperties"
    )
