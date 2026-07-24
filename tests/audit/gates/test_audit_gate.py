import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from company_quality.audit.gates import (
    AuditGatePolicy,
    AuditGatePolicyError,
    apply_ceiling,
    apply_floor,
    evaluate_audit_gate,
)
from company_quality.audit.inventory import AuditFilingInventory

FORMAL_EVIDENCE = ("pdf-page:formal-audit-report:1",)


def inventory(opinion="unmodified", *, coverage=Decimal("1"), gaps=()):
    return AuditFilingInventory(
        security_code="2330",
        issuer_id="22099131",
        market="TWSE",
        period="115Q1",
        filing_type="q1_review",
        issuer_type="domestic_general",
        industry_type="general",
        fiscal_period_start="2026-01-01",
        fiscal_period_end="2026-03-31",
        assurance_type="review",
        report_scope="consolidated",
        deadline_rule_id="securities-exchange-act-36",
        deadline_rule_version="2026-07-24.v1",
        ordinary_due_at="2026-05-15T23:59:59+08:00",
        holiday_adjustment_days=0,
        approved_extension_days=0,
        extension_rule_id=None,
        statutory_due_at="2026-05-15T23:59:59+08:00",
        holiday_calendar_version="weekends-only.v1",
        official_filed_at="2026-05-15T14:43:02+08:00",
        auditor_report_at=None,
        official_filed_at_source="official_filing_receipt",
        opinion_type=opinion,
        auditor_firm="勤業眾信聯合會計師事務所",
        auditors=("吳世宗", "陳彥君"),
        corrected=False,
        announcement_url="https://mops.twse.com.tw/mops/api/t163sb01",
        announcement_sha256="a" * 64,
        receipt_url="https://doc.twse.com.tw/server-java/t57sb01",
        receipt_sha256="b" * 64,
        pdf_filename="report.pdf",
        pdf_source_url="https://doc.twse.com.tw/pdf/report.pdf" if not gaps else None,
        pdf_sha256="c" * 64 if not gaps else None,
        pdf_path=Path("/tmp/report.pdf") if not gaps else None,
        retrieved_at="2026-07-24T10:30:00+08:00",
        available_at="2026-05-15T14:43:02+08:00",
        evidence_ids=("announcement:" + "a" * 64, "receipt:" + "b" * 64),
        mandatory_evidence_gaps=gaps,
        coverage=coverage,
    )


def policy():
    return AuditGatePolicy(
        version="audit-gate-policy.test.v1",
        adverse_quality_cap=25,
        qualified_quality_cap=60,
        severe_qualified_quality_cap=45,
        integrity_event_quality_cap=35,
    )


def test_unmodified_complete_evidence_is_clear() -> None:
    result = evaluate_audit_gate(inventory(), policy())

    assert result.gate_state == "clear"
    assert result.opinion_type == "unmodified"
    assert result.cap_value is None
    assert result.upside_star_cap is None
    assert result.floor_value is None
    assert result.no_rating_reason is None
    assert result.coverage == Decimal("1")
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"
    assert result.hard_gate_evidence_ids == ()


def test_missing_pdf_is_coverage_gap_not_formal_opinion_or_block() -> None:
    source = inventory(
        None,
        coverage=Decimal(2) / Decimal(3),
        gaps=("mandatory_audit_evidence_missing",),
    )
    result = evaluate_audit_gate(source, policy())

    assert result.gate_state == "clear"
    assert result.opinion_type is None
    assert result.no_rating_reason is None
    assert result.coverage == source.coverage
    assert "mandatory_audit_evidence_missing" in result.reasons


def test_disclaimer_is_no_rating_and_five_face_floor() -> None:
    result = evaluate_audit_gate(inventory("disclaimer"), policy())

    assert result.gate_state == "no_rating"
    assert result.no_rating_reason == "formal_disclaimer"
    assert result.cap_value is None
    assert result.upside_star_cap is None
    assert result.floor_value == 5


def test_adverse_uses_governed_cap_and_is_monotonic() -> None:
    result = evaluate_audit_gate(inventory("adverse"), policy())

    assert result.gate_state == "cap"
    assert result.cap_value == 25
    assert result.upside_star_cap == 1
    assert result.floor_value == 5
    assert apply_ceiling(20, result.cap_value) == 20
    assert apply_ceiling(80, result.cap_value) == 25
    assert apply_ceiling(None, result.cap_value) is None


