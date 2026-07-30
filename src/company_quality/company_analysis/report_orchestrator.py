"""Bind a current evidence bundle to a conservative single-company report."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Literal, Sequence

from company_quality.audit.inventory import AuditFilingInventory
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
from company_quality.company_analysis.candidate_admission import (
    HermesApiCandidateAdapter,
    HermesCandidateAdapter,
    admit_kam_judgement,
    admit_hermes_candidates,
)
from company_quality.company_analysis.evidence_bundle import (
    CompanyEvidenceBundle,
    collect_company_evidence_bundle,
)
from company_quality.company_analysis.detailed_analysis import build_detailed_analysis
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
from company_quality.filing_store import FilingStoreStats


class ReportOrchestrationError(RuntimeError):
    """Raised when current-generation evidence cannot safely form a report."""


@dataclass(frozen=True, slots=True)
class KamAnnualTimeline:
    period: str
    citation: EvidenceCitation
    kam_present: bool
    opinion_type: str | None
    modified_opinion: bool | None
    going_concern: bool
    emphasis_matter: bool
    auditor_change: bool | None


@dataclass(frozen=True, slots=True)
class KamJudgement:
    generation_id: str
    status: Literal["available", "partial"]
    coverage: SourceCoverage
    years: tuple[KamAnnualTimeline, ...]
    missing_year_reasons: tuple[str, ...]
    change_summary: str | None
    risk_mechanism: str | None
    counterevidence: str | None
    severity: Literal["none", "low", "medium", "high", "critical"] | None
    confidence: Decimal | None
    monitoring: str | None
    invalidation: str | None
    rejection_reasons: tuple[str, ...]
    schema_version: Literal["KamJudgement.v1"] = "KamJudgement.v1"


@dataclass(frozen=True, slots=True)
class CompanyAnalysisResult:
    generation_id: str
    identity: CompanyIdentity
    evidence_status: Literal["available", "partial", "blocked"]
    source_coverage: tuple[SourceCoverage, ...]
    kam_judgement: KamJudgement
    research_report: SingleCompanyResearchReport
    probability_calibration: SingleCompanyProbabilityCalibration | None
    calibration_error: str | None
    filing_store_stats: FilingStoreStats | None = None
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


def _pdf_pages(path: Path) -> tuple[str, ...]:
    from pypdf import PdfReader

    return tuple((page.extract_text() or "") for page in PdfReader(path).pages)


def _kam_excerpt(pages: Sequence[str]) -> tuple[int, str] | None:
    marker = "關鍵查核事項"
    for page_number, raw in enumerate(pages, start=1):
        text = " ".join(raw.replace("\xa0", " ").split())
        index = text.find(marker)
        if index < 0:
            continue
        excerpt = text[index : index + 3900].strip()
        if len(excerpt) > len(marker) + 8:
            return page_number, excerpt
    return None


def build_kam_judgement(
    *,
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    candidate_adapter: HermesCandidateAdapter | None,
) -> KamJudgement:
    """Build the latest-three available annual KAM timeline and admit Hermes judgement."""

    decision = datetime.fromisoformat(bundle.request.as_of.replace("Z", "+00:00"))
    rows: list[tuple[AuditFilingInventory, EvidenceCitation, tuple[str, ...]]] = []
    missing: list[str] = []
    annuals = sorted(
        (item for item in bundle.periods if item.is_annual),
        key=lambda item: item.period,
        reverse=True,
    )
    for period in annuals:
        audit = period.audit
        if audit is None:
            missing.append(f"{period.period}:annual_audit_pdf:missing")
            continue
        if audit.issuer_id != bundle.request.issuer_id:
            missing.append(f"{period.period}:kam:wrong_issuer")
            continue
        available = datetime.fromisoformat(audit.available_at.replace("Z", "+00:00"))
        if available > decision:
            missing.append(f"{period.period}:kam:after_as_of")
            continue
        if (
            audit.pdf_path is None
            or audit.pdf_sha256 is None
            or audit.pdf_source_url is None
            or not audit.pdf_path.is_file()
        ):
            missing.append(f"{period.period}:kam:pdf_missing")
            continue
        body = audit.pdf_path.read_bytes()
        if sha256(body).hexdigest() != audit.pdf_sha256:
            missing.append(f"{period.period}:kam:content_hash_mismatch")
            continue
        try:
            pages = _pdf_pages(audit.pdf_path)
        except Exception:
            missing.append(f"{period.period}:kam:pdf_parse_failed")
            continue
        located = _kam_excerpt(pages)
        if located is None:
            missing.append(f"{period.period}:kam:original_text_missing")
            continue
        page, excerpt = located
        citation = EvidenceCitation(
            evidence_id=f"kam:{audit.period}:{audit.pdf_sha256}",
            source_id=f"annual-audit:{audit.period}",
            source_tier="official",
            url=audit.pdf_source_url,
            content_sha256=audit.pdf_sha256,
            period=audit.period,
            available_at=audit.available_at,
            page=page,
            coordinate=(Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1")),
            verbatim_excerpt=excerpt,
        )
        rows.append((audit, citation, pages))
        if len(rows) == 3:
            break

    if len(rows) < 3:
        annual_coverage = next(
            (item for item in bundle.source_coverage if item.family == "annual_audit_pdf"),
            None,
        )
        if annual_coverage is not None:
            missing.extend(annual_coverage.missing_reasons)
        if not missing:
            missing.append(f"kam_annual_comparison:only_{len(rows)}_available")
    missing_reasons = tuple(dict.fromkeys(missing))
    years: list[KamAnnualTimeline] = []
    for index, (audit, citation, pages) in enumerate(rows):
        older = rows[index + 1][0] if index + 1 < len(rows) else None
        current_auditor = (audit.auditor_firm, audit.auditors)
        older_auditor = (
            (older.auditor_firm, older.auditors)
            if older is not None
            else None
        )
        full_text = " ".join(pages)
        opinion = audit.opinion_type
        years.append(
            KamAnnualTimeline(
                period=citation.period,
                citation=citation,
                kam_present=True,
                opinion_type=opinion,
                modified_opinion=None if opinion is None else opinion != "unmodified",
                going_concern="繼續經營有關之重大不確定性" in full_text,
                emphasis_matter="強調事項" in full_text,
                auditor_change=(
                    current_auditor != older_auditor if older_auditor is not None else None
                ),
            )
        )

    admitted = None
    rejection_reasons: tuple[str, ...]
    citations = tuple(item.citation for item in years)
    if not citations:
        rejection_reasons = ("kam_timeline_unavailable",)
    elif candidate_adapter is None:
        rejection_reasons = ("hermes_not_configured",)
    else:
        try:
            candidate = candidate_adapter.judge_kam(
                issuer_id=bundle.request.issuer_id,
                as_of=bundle.request.as_of,
                generation_id=generation_id,
                citations=citations,
            )
            admitted, rejection_reasons = admit_kam_judgement(
                candidate=candidate,
                issuer_id=bundle.request.issuer_id,
                citations=citations,
            )
        except Exception:
            rejection_reasons = ("hermes_unavailable",)
    complete = len(years) == 3 and admitted is not None
    return KamJudgement(
        generation_id=generation_id,
        status="available" if complete else "partial",
        coverage=SourceCoverage(
            family="kam_annual_comparison",
            required=3,
            available=len(years),
            missing_reasons=missing_reasons,
        ),
        years=tuple(years),
        missing_year_reasons=missing_reasons,
        change_summary=admitted.change_summary if admitted else None,
        risk_mechanism=admitted.risk_mechanism if admitted else None,
        counterevidence=admitted.counterevidence if admitted else None,
        severity=admitted.severity if admitted else None,
        confidence=admitted.confidence if admitted else None,
        monitoring=admitted.monitoring if admitted else None,
        invalidation=admitted.invalidation if admitted else None,
        rejection_reasons=rejection_reasons,
    )


def _with_hermes_candidates(
    *,
    report: SingleCompanyResearchReport,
    candidate_adapter: HermesCandidateAdapter | None,
) -> SingleCompanyResearchReport:
    if candidate_adapter is None:
        return replace(
            report,
            limitations=(
                *report.limitations,
                "Hermes候選抽取：partial (hermes_not_configured)。",
            ),
        )
    try:
        candidates = candidate_adapter.extract_candidates(
            issuer_id=report.request.issuer_id,
            as_of=report.request.as_of,
            generation_id=report.generation_id,
            citations=report.citations,
        )
        admission = admit_hermes_candidates(
            candidates=candidates,
            issuer_id=report.request.issuer_id,
            as_of=report.request.as_of,
            citations=report.citations,
        )
    except Exception:
        return replace(
            report,
            limitations=(
                *report.limitations,
                "Hermes候選抽取：partial (hermes_unavailable)。",
            ),
        )
    findings = tuple(
        Finding(
            finding_id=item.candidate_id,
            kind="fact",
            direction="context",
            statement=item.statement,
            materiality=Decimal("0"),
            evidence_ids=(item.evidence_id,),
            supporting_finding_ids=(),
            counter_finding_ids=(),
            counter_evidence_reason=None,
        )
        for item in admission.admitted
    )
    rejected = ",".join(item.reason for item in admission.rejected)
    status = "available" if not admission.rejected else "partial"
    detail = f"；typed_rejections={rejected}" if rejected else ""
    return build_single_company_research_report(
        request=report.request,
        generation_id=report.generation_id,
        generated_at=report.generated_at,
        citations=report.citations,
        source_coverage=report.source_coverage,
        downside=replace(report.downside, findings=(*report.downside.findings, *findings)),
        upside=report.upside,
        limitations=(
            *report.limitations,
            f"Hermes候選抽取：{status}{detail}。",
        ),
    )


def build_report_from_evidence(
    *,
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    generated_at: str,
    calibration: SingleCompanyProbabilityCalibration | None = None,
    calibration_unavailable_reason: str | None = None,
    candidate_adapter: HermesCandidateAdapter | None = None,
) -> SingleCompanyResearchReport:
    """Produce a valid conservative report without inventing unimplemented analysis."""

    try:
        generated = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise ReportOrchestrationError("invalid generated_at") from exc
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ReportOrchestrationError("generated_at must be timezone-aware")
    audit_available, audit_required = _coverage(bundle, "audit_or_review_pdf")
    annual_available, annual_required = _coverage(bundle, "annual_audit_pdf")
    positive, outperform = _probabilities(
        bundle, generation_id, calibration, calibration_unavailable_reason
    )
    detailed = build_detailed_analysis(bundle)
    if detailed.available:
        limitations = [
            *detailed.limitations,
            f"查核／核閱PDF coverage為{audit_available}/{audit_required}；年度查核PDF為{annual_available}/{annual_required}。",
        ]
        if positive.status != "formal":
            limitations.append("本generation沒有正式12個月報酬機率，Dashboard必須顯示unavailable。")
        report = build_single_company_research_report(
            request=bundle.request,
            generation_id=generation_id,
            generated_at=generated_at,
            citations=detailed.citations,
            source_coverage=bundle.source_coverage,
            downside=DownsideCase(
                generation_id=generation_id,
                status="research_only",
                headline=detailed.downside_headline,
                findings=detailed.downside_findings,
                twelve_month_drawdown_probability=_unavailable(
                    "未來12個月最大跌幅事件尚未正式校準。"
                ),
                confidence=detailed.downside_confidence,
            ),
            upside=UpsideCase(
                generation_id=generation_id,
                status="research_only",
                headline=detailed.upside_headline,
                findings=detailed.upside_findings,
                positive_return_probability=positive,
                benchmark_outperform_probability=outperform,
                confidence=detailed.upside_confidence,
            ),
            limitations=tuple(limitations),
        )
        return _with_hermes_candidates(
            report=report, candidate_adapter=candidate_adapter
        )

    citation = _citation(bundle)
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
    report = build_single_company_research_report(
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
    return _with_hermes_candidates(report=report, candidate_adapter=candidate_adapter)


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
    filing_store_root: Path | None = None,
) -> CompanyAnalysisResult:
    """Collect current evidence and bind the same generation to a report."""

    bundle = collect_company_evidence_bundle(
        identifier=identifier,
        requested_market=requested_market,
        as_of=as_of,
        retrieved_at=retrieved_at,
        output_root=output_root / "evidence",
        identity_sources=identity_sources,
        filing_store_root=filing_store_root,
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
    candidate_adapter = HermesApiCandidateAdapter.from_environment(generation_id)
    report = build_report_from_evidence(
        bundle=bundle,
        generation_id=generation_id,
        generated_at=generated_at,
        calibration=calibration,
        calibration_unavailable_reason=calibration_error,
        candidate_adapter=candidate_adapter,
    )
    kam_judgement = build_kam_judgement(
        bundle=bundle,
        generation_id=generation_id,
        candidate_adapter=candidate_adapter,
    )
    return CompanyAnalysisResult(
        generation_id=generation_id,
        identity=bundle.identity,
        evidence_status=bundle.status,
        source_coverage=bundle.source_coverage,
        kam_judgement=kam_judgement,
        research_report=report,
        probability_calibration=calibration,
        calibration_error=calibration_error,
        filing_store_stats=bundle.filing_store_stats,
    )


__all__ = [
    "CompanyAnalysisResult",
    "HermesApiCandidateAdapter",
    "KamAnnualTimeline",
    "KamJudgement",
    "ReportOrchestrationError",
    "admit_hermes_candidates",
    "build_report_from_evidence",
    "build_kam_judgement",
    "run_single_company_analysis",
]
