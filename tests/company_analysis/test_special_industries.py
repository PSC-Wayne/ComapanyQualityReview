from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from company_quality.company_analysis.checklist_analysis import build_checklist_assessment
from company_quality.company_analysis.contracts import (
    CompanyAnalysisRequest,
    EvidenceCitation,
    SourceCoverage,
)
from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle
from company_quality.company_analysis.report_orchestrator import build_report_from_evidence
from company_quality.company_analysis.special_industries import (
    SpecialIndustryEvidenceError,
    SpecialIndustryEvidenceFact,
    build_special_industry_assessment,
)
from company_quality.identity import CompanyIdentity, IdentityResolution
from company_quality.industry.routing import (
    CompanyLevelRouteEvidence,
    IndustryAuthority,
    route_industry,
)
from company_quality.sources.monthly_revenue import MonthlyRevenueArtifact


AS_OF = "2026-08-03T12:00:00+08:00"


def _identity(*, code: str = "7777", issuer_id: str = "12345678") -> IdentityResolution:
    return IdentityResolution(
        identifier=code,
        requested_market="TWSE",
        decision_time=AS_OF,
        status="resolved",
        identity=CompanyIdentity(
            security_id=f"TWSE:{code}",
            security_code=code,
            issuer_id=issuer_id,
            company_name="不作路由依據的正式名稱",
            short_name="不猜名稱",
            market="TWSE",
            valid_from="2020-01-01T00:00:00+08:00",
        ),
        evidence_urls=("https://official.example/identity",),
    )


def _authority(industry_code: str, *, code: str = "7777", issuer_id: str = "12345678") -> IndustryAuthority:
    body = f"{code}:{issuer_id}:{industry_code}".encode()
    return IndustryAuthority(
        market="TWSE",
        url="https://official.example/company-list",
        content_sha256=sha256(body).hexdigest(),
        available_at="2026-08-03T00:00:00+08:00",
        retrieved_at="2026-08-03T11:00:00+08:00",
        rows=({
            "security_code": code,
            "issuer_id": issuer_id,
            "company_name": "來源使用另一個合法全名",
            "short_name": "另一簡稱",
            "industry_code": industry_code,
        },),
    )


def _business(*, issuer_id: str = "12345678", available_at: str = "2026-08-02T18:00:00+08:00") -> CompanyLevelRouteEvidence:
    return CompanyLevelRouteEvidence(
        issuer_id=issuer_id,
        business_model="研發、授權及銷售產品",
        products=("產品組合A",),
        end_markets=("醫療或能源終端市場",),
        evidence_ids=("annual-report:business", "ir:products", "annual-report:end-market"),
        available_at=available_at,
    )


@pytest.mark.parametrize(("industry_code", "sector", "tag"), [
    ("22", "biotechnology", "specialised_route:biotech"),
    ("23", "energy_utilities", "specialised_route:energy"),
    ("35", "energy_utilities", "specialised_route:energy"),
])
def test_special_route_requires_official_identity_and_company_business_evidence(
    industry_code: str, sector: str, tag: str
) -> None:
    result = route_industry(
        _identity(), _authority(industry_code), company_business_evidence=_business()
    )

    assert result.status == "routed"
    assert result.sector_code == sector
    assert tag in result.business_model_tags
    assert set(_business().evidence_ids).issubset(result.evidence_ids)
    # Legal-name aliases are provenance, never a company-name classifier.
    assert result.reason is None


@pytest.mark.parametrize("industry_code", ["22", "23", "35"])
def test_special_route_fails_closed_without_complete_company_business_evidence(
    industry_code: str,
) -> None:
    absent = route_industry(_identity(), _authority(industry_code))
    partial = route_industry(
        _identity(),
        _authority(industry_code),
        company_business_evidence=replace(_business(), end_markets=()),
    )

    assert (absent.status, absent.reason) == (
        "blocked", "company_level_business_evidence_required"
    )
    assert (partial.status, partial.reason) == (
        "blocked", "company_level_business_evidence_incomplete"
    )
    assert partial.evidence_ids[-3:] == _business().evidence_ids


