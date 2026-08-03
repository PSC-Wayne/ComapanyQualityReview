from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from company_quality.company_analysis.checklist_analysis import (
    _apply_financial_institution_assessment,
    _placeholder_checks,
)
from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.financial_institutions import (
    FinancialInstitutionFact,
    FinancialSubtypeRouteClaim,
    build_financial_institution_assessment,
)
from company_quality.identity import CompanyIdentity

AS_OF = "2026-03-31T23:59:59+08:00"
ISSUER = "12345678"
SECURITY_CODE = "2899"

ROUTE_PARTS = {
    "bank": ("regulated_license", "deposit_taking", "lending"),
    "life_insurer": ("regulated_license", "life_insurance_underwriting", "long_term_policy_obligations"),
    "property_insurer": ("regulated_license", "property_casualty_underwriting", "claims_obligations"),
    "securities_firm": ("regulated_license", "securities_brokerage_dealing", "securities_regulatory_capital"),
}
ROW_FACTS = {
    "bank": ("I-FIN-01", ("net_interest_margin", "nonperforming_loan_ratio", "common_equity_tier1_ratio")),
    "life_insurer": ("I-FIN-02", ("contractual_service_margin", "solvency_ratio", "insurance_contract_reserve", "asset_liability_mismatch")),
    "property_insurer": ("I-FIN-03", ("combined_ratio", "loss_ratio", "insurance_contract_reserve")),
    "securities_firm": ("I-FIN-04", ("brokerage_revenue", "trading_income", "capital_adequacy_ratio")),
}


def _identity(*, name: str = "測試控股股份有限公司", industry_code: str = "17") -> CompanyIdentity:
    return CompanyIdentity(
        security_id=f"TWSE:{SECURITY_CODE}",
        security_code=SECURITY_CODE,
        issuer_id=ISSUER,
        company_name=name,
        short_name=name[:2],
        market="TWSE",
        valid_from="2020-01-01T00:00:00+08:00",
        industry_code=industry_code,
    )


def _citation(evidence_id: str, excerpt: str, *, period: str = "2025Q4", available_at: str = "2026-03-31T18:00:00+08:00") -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=evidence_id.split(":", 1)[0],
        source_tier="official",
        url=f"https://regulator.example/{evidence_id.replace(':', '-')}",
        content_sha256=sha256(excerpt.encode()).hexdigest(),
        period=period,
        available_at=available_at,
        page=12,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="pdf",
        locator=f"page:12:{evidence_id}",
    )


def _route_claims(subtype: str, *, available_at: str = "2026-03-31T18:00:00+08:00") -> tuple[FinancialSubtypeRouteClaim, ...]:
    return tuple(
        FinancialSubtypeRouteClaim(
            issuer_id=ISSUER,
            security_code=SECURITY_CODE,
            financial_subtype=subtype,  # type: ignore[arg-type]
            claim_part=part,  # type: ignore[arg-type]
            value=f"主管機關及公司揭露：{part}",
            period="2025Q4",
            citation=_citation(f"route:{subtype}:{index}", part, available_at=available_at),
        )
        for index, part in enumerate(ROUTE_PARTS[subtype])
    )


def _fact(fact_type: str, index: int, *, signal: str = "counterevidence", available_at: str = "2026-03-31T18:00:00+08:00") -> FinancialInstitutionFact:
    return FinancialInstitutionFact(
        issuer_id=ISSUER,
        security_code=SECURITY_CODE,
        fact_type=fact_type,  # type: ignore[arg-type]
        value=f"issuer disclosed {fact_type}={index}",
        definition=f"issuer/regulator definition of {fact_type}",
        period="2025Q4",
        scope="consolidated:regulated-business",
        signal=signal,  # type: ignore[arg-type]
        evidence_role="substantive",
        citation=_citation(f"fact:{fact_type}:{index}", f"{fact_type}={index}", available_at=available_at),
    )


