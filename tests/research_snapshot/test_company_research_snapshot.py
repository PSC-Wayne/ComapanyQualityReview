import json
from dataclasses import asdict
from pathlib import Path
from decimal import Decimal

import jsonschema
import pytest

from company_quality.lab.outcome_labels import TwelveMonthReturnLabel
from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.rating_evidence_policy import (
    RatingEvidenceInput,
    admit_rating_evidence,
)
from company_quality.research_snapshot import (
    CompanyResearchSnapshotError,
    DownsideCoreResult,
    QualityCoreResult,
    UpsideCoreResult,
    build_company_research_snapshot,
)


ROOT = Path(__file__).parents[2]
GENERATION = "real-t20-2026-07-25"


def _real_research_snapshot(label: TwelveMonthReturnLabel | None = None):
    pipeline = json.loads(
        (ROOT / "artifacts/real_data/real-t20-t22-execution.json").read_text()
    )
    upside_report = json.loads(
        (ROOT / "artifacts/real_data/real-upside-validation-report.json").read_text()
    )
    t22 = pipeline["stage_results"]["T22"]

    return build_company_research_snapshot(
        issuer_id="REAL_VALIDATION_COHORT",
        security_code=None,
        market=None if label is None else label.market,
        generated_at=pipeline["generated_at"],
        input_source_versions={
            "pipeline": pipeline["schema_version"],
            "upside": upside_report["schema_version"],
        },
        quality=QualityCoreResult(
            generation_id=GENERATION,
            status="research_only",
            score=None,
            confidence=None,
            model_version="train-only-pava-quality.v1",
            data_as_of=t22["holdout_end"] if "holdout_end" in t22 else "2024-06-30",
        ),
        upside=UpsideCoreResult(
            generation_id=upside_report["generation_id"],
            status="research_only",
            positive_return_probability=None,
            official_benchmark_outperform_probability=None,
            secondary_market_median_outperform_probability=None,
            p10_return=None,
            p50_return=None,
            p90_return=None,
            p10_price=None,
            p50_price=None,
            p90_price=None,
            stars=None,
            confidence=None,
            model_version=upside_report["model_version"],
            data_as_of=upside_report["temporal_windows"][-1]["holdout_end"],
        ),
        downside=DownsideCoreResult(
            generation_id=GENERATION,
            status="research_only",
            risk_score=None,
            faces=None,
            confidence=None,
            model_version="train-only-pava-adverse-risk.v1",
            data_as_of="2024-06-30",
        ),
        twelve_month_return=label,
    )


def test_real_non_publishable_artifacts_build_one_closed_research_snapshot() -> None:
    snapshot = _real_research_snapshot()
    payload = asdict(snapshot)
    schema = json.loads(
        (
            ROOT
            / "src/company_quality/research_snapshot/contracts/CompanyResearchSnapshot.schema.json"
        ).read_text()
    )

    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        payload
    )
    assert snapshot.generation_id == GENERATION
    assert snapshot.status == "research_only"
    assert snapshot.ai_status == "AI_unavailable"
    assert snapshot.quality.score is None
    assert snapshot.upside.stars is None
    assert snapshot.downside.faces is None
    assert snapshot.rating_disposition == "RESEARCH_ONLY"
    assert snapshot.schema_version == "CompanyResearchSnapshot.v2"
    assert set(snapshot.rating_evidence) == {"quality", "upside", "downside"}
    assert all(
        not item.core_rating_eligible for item in snapshot.rating_evidence.values()
    )
    assert snapshot.input_source_versions["rating_evidence_policy"] == (
        "OfficialDisclosureRatingPolicy.v1"
    )


def test_snapshot_carries_same_generation_twelve_month_label_without_publishing_stars() -> None:
    label = TwelveMonthReturnLabel(
        generation_id=GENERATION,
        market="TWSE",
        decision_date="2023-06-30",
        result_end_date="2024-06-30",
        actual_total_return=Decimal("0.2"),
        official_benchmark_return=Decimal("0.1"),
        official_excess_return=Decimal("0.1"),
        same_market_median_return=Decimal("0.05"),
        positive_return=True,
        outperformed_official_market=True,
        company_total_return_source_ref="finlab://etl/adj_close/2330",
        official_benchmark_source_ref="https://openapi.twse.com.tw/v1/indicesReport/MFI94U",
        same_market_median_source_ref="generation://real/TWSE/2023-06-30/median",
        status="complete",
        evidence_ids=("company-adjusted-return", "TWSE-MFI94U"),
    )

    snapshot = _real_research_snapshot(label)

    assert snapshot.twelve_month_return == label
    assert snapshot.upside.stars is None
    assert snapshot.status == "research_only"