def test_special_route_rejects_post_as_of_business_evidence() -> None:
    result = route_industry(
        _identity(),
        _authority("22"),
        company_business_evidence=_business(available_at="2026-08-04T00:00:00+08:00"),
    )

    assert result.status == "blocked"
    assert result.reason == "company_business_evidence_not_available_at_decision_time"


def _citation(evidence_id: str, fact_type: str, *, period: str = "2025") -> EvidenceCitation:
    excerpt = f"{period} {fact_type} 官方逐字證據。"
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=evidence_id.split(":", 1)[0],
        source_tier="official" if evidence_id.startswith("regulator:") else "issuer_primary",
        url=f"https://issuer.example/{evidence_id.replace(':', '-')}",
        content_sha256=sha256(excerpt.encode()).hexdigest(),
        period=period,
        available_at="2026-03-31T18:00:00+08:00",
        page=10,
        coordinate=(Decimal("0.1"), Decimal("0.1"), Decimal("0.9"), Decimal("0.2")),
        verbatim_excerpt=excerpt,
        source_format="pdf",
        locator=None,
    )


def _fact(fact_type: str, *, index: int, signal: str = "counterevidence") -> SpecialIndustryEvidenceFact:
    citation = _citation(f"issuer:{fact_type}:{index}", fact_type)
    return SpecialIndustryEvidenceFact(
        issuer_id="12345678",
        fact_type=fact_type,  # type: ignore[arg-type]
        value=f"{fact_type}=已取得",
        period=citation.period,
        signal=signal,  # type: ignore[arg-type]
        evidence_role="substantive",
        citation=citation,
    )


BIO_FACTS = {
    "I-BIO-01": ("clinical_stage",),
    "I-BIO-02": ("trial_endpoint", "enrollment"),
    "I-BIO-03": ("regulatory_status", "approval_status"),
    "I-BIO-04": ("ip_rights",),
    "I-BIO-05": ("commercial_evidence",),
}
ENERGY_FACTS = {
    "I-ENERGY-01": ("reserves",),
    "I-ENERGY-02": ("capacity", "utilization"),
    "I-ENERGY-03": ("contract_terms",),
    "I-ENERGY-04": ("commodity_exposure",),
    "I-ENERGY-05": ("capex", "decommissioning"),
}


def _route(industry_code: str):
    return route_industry(
        _identity(), _authority(industry_code), company_business_evidence=_business()
    )


@pytest.mark.parametrize(("industry_code", "rows"), [("22", BIO_FACTS), ("23", ENERGY_FACTS)])
def test_all_special_industry_rows_complete_only_from_exact_evidence(
    industry_code: str, rows: dict[str, tuple[str, ...]]
) -> None:
    facts = tuple(
        _fact(fact_type, index=index)
        for index, fact_type in enumerate(
            fact_type for requirements in rows.values() for fact_type in requirements
        )
    )

    assessment = build_special_industry_assessment(_route(industry_code), facts)

    assert assessment.route_status == "routed"
    assert tuple(item.check_id for item in assessment.checks) == tuple(rows)
    assert all(item.status == "evaluated" for item in assessment.checks)
    assert all(item.counterevidence for item in assessment.checks)


@pytest.mark.parametrize(("industry_code", "rows"), [("22", BIO_FACTS), ("23", ENERGY_FACTS)])
def test_partial_and_absent_special_industry_evidence_stay_unresolved(
    industry_code: str, rows: dict[str, tuple[str, ...]]
) -> None:
    first_row = next(iter(rows))
    partial = _fact(rows[first_row][0], index=1, signal="risk")

    assessment = build_special_industry_assessment(_route(industry_code), (partial,))

    first = assessment.check(first_row)
    assert (first.status, first.applicability) == ("unresolved", "triggered")
    assert first.evidence_ids == (partial.citation.evidence_id,)
    assert first.observations == (partial.value,)
    assert "尚缺" in first.unresolved_reasons[0] or "完整證據鏈" in first.unresolved_reasons[0]
    for row in tuple(rows)[1:]:
        assert assessment.check(row).status == "unresolved"
        assert "未取得" in assessment.check(row).unresolved_reasons[0]


