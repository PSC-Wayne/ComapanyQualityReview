import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from company_quality.audit.reliability import (
    AuditReliabilityError,
    build_audit_reliability_candidate,
)


def inputs(
    *, triggered=False, late=False, corrected=False, restatement=False
) -> tuple[Any, Any, Any]:
    inventory = SimpleNamespace(
        schema_version="AuditFilingInventory.v1",
        opinion_type="unmodified",
        period="2025Q4",
        corrected=corrected,
        official_filed_at=(
            "2026-04-01T12:00:00+08:00"
            if late
            else "2026-03-01T12:00:00+08:00"
        ),
        statutory_due_at="2026-03-31T23:59:59+08:00",
        available_at="2026-03-02T00:00:00+08:00",
        evidence_ids=("audit-receipt", "audit-pdf"),
        mandatory_evidence_gaps=(),
        coverage=Decimal("0.8"),
    )
    gate = SimpleNamespace(
        schema_version="AuditGateDecision.v1",
        source_version="AuditFilingInventory.v1",
        opinion_type="unmodified",
        restatement=restatement,
        reasons=("going_concern_material_uncertainty",) if triggered else (
            "no_audit_hard_gate_triggered",
        ),
        evidence_ids=("audit-receipt", "audit-pdf", "gate-extra"),
        available_at="2026-03-03T00:00:00+08:00",
        coverage=Decimal("0.9"),
    )
    notes = SimpleNamespace(
        schema_version="HighRiskNoteRegister.v1",
        source_version="CanonicalFinancialFacts.v1+AuditFilingInventory.v1",
        items=(
            SimpleNamespace(period="2025Q4", evidence_id="note-1"),
            SimpleNamespace(period="2025Q4", evidence_id=None),
        ),
        available_at="2026-03-04T00:00:00+08:00",
        coverage=Decimal("0.6"),
    )
    return inventory, gate, notes


def test_outputs_unscored_conservative_diagnostics() -> None:
    result = build_audit_reliability_candidate(*inputs())

    assert result.ordinary_score is None
    assert result.ordinary_weight == Decimal("0.10")
    assert result.completeness == Decimal("0.6")
    assert result.timeliness == Decimal("1")
    assert result.consistency == Decimal("1")
    assert result.coverage == Decimal("0.6")
    assert result.available_at == "2026-03-04T00:00:00+08:00"
    assert result.reasons["ordinary_score"] == "calibration_pending_t23"
    assert result.metric_lineage["ordinary_score"] == ()


def test_late_and_corrected_are_diagnostics_not_a_score() -> None:
    result = build_audit_reliability_candidate(
        *inputs(late=True, corrected=True)
    )

    assert result.timeliness == 0
    assert result.consistency == 0
    assert result.ordinary_score is None
    assert result.reasons["timeliness"] == "official_filing_after_statutory_due_at"
    assert result.reasons["consistency"] == "correction_or_restatement_present"


def test_restatement_alone_makes_consistency_zero() -> None:
    result = build_audit_reliability_candidate(*inputs(restatement=True))
    assert result.consistency == 0
    assert result.ordinary_score is None


def test_t07_trigger_evidence_is_conservatively_excluded() -> None:
    result = build_audit_reliability_candidate(*inputs(triggered=True))

    assert result.hard_gate_excluded_evidence_ids == (
        "audit-receipt",
        "audit-pdf",
        "gate-extra",
    )
    assert result.reasons["hard_gate_exclusion"] == (
        "t07_trigger_evidence_excluded_from_ordinary_score"
    )


def test_clear_gate_excludes_nothing() -> None:
    result = build_audit_reliability_candidate(*inputs())
    assert result.hard_gate_excluded_evidence_ids == ()


def test_contract_mismatch_and_cross_artifact_conflict_fail_closed() -> None:
    inventory, gate, notes = inputs()
    gate.schema_version = "AuditGateDecision.v2"
    with pytest.raises(AuditReliabilityError, match="BLOCKED_CONTRACT"):
        build_audit_reliability_candidate(inventory, gate, notes)

    inventory, gate, notes = inputs()
    gate.opinion_type = "qualified"
    with pytest.raises(AuditReliabilityError, match="opinion"):
        build_audit_reliability_candidate(inventory, gate, notes)

    inventory, gate, notes = inputs()
    notes.items = (SimpleNamespace(period="2024Q4", evidence_id="note-old"),)
    with pytest.raises(AuditReliabilityError, match="period"):
        build_audit_reliability_candidate(inventory, gate, notes)

    with pytest.raises(AuditReliabilityError, match="BLOCKED_CONTRACT"):
        build_audit_reliability_candidate(None, gate, notes)


def test_schema_is_closed_and_accepts_output() -> None:
    result = build_audit_reliability_candidate(*inputs(triggered=True))
    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/audit/reliability/contracts/"
        "Pillar1AuditReliabilityCandidate.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(result), default=float))
    validator.validate(payload)
    assert next(validator.iter_errors(payload | {"stars": 5})).validator == (
        "additionalProperties"
    )
