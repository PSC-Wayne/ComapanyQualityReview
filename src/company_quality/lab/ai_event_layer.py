"""Source-grounded AI event overlay that never mutates core model output."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Literal, Sequence

import jsonschema

from company_quality.research_snapshot import CompanyResearchSnapshot


_CORE_SCHEMA = (
    Path(__file__).parents[1]
    / "research_snapshot/contracts/CompanyResearchSnapshot.schema.json"
)


@dataclass(frozen=True, slots=True)
class AIEventEvidence:
    evidence_id: str
    generation_id: str
    source_name: str
    source_url: str
    source_kind: Literal["official", "reliable"]
    independence_key: str
    published_at: str
    checked_at: str
    supported_reason: str
    validity: Literal["confirmed_current", "unavailable", "contradicted"]


@dataclass(frozen=True, slots=True)
class ProposedDimensionDelta:
    raw_delta: float
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AIEventProposal:
    quality: ProposedDimensionDelta
    stars: ProposedDimensionDelta
    downside_faces: ProposedDimensionDelta


@dataclass(frozen=True, slots=True)
class DimensionAdjustment:
    dimension: Literal["quality", "stars", "downside_faces"]
    core_value: float | None
    core_color: Literal["yellow"]
    raw_delta: float
    delta_color: Literal["yellow", "green", "red"]
    effect_direction: Literal["neutral", "favorable", "adverse"]
    adjusted_value: float | None
    evidence_ids: tuple[str, ...]
    sourced_reason: str
    status: Literal["AI_adjusted", "AI_no_adjustment", "AI_unavailable"]


@dataclass(frozen=True, slots=True)
class AIAdjustedCompanyResearchSnapshot:
    generation_id: str
    checked_at: str
    ai_status: Literal["AI_adjusted", "AI_no_adjustment", "AI_unavailable"]
    core_snapshot: CompanyResearchSnapshot
    quality: DimensionAdjustment
    stars: DimensionAdjustment
    downside_faces: DimensionAdjustment
    verified_evidence: tuple[AIEventEvidence, ...]
    writes_core_model: Literal[False] = False
    writes_labels: Literal[False] = False
    writes_validation_metrics: Literal[False] = False
    schema_version: Literal["AIAdjustedCompanyResearchSnapshot.v1"] = (
        "AIAdjustedCompanyResearchSnapshot.v1"
    )


def _instant(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _qualified_evidence(
    proposal: ProposedDimensionDelta,
    evidence: dict[str, AIEventEvidence],
    generation_id: str,
    checked_at: str,
) -> tuple[AIEventEvidence, ...] | None:
    selected: list[AIEventEvidence] = []
    checked = _instant(checked_at, "checked_at")
    for evidence_id in proposal.evidence_ids:
        item = evidence.get(evidence_id)
        if item is None:
            return None
        if (
            item.generation_id != generation_id
            or item.checked_at != checked_at
            or item.validity != "confirmed_current"
            or _instant(item.published_at, "published_at") > checked
            or _instant(item.checked_at, "evidence checked_at") != checked
        ):
            return None
        selected.append(item)
    if len({item.evidence_id for item in selected}) != len(selected):
        return None
    if any(item.source_kind == "official" for item in selected):
        return tuple(selected)
    independent = {
        item.independence_key
        for item in selected
        if item.source_kind == "reliable" and item.independence_key
    }
    if len(independent) >= 2:
        return tuple(selected)
    return None


def _adjustment(
    *,
    dimension: Literal["quality", "stars", "downside_faces"],
    core_value: float | None,
    proposal: ProposedDimensionDelta,
    evidence: dict[str, AIEventEvidence],
    generation_id: str,
    checked_at: str,
    ai_available: bool,
    maximum: float,
) -> DimensionAdjustment:
    if not ai_available:
        return DimensionAdjustment(
            dimension, core_value, "yellow", 0.0, "yellow", "neutral",
            core_value, (), "AI or current source evidence unavailable", "AI_unavailable",
        )
    if proposal.raw_delta == 0:
        return DimensionAdjustment(
            dimension, core_value, "yellow", 0.0, "yellow", "neutral",
            core_value, (), "no source-grounded adjustment", "AI_no_adjustment",
        )
    selected = _qualified_evidence(
        proposal, evidence, generation_id, checked_at
    )
    if selected is None:
        return DimensionAdjustment(
            dimension, core_value, "yellow", 0.0, "yellow", "neutral",
            core_value, (), "AI or current source evidence unavailable", "AI_unavailable",
        )
    favorable = (
        proposal.raw_delta < 0
        if dimension == "downside_faces"
        else proposal.raw_delta > 0
    )
    adjusted = (
        None
        if core_value is None
        else min(max(core_value + proposal.raw_delta, 0.0), maximum)
    )
    return DimensionAdjustment(
        dimension=dimension,
        core_value=core_value,
        core_color="yellow",
        raw_delta=proposal.raw_delta,
        delta_color="green" if favorable else "red",
        effect_direction="favorable" if favorable else "adverse",
        adjusted_value=adjusted,
        evidence_ids=tuple(item.evidence_id for item in selected),
        sourced_reason="; ".join(item.supported_reason for item in selected),
        status="AI_adjusted",
    )


def apply_ai_event_layer(
    *,
    core_snapshot: CompanyResearchSnapshot,
    checked_at: str,
    ai_available: bool,
    proposal: AIEventProposal,
    evidence: Sequence[AIEventEvidence],
) -> AIAdjustedCompanyResearchSnapshot:
    _instant(checked_at, "checked_at")
    core_schema = json.loads(_CORE_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        core_schema, format_checker=jsonschema.FormatChecker()
    ).validate(asdict(core_snapshot))
    by_id = {item.evidence_id: item for item in evidence}
    if len(by_id) != len(evidence):
        raise ValueError("evidence_id must be unique")
    quality = _adjustment(
        dimension="quality", core_value=core_snapshot.quality.score,
        proposal=proposal.quality, evidence=by_id,
        generation_id=core_snapshot.generation_id, checked_at=checked_at,
        ai_available=ai_available, maximum=100.0,
    )
    stars = _adjustment(
        dimension="stars", core_value=core_snapshot.upside.stars,
        proposal=proposal.stars, evidence=by_id,
        generation_id=core_snapshot.generation_id, checked_at=checked_at,
        ai_available=ai_available, maximum=5.0,
    )
    faces = _adjustment(
        dimension="downside_faces", core_value=core_snapshot.downside.faces,
        proposal=proposal.downside_faces, evidence=by_id,
        generation_id=core_snapshot.generation_id, checked_at=checked_at,
        ai_available=ai_available, maximum=5.0,
    )
    statuses = {quality.status, stars.status, faces.status}
    if "AI_adjusted" in statuses:
        ai_status = "AI_adjusted"
    elif "AI_unavailable" in statuses or not ai_available:
        ai_status = "AI_unavailable"
    else:
        ai_status = "AI_no_adjustment"
    used_ids = set(quality.evidence_ids + stars.evidence_ids + faces.evidence_ids)
    verified = tuple(item for item in evidence if item.evidence_id in used_ids)
    return AIAdjustedCompanyResearchSnapshot(
        generation_id=core_snapshot.generation_id,
        checked_at=checked_at,
        ai_status=ai_status,
        core_snapshot=core_snapshot,
        quality=quality,
        stars=stars,
        downside_faces=faces,
        verified_evidence=verified,
    )


__all__ = [
    "AIAdjustedCompanyResearchSnapshot", "AIEventEvidence", "AIEventProposal",
    "DimensionAdjustment", "ProposedDimensionDelta", "apply_ai_event_layer",
]
