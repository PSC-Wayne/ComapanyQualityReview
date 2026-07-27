import json
from dataclasses import asdict
from pathlib import Path

import jsonschema
import pytest

from company_quality.research_snapshot import (
    CompanyResearchSnapshotError,
    DownsideCoreResult,
    QualityCoreResult,
    UpsideCoreResult,
    build_company_research_snapshot,
)


ROOT = Path(__file__).parents[2]
GENERATION = "real-t20-2026-07-25"


def _real_research_snapshot():
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
        market=None,
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
    assert snapshot.rating_disposition == "NO_RATING_NOT_APPLICABLE"


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
