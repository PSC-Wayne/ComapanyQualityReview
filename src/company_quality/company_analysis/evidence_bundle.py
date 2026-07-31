"""Collect one company's five-year official financial evidence bundle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
from pathlib import Path
import time
from typing import Literal, Protocol, Sequence
from zoneinfo import ZoneInfo

from company_quality.audit.inventory import (
    AuditArtifactConflictError,
    AuditFilingInventory,
    AuditSourceError,
    MopsAuditInventoryCollector,
)
from company_quality.company_analysis.contracts import (
    CompanyAnalysisRequest,
    SourceCoverage,
)
from company_quality.identity import (
    CompanyIdentity,
    OfficialIdentitySource,
    admit_artifact_identity,
    resolve_identity,
)
from company_quality.filing_store import FilingStore, FilingStoreStats
from company_quality.facts.financial import CanonicalFinancialFacts, FinancialFactParser
from company_quality.sources.financial import (
    ArtifactConflictError,
    MopsFinancialCollector,
    Period,
    PeriodCollection,
    SourceArtifactError,
    latest_published_period,
    trailing_quarters,
)
from company_quality.sources.monthly_revenue import (
    MonthlyRevenueArtifact,
    MonthlyRevenueError,
    MopsMonthlyRevenueCollector,
    RevenueMonth,
    trailing_months,
)


_TAIPEI = ZoneInfo("Asia/Taipei")
_EXPECTED_REPORTS = frozenset({"balance", "income", "cash_flow"})
_EXPECTED_EQUITY_REPORTS = frozenset({"equity_changes"})


class CompanyEvidenceBundleError(RuntimeError):
    """Raised when bundle-level prerequisites are not satisfied."""


class FinancialCollector(Protocol):
    def collect_period(self, **kwargs: object) -> PeriodCollection: ...


class AuditCollector(Protocol):
    def collect_period(self, **kwargs: object) -> AuditFilingInventory: ...


class MonthlyRevenueCollector(Protocol):
    def collect_month(self, **kwargs: object) -> MonthlyRevenueArtifact: ...


@dataclass(frozen=True, slots=True)
class PeriodEvidence:
    period: str
    is_annual: bool
    financial: PeriodCollection | None
    audit: AuditFilingInventory | None
    missing_reasons: tuple[str, ...]
    canonical_financial: CanonicalFinancialFacts | None = None


@dataclass(frozen=True, slots=True)
class CompanyEvidenceBundle:
    request: CompanyAnalysisRequest
    identity: CompanyIdentity
    retrieved_at: str
    periods: tuple[PeriodEvidence, ...]
    monthly_revenue: tuple[MonthlyRevenueArtifact, ...]
    source_coverage: tuple[SourceCoverage, ...]
    status: Literal["available", "partial", "blocked"]
    filing_store_stats: FilingStoreStats | None = None
    schema_version: Literal["CompanyEvidenceBundle.v2"] = "CompanyEvidenceBundle.v2"


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CompanyEvidenceBundleError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CompanyEvidenceBundleError(f"{field} must be timezone-aware")
    return result


def _periods(values: Sequence[Period] | None, identity: CompanyIdentity) -> tuple[Period, ...]:
    selected = tuple(values) if values is not None else trailing_quarters(
        latest_published_period(identity.market, identity.security_code)
    )
    if len(selected) != 20 or len({item.key for item in selected}) != 20:
        raise CompanyEvidenceBundleError("five-year bundle requires exactly 20 unique quarters")
    absolute = tuple(item.roc_year * 4 + item.quarter - 1 for item in selected)
    if absolute != tuple(range(absolute[0], absolute[0] + 20)):
        raise CompanyEvidenceBundleError("five-year bundle quarters must be contiguous and ordered")
    return selected


def _reason(prefix: str, period: Period, exc: BaseException) -> str:
    detail = " ".join(str(exc).split())[:300]
    return f"{period.key}:{prefix}:{type(exc).__name__}:{detail or 'no_detail'}"


def _month_reason(prefix: str, month: RevenueMonth, exc: BaseException) -> str:
    detail = " ".join(str(exc).split())[:300]
    return f"{month.key}:{prefix}:{type(exc).__name__}:{detail or 'no_detail'}"


def _latest_revenue_month(as_of: datetime) -> RevenueMonth:
    # Listed issuers normally file prior-month revenue by the 10th. A late
    # filing remains an explicit source gap rather than being treated as zero.
    offset = 1 if as_of.day >= 11 else 2
    absolute = as_of.year * 12 + as_of.month - 1 - offset
    year, zero_based_month = divmod(absolute, 12)
    return RevenueMonth(year - 1911, zero_based_month + 1)


def _coverage_reason(period: str, category: str, detail: str) -> str:
    return f"{period}:{category}:{detail}"


def collect_company_evidence_bundle(
    *,
    identifier: str,
    requested_market: Literal["TWSE", "TPEx"] | None,
    as_of: str,
    output_root: Path,
    identity_sources: Sequence[OfficialIdentitySource] | None = None,
    periods: Sequence[Period] | None = None,
    financial_collector: FinancialCollector | None = None,
    audit_collector: AuditCollector | None = None,
    monthly_revenue_collector: MonthlyRevenueCollector | None = None,
    revenue_months: Sequence[RevenueMonth] | None = None,
    retrieved_at: str | None = None,
    issuer_type: Literal[
        "domestic_general", "foreign_primary", "foreign_secondary"
    ] = "domestic_general",
    industry_type: Literal[
        "general", "financial_insurance", "other_regulated"
    ] = "general",
    filing_store_root: Path | None = None,
) -> CompanyEvidenceBundle:
    """Collect 20 quarters without converting source failures into false absence."""

    decision_time = _instant(as_of, "analysis as_of")
    retrieved = retrieved_at or datetime.now(_TAIPEI).isoformat(timespec="seconds")
    _instant(retrieved, "retrieved_at")
    resolution = resolve_identity(
        identifier,
        requested_market,
        as_of,
        sources=identity_sources,
    )
    if resolution.status != "resolved" or resolution.identity is None:
        raise CompanyEvidenceBundleError(
            f"official identity resolution failed: {resolution.status}"
        )
    identity = resolution.identity
    selected_periods = _periods(periods, identity)
    filing_store = FilingStore(filing_store_root) if filing_store_root is not None else None
    financial_source = financial_collector or MopsFinancialCollector(
        filing_store=filing_store
    )
    audit_source = audit_collector or MopsAuditInventoryCollector(filing_store=filing_store)
    revenue_source = monthly_revenue_collector or MopsMonthlyRevenueCollector(
        filing_store=filing_store
    )

    collected: list[PeriodEvidence] = []
    statement_missing: list[str] = []
    equity_missing: list[str] = []
    audit_missing: list[str] = []
    annual_missing: list[str] = []
    statement_count = 0
    equity_count = 0
    audit_pdf_count = 0
    annual_pdf_count = 0

    selected_revenue_months = (
        tuple(revenue_months)
        if revenue_months is not None
        else trailing_months(_latest_revenue_month(decision_time))
    )
    if len(selected_revenue_months) != 60 or len(set(selected_revenue_months)) != 60:
        raise CompanyEvidenceBundleError("monthly revenue requires exactly 60 unique months")
    monthly_revenue: list[MonthlyRevenueArtifact] = []
    monthly_revenue_missing: list[str] = []
    for month in selected_revenue_months:
        try:
            artifact = revenue_source.collect_month(
                security_code=identity.security_code,
                company_name=identity.company_name,
                company_short_name=identity.short_name,
                issuer_id=identity.issuer_id,
                market=identity.market,
                month=month,
                retrieved_at=retrieved,
                as_of=decision_time.isoformat(),
            )
            if _instant(artifact.available_at, "monthly revenue available_at") > decision_time:
                monthly_revenue_missing.append(
                    f"{month.key}:monthly_revenue_html:artifact_after_as_of"
                )
            else:
                monthly_revenue.append(artifact)
        except (
            MonthlyRevenueError,
            OSError,
            HTTPException,
            RuntimeError,
            ValueError,
        ) as exc:
            monthly_revenue_missing.append(
                _month_reason("monthly_revenue_html", month, exc)
            )

    collection_order = tuple(
        sorted(selected_periods, key=lambda item: (item.quarter != 4, item.roc_year, item.quarter))
    )
    for period in collection_order:
        reasons: list[str] = []
        financial: PeriodCollection | None = None
        try:
            candidate = financial_source.collect_period(
                security_code=identity.security_code,
                company_name=identity.company_name,
                company_short_name=identity.short_name,
                issuer_id=identity.issuer_id,
                market=identity.market,
                period=period,
                output_root=output_root / "financial_statements",
                retrieved_at=retrieved,
                as_of=decision_time.isoformat(),
            )
            reports = {artifact.report for artifact in candidate.artifacts}
            admissions = tuple(
                admit_artifact_identity(
                    identity,
                    artifact_market=artifact.market,
                    artifact_security_code=artifact.security_code,
                    artifact_issuer_id=artifact.issuer_id,
                    identity_evidence_url=artifact.official_url,
                )
                for artifact in candidate.artifacts
            )
            rejected = tuple(item for item in admissions if item.status == "rejected")
            future = tuple(
                artifact
                for artifact in candidate.artifacts
                if _instant(artifact.available_at, "financial artifact available_at")
                > decision_time
            )
            if rejected:
                reason = _coverage_reason(
                    period.key,
                    "three_statement_html",
                    rejected[0].reason,
                )
                statement_missing.append(reason)
                reasons.append(reason)
                equity_reason = _coverage_reason(
                    period.key, "equity_changes_html", rejected[0].reason
                )
                equity_missing.append(equity_reason)
                reasons.append(equity_reason)
            elif future:
                reason = _coverage_reason(
                    period.key, "three_statement_html", "artifact_after_as_of"
                )
                statement_missing.append(reason)
                reasons.append(reason)
                equity_reason = _coverage_reason(
                    period.key, "equity_changes_html", "artifact_after_as_of"
                )
                equity_missing.append(equity_reason)
                reasons.append(equity_reason)
            else:
                financial = candidate
                statement_count += len(reports & _EXPECTED_REPORTS)
                equity_count += len(reports & _EXPECTED_EQUITY_REPORTS)
                missing_reports = sorted(_EXPECTED_REPORTS - reports)
                if missing_reports:
                    reason = _coverage_reason(
                        period.key,
                        "three_statement_html",
                        "missing_" + "_".join(missing_reports),
                    )
                    statement_missing.append(reason)
                    reasons.append(reason)
                missing_equity = sorted(_EXPECTED_EQUITY_REPORTS - reports)
                if missing_equity:
                    reason = _coverage_reason(
                        period.key,
                        "equity_changes_html",
                        "missing_" + "_".join(missing_equity),
                    )
                    equity_missing.append(reason)
                    reasons.append(reason)
        except (
            SourceArtifactError,
            ArtifactConflictError,
            OSError,
            HTTPException,
            RuntimeError,
            ValueError,
        ) as exc:
            reason = _reason("three_statement_html", period, exc)
            statement_missing.append(reason)
            reasons.append(reason)
            equity_reason = _reason("equity_changes_html", period, exc)
            equity_missing.append(equity_reason)
            reasons.append(equity_reason)

        canonical_financial: CanonicalFinancialFacts | None = None
        if financial is not None:
            try:
                canonical_financial = FinancialFactParser().parse(financial.artifacts)
            except (OSError, RuntimeError, ValueError) as exc:
                reasons.append(_reason("canonical_financial_facts", period, exc))

        audit: AuditFilingInventory | None = None
        try:
            attempts = 2 if period.quarter == 4 else 1
            candidate_audit: AuditFilingInventory | None = None
            for attempt in range(attempts):
                try:
                    candidate_audit = audit_source.collect_period(
                        security_code=identity.security_code,
                        issuer_id=identity.issuer_id,
                        market=identity.market,
                        roc_year=period.roc_year,
                        quarter=period.quarter,
                        issuer_type=issuer_type,
                        industry_type=industry_type,
                        output_root=output_root / "audit_inventory",
                        retrieved_at=retrieved,
                        as_of=decision_time.isoformat(),
                    )
                    break
                except (AuditSourceError, OSError, HTTPException):
                    if attempt + 1 == attempts:
                        raise
                    time.sleep(2)
            if candidate_audit is None:
                raise RuntimeError("audit collector returned no result")
            audit_admission = admit_artifact_identity(
                identity,
                artifact_market=candidate_audit.market,
                artifact_security_code=candidate_audit.security_code,
                artifact_issuer_id=candidate_audit.issuer_id,
                identity_evidence_url=candidate_audit.receipt_url,
            )
            if audit_admission.status == "rejected":
                reason = _coverage_reason(
                    period.key,
                    "audit_or_review_pdf",
                    audit_admission.reason,
                )
                audit_missing.append(reason)
                reasons.append(reason)
                if period.quarter == 4:
                    annual_missing.append(reason)
            elif _instant(candidate_audit.available_at, "audit available_at") > decision_time:
                reason = _coverage_reason(
                    period.key, "audit_or_review_pdf", "filing_after_as_of"
                )
                audit_missing.append(reason)
                reasons.append(reason)
                if period.quarter == 4:
                    annual_missing.append(reason)
            else:
                audit = candidate_audit
                if candidate_audit.pdf_sha256 is not None and candidate_audit.pdf_path is not None:
                    audit_pdf_count += 1
                    if period.quarter == 4:
                        annual_pdf_count += 1
                else:
                    detail = "+".join(candidate_audit.mandatory_evidence_gaps) or "pdf_missing"
                    reason = _coverage_reason(period.key, "audit_or_review_pdf", detail)
                    audit_missing.append(reason)
                    reasons.append(reason)
                    if period.quarter == 4:
                        annual_missing.append(reason)
        except (
            AuditSourceError,
            AuditArtifactConflictError,
            OSError,
            HTTPException,
            RuntimeError,
            ValueError,
        ) as exc:
            reason = _reason("audit_or_review_pdf", period, exc)
            audit_missing.append(reason)
            reasons.append(reason)
            if period.quarter == 4:
                annual_missing.append(reason)

        collected.append(
            PeriodEvidence(
                period=period.key,
                is_annual=period.quarter == 4,
                financial=financial,
                audit=audit,
                missing_reasons=tuple(reasons),
                canonical_financial=canonical_financial,
            )
        )

    coverage = (
        SourceCoverage(
            family="three_statement_html",
            required=60,
            available=statement_count,
            missing_reasons=tuple(statement_missing),
        ),
        SourceCoverage(
            family="equity_changes_html",
            required=20,
            available=equity_count,
            missing_reasons=tuple(equity_missing),
        ),
        SourceCoverage(
            family="audit_or_review_pdf",
            required=20,
            available=audit_pdf_count,
            missing_reasons=tuple(audit_missing),
        ),
        SourceCoverage(
            family="annual_audit_pdf",
            required=5,
            available=annual_pdf_count,
            missing_reasons=tuple(annual_missing),
        ),
        SourceCoverage(
            family="monthly_revenue_html",
            required=60,
            available=len(monthly_revenue),
            missing_reasons=tuple(monthly_revenue_missing),
        ),
    )
    if statement_count == 0 and audit_pdf_count == 0:
        status: Literal["available", "partial", "blocked"] = "blocked"
    elif (
        statement_count == 60
        and equity_count == 20
        and audit_pdf_count == 20
        and annual_pdf_count == 5
        and len(monthly_revenue) == 60
    ):
        status = "available"
    else:
        status = "partial"
    period_rank = {period.key: index for index, period in enumerate(selected_periods)}
    collected.sort(key=lambda item: period_rank[item.period])
    return CompanyEvidenceBundle(
        request=CompanyAnalysisRequest(
            issuer_id=identity.issuer_id,
            security_code=identity.security_code,
            market=identity.market,
            as_of=decision_time.isoformat(),
        ),
        identity=identity,
        retrieved_at=retrieved,
        periods=tuple(collected),
        monthly_revenue=tuple(monthly_revenue),
        source_coverage=coverage,
        status=status,
        filing_store_stats=filing_store.stats() if filing_store is not None else None,
    )


__all__ = [
    "CompanyEvidenceBundle",
    "CompanyEvidenceBundleError",
    "PeriodEvidence",
    "collect_company_evidence_bundle",
]
