import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from company_quality.audit.high_risk_notes import (
    CATEGORIES,
    Coordinate,
    HighRiskNoteError,
    NoteObservation,
    build_high_risk_note_register,
)
from company_quality.audit.inventory import AuditFilingInventory
from company_quality.facts.financial import CanonicalFinancialFact, CanonicalFinancialFacts


def financial_facts() -> CanonicalFinancialFacts:
    fact = CanonicalFinancialFact(
        fact_id="fact-receivable",
        concept_id="balance.accounts_receivable_net",
        value=Decimal("1000"),
        unit="TWD_thousands",
        period_start=None,
        period_end="2026-03-31",
        source_artifact_id="balance-artifact",
        source_artifact_sha256="a" * 64,
        source_table_index=0,
        source_row_index=1,
        source_column_index=1,
        source_label="應收帳款淨額",
        source_value="1,000",
        available_at="2026-05-15T14:43:02+08:00",
        lineage_hash="b" * 64,
        conflict_state="clear",
        failure_reason=None,
    )
    return CanonicalFinancialFacts(
        status="available",
        facts=(fact,),
        missing_concepts=(),
        fact_coverage=Decimal("1"),
    )


def audit_inventory(tmp_path: Path, *, with_pdf: bool = True) -> AuditFilingInventory:
    pdf = b"%PDF-1.7 frozen official fixture"
    digest = hashlib.sha256(pdf).hexdigest()
    path = tmp_path / "report.pdf"
    if with_pdf:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf)
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
        opinion_type="unmodified" if with_pdf else None,
        auditor_firm="勤業眾信聯合會計師事務所",
        auditors=("吳世宗", "陳彥君"),
        corrected=False,
        announcement_url="https://mops.twse.com.tw/mops/api/t163sb01",
        announcement_sha256="c" * 64,
        receipt_url="https://doc.twse.com.tw/server-java/t57sb01",
        receipt_sha256="d" * 64,
        pdf_filename="report.pdf",
        pdf_source_url="https://doc.twse.com.tw/pdf/report.pdf" if with_pdf else None,
        pdf_sha256=digest if with_pdf else None,
        pdf_path=path if with_pdf else None,
        retrieved_at="2026-07-24T10:30:00+08:00",
        available_at="2026-05-15T14:43:02+08:00",
        evidence_ids=("pdf:" + digest,) if with_pdf else ("receipt:" + "d" * 64,),
        mandatory_evidence_gaps=() if with_pdf else ("mandatory_audit_evidence_missing",),
        coverage=Decimal("1") if with_pdf else Decimal(2) / Decimal(3),
    )


def coordinate() -> Coordinate:
    return Coordinate(
        x0=Decimal("0.10"), y0=Decimal("0.20"),
        x1=Decimal("0.90"), y1=Decimal("0.30"),
    )


def observations(inventory: AuditFilingInventory) -> tuple[NoteObservation, ...]:
    evidence = inventory.evidence_ids[0]
    return (
        NoteObservation(
            category="related_parties",
            state="present",
            reason="official note discloses related-party transactions",
            amount=Decimal("100"),
            unit="TWD_thousands",
            period="115Q1",
            evidence_id=evidence,
            page=42,
            coordinate=coordinate(),
            materiality=Decimal("0.10"),
        ),
        NoteObservation(
            category="guarantees",
            state="not_applicable",
            reason="official note explicitly states no guarantees",
            amount=None,
            unit=None,
            period="115Q1",
            evidence_id=evidence,
            page=58,
            coordinate=coordinate(),
            materiality=None,
        ),
    )


def test_builds_exact_nine_category_register_with_explicit_missing() -> None:
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        audit = audit_inventory(Path(directory))
        result = build_high_risk_note_register(
            financial_facts(), audit, observations(audit)
        )

    assert tuple(item.category for item in result.items) == CATEGORIES
    assert len(result.items) == 9
    assert result.items[0].state == "present"
    assert result.items[1].state == "not_applicable"
    assert all(item.state == "missing" for item in result.items[2:])
    assert result.categories_covered == ("related_parties", "guarantees")
    assert result.missing_categories == CATEGORIES[2:]
    assert result.coverage == Decimal(2) / Decimal(9)
    assert result.available_at == audit.available_at
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"


