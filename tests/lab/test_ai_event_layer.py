from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

import jsonschema
import pytest

from company_quality.lab.ai_event_layer import (
    AIEventEvidence,
    AIEventProposal,
    ProposedDimensionDelta,
    apply_ai_event_layer,
)
from company_quality.research_snapshot import (
    DownsideCoreResult,
    QualityCoreResult,
    UpsideCoreResult,
    build_company_research_snapshot,
)


ROOT = Path(__file__).parents[2]
CHECKED = "2026-07-27T12:00:00+08:00"


def _core():
    generation = "g-ai"
    snapshot = build_company_research_snapshot(
        issuer_id="issuer-2330",
        security_code="2330",
        market="TWSE",
        generated_at="2026-07-27T11:00:00+08:00",
        input_source_versions={"core": "annual-2026.v1"},
        quality=QualityCoreResult(
            generation, "research_only", 60.0, 0.8, "quality-2026.v1", "2026-07-27"
        ),
        upside=UpsideCoreResult(
            generation, "research_only", 0.7, 0.65, None,
            -0.1, 0.2, 0.4, 90.0, 120.0, 140.0,
            None, 0.75, "upside-2026.v1", "2026-07-27",
        ),
        downside=DownsideCoreResult(
            generation, "research_only", 30.0, None, 0.7,
            "downside-2026.v1", "2026-07-27",
        ),
    )
    # Numerical clipping is tested on a synthetic future core payload only. The
    # production builder remains unchanged and still emits no formal ratings.
    return replace(
        snapshot,
        upside=replace(snapshot.upside, stars=4.0),
        downside=replace(snapshot.downside, faces=4.0),
    )


def _evidence(
    evidence_id: str,
    *,
    kind: str = "official",
    independence_key: str = "TWSE",
    checked_at: str = CHECKED,
    validity: str = "confirmed_current",
    reason: str | None = None,
) -> AIEventEvidence:
    return AIEventEvidence(
        evidence_id=evidence_id,
        generation_id="g-ai",
        source_name=evidence_id,
        source_url=f"https://example.com/{evidence_id}",
        source_kind=kind,  # type: ignore[arg-type]
        independence_key=independence_key,
        published_at="2020-01-01T09:00:00+08:00",
        checked_at=checked_at,
        supported_reason=reason or f"official reason {evidence_id}",
        validity=validity,  # type: ignore[arg-type]
    )


def _proposal(
    quality: tuple[float, tuple[str, ...]] = (0.0, ()),
    stars: tuple[float, tuple[str, ...]] = (0.0, ()),
    faces: tuple[float, tuple[str, ...]] = (0.0, ()),
) -> AIEventProposal:
    return AIEventProposal(
        ProposedDimensionDelta(*quality),
        ProposedDimensionDelta(*stars),
        ProposedDimensionDelta(*faces),
    )


def test_official_and_two_independent_sources_adjust_without_mutating_core() -> None:
    core = _core()
    evidence = (
        _evidence("official", reason="official material event confirmed"),
        _evidence("wire-a", kind="reliable", independence_key="wire-a"),
        _evidence("wire-b", kind="reliable", independence_key="wire-b"),
    )
    overlay = apply_ai_event_layer(
        core_snapshot=core,
        checked_at=CHECKED,
        ai_available=True,
        proposal=_proposal(
            quality=(80.0, ("official",)),
            stars=(-10.0, ("wire-a", "wire-b")),
            faces=(10.0, ("official",)),
        ),
        evidence=evidence,
    )

    assert overlay.core_snapshot == core
    assert overlay.ai_status == "AI_adjusted"
    assert overlay.quality.core_value == 60.0
    assert overlay.quality.core_color == "yellow"
    assert overlay.quality.raw_delta == 80.0
    assert overlay.quality.adjusted_value == 100.0
    assert overlay.quality.delta_color == "green"
    assert overlay.stars.raw_delta == -10.0
    assert overlay.stars.adjusted_value == 0.0
    assert overlay.stars.delta_color == "red"
    assert overlay.downside_faces.raw_delta == 10.0
    assert overlay.downside_faces.adjusted_value == 5.0
    assert overlay.downside_faces.delta_color == "red"
    assert overlay.quality.sourced_reason == "official material event confirmed"
    assert overlay.writes_core_model is False
    assert overlay.writes_labels is False
    assert overlay.writes_validation_metrics is False

    schema = json.loads((
        ROOT / "src/company_quality/lab/contracts/AIAdjustedCompanyResearchSnapshot.schema.json"
    ).read_text())
    payload = json.loads(json.dumps(asdict(overlay)))
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(payload)


def test_one_reliable_source_or_non_independent_sources_cannot_adjust() -> None:
    core = _core()
    one = apply_ai_event_layer(
        core_snapshot=core,
        checked_at=CHECKED,
        ai_available=True,
        proposal=_proposal(quality=(20.0, ("wire-a",))),
        evidence=(_evidence("wire-a", kind="reliable", independence_key="wire"),),
    )
    assert one.quality.raw_delta == 0.0
    assert one.quality.adjusted_value == core.quality.score
    assert one.quality.status == "AI_unavailable"
    assert one.ai_status == "AI_unavailable"

    duplicate_origin = apply_ai_event_layer(
        core_snapshot=core,
        checked_at=CHECKED,
        ai_available=True,
        proposal=_proposal(quality=(20.0, ("wire-a", "wire-b"))),
        evidence=(
            _evidence("wire-a", kind="reliable", independence_key="same-wire"),
            _evidence("wire-b", kind="reliable", independence_key="same-wire"),
        ),
    )
    assert duplicate_origin.quality.raw_delta == 0.0
    assert duplicate_origin.quality.status == "AI_unavailable"


def test_every_refresh_requires_current_recheck_but_has_no_fixed_expiry() -> None:
    core = _core()
    old_publication_rechecked_now = apply_ai_event_layer(
        core_snapshot=core,
        checked_at=CHECKED,
        ai_available=True,
        proposal=_proposal(quality=(5.0, ("official",))),
        evidence=(_evidence("official"),),
    )
    assert old_publication_rechecked_now.quality.raw_delta == 5.0

    stale_check = apply_ai_event_layer(
        core_snapshot=core,
        checked_at=CHECKED,
        ai_available=True,
        proposal=_proposal(quality=(5.0, ("official",))),
        evidence=(_evidence(
            "official", checked_at="2026-07-26T12:00:00+08:00"
        ),),
    )
    assert stale_check.quality.raw_delta == 0.0
    assert stale_check.quality.status == "AI_unavailable"
    assert stale_check.verified_evidence == ()


def test_ai_failure_zeros_every_delta_and_preserves_core() -> None:
    core = _core()
    overlay = apply_ai_event_layer(
        core_snapshot=core,
        checked_at=CHECKED,
        ai_available=False,
        proposal=_proposal(
            quality=(999.0, ("official",)),
            stars=(999.0, ("official",)),
            faces=(-999.0, ("official",)),
        ),
        evidence=(_evidence("official"),),
    )

    assert overlay.ai_status == "AI_unavailable"
    for adjustment in (overlay.quality, overlay.stars, overlay.downside_faces):
        assert adjustment.raw_delta == 0.0
        assert adjustment.status == "AI_unavailable"
        assert adjustment.delta_color == "yellow"
    assert overlay.quality.adjusted_value == core.quality.score
    assert overlay.stars.adjusted_value == core.upside.stars
    assert overlay.downside_faces.adjusted_value == core.downside.faces
