"""Deterministic report rendering for the controlled golden path."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RenderedReport:
    generation_id: str
    decision_time: str
    manifest_version: str
    model_version: str
    schema_version: str
    complete: bool
    content: Mapping[str, Any]


def render_report(
    *,
    generation_id: str,
    decision_time: str,
    manifest_version: str,
    model_version: str,
    canonical_identifier: str,
) -> RenderedReport:
    """Render one complete immutable report from a same-generation snapshot."""
    content = MappingProxyType(
        {
            "canonical_identifier": canonical_identifier,
            "rating_disposition": "NO_RATING_NOT_APPLICABLE",
        }
    )
    return RenderedReport(
        generation_id=generation_id,
        decision_time=decision_time,
        manifest_version=manifest_version,
        model_version=model_version,
        schema_version="RenderedReport.v1",
        complete=True,
        content=content,
    )
