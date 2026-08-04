from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from company_quality.industry.primary_business import (
    AnnualReportDocument,
    PrimaryBusinessEvidenceError,
    ReportedRevenueCategory,
    build_primary_business_pit_observation,
    parse_mops_annual_report_listing,
    select_pre_decision_annual_report,
    validate_primary_business_pilot,
)


ARTIFACT = (
    Path(__file__).parents[2]
    / "artifacts"
    / "real_data"
    / "tpex-f000-primary-business-pilot.json"
)


def _payload() -> dict[str, object]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_official_pit_primary_business_pilot_is_bounded_and_evidence_backed() -> None:
    payload = _payload()
    summary = validate_primary_business_pilot(payload)

    assert summary == {
        "observation_count": 8,
        "attributed_count": 7,
        "ambiguous_count": 1,
        "missing_evidence_count": 0,
        "attributed_coverage": 0.875,
        "market_count": 2,
        "primary_node_count": 7,
        "scale_recommendation": "CONDITIONAL_SCALE_WITH_EXCLUSION",
    }
    rows = payload["observations"]
    assert isinstance(rows, list)
    attributed_nodes = {
        row["primary_child"]["node_code"]
        for row in rows
        if row["status"] == "attributed"
    }
    assert {"FM00", "FK00", "F600", "F800", "FB00", "FG00", "F500"} <= attributed_nodes
    assert {row["market"] for row in rows} == {"TWSE", "TPEx"}
    assert next(row for row in rows if row["security_code"] == "2376")["status"] == "ambiguous"
    assert payload["current_backfill_used"] is False


def test_ambiguous_observation_cannot_claim_a_primary_child() -> None:
    payload = deepcopy(_payload())
    rows = payload["observations"]
    assert isinstance(rows, list)
    ambiguous = next(row for row in rows if row["security_code"] == "2376")
    ambiguous["primary_child"] = {"node_code": "FM00", "node_name": "伺服器"}
    ambiguous["reported_revenue_share_pct"] = 64.27

    with pytest.raises(PrimaryBusinessEvidenceError, match="ambiguous/missing"):
        validate_primary_business_pilot(payload)


def test_mops_listing_selects_latest_report_available_by_decision_date() -> None:
    source = (
        "https://doc.twse.com.tw/server-java/t57sb01?step=1&kind=F&co_id=6203&year=114"
    )
    listing = """
    <table>
      <tr><td>6203</td><td>113 年</td><td>2023_6203_20240531F04.pdf</td>
          <td align='cetern'>113/05/01 09:30:00</td></tr>
      <tr><td>6203</td><td>114 年</td><td>2024_6203_20250613F04.pdf</td>
          <td align='cetern'>114/05/23 17:43:27</td></tr>
    </table>
    """.encode("big5")

    documents = parse_mops_annual_report_listing(
        listing, security_code="6203", source_url=source
    )
    selected = select_pre_decision_annual_report(
        documents, decision_date="2024-06-30"
    )

    assert [item.report_year for item in documents] == [2023, 2024]
    assert selected is not None
    assert selected.document_filename == "2023_6203_20240531F04.pdf"
    assert select_pre_decision_annual_report(
        documents, decision_date="2024-04-30"
    ) is None
    with pytest.raises(PrimaryBusinessEvidenceError, match="official MOPS"):
        parse_mops_annual_report_listing(
            listing, security_code="6203", source_url="https://example.com/report"
        )


def _document(code: str = "6203") -> AnnualReportDocument:
    return AnnualReportDocument(
        security_code=code,
        report_year=2023,
        document_filename=f"2023_{code}_20240531F04.pdf",
        available_at=datetime(
            2024, 5, 1, 9, 30, tzinfo=timezone(timedelta(hours=8))
        ),
        source_url=(
            "https://doc.twse.com.tw/server-java/t57sb01?"
            f"step=1&kind=F&co_id={code}&year=113"
        ),
    )


def test_primary_business_contract_attributes_direct_reported_revenue_without_fallback() -> None:
    result = build_primary_business_pit_observation(
        issuer_id="04329168",
        security_code="6203",
        market="TPEx",
        decision_date="2024-06-30",
        candidate_nodes=[
            {"node_code": "F800", "node_name": "電源供應器"},
            {"node_code": "FB00", "node_name": "散熱模組"},
        ],
        document=_document(),
        categories=[
            ReportedRevenueCategory("電源供應器", 98.34, "F800", 85, "年報產品營收表"),
            ReportedRevenueCategory("其他", 1.66, None, 85, "年報產品營收表"),
        ],
    )

    assert result["status"] == "attributed"
    assert result["primary_child"] == {"node_code": "F800", "node_name": "電源供應器"}
    assert result["reported_revenue_share_pct"] == 98.34
    assert result["model_excluded"] is False
    assert result["fallback_used"] is False
    assert result["current_backfill_used"] is False
    json.dumps(result, ensure_ascii=False)


def test_primary_business_contract_excludes_ambiguous_missing_and_unavailable_rows() -> None:
    common = {
        "issuer_id": "22044755",
        "security_code": "2376",
        "market": "TWSE",
        "decision_date": "2024-06-30",
        "candidate_nodes": [
            {"node_code": "F600", "node_name": "主機板"},
            {"node_code": "FM00", "node_name": "伺服器"},
        ],
    }
    ambiguous = build_primary_business_pit_observation(
        **common,
        document=_document("2376"),
        categories=[
            ReportedRevenueCategory("網通產品", 64.27, None, 66, "無法唯一映射候選節點"),
            ReportedRevenueCategory("電腦組件", 31.22, "F600", 66, "年報產品營收表"),
        ],
    )
    missing = build_primary_business_pit_observation(
        **common, document=_document("2376"), categories=[]
    )
    unavailable = build_primary_business_pit_observation(
        **common, document=None, categories=[]
    )

    assert [ambiguous["status"], missing["status"], unavailable["status"]] == [
        "ambiguous", "missing_evidence", "document_unavailable"
    ]
    for result in (ambiguous, missing, unavailable):
        assert result["primary_child"] is None
        assert result["model_excluded"] is True
        assert result["fallback_used"] is False