def test_no_pdf_produces_missing_not_not_applicable(tmp_path) -> None:
    result = build_high_risk_note_register(
        financial_facts(), audit_inventory(tmp_path, with_pdf=False), ()
    )
    assert result.coverage == 0
    assert result.categories_covered == ()
    assert result.missing_categories == CATEGORIES
    assert all(item.state == "missing" for item in result.items)


def test_observation_requires_verified_pdf(tmp_path) -> None:
    audit = audit_inventory(tmp_path, with_pdf=False)
    fabricated = replace(
        observations(audit_inventory(tmp_path / "other"))[0],
        evidence_id=audit.evidence_ids[0],
    )
    with pytest.raises(HighRiskNoteError, match="PDF evidence"):
        build_high_risk_note_register(financial_facts(), audit, (fabricated,))


def test_pdf_hash_mismatch_blocks(tmp_path) -> None:
    audit = audit_inventory(tmp_path)
    assert audit.pdf_path is not None
    audit.pdf_path.write_bytes(b"changed")
    with pytest.raises(HighRiskNoteError, match="hash mismatch"):
        build_high_risk_note_register(financial_facts(), audit, observations(audit))


def test_duplicate_category_is_rejected(tmp_path) -> None:
    audit = audit_inventory(tmp_path)
    duplicate = observations(audit)[0]
    with pytest.raises(HighRiskNoteError, match="duplicate"):
        build_high_risk_note_register(
            financial_facts(), audit, (duplicate, duplicate)
        )


def test_invalid_coordinate_is_rejected(tmp_path) -> None:
    audit = audit_inventory(tmp_path)
    invalid = replace(
        observations(audit)[0],
        coordinate=replace(coordinate(), x1=Decimal("1.1")),
    )
    with pytest.raises(HighRiskNoteError, match="coordinate"):
        build_high_risk_note_register(financial_facts(), audit, (invalid,))


def test_not_applicable_requires_explicit_page_evidence(tmp_path) -> None:
    audit = audit_inventory(tmp_path)
    invalid = replace(observations(audit)[1], evidence_id=None, page=None, coordinate=None)
    with pytest.raises(HighRiskNoteError, match="evidence"):
        build_high_risk_note_register(financial_facts(), audit, (invalid,))


def test_amount_and_unit_must_be_paired(tmp_path) -> None:
    audit = audit_inventory(tmp_path)
    invalid = replace(observations(audit)[0], unit=None)
    with pytest.raises(HighRiskNoteError, match="amount and unit"):
        build_high_risk_note_register(financial_facts(), audit, (invalid,))


def test_period_or_producer_schema_mismatch_blocks(tmp_path) -> None:
    audit = audit_inventory(tmp_path)
    wrong_period = replace(observations(audit)[0], period="114Q4")
    with pytest.raises(HighRiskNoteError, match="period"):
        build_high_risk_note_register(financial_facts(), audit, (wrong_period,))
    with pytest.raises(HighRiskNoteError, match="CanonicalFinancialFacts.v1"):
        build_high_risk_note_register(
            replace(financial_facts(), schema_version="CanonicalFinancialFacts.v2"),
            audit,
            (),
        )


def test_json_schema_declares_closed_contract() -> None:
    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/audit/high_risk_notes/contracts/HighRiskNoteRegister.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "HighRiskNoteRegister.v1"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["items"]["minItems"] == 9
    assert schema["properties"]["items"]["maxItems"] == 9
    assert "available_at" in schema["required"]
    declared = tuple(
        entry["allOf"][1]["properties"]["category"]["const"]
        for entry in schema["properties"]["items"]["prefixItems"]
    )
    assert declared == CATEGORIES
