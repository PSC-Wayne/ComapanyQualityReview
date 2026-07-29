"""Evidence-first contracts for one-company research.

The public seam is ``build_single_company_research_report``.  It binds one
identity and as-of time to source citations and two permanently independent
cases.  It deliberately contains no combined investment score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
from typing import Literal, Sequence


Market = Literal["TWSE", "TPEx"]
SourceTier = Literal["official", "issuer_primary", "trusted_secondary"]
FindingKind = Literal["fact", "inference", "judgement"]
FindingDirection = Literal["support", "counter", "context"]
CaseStatus = Literal["research_only", "available", "blocked"]
ProbabilityStatus = Literal["formal", "research_only", "unavailable"]
Coordinate = tuple[Decimal, Decimal, Decimal, Decimal]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CompanyAnalysisContractError(ValueError):
    """Raised when evidence cannot safely enter a one-company report."""


@dataclass(frozen=True, slots=True)
class CompanyAnalysisRequest:
    issuer_id: str
    security_code: str
    market: Market
    as_of: str
    horizon_months: Literal[12] = 12


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    evidence_id: str
    source_id: str
    source_tier: SourceTier
    url: str
    content_sha256: str
    period: str
    available_at: str
    page: int
    coordinate: Coordinate
    verbatim_excerpt: str


@dataclass(frozen=True, slots=True)
class SourceCoverage:
    family: str
    required: int
    available: int
    missing_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    kind: FindingKind
    direction: FindingDirection
    statement: str
    materiality: Decimal
    evidence_ids: tuple[str, ...]
    supporting_finding_ids: tuple[str, ...]
    counter_finding_ids: tuple[str, ...]
    counter_evidence_reason: str | None


@dataclass(frozen=True, slots=True)
class CaseProbability:
    status: ProbabilityStatus
    lower: Decimal | None
    point: Decimal | None
    upper: Decimal | None
    confidence: Decimal | None
    calibration_id: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class DownsideCase:
    generation_id: str
    status: CaseStatus
    headline: str
    findings: tuple[Finding, ...]
    twelve_month_drawdown_probability: CaseProbability
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class UpsideCase:
    generation_id: str
    status: CaseStatus
    headline: str
    findings: tuple[Finding, ...]
    positive_return_probability: CaseProbability
    benchmark_outperform_probability: CaseProbability
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class SingleCompanyResearchReport:
    request: CompanyAnalysisRequest
    generation_id: str
    generated_at: str
    citations: tuple[EvidenceCitation, ...]
    source_coverage: tuple[SourceCoverage, ...]
    downside: DownsideCase
    upside: UpsideCase
    limitations: tuple[str, ...]
    status: Literal["research_only"] = "research_only"
    schema_version: Literal["SingleCompanyResearchReport.v2"] = (
        "SingleCompanyResearchReport.v2"
    )


def _text(value: object, field: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise CompanyAnalysisContractError(f"invalid {field}")
    return value.strip()


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CompanyAnalysisContractError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CompanyAnalysisContractError(f"{field} must be timezone-aware")
    return result


def _ratio(value: Decimal | None, field: str) -> None:
    if value is not None and not Decimal("0") <= value <= Decimal("1"):
        raise CompanyAnalysisContractError(f"{field} must be within 0..1")


def _validate_request(request: CompanyAnalysisRequest) -> datetime:
    _text(request.issuer_id, "issuer_id", 64)
    _text(request.security_code, "security_code", 32)
    if request.market not in ("TWSE", "TPEx"):
        raise CompanyAnalysisContractError("invalid market")
    if request.horizon_months != 12:
        raise CompanyAnalysisContractError("only the 12-month horizon is supported")
    return _instant(request.as_of, "analysis as_of")


def _validate_citations(
    citations: Sequence[EvidenceCitation], as_of: datetime
) -> set[str]:
    if not citations:
        raise CompanyAnalysisContractError("at least one evidence citation is required")
    ids: set[str] = set()
    for citation in citations:
        evidence_id = _text(citation.evidence_id, "evidence_id", 256)
        if evidence_id in ids:
            raise CompanyAnalysisContractError("duplicate evidence_id")
        ids.add(evidence_id)
        _text(citation.source_id, "source_id", 256)
        if citation.source_tier not in ("official", "issuer_primary", "trusted_secondary"):
            raise CompanyAnalysisContractError("invalid source tier")
        if not _text(citation.url, "source URL").startswith("https://"):
            raise CompanyAnalysisContractError("source URL must use https")
        if _SHA256.fullmatch(citation.content_sha256) is None:
            raise CompanyAnalysisContractError("invalid citation SHA256")
        _text(citation.period, "citation period", 64)
        if _instant(citation.available_at, "citation available_at") > as_of:
            raise CompanyAnalysisContractError("evidence published after analysis as_of")
        if citation.page < 1:
            raise CompanyAnalysisContractError("citation page must be positive")
        x0, y0, x1, y1 = citation.coordinate
        if any(value < 0 or value > 1 for value in citation.coordinate):
            raise CompanyAnalysisContractError("citation coordinate must be within 0..1")
        if x0 >= x1 or y0 >= y1:
            raise CompanyAnalysisContractError("citation coordinate must have positive area")
        _text(citation.verbatim_excerpt, "verbatim excerpt", 4000)
    return ids


def _validate_coverage(items: Sequence[SourceCoverage]) -> None:
    if not items:
        raise CompanyAnalysisContractError("source coverage is required")
    families: set[str] = set()
    for item in items:
        family = _text(item.family, "coverage family", 128)
        if family in families:
            raise CompanyAnalysisContractError("duplicate coverage family")
        families.add(family)
        if item.required < 0 or not 0 <= item.available <= item.required:
            raise CompanyAnalysisContractError("invalid source coverage counts")
        for reason in item.missing_reasons:
            _text(reason, "missing source reason", 512)
        if item.available < item.required and not item.missing_reasons:
            raise CompanyAnalysisContractError(
                "incomplete source coverage requires missing reasons"
            )


def _validate_probability(value: CaseProbability, field: str) -> None:
    if value.status not in ("formal", "research_only", "unavailable"):
        raise CompanyAnalysisContractError(f"invalid {field} status")
    for name, item in (
        ("lower", value.lower),
        ("point", value.point),
        ("upper", value.upper),
        ("confidence", value.confidence),
    ):
        _ratio(item, f"{field} {name}")
    numeric = (value.lower, value.point, value.upper)
    present = [item for item in numeric if item is not None]
    if present and value.lower is not None and value.upper is not None:
        if value.lower > value.upper:
            raise CompanyAnalysisContractError(f"invalid {field} interval")
        if value.point is not None and not value.lower <= value.point <= value.upper:
            raise CompanyAnalysisContractError(f"invalid {field} point")
    if value.status == "formal":
        if any(item is None for item in (*numeric, value.confidence)):
            raise CompanyAnalysisContractError(f"formal {field} requires complete values")
        _text(value.calibration_id, f"{field} calibration_id", 256)
    elif value.status == "research_only":
        if not present or value.confidence is None:
            raise CompanyAnalysisContractError(
                f"research-only {field} requires an interval and confidence"
            )
        if value.calibration_id is not None:
            raise CompanyAnalysisContractError(
                f"research-only {field} cannot claim formal calibration"
            )
        _text(value.reason, f"{field} reason", 512)
    else:
        if present or value.confidence is not None or value.calibration_id is not None:
            raise CompanyAnalysisContractError(
                f"unavailable {field} cannot carry probability values"
            )
        _text(value.reason, f"{field} reason", 512)


def _validate_findings(
    findings: Sequence[Finding], evidence_ids: set[str], case_name: str
) -> None:
    if not findings:
        raise CompanyAnalysisContractError(f"{case_name} findings are required")
    by_id: dict[str, Finding] = {}
    for item in findings:
        finding_id = _text(item.finding_id, "finding_id", 256)
        if finding_id in by_id:
            raise CompanyAnalysisContractError("duplicate finding_id")
        by_id[finding_id] = item
    for item in findings:
        _text(item.statement, "finding statement", 2000)
        _ratio(item.materiality, "finding materiality")
        if item.kind not in ("fact", "inference", "judgement"):
            raise CompanyAnalysisContractError("invalid finding kind")
        if item.direction not in ("support", "counter", "context"):
            raise CompanyAnalysisContractError("invalid finding direction")
        if not set(item.evidence_ids).issubset(evidence_ids):
            raise CompanyAnalysisContractError("finding cites unknown evidence")
        if item.kind == "fact" and not item.evidence_ids:
            raise CompanyAnalysisContractError("fact requires evidence citation")
        if item.kind in ("inference", "judgement"):
            if not item.supporting_finding_ids:
                raise CompanyAnalysisContractError(
                    "inference or judgement requires supporting findings"
                )
            if not item.counter_finding_ids and not item.counter_evidence_reason:
                raise CompanyAnalysisContractError(
                    "inference or judgement requires counter-evidence handling"
                )
        references = (*item.supporting_finding_ids, *item.counter_finding_ids)
        if item.finding_id in references or any(reference not in by_id for reference in references):
            raise CompanyAnalysisContractError("finding references are invalid")
        if item.counter_evidence_reason is not None:
            _text(item.counter_evidence_reason, "counter evidence reason", 1000)


def _validate_case_common(
    *,
    generation_id: str,
    expected_generation: str,
    status: CaseStatus,
    headline: str,
    findings: Sequence[Finding],
    confidence: Decimal,
    evidence_ids: set[str],
    case_name: str,
) -> None:
    if generation_id != expected_generation:
        raise CompanyAnalysisContractError("both cases must bind the same generation")
    if status not in ("research_only", "available", "blocked"):
        raise CompanyAnalysisContractError(f"invalid {case_name} status")
    _text(headline, f"{case_name} headline", 1000)
    _ratio(confidence, f"{case_name} confidence")
    _validate_findings(findings, evidence_ids, case_name)


def build_single_company_research_report(
    *,
    request: CompanyAnalysisRequest,
    generation_id: str,
    generated_at: str,
    citations: Sequence[EvidenceCitation],
    source_coverage: Sequence[SourceCoverage],
    downside: DownsideCase,
    upside: UpsideCase,
    limitations: Sequence[str] = (),
) -> SingleCompanyResearchReport:
    """Validate and bind one evidence-first report without blending its cases."""

    as_of = _validate_request(request)
    generation = _text(generation_id, "generation_id", 256)
    generated = _instant(generated_at, "generated_at")
    if generated < as_of:
        raise CompanyAnalysisContractError("generated_at cannot precede analysis as_of")
    evidence_ids = _validate_citations(citations, as_of)
    _validate_coverage(source_coverage)
    _validate_case_common(
        generation_id=downside.generation_id,
        expected_generation=generation,
        status=downside.status,
        headline=downside.headline,
        findings=downside.findings,
        confidence=downside.confidence,
        evidence_ids=evidence_ids,
        case_name="downside",
    )
    _validate_probability(
        downside.twelve_month_drawdown_probability,
        "twelve-month drawdown probability",
    )
    _validate_case_common(
        generation_id=upside.generation_id,
        expected_generation=generation,
        status=upside.status,
        headline=upside.headline,
        findings=upside.findings,
        confidence=upside.confidence,
        evidence_ids=evidence_ids,
        case_name="upside",
    )
    _validate_probability(upside.positive_return_probability, "positive-return probability")
    _validate_probability(
        upside.benchmark_outperform_probability,
        "benchmark-outperform probability",
    )
    normalized_limitations = tuple(
        _text(item, "limitation", 1000) for item in limitations
    )
    return SingleCompanyResearchReport(
        request=request,
        generation_id=generation,
        generated_at=generated.isoformat(),
        citations=tuple(citations),
        source_coverage=tuple(source_coverage),
        downside=downside,
        upside=upside,
        limitations=normalized_limitations,
    )


__all__ = [
    "CaseProbability",
    "CompanyAnalysisContractError",
    "CompanyAnalysisRequest",
    "DownsideCase",
    "EvidenceCitation",
    "Finding",
    "SingleCompanyResearchReport",
    "SourceCoverage",
    "UpsideCase",
    "build_single_company_research_report",
]
