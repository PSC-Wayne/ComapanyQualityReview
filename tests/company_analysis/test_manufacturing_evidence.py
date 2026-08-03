from __future__ import annotations

from hashlib import sha256

import pytest

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.manufacturing import (
    ManufacturingEvidenceFact,
    build_manufacturing_assessment,
)


ROW_FACTS = {
    "I-MFG-01": (
        "capacity", "utilization", "yield", "depreciation_burden",
    ),
    "I-MFG-02": (
        "raw_materials", "work_in_process", "finished_goods", "inventory_aging",
        "inventory_write_down", "subsequent_sales_realization",
    ),
    "I-MFG-03": (
        "signed_purchase_commitment", "long_term_term", "non_cancellable_term",
        "prepayment", "cancellation_term", "demand_support",
    ),
    "I-MFG-04": ("end_application_distribution", "customer_substitution"),
    "I-MFG-05": (
        "customer_certification", "design_win", "mass_production", "mass_production_revenue",
    ),
    "I-MFG-06": (
        "fx_revenue_impact", "fx_gross_margin_impact", "fx_non_operating_impact",
        "fx_currency", "fx_exposure", "fx_hedge",
    ),
}


def _citation(evidence_id: str, excerpt: str, period: str) -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=evidence_id.split(":", 1)[0],
        source_tier="official" if evidence_id.startswith("note:") else "issuer_primary",
        url=f"https://issuer.example/{evidence_id.replace(':', '-')}.json",
        content_sha256=sha256(excerpt.encode()).hexdigest(),
        period=period,
        available_at="2026-03-31T18:00:00+08:00",
        page=None,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="json",
        locator=f"fact:{evidence_id}",
    )


def _fact(
    fact_type: str,
    *,
    index: int,
    signal: str = "counterevidence",
    period: str = "2025Q4",
    scope: str = "consolidated:fab-1",
    role: str = "substantive",
    evidence_id: str | None = None,
) -> ManufacturingEvidenceFact:
    evidence_id = evidence_id or f"note:{fact_type}:{index}"
    return ManufacturingEvidenceFact(
        fact_type=fact_type,  # type: ignore[arg-type]
        value=f"{fact_type}=已揭露",
        period=period,
        scope=scope,
        signal=signal,  # type: ignore[arg-type]
        evidence_role=role,  # type: ignore[arg-type]
        citation=_citation(evidence_id, f"{period} {scope} {fact_type} 已揭露。", period),
    )


def _complete_facts(check_id: str) -> tuple[ManufacturingEvidenceFact, ...]:
    facts = [
        _fact(fact_type, index=index, evidence_id=f"note:{fact_type}:{index}")
        for index, fact_type in enumerate(ROW_FACTS[check_id])
    ]
    # Rows requiring a trend need two comparable periods.  Use an independent IR source,
    # so one note can never complete a manufacturing row.
    if check_id in {"I-MFG-01", "I-MFG-02", "I-MFG-06"}:
        facts.extend(
            _fact(
                fact_type,
                index=100 + index,
                period="2024Q4",
                evidence_id=f"ir:{fact_type}:{index}",
            )
            for index, fact_type in enumerate(ROW_FACTS[check_id])
        )
    else:
        facts[-1] = _fact(
            ROW_FACTS[check_id][-1],
            index=99,
            evidence_id=f"ir:{ROW_FACTS[check_id][-1]}:99",
        )
    return tuple(facts)


@pytest.mark.parametrize("check_id", tuple(ROW_FACTS))
def test_complete_domain_evidence_evaluates_each_manufacturing_row(check_id: str) -> None:
    assessment = build_manufacturing_assessment(_complete_facts(check_id))

    row = assessment.check(check_id)
    assert (row.status, row.applicability) == ("evaluated", "not_triggered")
    assert len(row.evidence_ids) >= 2
    assert row.counterevidence
    assert row.unresolved_reasons == ()


@pytest.mark.parametrize("check_id", tuple(ROW_FACTS))
def test_partial_official_evidence_is_retained_while_row_stays_unresolved(check_id: str) -> None:
    partial = _fact(ROW_FACTS[check_id][0], index=1, signal="risk")

    row = build_manufacturing_assessment((partial,)).check(check_id)

    assert (row.status, row.applicability) == ("unresolved", "triggered")
    assert row.evidence_ids == (partial.citation.evidence_id,)
    assert row.observations == (partial.value,)
    assert "尚缺" in row.unresolved_reasons[0]


@pytest.mark.parametrize("check_id", tuple(ROW_FACTS))
def test_absent_evidence_is_unresolved_not_no_risk(check_id: str) -> None:
    row = build_manufacturing_assessment(()).check(check_id)

    assert (row.status, row.applicability) == ("unresolved", "unresolved")
    assert row.evidence_ids == ()
    assert "未取得" in row.unresolved_reasons[0]


def test_headings_esg_metrics_current_feed_absence_and_single_note_cannot_complete() -> None:
    facts = tuple(
        _fact(
            fact_type,
            index=index,
            role="context",
            evidence_id=f"esg:{fact_type}:{index}",
        )
        for index, fact_type in enumerate(ROW_FACTS["I-MFG-03"])
    ) + tuple(
        _fact(
            fact_type,
            index=20 + index,
            evidence_id="note:commitments:one-note",
        )
        for index, fact_type in enumerate(ROW_FACTS["I-MFG-03"])
    )

    row = build_manufacturing_assessment(facts).check("I-MFG-03")

    assert row.status == "unresolved"
    assert "note:commitments:one-note" in row.evidence_ids
    assert any("單一來源文件" in reason for reason in row.unresolved_reasons)


def test_risk_and_counterevidence_are_kept_separate_when_domain_is_complete() -> None:
    facts = list(_complete_facts("I-MFG-05"))
    facts[0] = _fact("customer_certification", index=1, signal="risk")

    row = build_manufacturing_assessment(facts).check("I-MFG-05")

    assert (row.status, row.applicability) == ("evaluated", "triggered")
    assert row.supporting_evidence
    assert row.counterevidence
