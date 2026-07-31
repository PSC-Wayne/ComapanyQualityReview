from pathlib import Path
from types import SimpleNamespace
from http.client import BadStatusLine

import pytest
import company_quality.company_analysis.evidence_bundle as evidence_bundle_module

from company_quality.company_analysis.evidence_bundle import (
    CompanyEvidenceBundleError,
    collect_company_evidence_bundle,
)
from company_quality.identity import OfficialIdentitySource
from company_quality.sources.financial import Period


AS_OF = "2026-07-29T12:00:00+08:00"
IDENTITY_SOURCE = OfficialIdentitySource(
    market="TWSE",
    url="https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    available_at="2026-07-28T00:00:00+08:00",
    rows=(
        {
            "security_code": "2330",
            "company_name": "台灣積體電路製造股份有限公司",
            "short_name": "台積電",
            "issuer_id": "22099131",
            "listing_date": "0831105",
        },
    ),
)


class FakeFinancialCollector:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.calls: list[Period] = []
        self.missing = missing or set()

    def collect_period(self, **kwargs):
        period = kwargs["period"]
        self.calls.append(period)
        if period.key in self.missing:
            raise RuntimeError("statement unavailable")
        return SimpleNamespace(
            status="available",
            artifacts=tuple(
                SimpleNamespace(
                    report=report,
                    market=kwargs["market"],
                    security_code=kwargs["security_code"],
                    issuer_id=kwargs["issuer_id"],
                    official_url="https://mops.twse.com.tw/official-statement",
                    available_at=kwargs["retrieved_at"],
                    path=Path(kwargs["output_root"]) / period.key / f"{report}.html",
                )
                for report in ("balance", "income", "cash_flow", "equity_changes")
            ),
            artifact_coverage=1.0,
        )


