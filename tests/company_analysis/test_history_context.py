from decimal import Decimal
from types import SimpleNamespace

from company_quality.company_analysis.history_context import (
    BusinessModelClaim,
    GuidanceActual,
    GuidanceRevision,
    HistoricalObservation,
    build_bundle_history_context,
    build_historical_context,
)

AS_OF = "2026-08-03T12:00:00+08:00"
ISSUER_ID = "22099131"
URL = "https://official.example/filing"


def _history(*, annual=5, quarters=12, months=36):
    rows = []
    for year in range(110, 110 + annual):
        rows.append(HistoricalObservation(
            f"a{year}", "annual", f"{year}Q4", f"{year + 1912}-03-31T18:00:00+08:00",
            f"audit:{year}", URL, "official_historical_filing", "annual", "audit",
        ))
    for index in range(quarters):
        year, quarter = divmod(index, 4)
        rows.append(HistoricalObservation(
            f"q{index}", "quarterly", f"{112 + year}Q{quarter + 1}",
            f"{2023 + year}-{quarter * 3 + 3:02d}-30T18:00:00+08:00",
            f"quarter:{index}", URL, "official_historical_filing", "single_quarter", "review",
        ))
    yoy_pattern = (Decimal("-5"), Decimal("-2"), Decimal("2"), Decimal("6"), Decimal("3"), Decimal("-1"))
    for index in range(months):
        year, month = divmod(index, 12)
        rows.append(HistoricalObservation(
            f"m{index}", "monthly", f"{111 + year}-{month + 1:02d}",
            f"{2022 + year}-{month + 1:02d}-10T18:00:00+08:00",
            f"month:{index}", URL, "official_monthly_filing", "single_month", "unaudited",
            Decimal(100 + month * 10 + year), yoy_pattern[index % len(yoy_pattern)],
        ))
    return tuple(rows)


def _business():
    return tuple(
        BusinessModelClaim(
            f"b:{axis}", axis, f"official {axis}", "114", "2026-03-31T18:00:00+08:00",
            f"business:{axis}", URL,
        )
        for axis in ("business_model", "products_services", "customers", "end_markets")
    )


def _guidance():
    guidance = (
        GuidanceRevision(
            "g1-original", "114Q1", "revenue", "single_quarter", Decimal("90"),
            Decimal("110"), "TWD_million", "2025-01-10T10:00:00+08:00", "g:e1", URL,
        ),
        GuidanceRevision(
            "g1-revised", "114Q1", "revenue", "single_quarter", Decimal("100"),
            Decimal("120"), "TWD_million", "2025-02-10T10:00:00+08:00", "g:e2", URL,
            revision_of="g1-original",
        ),
        GuidanceRevision(
            "g2", "114Q2", "revenue", "single_quarter", Decimal("120"),
            Decimal("140"), "TWD_million", "2025-04-10T10:00:00+08:00", "g:e3", URL,
        ),
    )
    actuals = (
        GuidanceActual(
            "actual1", "114Q1", "revenue", "single_quarter", Decimal("115"),
            "TWD_million", "2025-05-15T18:00:00+08:00", "a:e1", URL,
        ),
        GuidanceActual(
            "actual2", "114Q2", "revenue", "single_quarter", Decimal("145"),
            "TWD_million", "2025-08-14T18:00:00+08:00", "a:e2", URL,
        ),
    )
    return guidance, actuals


def test_full_context_has_independent_history_seasonality_business_and_hits():
    guidance, actuals = _guidance()
    result = build_historical_context(
        issuer_id=ISSUER_ID,
        as_of=AS_OF, observations=_history(), business_claims=_business(),
        guidance=guidance, actuals=actuals,
    )

    assert result.status == "full"
    assert all(item.status == "full" for item in result.coverage)
    assert len(result.seasonality) == 12
    assert result.seasonality[0].observation_count == 3
    assert result.turning_points
    assert [item.guidance_id for item in result.guidance_hits] == [
        "g1-original", "g1-revised", "g2"
    ]
    assert [item.hit for item in result.guidance_hits] == [False, True, False]
    assert result.guidance_hits[1].revision_of == "g1-original"
    assert result.guidance_hits[1].period_basis == "single_quarter"
    assert result.guidance_hits[1].guidance_source_url == URL


