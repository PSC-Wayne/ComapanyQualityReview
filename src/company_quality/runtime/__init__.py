"""Deterministic controlled-fixture golden path for equity research."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Mapping
from zoneinfo import ZoneInfo

from company_quality.report_shell import RenderedReport, render_report

SOURCE_VERSION = "controlled-fixture.v1"
FORMULA_VERSION = "identity-only.v1"
MODEL_VERSION = "no-rating-model.v1"
MANIFEST_VERSION = "controlled-manifest.v1"
SCHEMA_VERSION = "GoldenPathResult.v1"
INVALID_TIME_SENTINEL = "1970-01-01T00:00:00+08:00"
_ERROR_CODES = (
    "invalid_decision_time",
    "identity_ambiguous",
    "unsupported_scope",
    "blocked_contract",
    "generation_mismatch",
)
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True, slots=True)
class GoldenPathQuery:
    identifier: str
    market: str | None
    decision_time: str


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    canonical_identifier: str
    company_name: str
    market: Literal["TWSE", "TPEx"]


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    generation_id: str
    decision_time: str
    manifest_version: str
    source_version: str
    formula_version: str
    model_version: str
    identity: ResolvedIdentity
    sections: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GoldenPathResult:
    query: GoldenPathQuery
    generation_id: str | None
    snapshot_hash: str | None
    report_hash: str | None
    error_code: str | None
    failure_reason: str | None
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"]
    source_version: str
    formula_version: str
    model_version: str
    schema_version: Literal["GoldenPathResult.v1"]
    manifest_version: str
    snapshot: AnalysisSnapshot | None
    report: RenderedReport | None

    def contract_dict(self) -> dict[str, Any]:
        return {
            "query": asdict(self.query),
            "generation_id": self.generation_id,
            "snapshot_hash": self.snapshot_hash,
            "report_hash": self.report_hash,
            "error_code": self.error_code,
            "failure_reason": self.failure_reason,
            "rating_disposition": self.rating_disposition,
            "source_version": self.source_version,
            "formula_version": self.formula_version,
            "model_version": self.model_version,
            "schema_version": self.schema_version,
            "manifest_version": self.manifest_version,
        }


def _thaw(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _thaw(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _sha256(value: Any) -> str:
    payload = json.dumps(
        _thaw(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalized_decision_time(value: Any) -> str | None:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    local = parsed.astimezone(ZoneInfo("Asia/Taipei"))
    return local.isoformat(timespec="microseconds" if local.microsecond else "seconds")


def _contract_query(query: GoldenPathQuery, normalized_time: str | None) -> GoldenPathQuery:
    identifier = (
        query.identifier
        if isinstance(query.identifier, str) and 1 <= len(query.identifier) <= 128
        else "INVALID_IDENTIFIER"
    )
    market = query.market if query.market in (None, "TWSE", "TPEx") else None
    return GoldenPathQuery(identifier, market, normalized_time or INVALID_TIME_SENTINEL)


def _resolve(query: GoldenPathQuery) -> tuple[ResolvedIdentity | None, str | None, str | None]:
    if query.market not in (None, "TWSE", "TPEx"):
        return None, "unsupported_scope", "market is outside the controlled TWSE/TPEx scope"
    if query.identifier == "ACME" and query.market is None:
        return None, "identity_ambiguous", "identifier resolves to multiple controlled candidates"
    if query.identifier in {"2330", "台積電"} and query.market in (None, "TWSE"):
        return ResolvedIdentity("TWSE:2330", "台灣積體電路製造", "TWSE"), None, None
    return None, "unsupported_scope", "identifier is not present in the controlled fixture scope"


def _failure(query: GoldenPathQuery, error_code: str, failure_reason: str) -> GoldenPathResult:
    assert error_code in _ERROR_CODES
    return GoldenPathResult(
        query=query,
        generation_id=None,
        snapshot_hash=None,
        report_hash=None,
        error_code=error_code,
        failure_reason=failure_reason,
        rating_disposition="NO_RATING_NOT_APPLICABLE",
        source_version=SOURCE_VERSION,
        formula_version=FORMULA_VERSION,
        model_version=MODEL_VERSION,
        schema_version=SCHEMA_VERSION,
        manifest_version=MANIFEST_VERSION,
        snapshot=None,
        report=None,
    )


def validate_same_generation(
    snapshot: AnalysisSnapshot,
    report: RenderedReport,
    expected_report_hash: str | None,
) -> str | None:
    if (
        snapshot.generation_id != report.generation_id
        or snapshot.decision_time != report.decision_time
        or snapshot.manifest_version != report.manifest_version
        or snapshot.model_version != report.model_version
    ):
        return "generation_mismatch"
    if expected_report_hash is None or _sha256(report) != expected_report_hash:
        return "blocked_contract"
    return None


def run_golden_path(query: GoldenPathQuery) -> GoldenPathResult:
    """Resolve, freeze and render one deterministic controlled-fixture analysis."""
    normalized_time = _normalized_decision_time(query.decision_time)
    normalized_query = _contract_query(query, normalized_time)
    if normalized_time is None:
        return _failure(
            normalized_query,
            "invalid_decision_time",
            "decision_time must be an exact timezone-aware RFC3339 instant",
        )
    if not isinstance(query.identifier, str) or not 1 <= len(query.identifier) <= 128:
        return _failure(
            normalized_query,
            "unsupported_scope",
            "identifier must contain between 1 and 128 characters",
        )
    identity, error_code, failure_reason = _resolve(query)
    if error_code is not None or identity is None:
        return _failure(
            normalized_query,
            error_code or "blocked_contract",
            failure_reason or "identity resolution failed",
        )

    generation_seed = {
        "query": asdict(normalized_query),
        "identity": asdict(identity),
        "source_version": SOURCE_VERSION,
        "formula_version": FORMULA_VERSION,
        "model_version": MODEL_VERSION,
        "manifest_version": MANIFEST_VERSION,
    }
    generation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, _sha256(generation_seed)))
    sections = MappingProxyType(
        {
            "golden_path": MappingProxyType(
                {"status": "complete", "contract_version": SCHEMA_VERSION}
            ),
            "identity_resolution": MappingProxyType(
                {"status": "resolved", "route": identity.market}
            ),
            "analysis": MappingProxyType(
                {"status": "controlled_fixture_complete", "rating": None}
            ),
        }
    )
    snapshot = AnalysisSnapshot(
        generation_id=generation_id,
        decision_time=normalized_time,
        manifest_version=MANIFEST_VERSION,
        source_version=SOURCE_VERSION,
        formula_version=FORMULA_VERSION,
        model_version=MODEL_VERSION,
        identity=identity,
        sections=sections,
    )
    snapshot_hash = _sha256(snapshot)
    report = render_report(
        generation_id=generation_id,
        decision_time=normalized_time,
        manifest_version=MANIFEST_VERSION,
        model_version=MODEL_VERSION,
        canonical_identifier=identity.canonical_identifier,
    )
    report_hash = _sha256(report)
    seam_error = validate_same_generation(snapshot, report, report_hash)
    if seam_error is not None:
        return _failure(
            normalized_query,
            seam_error,
            "snapshot/report generation or report hash did not match",
        )
    return GoldenPathResult(
        query=normalized_query,
        generation_id=generation_id,
        snapshot_hash=snapshot_hash,
        report_hash=report_hash,
        error_code=None,
        failure_reason=None,
        rating_disposition="NO_RATING_NOT_APPLICABLE",
        source_version=SOURCE_VERSION,
        formula_version=FORMULA_VERSION,
        model_version=MODEL_VERSION,
        schema_version=SCHEMA_VERSION,
        manifest_version=MANIFEST_VERSION,
        snapshot=snapshot,
        report=report,
    )
