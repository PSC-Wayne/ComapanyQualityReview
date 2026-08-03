from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.history_context import (
    BusinessModelClaim,
    build_historical_context,
)
from company_quality.company_analysis.software_ai import (
    SoftwareAIEvidenceFact,
    build_software_ai_assessment,
    resolve_software_ai_route,
)
from company_quality.identity import CompanyIdentity

AS_OF = "2026-08-03T12:00:00+08:00"
ISSUER = "12345678"
URL = "https://issuer.example/annual-report.pdf"
ROW_FACTS = {
    "I-SW-01": ("recurring_revenue", "renewal", "churn", "arpu"),
    "I-SW-02": ("contract_liability", "deferred_revenue", "revenue_conversion"),
    "I-SW-03": ("contract_acquisition_cost", "development_cost_capitalization"),
    "I-SW-04": ("cloud_cost", "service_cost", "gross_margin"),
    "I-SW-05": ("share_based_payment_cost", "dilution"),
}


def _citation(evidence_id: str, excerpt: str, period: str, *, available_at: str = "2026-03-31T18:00:00+08:00") -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=evidence_id.split(":", 1)[0],
        source_tier="issuer_primary",
        url=URL,
        content_sha256=sha256(excerpt.encode()).hexdigest(),
        period=period,
        available_at=available_at,
        page=10,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="pdf",
        locator=None,
    )


def _fact(fact_type: str, *, period: str, signal: str = "counterevidence", available_at: str = "2026-03-31T18:00:00+08:00") -> SoftwareAIEvidenceFact:
    excerpt = f"{period} {fact_type} issuer disclosure"
    return SoftwareAIEvidenceFact(
        issuer_id=ISSUER,
        fact_type=fact_type,  # type: ignore[arg-type]
        value=f"{fact_type}=issuer disclosed",
        period=period,
        scope="consolidated:software-services",
        signal=signal,  # type: ignore[arg-type]
        evidence_role="substantive",
        citation=_citation(f"ir:{period}:{fact_type}", excerpt, period, available_at=available_at),
    )


def _complete_facts(check_id: str) -> tuple[SoftwareAIEvidenceFact, ...]:
    result = []
    for period in ("2024", "2025"):
        for index, fact_type in enumerate(ROW_FACTS[check_id]):
            result.append(_fact(fact_type, period=period, signal="risk" if index == 0 else "counterevidence"))
    return tuple(result)


@pytest.mark.parametrize("check_id", tuple(ROW_FACTS))
def test_claim_complete_evidence_evaluates_exact_software_rows(check_id: str) -> None:
    assessment = build_software_ai_assessment(
        issuer_id=ISSUER, as_of=AS_OF, facts=_complete_facts(check_id)
    )

    row = assessment.check(check_id)
    assert (row.status, row.applicability) == ("evaluated", "triggered")
    assert row.supporting_evidence
    assert row.counterevidence
    assert row.monitoring_metrics
    assert row.financial_period == "2024/2025"
    assert row.first_detectable_at == "2026-03-31T18:00:00+08:00"
    assert row.unresolved_reasons == ()


@pytest.mark.parametrize("check_id", tuple(ROW_FACTS))
def test_partial_evidence_is_retained_but_never_completes_row(check_id: str) -> None:
    partial = _fact(ROW_FACTS[check_id][0], period="2025", signal="risk")

    row = build_software_ai_assessment(
        issuer_id=ISSUER, as_of=AS_OF, facts=(partial,)
    ).check(check_id)

    assert (row.status, row.applicability) == ("unresolved", "triggered")
    assert row.evidence_ids == (partial.citation.evidence_id,)
    assert row.observations == (partial.value,)
    assert row.supporting_evidence
    assert "尚缺" in row.unresolved_reasons[0]


def test_absence_and_post_as_of_evidence_remain_explicit_unresolved_states() -> None:
    future = _fact(
        "recurring_revenue",
        period="2026",
        signal="counterevidence",
        available_at="2026-08-04T00:00:00+08:00",
    )

    assessment = build_software_ai_assessment(
        issuer_id=ISSUER, as_of=AS_OF, facts=(future,)
    )
    row = assessment.check("I-SW-01")

    assert assessment.excluded_post_as_of_evidence_ids == (future.citation.evidence_id,)
    assert (row.status, row.applicability) == ("unresolved", "unresolved")
    assert row.evidence_ids == ()
    assert "未取得" in row.unresolved_reasons[0]


def _context(*, include_products: bool = True):
    axes = ["business_model"]
    if include_products:
        axes.append("products_services")
    claims = tuple(
        BusinessModelClaim(
            claim_id=f"business:{axis}",
            axis=axis,  # type: ignore[arg-type]
            statement=f"issuer describes its {axis}",
            period="2025",
            available_at="2026-03-31T18:00:00+08:00",
            evidence_id=f"ir:{axis}",
            source_url=URL,
        )
        for axis in axes
    )
    return build_historical_context(
        issuer_id=ISSUER, as_of=AS_OF, observations=(), business_claims=claims
    )


def _identity(industry_code: str = "30") -> CompanyIdentity:
    return CompanyIdentity(
        security_id="TWSE:9999",
        security_code="9999",
        issuer_id=ISSUER,
        company_name="測試股份有限公司",
        short_name="測試",
        market="TWSE",
        valid_from="2020-01-01T00:00:00+08:00",
        industry_code=industry_code,
    )


def test_route_requires_official_identity_and_company_level_business_evidence() -> None:
    routed = resolve_software_ai_route(identity=_identity(), context=_context())
    broad_code_only = resolve_software_ai_route(identity=_identity(), context=None)
    partial_business = resolve_software_ai_route(
        identity=_identity(), context=_context(include_products=False)
    )
    other_official_industry = resolve_software_ai_route(
        identity=_identity("24"), context=_context()
    )

    assert routed.route == "software_ai"
    assert routed.status == "routed"
    assert set(routed.evidence_ids) == {
        "identity:TWSE:9999", "ir:business_model", "ir:products_services"
    }
    assert broad_code_only.route == "unresolved"
    assert broad_code_only.reason == "company_level_business_evidence_missing"
    assert partial_business.route == "unresolved"
    assert partial_business.reason == "company_level_business_evidence_incomplete"
    assert other_official_industry.route == "not_applicable"


def test_route_rejects_cross_issuer_context_instead_of_guessing() -> None:
    with pytest.raises(ValueError, match="issuer mismatch"):
        resolve_software_ai_route(
            identity=_identity(), context=replace(_context(), issuer_id="87654321")
        )
