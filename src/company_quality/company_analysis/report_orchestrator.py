"""Bind a current evidence bundle to a conservative single-company report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Literal, Sequence

from company_quality.company_analysis.contracts import (
    CaseProbability,
    DownsideCase,
    EvidenceCitation,
    Finding,
    SingleCompanyResearchReport,
    SourceCoverage,
    UpsideCase,
    build_single_company_research_report,
)
from company_quality.company_analysis.evidence_bundle import (
    CompanyEvidenceBundle,
    collect_company_evidence_bundle,
)
from company_quality.company_analysis.probability_calibration import (
    EmpiricalProbabilityCalibration,
    SingleCompanyProbabilityCalibration,
)
from company_quality.company_analysis.probability_provider import (
    ProbabilitySourceError,
    calibrate_current_generation,
)
from company_quality.sources.financial import FinancialArtifact
from company_quality.identity import CompanyIdentity, OfficialIdentitySource


class ReportOrchestrationError(RuntimeError):
    """Raised when current-generation evidence cannot safely form a report."""


@dataclass(frozen=True, slots=True)
class CompanyAnalysisResult:
    generation_id: str
    identity: CompanyIdentity
    evidence_status: Literal["available", "partial", "blocked"]
    source_coverage: tuple[SourceCoverage, ...]
    research_report: SingleCompanyResearchReport
    probability_calibration: SingleCompanyProbabilityCalibration | None
    calibration_error: str | None
    status: Literal["research_only"] = "research_only"
    schema_version: Literal["DashboardCompanyAnalysisResult.v1"] = (
        "DashboardCompanyAnalysisResult.v1"
    )


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.replace("\xa0", " ").split())
        if text:
            self.parts.append(text)


def _income_artifacts(bundle: CompanyEvidenceBundle) -> Iterable[FinancialArtifact]:
    for period in reversed(bundle.periods):
        if period.financial is None:
            continue
        for artifact in period.financial.artifacts:
            if artifact.report == "income":
                yield artifact


def _citation(bundle: CompanyEvidenceBundle) -> EvidenceCitation:
    artifact = next(iter(_income_artifacts(bundle)), None)
    if artifact is None:
        raise ReportOrchestrationError("no citable official income statement")
    body = artifact.path.read_bytes()
    if sha256(body).hexdigest() != artifact.content_sha256:
        raise ReportOrchestrationError("financial artifact content hash mismatch")
    parser = _VisibleText()
    parser.feed(body.decode("utf-8", "replace"))
    text = " ".join(parser.parts)
    marker = "綜合損益表"
    index = text.find(marker)
    if index < 0:
        raise ReportOrchestrationError("income statement title not found in official artifact")
    start = max(0, index - 120)
    excerpt = text[start : index + len(marker) + 180].strip()
    if not excerpt:
        raise ReportOrchestrationError("official income statement has no citable text")
    return EvidenceCitation(
        evidence_id=artifact.artifact_id,
        source_id=artifact.artifact_id,
        source_tier="official",
        url=artifact.official_url,
        content_sha256=artifact.content_sha256,
        period=artifact.period,
        available_at=artifact.available_at,
        page=None,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="html",
        locator="document-text:contains(綜合損益表)",
    )


def _unavailable(reason: str) -> CaseProbability:
    return CaseProbability(
        status="unavailable",
        lower=None,
        point=None,
        upper=None,
        confidence=None,
        calibration_id=None,
        reason=reason,
    )


def _formal(metric: EmpiricalProbabilityCalibration) -> CaseProbability:
    if any(
        value is None
        for value in (
            metric.lower,
            metric.point,
            metric.upper,
            metric.confidence_level,
            metric.calibration_id,
        )
    ):
        raise ReportOrchestrationError("formal calibration has incomplete values")
    return CaseProbability(
        status="formal",
        lower=metric.lower,
        point=metric.point,
        upper=metric.upper,
        confidence=metric.confidence_level,
        calibration_id=metric.calibration_id,
        reason="歷史季節匹配、互不重疊12個月標籤的Wilson 90%區間；不是當前證據條件機率。",
    )


def _probabilities(
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    calibration: SingleCompanyProbabilityCalibration | None,
    unavailable_reason: str | None,
) -> tuple[CaseProbability, CaseProbability]:
    if calibration is None:
        reason = unavailable_reason or "本generation尚未取得可重現的公司總報酬與官方benchmark校準輸入。"
        return _unavailable(reason), _unavailable(reason)
    if calibration.generation_id != generation_id:
        raise ReportOrchestrationError("calibration generation mismatch")
    if (
        calibration.issuer_id != bundle.identity.issuer_id
        or calibration.security_code != bundle.identity.security_code
        or calibration.market != bundle.identity.market
    ):
        raise ReportOrchestrationError("calibration identity mismatch")
    if calibration.status != "formal":
        reason = calibration.failure_reasons.get(
            "minimum_observations", "formal probability calibration unavailable"
        )
        return _unavailable(reason), _unavailable(reason)
    return _formal(calibration.positive_return), _formal(calibration.official_outperformance)


def _coverage(bundle: CompanyEvidenceBundle, family: str) -> tuple[int, int]:
    item = next((row for row in bundle.source_coverage if row.family == family), None)
    return (item.available, item.required) if item is not None else (0, 0)


def build_report_from_evidence(
    *,
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    generated_at: str,
    calibration: SingleCompanyProbabilityCalibration | None = None,
    calibration_unavailable_reason: str | None = None,
) -> SingleCompanyResearchReport:
    """Produce a valid conservative report without inventing unimplemented analysis."""

    try:
        generated = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise ReportOrchestrationError("invalid generated_at") from exc
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ReportOrchestrationError("generated_at must be timezone-aware")
    citation = _citation(bundle)
    audit_available, audit_required = _coverage(bundle, "audit_or_review_pdf")
    annual_available, annual_required = _coverage(bundle, "annual_audit_pdf")
    positive, outperform = _probabilities(
        bundle, generation_id, calibration, calibration_unavailable_reason
    )
    downside_fact = Finding(
        finding_id=f"downside:{citation.evidence_id}",
        kind="fact",
        direction="context",
        statement=f"MOPS官方來源已取得{citation.period}綜合損益表。",
        materiality=Decimal("0.30"),
        evidence_ids=(citation.evidence_id,),
        supporting_finding_ids=(),
        counter_finding_ids=(),
        counter_evidence_reason=None,
    )
    upside_fact = Finding(
        finding_id=f"upside:{citation.evidence_id}",
        kind="fact",
        direction="context",
        statement=f"MOPS官方來源已取得{citation.period}綜合損益表。",
        materiality=Decimal("0.30"),
        evidence_ids=(citation.evidence_id,),
        supporting_finding_ids=(),
        counter_finding_ids=(),
        counter_evidence_reason=None,
    )
    limitations = [
        "通用KAM、高風險附註、重大事件、產業前景與估值extractor尚未接入；不得由財報存在推導投資結論。",
        f"查核／核閱PDF coverage為{audit_available}/{audit_required}；年度查核PDF為{annual_available}/{annual_required}。",
    ]
    if positive.status != "formal":
        limitations.append("本generation沒有正式12個月報酬機率，Dashboard必須顯示unavailable。")
    return build_single_company_research_report(
        request=bundle.request,
        generation_id=generation_id,
        generated_at=generated_at,
        citations=(citation,),
        source_coverage=bundle.source_coverage,
        downside=DownsideCase(
            generation_id=generation_id,
            status="blocked",
            headline=(
                "下跌風險結論被阻擋：尚未完成通用KAM、高風險附註與重大事件抽取；"
                f"目前查核／核閱PDF coverage為{audit_available}/{audit_required}。"
            ),
            findings=(downside_fact,),
            twelve_month_drawdown_probability=_unavailable(
                "未來12個月最大跌幅事件尚未正式校準。"
            ),
            confidence=Decimal("0.10"),
        ),
        upside=UpsideCase(
            generation_id=generation_id,
            status="blocked",
            headline="上漲潛力結論被阻擋：尚未完成通用產業前景、成長驅動與估值抽取。",
            findings=(upside_fact,),
            positive_return_probability=positive,
            benchmark_outperform_probability=outperform,
            confidence=Decimal("0.10"),
        ),
        limitations=tuple(limitations),
    )


def run_single_company_analysis(
    *,
    identifier: str,
    requested_market: Literal["TWSE", "TPEx"] | None,
    as_of: str,
    retrieved_at: str,
    output_root: Path,
    generation_id: str,
    identity_sources: Sequence[OfficialIdentitySource] | None = None,
    calibration: SingleCompanyProbabilityCalibration | None = None,
) -> CompanyAnalysisResult:
    """Collect current evidence and bind the same generation to a report."""

    bundle = collect_company_evidence_bundle(
        identifier=identifier,
        requested_market=requested_market,
        as_of=as_of,
        retrieved_at=retrieved_at,
        output_root=output_root / "evidence",
        identity_sources=identity_sources,
    )
    decision = datetime.fromisoformat(as_of)
    generated_at = datetime.now(decision.tzinfo).isoformat(timespec="seconds")
    calibration_error: str | None = None
    if calibration is None:
        try:
            calibration = calibrate_current_generation(
                issuer_id=bundle.identity.issuer_id,
                security_code=bundle.identity.security_code,
                market=bundle.identity.market,
                as_of=as_of,
                generated_at=generated_at,
                generation_id=generation_id,
                output_root=output_root / "calibration",
            )
            if calibration is None:
                calibration_error = "目前只支援TWSE官方benchmark校準。"
        except ProbabilitySourceError as exc:
            calibration_error = str(exc)
    report = build_report_from_evidence(
        bundle=bundle,
        generation_id=generation_id,
        generated_at=generated_at,
        calibration=calibration,
        calibration_unavailable_reason=calibration_error,
    )
    return CompanyAnalysisResult(
        generation_id=generation_id,
        identity=bundle.identity,
        evidence_status=bundle.status,
        source_coverage=bundle.source_coverage,
        research_report=report,
        probability_calibration=calibration,
        calibration_error=calibration_error,
    )


__all__ = [
    "CompanyAnalysisResult",
    "ReportOrchestrationError",
    "build_report_from_evidence",
    "run_single_company_analysis",
]
