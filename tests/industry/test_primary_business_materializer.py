from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from company_quality.industry.materialize_primary_business import materialize_primary_business_pit
from company_quality.sources.mops_annual_reports import (
    AnnualReportDocument,
    AnnualReportProbe,
    AnnualReportSourceState,
)


def _probe(code: str, state: AnnualReportSourceState, path: Path) -> AnnualReportProbe:
    base = AnnualReportProbe(
        security_code=code, report_year=2020, decision_date="2021-06-30", state=state,
        listing_url=f"https://doc.twse.com.tw/server-java/t57sb01?co_id={code}",
        request_count=1, detail=state.value,
    )
    if state is not AnnualReportSourceState.AVAILABLE:
        return base
    return replace(
        base,
        document=AnnualReportDocument(
            security_code=code, report_year=2020, filename=f"2020_{code}_F04.pdf",
            available_at="2021-05-01T09:00:00+08:00", listing_url=base.listing_url,
        ),
        pdf_path=path / f"{code}.pdf",
    )


class FakeAcquirer:
    def __init__(self, probes):
        self.probes = probes
        self.calls = []

    def acquire(self, security_code, report_year, decision_date):
        self.calls.append((security_code, report_year, decision_date))
        return self.probes[security_code]


def test_materializer_preserves_source_and_evidence_states_without_fallback(tmp_path: Path) -> None:
    codes = ["3001", "3002", "3003", "3004"]
    labels = pd.DataFrame([
        {
            "issuer_id": f"issuer-{code}", "security_code": code,
            "decision_date": "2021-06-30", "market": "TWSE" if code != "3002" else "TPEx",
            "fully_observed": True, "actual_total_return": 0.1,
            "official_benchmark_return": 0.02, "official_excess_return": 0.08,
            "official_industry_code": "25",
        }
        for code in codes
    ])
    memberships = pd.DataFrame([
        {
            "decision_date": "2021-06-30", "security_code": code, "chain_code": "F000",
            "node_code": "F800", "node_name": "電源供應器", "fresh_within_365d": True,
            "snapshot_timestamp": "20210101000000", "snapshot_age_days": 180,
            "source_url": "https://web.archive.org/official-f000",
        }
        for code in codes
    ])
    acquirer = FakeAcquirer({
        "3001": _probe("3001", AnnualReportSourceState.AVAILABLE, tmp_path),
        "3002": _probe("3002", AnnualReportSourceState.AVAILABLE, tmp_path),
        "3003": _probe("3003", AnnualReportSourceState.DOCUMENT_NOT_LISTED, tmp_path),
        "3004": _probe("3004", AnnualReportSourceState.SOURCE_UNAVAILABLE, tmp_path),
    })

    def pages(path: Path):
        if path.stem == "3001":
            return [(42, "產品別 營業收入比重\n電源供應器 100%\n合計 100%")]
        return [(1, "掃描文件無文字產品營收表")]

    payload = materialize_primary_business_pit(
        labels=labels, memberships=memberships, decision_dates=["2021-06-30"],
        acquirer=acquirer, page_text_provider=pages,
    )

    rows = payload["observations"]
    assert isinstance(rows, list)
    assert [row["status"] for row in rows] == [
        "attributed", "missing_evidence", "document_not_listed", "source_unavailable"
    ]
    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["attempted_count"] == 4
    assert summary["excluded_count"] == 3
    assert len(acquirer.calls) == 4
    assert all(call[1] == 2020 for call in acquirer.calls)
    assert payload["current_fill_used"] is False
    assert payload["fallback_used"] is False
    assert payload["pooling_used"] is False
    assert payload["final_oos_read"] is False