@pytest.mark.parametrize("subtype", tuple(ROW_FACTS))
def test_routes_and_evaluates_only_exact_subtype_semantics(subtype: str) -> None:
    check_id, fact_types = ROW_FACTS[subtype]
    facts = tuple(_fact(item, index, signal="risk" if index == 0 else "counterevidence") for index, item in enumerate(fact_types))

    assessment = build_financial_institution_assessment(
        identity=_identity(), route_claims=_route_claims(subtype), facts=facts, as_of=AS_OF
    )

    assert assessment.route_status == "routed"
    assert assessment.financial_subtype == subtype
    assert assessment.company_route == subtype
    assert assessment.issuer_id == ISSUER
    assert assessment.as_of == AS_OF
    assert assessment.check(check_id).status == "evaluated"
    assert assessment.check(check_id).financial_period == "2025Q4"
    assert assessment.check(check_id).supporting_evidence
    assert assessment.check(check_id).counterevidence
    for other_id, _ in (item for key, item in ROW_FACTS.items() if key != subtype):
        other = assessment.check(other_id)
        assert (other.status, other.applicability) == ("evaluated", "not_applicable")
        assert other.evidence_ids == ()


@pytest.mark.parametrize("subtype", tuple(ROW_FACTS))
def test_partial_subtype_fact_set_preserves_evidence_and_stays_unresolved(subtype: str) -> None:
    check_id, fact_types = ROW_FACTS[subtype]
    partial = _fact(fact_types[0], 0, signal="risk")

    row = build_financial_institution_assessment(
        identity=_identity(), route_claims=_route_claims(subtype), facts=(partial,), as_of=AS_OF
    ).check(check_id)

    assert (row.status, row.applicability) == ("unresolved", "triggered")
    assert row.evidence_ids == (partial.citation.evidence_id,)
    assert "尚缺" in row.unresolved_reasons[0]


def test_broad_financial_identity_or_conflicting_subtypes_remain_blocked() -> None:
    broad_only = build_financial_institution_assessment(
        identity=_identity(), route_claims=(), facts=(), as_of=AS_OF
    )
    conflict = build_financial_institution_assessment(
        identity=_identity(),
        route_claims=(*_route_claims("bank"), *_route_claims("life_insurer")),
        facts=(),
        as_of=AS_OF,
    )

    assert broad_only.route_status == "blocked"
    assert broad_only.company_route == "financial_institution_unrouted"
    assert conflict.route_status == "blocked"
    assert "conflicting" in conflict.route_unresolved_reasons[0]


def test_company_name_never_routes_and_nonfinancial_identity_is_not_applicable() -> None:
    named_like_bank = build_financial_institution_assessment(
        identity=_identity(name="超級銀行人壽產險證券股份有限公司"),
        route_claims=(), facts=(), as_of=AS_OF,
    )
    nonfinancial = build_financial_institution_assessment(
        identity=_identity(industry_code="24"),
        route_claims=_route_claims("bank"), facts=(), as_of=AS_OF,
    )

    assert named_like_bank.route_status == "blocked"
    assert nonfinancial.route_status == "not_applicable"


def test_point_in_time_excludes_future_route_and_metric_evidence() -> None:
    future_claims = tuple(
        replace(item, citation=replace(item.citation, available_at="2026-04-01T00:00:00+08:00"))
        for item in _route_claims("bank")
    )
    route = build_financial_institution_assessment(
        identity=_identity(), route_claims=future_claims, facts=(), as_of=AS_OF
    )
    future_fact = _fact("net_interest_margin", 0, available_at="2026-04-01T00:00:00+08:00")
    facts = tuple(_fact(item, index) for index, item in enumerate(ROW_FACTS["bank"][1][1:]))
    assessed = build_financial_institution_assessment(
        identity=_identity(), route_claims=_route_claims("bank"), facts=(future_fact, *facts), as_of=AS_OF
    )

    assert route.route_status == "blocked"
    assert set(route.excluded_post_as_of_evidence_ids) == {item.citation.evidence_id for item in future_claims}
    row = assessed.check("I-FIN-01")
    assert row.status == "unresolved"
    assert future_fact.citation.evidence_id not in row.evidence_ids
    assert future_fact.citation.evidence_id in assessed.excluded_post_as_of_evidence_ids


def test_checklist_overlay_replaces_only_financial_rows() -> None:
    assessment = build_financial_institution_assessment(
        identity=_identity(),
        route_claims=_route_claims("securities_firm"),
        facts=tuple(_fact(item, index) for index, item in enumerate(ROW_FACTS["securities_firm"][1])),
        as_of=AS_OF,
    )
    placeholders = _placeholder_checks("blocked", "financial")

    overlaid = _apply_financial_institution_assessment(placeholders, assessment)
    rows = {item.check_id: item for item in overlaid}

    assert rows["I-FIN-04"].status == "evaluated"
    assert rows["I-FIN-01"].applicability == "not_applicable"
    assert rows["G01"].status == "unresolved"
