from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

import jsonschema
import pytest

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.rating_evidence_policy import (
    RatingEvidenceInput,
    admit_rating_evidence,
)
from company_quality.quality_rating import (
    KamFocus,
    OfficialQualityMetric,
    QualityRatingError,
    build_company_quality_rating,
)


AS_OF = "2026-08-03T12:00:00+08:00"
GENERATION = "quality-generation-1"
PILLARS = (
    "earnings_quality",
    "financial_reliability",
    "cash_balance",
    "capital_efficiency",
    "industry_financial",
)


def _citation(evidence_id: str, *, supplemental: bool = False) -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=f"source:{evidence_id}",
        source_tier="trusted_secondary" if supplemental else "official",
        url=(
            "https://example.com/supplemental"
            if supplemental
            else "https://mops.twse.com.tw/example"
        ),
        content_sha256="a" * 64,
        period="2025Q4",
        available_at="2026-04-01T18:00:00+08:00",
        page=None,
        coordinate=None,
        verbatim_excerpt="正式揭露內容",
        source_format="html",
        locator="row:1",
    )


def _fixture(
    *,
    code: str = "2330",
    market: str = "TWSE",
    omit_target_pillar: str | None = None,
    extra_points: Decimal = Decimal("0"),
):
    issuer = "22099131" if code == "2330" else "28113286"
    evidence_ids = {pillar: f"mops:{code}:{pillar}" for pillar in PILLARS}
    observations = []
    values = (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5"))
    issuer_ids = (f"peer-{market}-1", f"peer-{market}-2", issuer, f"peer-{market}-4", f"peer-{market}-5")
    for peer_id, value in zip(issuer_ids, values, strict=True):
        for pillar in PILLARS:
            if peer_id == issuer and pillar == omit_target_pillar:
                continue
            observations.append(
                OfficialQualityMetric(
                    issuer_id=peer_id,
                    security_code=code if peer_id == issuer else f"P{value}",
                    market=market,  # type: ignore[arg-type]
                    industry_code="semiconductor",
                    decision_date="2026-08-03",
                    generation_id=GENERATION,
                    pillar=pillar,  # type: ignore[arg-type]
                    metric_id=f"{pillar}:primary",
                    value=value,
                    direction="high_good",
                    evidence_ids=(
                        evidence_ids[pillar]
                        if peer_id == issuer
                        else f"official:{peer_id}:{pillar}",
                    ),
                    available_at="2026-04-01T18:00:00+08:00",
                )
            )
    evidence = [
        RatingEvidenceInput(
            issuer_id=issuer,
            disclosure_kind="financial_statement",
            role="core",
            citation=_citation(evidence_id),
        )
        for evidence_id in evidence_ids.values()
    ]
    if extra_points:
        evidence.append(
            RatingEvidenceInput(
                issuer_id=issuer,
                disclosure_kind="verified_supplemental",
                role="extra",
                citation=_citation(f"extra:{code}", supplemental=True),
                extra_points=extra_points,
            )
        )
    decision = admit_rating_evidence(
        dimension="quality",
        issuer_id=issuer,
        as_of=AS_OF,
        evidence=evidence,
        checklist_unresolved_ids=("R11", "I-MFG-03"),
    )
    return issuer, tuple(observations), decision, evidence_ids


@pytest.mark.parametrize(
    ("code", "market"),
    [("2330", "TWSE"), ("6488", "TPEx")],
)
def test_real_market_identity_gets_formal_equal_pillar_quality_rating(
    code: str, market: str
) -> None:
    issuer, observations, decision, _ = _fixture(code=code, market=market)

    rating = build_company_quality_rating(
        issuer_id=issuer,
        security_code=code,
        market=market,  # type: ignore[arg-type]
        generation_id=GENERATION,
        rating_as_of=AS_OF,
        observations=observations,
        rating_evidence=decision,
    )

    assert rating.status == "formal"
    assert rating.base_score == Decimal("50.000000")
    assert rating.score == Decimal("50.000000")
    assert rating.confidence == Decimal("1.000000")
    assert set(rating.pillars) == set(PILLARS)
    assert rating.checklist_unresolved_ids == ("R11", "I-MFG-03")
    assert rating.model_scope == "descriptive_official_financial_quality"
    assert rating.predicts_price_or_adverse_event is False
    schema = json.loads(
        (
            Path(__file__).parents[2]
            / "src/company_quality/quality_rating/contracts/CompanyQualityRating.schema.json"
        ).read_text()
    )
    payload = json.loads(json.dumps(asdict(rating), default=float))
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_verified_supplemental_is_transparent_bonus_not_required_baseline() -> None:
    issuer, observations, without_extra, _ = _fixture()
    _, _, with_extra, _ = _fixture(extra_points=Decimal("2.5"))

    baseline = build_company_quality_rating(
        issuer_id=issuer,
        security_code="2330",
        market="TWSE",
        generation_id=GENERATION,
        rating_as_of=AS_OF,
        observations=observations,
        rating_evidence=without_extra,
    )
    adjusted = build_company_quality_rating(
        issuer_id=issuer,
        security_code="2330",
        market="TWSE",
        generation_id=GENERATION,
        rating_as_of=AS_OF,
        observations=observations,
        rating_evidence=with_extra,
    )

    assert baseline.score == Decimal("50.000000")
    assert adjusted.base_score == baseline.base_score
    assert adjusted.extra_points == Decimal("2.500000")
    assert adjusted.score == Decimal("52.500000")


def test_missing_official_pillar_stops_formal_but_unresolved_checklist_does_not() -> None:
    issuer, observations, decision, _ = _fixture(omit_target_pillar="industry_financial")

    rating = build_company_quality_rating(
        issuer_id=issuer,
        security_code="2330",
        market="TWSE",
        generation_id=GENERATION,
        rating_as_of=AS_OF,
        observations=observations,
        rating_evidence=decision,
    )

    assert rating.status == "research_only"
    assert rating.score is None
    assert rating.confidence == Decimal("0.800000")
    assert rating.missing_primary_pillars == ("industry_financial",)
    assert rating.checklist_unresolved_ids == ("R11", "I-MFG-03")


def test_kam_is_context_and_never_an_automatic_penalty() -> None:
    issuer, observations, decision, evidence_ids = _fixture()
    without_kam = build_company_quality_rating(
        issuer_id=issuer,
        security_code="2330",
        market="TWSE",
        generation_id=GENERATION,
        rating_as_of=AS_OF,
        observations=observations,
        rating_evidence=decision,
    )
    with_kam = build_company_quality_rating(
        issuer_id=issuer,
        security_code="2330",
        market="TWSE",
        generation_id=GENERATION,
        rating_as_of=AS_OF,
        observations=observations,
        rating_evidence=decision,
        kam_focuses=(
            KamFocus(
                topic="收入認列",
                evidence_ids=(evidence_ids["financial_reliability"],),
                linked_metric_ids=("financial_reliability:primary",),
            ),
        ),
    )

    assert with_kam.score == without_kam.score
    assert with_kam.kam_focuses[0].topic == "收入認列"
    assert any(driver.direction == "context" for driver in with_kam.drivers)


def test_target_metric_requires_admitted_official_evidence() -> None:
    issuer, observations, decision, _ = _fixture()
    bad = list(observations)
    target_index = next(index for index, item in enumerate(bad) if item.issuer_id == issuer)
    item = bad[target_index]
    bad[target_index] = OfficialQualityMetric(
        issuer_id=item.issuer_id,
        security_code=item.security_code,
        market=item.market,
        industry_code=item.industry_code,
        decision_date=item.decision_date,
        generation_id=item.generation_id,
        pillar=item.pillar,
        metric_id=item.metric_id,
        value=item.value,
        direction=item.direction,
        evidence_ids=("unadmitted:evidence",),
        available_at=item.available_at,
    )

    with pytest.raises(QualityRatingError, match="official policy evidence"):
        build_company_quality_rating(
            issuer_id=issuer,
            security_code="2330",
            market="TWSE",
            generation_id=GENERATION,
            rating_as_of=AS_OF,
            observations=bad,
            rating_evidence=decision,
        )