class FakeAuditCollector:
    def __init__(self, missing_pdf: set[str] | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self.missing_pdf = missing_pdf or set()

    def collect_period(self, **kwargs):
        key = f"{kwargs['roc_year']}Q{kwargs['quarter']}"
        self.calls.append((kwargs["roc_year"], kwargs["quarter"]))
        missing = key in self.missing_pdf
        return SimpleNamespace(
            market=kwargs["market"],
            security_code=kwargs["security_code"],
            issuer_id=kwargs["issuer_id"],
            receipt_url="https://mops.twse.com.tw/official-receipt",
            period=key,
            filing_type="annual_audit" if kwargs["quarter"] == 4 else "q1_review",
            official_filed_at="2026-03-10T17:00:00+08:00",
            available_at="2026-03-10T17:00:00+08:00",
            pdf_path=None if missing else Path(kwargs["output_root"]) / key / "report.pdf",
            pdf_sha256=None if missing else "a" * 64,
            mandatory_evidence_gaps=("mandatory_audit_evidence_missing",) if missing else (),
            coverage=2 / 3 if missing else 1,
        )


def _collect(tmp_path, *, financial=None, audit=None):
    return collect_company_evidence_bundle(
        identifier="2330",
        requested_market=None,
        as_of=AS_OF,
        output_root=tmp_path,
        identity_sources=(IDENTITY_SOURCE,),
        periods=tuple(
            Period(year, quarter)
            for year, quarter in (
                (110, 2), (110, 3), (110, 4),
                (111, 1), (111, 2), (111, 3), (111, 4),
                (112, 1), (112, 2), (112, 3), (112, 4),
                (113, 1), (113, 2), (113, 3), (113, 4),
                (114, 1), (114, 2), (114, 3), (114, 4),
                (115, 1),
            )
        ),
        financial_collector=financial or FakeFinancialCollector(),
        audit_collector=audit or FakeAuditCollector(),
        retrieved_at=AS_OF,
    )


def test_collects_twenty_quarters_and_five_annual_audit_pdfs(tmp_path) -> None:
    financial = FakeFinancialCollector()
    audit = FakeAuditCollector()

    bundle = _collect(tmp_path, financial=financial, audit=audit)

    assert bundle.status == "available"
    assert bundle.identity.security_code == "2330"
    assert bundle.identity.issuer_id == "22099131"
    assert len(bundle.periods) == 20
    assert len(financial.calls) == 20
    assert len(audit.calls) == 20
    assert sum(len(period.financial.artifacts) for period in bundle.periods) == 80
    assert [period.period for period in bundle.periods if period.is_annual] == [
        "110Q4", "111Q4", "112Q4", "113Q4", "114Q4"
    ]
    assert all(period.audit.pdf_sha256 for period in bundle.periods)
    coverage = {item.family: item for item in bundle.source_coverage}
    assert (coverage["three_statement_html"].available, coverage["three_statement_html"].required) == (60, 60)
    assert (coverage["equity_changes_html"].available, coverage["equity_changes_html"].required) == (20, 20)
    assert (coverage["audit_or_review_pdf"].available, coverage["audit_or_review_pdf"].required) == (20, 20)
    assert (coverage["annual_audit_pdf"].available, coverage["annual_audit_pdf"].required) == (5, 5)


def test_missing_period_is_partial_with_exact_coverage_reasons(tmp_path) -> None:
    bundle = _collect(
        tmp_path,
        financial=FakeFinancialCollector(missing={"112Q2"}),
        audit=FakeAuditCollector(missing_pdf={"113Q4"}),
    )

    assert bundle.status == "partial"
    coverage = {item.family: item for item in bundle.source_coverage}
    assert coverage["three_statement_html"].available == 57
    assert coverage["audit_or_review_pdf"].available == 19
    assert coverage["annual_audit_pdf"].available == 4
    assert any("112Q2" in reason for reason in coverage["three_statement_html"].missing_reasons)
    assert any("113Q4" in reason for reason in coverage["annual_audit_pdf"].missing_reasons)


def test_malformed_http_response_becomes_source_gap_not_bundle_failure(tmp_path) -> None:
    class BadTransportFinancialCollector(FakeFinancialCollector):
        def collect_period(self, **kwargs):
            if kwargs["period"].key == "112Q2":
                raise BadStatusLine("<!DOCTYPE HTML>")
            return super().collect_period(**kwargs)

    bundle = _collect(tmp_path, financial=BadTransportFinancialCollector())
    coverage = {item.family: item for item in bundle.source_coverage}
    assert bundle.status == "partial"
    assert coverage["three_statement_html"].available == 57
    assert any(
        "112Q2:three_statement_html:BadStatusLine" in reason
        for reason in coverage["three_statement_html"].missing_reasons
    )


def test_retries_one_transient_failure_for_each_annual_audit(
    tmp_path, monkeypatch
) -> None:
    class TransientAnnualAuditCollector(FakeAuditCollector):
        def __init__(self) -> None:
            super().__init__()
            self.attempts: dict[str, int] = {}

        def collect_period(self, **kwargs):
            key = f"{kwargs['roc_year']}Q{kwargs['quarter']}"
            self.attempts[key] = self.attempts.get(key, 0) + 1
            if kwargs["quarter"] == 4 and self.attempts[key] == 1:
                raise BadStatusLine("temporary MOPS response")
            return super().collect_period(**kwargs)

    monkeypatch.setattr(evidence_bundle_module.time, "sleep", lambda _: None)
    audit = TransientAnnualAuditCollector()
    bundle = _collect(tmp_path, audit=audit)

    coverage = {item.family: item for item in bundle.source_coverage}
    assert coverage["annual_audit_pdf"].available == 5
    assert all(audit.attempts[f"{year}Q4"] == 2 for year in range(110, 115))


def test_unresolved_identity_fails_before_collectors_are_called(tmp_path) -> None:
    financial = FakeFinancialCollector()
    audit = FakeAuditCollector()

    with pytest.raises(CompanyEvidenceBundleError, match="identity"):
        collect_company_evidence_bundle(
            identifier="9999",
            requested_market=None,
            as_of=AS_OF,
            output_root=tmp_path,
            identity_sources=(IDENTITY_SOURCE,),
            periods=(Period(115, 1),),
            financial_collector=financial,
            audit_collector=audit,
            retrieved_at=AS_OF,
        )

    assert financial.calls == []
    assert audit.calls == []


def test_wrong_issuer_artifact_is_a_typed_gap_and_never_enters_period_facts(
    tmp_path,
) -> None:
    class WrongIssuerFinancialCollector(FakeFinancialCollector):
        def collect_period(self, **kwargs):
            result = super().collect_period(**kwargs)
            for artifact in result.artifacts:
                artifact.issuer_id = "12345678"
            return result

    bundle = _collect(tmp_path, financial=WrongIssuerFinancialCollector())
    coverage = {item.family: item for item in bundle.source_coverage}

    assert bundle.status == "partial"
    assert coverage["three_statement_html"].available == 0
    assert all(period.financial is None for period in bundle.periods)
    assert all(
        "wrong_issuer_candidate" in reason
        for reason in coverage["three_statement_html"].missing_reasons
    )
