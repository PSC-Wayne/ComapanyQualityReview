import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from company_quality.facts.financial import CanonicalFinancialFact, CanonicalFinancialFacts
from company_quality.governance.people_adaptability import (
    GovernancePeopleError,
    build_governance_people_candidate,
)
from company_quality.pit import AdmittedFactSet, FactAdmission


def fact(fact_id, fact_type, value, *, unit=None, effective="2026-01-01T00:00:00+08:00",
         available="2026-01-02T00:00:00+08:00", disposition="admitted"):
    return FactAdmission(
        fact_id=fact_id, fact_type=fact_type,
        value=value if disposition == "admitted" else None, unit=unit,
        effective_at=effective, announced_at=None, available_at=available,
        retrieved_at="2026-07-24T10:00:00+08:00",
        valid_from="2026-01-01T00:00:00+08:00", valid_to=None,
        authority_rank=0, append_sequence=0, version_id="v1", source_id="official",
        disposition=disposition,
        failure_reason=None if disposition == "admitted" else "not_yet_available",
        admission_coverage=1.0 if disposition == "admitted" else 0.0,
    )


def financials(*, revenue=Decimal("1000"), period="2025-12-31"):
    revenue_fact = CanonicalFinancialFact(
        fact_id="revenue-fact", concept_id="income.revenue", value=revenue,
        unit="TWD_thousands", period_start="2025-01-01", period_end=period,
        source_artifact_id="artifact", source_artifact_sha256="a" * 64,
        source_table_index=0, source_row_index=0, source_column_index=1,
        source_label="Revenue", source_value=str(revenue),
        available_at="2026-03-31T00:00:00+08:00", lineage_hash="b" * 64,
        conflict_state="clear", failure_reason=None,
    )
    return CanonicalFinancialFacts(
        status="available", facts=(revenue_fact,), missing_concepts=(),
        fact_coverage=Decimal("1"),
    )


def complete_facts():
    return (
        fact("board", "governance.board_independence_pct", "60"),
        fact("pledge", "governance.pledged_share_pct", "5"),
        fact("related", "governance.related_party_ratio", "3"),
        fact("alignment", "governance.incentive_alignment", "Long-term equity incentive disclosed"),
        fact("reg-complete", "governance.regulatory_history_complete", True),
        fact("reg-event", "governance.regulatory_event", "sanction", effective="2024-01-01T00:00:00+08:00"),
        fact("ceo", "people.key_person", {"role": "ceo", "tenure_years": "8"}),
        fact("succession", "succession.plan_disclosed", True),
        fact("dependency", "succession.key_person_dependency", "medium"),
        fact("rd", "adaptability.rd_expense", {"amount": "100", "period_end": "2025-12-31"}, unit="TWD_thousands"),
        fact("capability", "adaptability.capability_investment", "Advanced packaging capacity"),
        fact("commit", "management.commitment", {"commitment_id": "c1", "text": "Build capacity"}),
        fact("delivery", "management.delivery", {"commitment_id": "c1", "text": "Phase one completed"}),
    )


def admitted(facts=None):
    return AdmittedFactSet(
        decision_time="2026-07-24T12:00:00+08:00",
        facts=tuple(complete_facts() if facts is None else facts),
    )


def build(*, pit=None, finance=None):
    return build_governance_people_candidate(
        pit or admitted(), finance or financials(),
        generation_id="gen-001", producer_candidate_sha="c" * 40,
    )


def test_builds_governance_people_and_adaptability_candidate() -> None:
    result = build()
    assert result.governance_signals.board_independence_pct == Decimal("60")
    assert result.governance_signals.regulatory_events_5y == 1
    assert result.key_people[0].role == "ceo"
    assert result.succession.plan_disclosed is True
    assert result.succession.key_person_dependency == "medium"
    assert result.adaptability.rd_to_sales == Decimal("0.1")
    assert result.coverage == Decimal("1")
    assert result.candidate_score is None
    assert result.status == "NON_PUBLISHABLE_CANDIDATE"