def test_snapshot_rejects_mixed_generations() -> None:
    snapshot = _real_research_snapshot()
    mismatched = DownsideCoreResult(
        generation_id="other-generation",
        status=snapshot.downside.status,
        risk_score=snapshot.downside.risk_score,
        faces=snapshot.downside.faces,
        confidence=snapshot.downside.confidence,
        model_version=snapshot.downside.model_version,
        data_as_of=snapshot.downside.data_as_of,
    )

    with pytest.raises(CompanyResearchSnapshotError, match="same successful generation"):
        build_company_research_snapshot(
            issuer_id=snapshot.issuer_id,
            security_code=snapshot.security_code,
            market=snapshot.market,
            generated_at=snapshot.generated_at,
            input_source_versions=snapshot.input_source_versions,
            quality=snapshot.quality,
            upside=snapshot.upside,
            downside=mismatched,
        )


def _official_policy_decision(dimension: str, *, unresolved: tuple[str, ...] = ()):
    citation = EvidenceCitation(
        evidence_id=f"mops:{dimension}:statement",
        source_id="mops:financial-statement",
        source_tier="official",
        url="https://mops.twse.com.tw/example",
        content_sha256="a" * 64,
        period="2025Q4",
        available_at="2026-07-24T18:00:00+08:00",
        page=None,
        coordinate=None,
        verbatim_excerpt="正式財報揭露",
        source_format="html",
        locator="row:1",
    )
    return admit_rating_evidence(
        dimension=dimension,  # type: ignore[arg-type]
        issuer_id="REAL_VALIDATION_COHORT",
        as_of="2026-07-25T00:00:00+00:00",
        evidence=(
            RatingEvidenceInput(
                issuer_id="REAL_VALIDATION_COHORT",
                disclosure_kind="financial_statement",
                role="core",
                citation=citation,
            ),
        ),
        checklist_unresolved_ids=unresolved,
    )


def test_snapshot_carries_policy_summary_without_demoting_for_checklist_gaps() -> None:
    snapshot = _real_research_snapshot()
    rebuilt = build_company_research_snapshot(
        issuer_id=snapshot.issuer_id,
        security_code=snapshot.security_code,
        market=snapshot.market,
        generated_at=snapshot.generated_at,
        input_source_versions=snapshot.input_source_versions,
        quality=snapshot.quality,
        upside=snapshot.upside,
        downside=snapshot.downside,
        rating_evidence={
            "quality": _official_policy_decision("quality", unresolved=("R11", "R17")),
            "upside": _official_policy_decision("upside"),
            "downside": _official_policy_decision("downside"),
        },
    )

    assert rebuilt.status == "research_only"
    assert rebuilt.rating_evidence["quality"].core_rating_eligible is True
    assert rebuilt.rating_evidence["quality"].checklist_unresolved_ids == ["R11", "R17"]
    assert rebuilt.rating_evidence["quality"].extra_points == 0.0


def test_formal_core_rejects_missing_official_rating_evidence() -> None:
    snapshot = _real_research_snapshot()
    formal_quality = QualityCoreResult(
        generation_id=snapshot.generation_id,
        status="formal",
        score=75.0,
        confidence=0.8,
        model_version="formal-quality.v1",
        data_as_of=snapshot.quality.data_as_of,
    )

    with pytest.raises(
        CompanyResearchSnapshotError, match="formal quality requires official disclosure"
    ):
        build_company_research_snapshot(
            issuer_id=snapshot.issuer_id,
            security_code=snapshot.security_code,
            market=snapshot.market,
            generated_at=snapshot.generated_at,
            input_source_versions=snapshot.input_source_versions,
            quality=formal_quality,
            upside=snapshot.upside,
            downside=snapshot.downside,
        )
