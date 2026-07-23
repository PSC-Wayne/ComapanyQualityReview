"""Controlled, transform-only company-quality golden path."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from company_quality.report_shell import RenderedReport, render_report

SOURCE_VERSION = "controlled-fixture.v1"
FORMULA_VERSION = "canonical-sha256.v1"
MODEL_VERSION = "no-rating-model.v1"
MANIFEST_VERSION = "controlled-manifest.v1"
SCHEMA_VERSION = "GoldenPathResult.v1"
INVALID_TIME_SENTINEL = "1970-01-01T00:00:00Z"
FOUNDATION_ARTIFACTS = MappingProxyType(
    {
        "admission_scan_path": "tools/admission_scan.py",
        "validate_json_path": "tools/validate_json.py",
        "freeze_package_schema_path": "docs/governance/calibration-freeze/schemas/CalibrationFreezePackage.v1.json",
        "freeze_manifest_schema_path": "docs/governance/calibration-freeze/schemas/CalibrationFreezeManifest.v1.json",
    }
)


@dataclass(frozen=True, slots=True)
class GoldenPathQuery:
    identifier: str
    market: str | None
    decision_time: str


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    canonical_identifier: str
    legal_name: str
    market: str


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    generation_id: str
    producer_candidate_sha: str
    decision_time: str
    manifest_version: str
    source_version: str
    formula_version: str
    model_version: str
    schema_version: str
    identity: ResolvedIdentity | None
    sections: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GoldenPathResult:
    query: GoldenPathQuery
    generation_id: str
    snapshot_hash: str
    report_hash: str
    error_code: str | None
    failure_reason: str | None
    foundation_artifacts: Mapping[str, str]
    contract_coverage: float
    rating_disposition: str
    source_version: str
    formula_version: str
    model_version: str
    schema_version: str
    manifest_version: str
    producer_candidate_sha: str
    snapshot: AnalysisSnapshot
    report: RenderedReport

    def contract_dict(self) -> dict[str, Any]:
        """Return exactly the declared GoldenPathResult.v1 contract envelope."""
        return {
            "query": asdict(self.query),
            "generation_id": self.generation_id,
            "snapshot_hash": self.snapshot_hash,
            "report_hash": self.report_hash,
            "error_code": self.error_code,
            "failure_reason": self.failure_reason,
            "foundation_artifacts": dict(self.foundation_artifacts),
            "contract_coverage": self.contract_coverage,
            "rating_disposition": self.rating_disposition,
            "source_version": self.source_version,
            "formula_version": self.formula_version,
            "model_version": self.model_version,
            "schema_version": self.schema_version,
            "manifest_version": self.manifest_version,
            "producer_candidate_sha": self.producer_candidate_sha,
        }


def _canonical_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    return value


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        _canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _aware_decision_time(value: str) -> str | None:
    if not isinstance(value, str) or re.fullmatch(
        r"[^\s]+T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
    ) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return value


def _resolve(query: GoldenPathQuery) -> tuple[ResolvedIdentity | None, str | None, str | None]:
    if query.market not in (None, "TWSE", "TPEx"):
        return None, "unsupported_scope", f"market {query.market!r} is outside TWSE/TPEx scope"
    if query.identifier == "ACME" and query.market is None:
        return None, "identity_ambiguous", "identifier 'ACME' matches multiple controlled identities"
    if query.identifier == "BLOCKED":
        return None, "blocked_contract", "controlled fixture requires an unavailable contract major"
    if query.identifier == "MISMATCH":
        return None, "generation_mismatch", "controlled fixture snapshot and report generations disagree"
    if query.identifier == "2330" and query.market in (None, "TWSE"):
        return ResolvedIdentity("TWSE:2330", "Controlled Semiconductor Co.", "TWSE"), None, None
    return None, "unsupported_scope", "identifier is not present in the controlled fixture scope"


def run_golden_path(
    query: GoldenPathQuery, *, producer_candidate_sha: str | None
) -> GoldenPathResult:
    """Resolve, freeze and render one deterministic controlled-fixture analysis."""
    aware_time = _aware_decision_time(query.decision_time)
    normalized_query = GoldenPathQuery(
        query.identifier
        if isinstance(query.identifier, str) and 1 <= len(query.identifier) <= 128
        else "INVALID_IDENTIFIER",
        query.market if query.market in (None, "TWSE", "TPEx") else None,
        aware_time if aware_time is not None else INVALID_TIME_SENTINEL,
    )
    if not isinstance(producer_candidate_sha, str) or re.fullmatch(
        r"[0-9a-f]{40}", producer_candidate_sha
    ) is None:
        normalized_candidate_sha = "0" * 40
        identity, error_code, failure_reason = None, "blocked_contract", (
            "producer_candidate_sha must be a full 40-character lowercase Git SHA"
        )
    elif aware_time is None:
        normalized_candidate_sha = producer_candidate_sha
        identity, error_code, failure_reason = None, "invalid_decision_time", (
            "decision_time must be an exact timezone-aware RFC3339 value"
        )
    elif not isinstance(query.identifier, str) or not 1 <= len(query.identifier) <= 128:
        normalized_candidate_sha = producer_candidate_sha
        identity, error_code, failure_reason = None, "unsupported_scope", (
            "identifier must contain between 1 and 128 characters"
        )
    else:
        normalized_candidate_sha = producer_candidate_sha
        identity, error_code, failure_reason = _resolve(query)

    generation_seed = {
        "query": asdict(normalized_query),
        "producer_candidate_sha": normalized_candidate_sha,
        "source_version": SOURCE_VERSION,
        "formula_version": FORMULA_VERSION,
        "model_version": MODEL_VERSION,
        "manifest_version": MANIFEST_VERSION,
    }
    generation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical_hash(generation_seed)))
    sections = MappingProxyType(
        {
            "golden_path": MappingProxyType(
                {
                    "error_code": error_code,
                    "failure_reason": failure_reason,
                    "rating_disposition": "NO_RATING_NOT_APPLICABLE",
                }
            )
        }
    )
    snapshot = AnalysisSnapshot(
        generation_id=generation_id,
        producer_candidate_sha=normalized_candidate_sha,
        decision_time=normalized_query.decision_time,
        manifest_version=MANIFEST_VERSION,
        source_version=SOURCE_VERSION,
        formula_version=FORMULA_VERSION,
        model_version=MODEL_VERSION,
        schema_version="AnalysisSnapshot.v1",
        identity=identity,
        sections=sections,
    )
    report = render_report(
        generation_id=generation_id,
        producer_candidate_sha=normalized_candidate_sha,
        decision_time=snapshot.decision_time,
        manifest_version=snapshot.manifest_version,
        model_version=snapshot.model_version,
        error_code=error_code,
        failure_reason=failure_reason,
        canonical_identifier=identity.canonical_identifier if identity else None,
    )
    return GoldenPathResult(
        query=normalized_query,
        generation_id=generation_id,
        snapshot_hash=canonical_hash(snapshot),
        report_hash=canonical_hash(report),
        error_code=error_code,
        failure_reason=failure_reason,
        foundation_artifacts=FOUNDATION_ARTIFACTS,
        contract_coverage=1.0,
        rating_disposition="NO_RATING_NOT_APPLICABLE",
        source_version=SOURCE_VERSION,
        formula_version=FORMULA_VERSION,
        model_version=MODEL_VERSION,
        schema_version=SCHEMA_VERSION,
        manifest_version=MANIFEST_VERSION,
        producer_candidate_sha=normalized_candidate_sha,
        snapshot=snapshot,
        report=report,
    )


__all__ = [
    "AnalysisSnapshot",
    "GoldenPathQuery",
    "GoldenPathResult",
    "ResolvedIdentity",
    "canonical_hash",
    "run_golden_path",
]