def test_partial_axes_do_not_downgrade_completed_axes():
    result = build_historical_context(
        issuer_id=ISSUER_ID,
        as_of=AS_OF,
        observations=_history(annual=5, quarters=8, months=36),
    )

    assert result.status == "partial"
    assert result.by_axis["five_year_annual_audited"].status == "full"
    assert result.by_axis["monthly_seasonality"].status == "full"
    assert result.by_axis["twelve_quarters"].status == "partial"
    assert result.by_axis["official_business_model"].status == "unresolved"
    assert result.by_axis["guidance_hits"].status == "unresolved"


def test_unresolved_when_no_axis_has_admissible_history():
    latest = HistoricalObservation(
        "latest", "quarterly", "115Q2", "2026-07-31T18:00:00+08:00", "latest:e", URL,
        "current_snapshot", "single_quarter", "review",
    )
    result = build_historical_context(
        issuer_id=ISSUER_ID, as_of=AS_OF, observations=(latest,)
    )

    assert result.status == "unresolved"
    assert all(item.status == "unresolved" for item in result.coverage)
    assert result.by_axis["twelve_quarters"].observed == 0


def test_pit_excludes_post_as_of_observations_claims_guidance_and_actuals():
    guidance, actuals = _guidance()
    future = "2026-08-04T00:00:00+08:00"
    rows = (*_history(), HistoricalObservation(
        "future-month", "monthly", "115-07", future, "future:m", URL,
        "official_monthly_filing", "single_month", "unaudited", Decimal("999"), Decimal("999"),
    ))
    claims = (*_business(), BusinessModelClaim(
        "future-claim", "products_services", "future", "115", future, "future:b", URL,
    ))
    future_guidance = GuidanceRevision(
        "future-guidance", "115Q3", "revenue", "single_quarter", Decimal("1"), Decimal("2"),
        "TWD_million", future, "future:g", URL,
    )
    future_actual = GuidanceActual(
        "future-actual", "115Q3", "revenue", "single_quarter", Decimal("2"), "TWD_million",
        future, "future:a", URL,
    )

    result = build_historical_context(
        issuer_id=ISSUER_ID,
        as_of=AS_OF, observations=rows, business_claims=claims,
        guidance=(*guidance, future_guidance), actuals=(*actuals, future_actual),
    )

    assert "future:m" not in result.by_axis["monthly_seasonality"].evidence_ids
    assert all(item.claim_id != "future-claim" for item in result.business_claims)
    assert all(item.guidance_id != "future-guidance" for item in result.guidance_hits)


def test_bundle_hook_reuses_source_bound_history_without_copying_financial_values():
    artifact = SimpleNamespace(
        available_at="2026-03-31T18:00:00+08:00", artifact_id="financial:114Q4",
        official_url=URL,
    )
    audit = SimpleNamespace(
        pdf_path="filing.pdf", available_at="2026-03-31T18:00:00+08:00",
        evidence_ids=("audit:114",), pdf_source_url=URL,
    )
    month = SimpleNamespace(
        month="114-12", available_at="2026-01-10T18:00:00+08:00",
        artifact_id="month:114-12", official_url=URL,
        revenue_thousand_twd=Decimal("100"), yoy_percent=Decimal("5"),
    )
    bundle = SimpleNamespace(
        identity=SimpleNamespace(issuer_id=ISSUER_ID),
        request=SimpleNamespace(as_of=AS_OF),
        periods=(SimpleNamespace(
            period="114Q4", financial=SimpleNamespace(artifacts=(artifact,)),
            audit=audit, is_annual=True,
        ),),
        monthly_revenue=(month,),
    )

    result = build_bundle_history_context(bundle)

    assert result.by_axis["five_year_annual_audited"].observed == 1
    assert result.by_axis["twelve_quarters"].observed == 1
    assert result.by_axis["monthly_seasonality"].observed == 1
    assert result.business_claims == ()
    assert result.guidance_hits == ()