def test_alignment_and_commitment_delivery_remain_separate_and_traceable() -> None:
    result = build()
    assert result.alignment_signals[0].evidence_id == "alignment"
    ledger = result.commitment_delivery_ledger[0]
    assert ledger.commitment_evidence_id == "commit"
    assert ledger.delivery_evidence_ids == ("delivery",)
    assert ledger.commitment != ledger.deliveries[0]


def test_missing_qualitative_facts_are_unknown_not_neutral() -> None:
    result = build(pit=admitted(()), finance=CanonicalFinancialFacts(
        status="partial", facts=(), missing_concepts=("income.revenue",),
        fact_coverage=Decimal("0"),
    ))
    assert result.governance_signals.board_independence_pct is None
    assert result.governance_signals.regulatory_events_5y is None
    assert result.succession.plan_disclosed is None
    assert result.succession.key_person_dependency == "unknown"
    assert result.adaptability.rd_to_sales is None
    assert result.available_at is None
    assert result.coverage == 0
    assert "missing" in result.unavailable_reasons["board_independence_pct"]


def test_regulatory_zero_requires_explicit_complete_history() -> None:
    complete = build(pit=admitted((fact("complete", "governance.regulatory_history_complete", True),)))
    assert complete.governance_signals.regulatory_events_5y == 0
    unknown = build(pit=admitted(()))
    assert unknown.governance_signals.regulatory_events_5y is None


def test_rd_requires_matching_period_unit_and_nonzero_revenue() -> None:
    rd = fact("rd", "adaptability.rd_expense", {"amount": "100", "period_end": "2025-12-31"}, unit="USD")
    mismatch = build(pit=admitted((rd,)))
    assert mismatch.adaptability.rd_to_sales is None
    assert mismatch.metric_lineage["adaptability.rd_to_sales"] == ()
    zero = build(pit=admitted((replace(rd, unit="TWD_thousands"),)), finance=financials(revenue=Decimal("0")))
    assert zero.adaptability.rd_to_sales is None


def test_blocked_and_invalid_claims_are_not_used() -> None:
    claims = (
        fact("blocked-board", "governance.board_independence_pct", "70", disposition="blocked_unavailable"),
        fact("bad-person", "people.key_person", {"role": "founder", "tenure_years": "8"}),
        fact("bad-align", "governance.incentive_alignment", ""),
    )
    result = build(pit=admitted(claims))
    assert result.governance_signals.board_independence_pct is None
    assert result.key_people == ()
    assert {item.evidence_id for item in result.excluded_claims} == {"bad-person", "bad-align"}


def test_same_type_latest_conflict_and_commitment_conflict_block() -> None:
    same_time = "2026-01-01T00:00:00+08:00"
    with pytest.raises(GovernancePeopleError, match="conflicting latest"):
        build(pit=admitted((
            fact("a", "governance.board_independence_pct", "50", effective=same_time),
            fact("b", "governance.board_independence_pct", "60", effective=same_time),
        )))
    with pytest.raises(GovernancePeopleError, match="commitments"):
        build(pit=admitted((
            fact("a", "management.commitment", {"commitment_id": "c1", "text": "A"}),
            fact("b", "management.commitment", {"commitment_id": "c1", "text": "B"}),
        )))


def test_producer_contracts_fail_closed() -> None:
    with pytest.raises(GovernancePeopleError, match="AdmittedFactSet.v1"):
        build(pit=replace(admitted(), schema_version="AdmittedFactSet.v2"))
    with pytest.raises(GovernancePeopleError, match="CanonicalFinancialFacts.v1"):
        build(finance=replace(financials(), schema_version="CanonicalFinancialFacts.v2"))


def test_closed_schema_validates_output() -> None:
    path = Path(__file__).parents[3] / "src/company_quality/governance/people_adaptability/contracts/GovernancePeopleCandidate.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    payload = json.loads(json.dumps(asdict(build()), default=float))
    Draft202012Validator(schema).validate(payload)
    assert schema["$id"] == "GovernancePeopleCandidate.v1"
    assert schema["additionalProperties"] is False