def test_fact_after_route_decision_time_is_rejected_not_silently_admitted() -> None:
    fact = _fact("clinical_stage", index=1)
    future = replace(
        fact,
        citation=replace(fact.citation, available_at="2026-08-04T00:00:00+08:00"),
    )

    with pytest.raises(SpecialIndustryEvidenceError, match="PIT"):
        build_special_industry_assessment(_route("22"), (future,))


def test_special_industry_fact_must_bind_to_routed_issuer() -> None:
    fact = replace(_fact("clinical_stage", index=1), issuer_id="87654321")

    with pytest.raises(SpecialIndustryEvidenceError, match="issuer mismatch"):
        build_special_industry_assessment(_route("22"), (fact,))


def test_special_industry_producer_requires_complete_route_evidence() -> None:
    route = replace(_route("22"), evidence_ids=())

    with pytest.raises(SpecialIndustryEvidenceError, match="route evidence"):
        build_special_industry_assessment(route, ())


def test_context_evidence_cannot_complete_special_industry_row() -> None:
    context = replace(_fact("clinical_stage", index=1), evidence_role="context")

    row = build_special_industry_assessment(_route("22"), (context,)).check("I-BIO-01")

    assert row.status == "unresolved"
    assert row.evidence_ids == (context.citation.evidence_id,)
    assert row.counterevidence == ()


def _bundle(industry_code: str) -> CompanyEvidenceBundle:
    identity = _identity().identity
    assert identity is not None
    return CompanyEvidenceBundle(
        request=CompanyAnalysisRequest(
            identity.issuer_id, identity.security_code, identity.market, AS_OF
        ),
        identity=replace(identity, industry_code=industry_code),
        retrieved_at=AS_OF,
        periods=(),
        monthly_revenue=(
            MonthlyRevenueArtifact(
                artifact_id="monthly:7777:2026-07",
                issuer_id=identity.issuer_id,
                security_code=identity.security_code,
                market=identity.market,
                month="2026-07",
                revenue_thousand_twd=Decimal("100"),
                prior_year_revenue_thousand_twd=Decimal("90"),
                yoy_percent=Decimal("11.11"),
                cumulative_revenue_thousand_twd=Decimal("700"),
                prior_year_cumulative_revenue_thousand_twd=Decimal("630"),
                cumulative_yoy_percent=Decimal("11.11"),
                explanation=None,
                official_url="https://official.example/monthly",
                available_at=AS_OF,
                content_sha256=sha256(b"monthly").hexdigest(),
                path=Path("/fixture/monthly.json"),
            ),
        ),
        source_coverage=(
            SourceCoverage(
                family="three_statement_html",
                required=1,
                available=0,
                missing_reasons=("fixture intentionally blocks core statements",),
            ),
        ),
        status="partial",
    )


def test_special_industry_assessment_flows_through_checklist_and_report() -> None:
    facts = tuple(
        _fact(fact_type, index=index)
        for index, fact_type in enumerate(
            fact_type for requirements in BIO_FACTS.values() for fact_type in requirements
        )
    )
    special = build_special_industry_assessment(_route("22"), facts)
    bundle = _bundle("22")

    checklist = build_checklist_assessment(
        bundle,
        "generation-special",
        None,
        special_industry_assessment=special,
    )
    report = build_report_from_evidence(
        bundle=bundle,
        generation_id="generation-special",
        generated_at=AS_OF,
        special_industry_assessment=special,
    )

    assert checklist.industry_route == "biotech"
    assert all(checklist_check.status == "evaluated" for checklist_check in checklist.checks if checklist_check.check_id in BIO_FACTS)
    assert {item.evidence_id for item in special.citations}.issubset(
        {item.evidence_id for item in report.citations}
    )