def test_going_concern_has_fixed_cap_star_cap_and_floor() -> None:
    result = evaluate_audit_gate(
        inventory(), policy(), going_concern=True,
        additional_evidence_ids=FORMAL_EVIDENCE,
    )

    assert result.gate_state == "cap"
    assert result.cap_value == 40
    assert result.upside_star_cap == 2
    assert result.floor_value == 4
    assert result.hard_gate_evidence_ids == FORMAL_EVIDENCE


def test_combined_formal_flags_keep_the_strictest_values() -> None:
    result = evaluate_audit_gate(
        inventory("adverse"), policy(), going_concern=True, restatement=True,
        additional_evidence_ids=FORMAL_EVIDENCE,
    )

    assert result.cap_value == 25
    assert result.upside_star_cap == 1
    assert result.floor_value == 5
    assert result.restatement is True


def test_qualified_severity_is_policy_bound() -> None:
    ordinary = evaluate_audit_gate(
        inventory("qualified"), policy(), qualified_pervasive_or_core=False,
        additional_evidence_ids=FORMAL_EVIDENCE,
    )
    severe = evaluate_audit_gate(
        inventory("qualified"), policy(), qualified_pervasive_or_core=True,
        additional_evidence_ids=FORMAL_EVIDENCE,
    )

    assert ordinary.cap_value == 60
    assert severe.cap_value == 45
    assert severe.cap_value <= ordinary.cap_value
    assert ordinary.hard_gate_evidence_ids == inventory("qualified").evidence_ids


def test_unreliable_statements_produce_no_rating() -> None:
    result = evaluate_audit_gate(
        inventory(), policy(), restatement=True, statements_reliable=False,
        additional_evidence_ids=FORMAL_EVIDENCE,
    )

    assert result.gate_state == "no_rating"
    assert result.no_rating_reason == "authority_conflict"
    assert result.floor_value == 4


def test_first_occurrence_matters_are_negative_evidence_not_automatic_caps() -> None:
    result = evaluate_audit_gate(
        inventory(),
        policy(),
        key_audit_matter_first_occurrence=True,
        emphasis_matter_first_occurrence=True,
        auditor_change=True,
        additional_evidence_ids=FORMAL_EVIDENCE,
    )

    assert result.gate_state == "clear"
    assert result.cap_value is None
    assert result.floor_value is None
    assert "first_occurrence_key_audit_matter_negative_evidence" in result.reasons
    assert "first_occurrence_emphasis_matter_negative_evidence" in result.reasons
    assert "auditor_change_negative_evidence" in result.reasons
    assert result.hard_gate_evidence_ids == ()


def test_authority_conflict_blocks() -> None:
    result = evaluate_audit_gate(inventory(), policy(), authority_conflict=True)

    assert result.gate_state == "blocked"
    assert result.no_rating_reason == "authority_conflict"


def test_supplemental_formal_fact_without_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="evidence IDs"):
        evaluate_audit_gate(inventory(), policy(), going_concern=True)


def test_policy_rejects_uncalibrated_values() -> None:
    with pytest.raises(AuditGatePolicyError, match="adverse"):
        replace(policy(), adverse_quality_cap=31)
    with pytest.raises(AuditGatePolicyError, match="integrity"):
        replace(policy(), integrity_event_quality_cap=29)


def test_caps_and_floors_never_improve_existing_or_no_rating_values() -> None:
    assert apply_ceiling(0, 1) == 0
    assert apply_ceiling(1, 1) == 1
    assert apply_ceiling(None, 1) is None
    assert apply_floor(5, 4) == 5
    assert apply_floor(2, 4) == 4
    assert apply_floor(None, 4) is None


def test_json_schema_declares_contract_fields() -> None:
    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/audit/gates/contracts/AuditGateDecision.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    assert schema["$id"] == "AuditGateDecision.v1"
    assert set((
        "gate_state", "opinion_type", "going_concern", "restatement",
        "confirmed_fraud", "key_audit_matter_first_occurrence",
        "emphasis_matter_first_occurrence", "auditor_change",
        "cap_value", "upside_star_cap", "floor_value",
        "reasons", "evidence_ids", "hard_gate_evidence_ids",
        "available_at", "coverage",
        "no_rating_reason",
    )).issubset(schema["required"])
    assert schema["additionalProperties"] is False
