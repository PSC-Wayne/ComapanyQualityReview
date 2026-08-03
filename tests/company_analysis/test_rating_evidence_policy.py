from decimal import Decimal

import pytest

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.rating_evidence_policy import (
    RatingEvidenceInput,
    RatingEvidencePolicyError,
    UnavailableRatingInput,
    admit_rating_evidence,
)


AS_OF = "2026-08-03T12:00:00+08:00"


def _citation(
    evidence_id: str,
    *,
    tier: str = "official",
    available_at: str = "2026-04-01T18:00:00+08:00",
) -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=f"source:{evidence_id}",
        source_tier=tier,  # type: ignore[arg-type]
        url="https://mops.twse.com.tw/example",
        content_sha256="a" * 64,
        period="2025Q4",
        available_at=available_at,
        page=None,
        coordinate=None,
        verbatim_excerpt="正式揭露內容",
        source_format="html",
        locator="row:1",
    )


@pytest.mark.parametrize("dimension", ["quality", "upside", "downside"])
def test_all_rating_dimensions_share_official_disclosure_policy(dimension: str) -> None:
    decision = admit_rating_evidence(
        dimension=dimension,  # type: ignore[arg-type]
        issuer_id="22099131",
        as_of=AS_OF,
        evidence=(
            RatingEvidenceInput(
                issuer_id="22099131",
                disclosure_kind="financial_statement",
                role="core",
                citation=_citation("statement"),
            ),
            RatingEvidenceInput(
                issuer_id="22099131",
                disclosure_kind="kam",
                role="core",
                citation=_citation("kam"),
            ),
        ),
    )

    assert decision.core_rating_eligible is True
    assert decision.core_evidence_ids == ("statement", "kam")
    assert decision.extra_points == Decimal("0")


def test_unavailable_non_disclosed_inputs_do_not_block_or_deduct() -> None:
    decision = admit_rating_evidence(
        dimension="quality",
        issuer_id="22099131",
        as_of=AS_OF,
        evidence=(
            RatingEvidenceInput(
                issuer_id="22099131",
                disclosure_kind="financial_note",
                role="core",
                citation=_citation("note"),
            ),
        ),
        unavailable=(
            UnavailableRatingInput("oral-renewal", "oral_claim_not_formally_disclosed"),
            UnavailableRatingInput("contract-terms", "contract_terms_not_public"),
            UnavailableRatingInput("counterevidence", "supplemental_counterevidence_missing"),
        ),
        checklist_unresolved_ids=("R11", "R17", "I-MFG-03"),
    )

    assert decision.core_rating_eligible is True
    assert decision.extra_points == Decimal("0")
    assert decision.unavailable_inputs == (
        "oral-renewal",
        "contract-terms",
        "counterevidence",
    )
    assert decision.checklist_unresolved_ids == ("R11", "R17", "I-MFG-03")


def test_verified_supplemental_information_is_additive_only() -> None:
    without_extra = admit_rating_evidence(
        dimension="quality",
        issuer_id="22099131",
        as_of=AS_OF,
        evidence=(
            RatingEvidenceInput(
                issuer_id="22099131",
                disclosure_kind="financial_statement",
                role="core",
                citation=_citation("statement"),
            ),
        ),
    )
    with_extra = admit_rating_evidence(
        dimension="quality",
        issuer_id="22099131",
        as_of=AS_OF,
        evidence=(
            RatingEvidenceInput(
                issuer_id="22099131",
                disclosure_kind="financial_statement",
                role="core",
                citation=_citation("statement"),
            ),
            RatingEvidenceInput(
                issuer_id="22099131",
                disclosure_kind="verified_supplemental",
                role="extra",
                citation=_citation("supplemental", tier="trusted_secondary"),
                extra_points=Decimal("2.5"),
            ),
        ),
    )

    assert without_extra.core_rating_eligible is True
    assert with_extra.core_rating_eligible is True
    assert without_extra.extra_points == Decimal("0")
    assert with_extra.extra_points == Decimal("2.5")


def test_supplemental_information_cannot_deduct_from_core_rating() -> None:
    with pytest.raises(RatingEvidencePolicyError, match="non-negative"):
        admit_rating_evidence(
            dimension="downside",
            issuer_id="22099131",
            as_of=AS_OF,
            evidence=(
                RatingEvidenceInput(
                    issuer_id="22099131",
                    disclosure_kind="financial_statement",
                    role="core",
                    citation=_citation("statement"),
                ),
                RatingEvidenceInput(
                    issuer_id="22099131",
                    disclosure_kind="verified_supplemental",
                    role="extra",
                    citation=_citation("rumour", tier="trusted_secondary"),
                    extra_points=Decimal("-1"),
                ),
            ),
        )


def test_supplemental_information_alone_cannot_make_core_rating_eligible() -> None:
    decision = admit_rating_evidence(
        dimension="upside",
        issuer_id="22099131",
        as_of=AS_OF,
        evidence=(
            RatingEvidenceInput(
                issuer_id="22099131",
                disclosure_kind="verified_supplemental",
                role="extra",
                citation=_citation("supplemental", tier="trusted_secondary"),
                extra_points=Decimal("1"),
            ),
        ),
    )

    assert decision.core_rating_eligible is False
    assert decision.ineligibility_reason == "official_primary_disclosure_missing"
    assert decision.extra_points == Decimal("1")


def test_trusted_secondary_cannot_masquerade_as_core_disclosure() -> None:
    with pytest.raises(RatingEvidencePolicyError, match="official or issuer-primary"):
        admit_rating_evidence(
            dimension="quality",
            issuer_id="22099131",
            as_of=AS_OF,
            evidence=(
                RatingEvidenceInput(
                    issuer_id="22099131",
                    disclosure_kind="kam",
                    role="core",
                    citation=_citation("secondary-kam", tier="trusted_secondary"),
                ),
            ),
        )


def test_post_as_of_and_cross_issuer_evidence_fail_closed() -> None:
    with pytest.raises(RatingEvidencePolicyError, match="after rating as_of"):
        admit_rating_evidence(
            dimension="quality",
            issuer_id="22099131",
            as_of=AS_OF,
            evidence=(
                RatingEvidenceInput(
                    issuer_id="22099131",
                    disclosure_kind="official_material_event",
                    role="core",
                    citation=_citation(
                        "future-event", available_at="2026-08-04T09:00:00+08:00"
                    ),
                ),
            ),
        )

    with pytest.raises(RatingEvidencePolicyError, match="issuer mismatch"):
        admit_rating_evidence(
            dimension="quality",
            issuer_id="22099131",
            as_of=AS_OF,
            evidence=(
                RatingEvidenceInput(
                    issuer_id="other-issuer",
                    disclosure_kind="financial_statement",
                    role="core",
                    citation=_citation("other-company"),
                ),
            ),
        )
