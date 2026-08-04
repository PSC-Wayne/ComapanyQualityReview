from __future__ import annotations

from datetime import datetime

import pytest

from company_quality.industry.primary_business import (
    AnnualReportDocument,
    build_primary_business_pit_observation,
    extract_product_revenue_evidence,
)


CANDIDATES = [
    {"node_code": "F800", "node_name": "電源 供應器"},
    {"node_code": "FB00", "node_name": "散熱模組"},
]


def _observation(rows):
    return build_primary_business_pit_observation(
        issuer_id="04329168",
        security_code="6203",
        market="TPEx",
        decision_date="2024-06-30",
        candidate_nodes=CANDIDATES,
        document=AnnualReportDocument(
            security_code="6203",
            report_year=2023,
            document_filename="2023_6203_20240531F04.pdf",
            available_at=datetime.fromisoformat("2024-05-01T09:30:00+08:00"),
            source_url=(
                "https://doc.twse.com.tw/server-java/t57sb01?"
                "step=1&kind=F&co_id=6203&year=113"
            ),
        ),
        categories=rows,
    )


def test_extracts_all_rows_and_maps_only_unique_normalized_exact_node_name() -> None:
    result = extract_product_revenue_evidence(
        pages=[
            (84, "公司沿革與電源產品說明"),
            (
                85,
                "產品別  營業收入比重\n"
                "電源供應器  60.00%\n"
                "散熱模組  30.00%\n"
                "PSU  10.00%\n"
                "合計  100.00%",
            ),
        ],
        candidate_nodes=CANDIDATES,
    )

    assert result.status == "extracted"
    assert [(row.category, row.revenue_share_pct, row.node_code) for row in result.rows] == [
        ("電源供應器", 60.0, "F800"),
        ("散熱模組", 30.0, "FB00"),
        ("PSU", 10.0, None),
    ]
    assert all(row.page == 85 for row in result.rows)
    assert result.rows[0].source_text == "電源供應器  60.00%"
    assert _observation(result.rows)["status"] == "attributed"


def test_preserves_dominant_unmapped_category_for_contract_exclusion() -> None:
    result = extract_product_revenue_evidence(
        pages=[
            (
                66,
                "產品類別 營收占比\n"
                "網通產品 64.00%\n"
                "電源供應器 36.00%\n"
                "總計 100.00%",
            )
        ],
        candidate_nodes=CANDIDATES,
    )

    assert [(row.category, row.node_code) for row in result.rows] == [
        ("網通產品", None),
        ("電源供應器", "F800"),
    ]
    assert _observation(result.rows)["status"] == "ambiguous"


def test_preserves_equal_mapped_rows_for_contract_tie_exclusion() -> None:
    result = extract_product_revenue_evidence(
        pages=[
            (
                72,
                "產品項目 營收比重\n"
                "電源供應器 50%\n"
                "散熱模組 50%\n"
                "合計 100%",
            )
        ],
        candidate_nodes=CANDIDATES,
    )

    assert [row.revenue_share_pct for row in result.rows] == [50.0, 50.0]
    assert _observation(result.rows)["status"] == "ambiguous"


@pytest.mark.parametrize(
    ("pages", "reason"),
    [
        ([], "no_text"),
        ([(1, ""), (2, "   \n\t")], "no_text"),
        ([(12, "本公司主要產品包括電源供應器，詳細資訊請見下文。")], "no_table"),
    ],
)
def test_scanned_empty_or_no_explicit_table_is_missing_evidence(pages, reason) -> None:
    result = extract_product_revenue_evidence(
        pages=pages,
        candidate_nodes=CANDIDATES,
    )

    assert result.status == "missing_evidence"
    assert result.reason == reason
    assert result.rows == ()


@pytest.mark.parametrize(
    "table",
    [
        "產品別 營業收入比重\n電源供應器 60%\n散熱模組 30%\n合計 90%",
        "產品別 營業收入比重\n電源供應器 60%\n散熱模組 --%\n合計 100%",
        "產品別 營業收入比重\n電源供應器 101%\n合計 100%",
    ],
)
def test_rejects_unreconciled_or_malformed_revenue_tables(table: str) -> None:
    result = extract_product_revenue_evidence(
        pages=[(85, table)],
        candidate_nodes=CANDIDATES,
    )

    assert result.status == "missing_evidence"
    assert result.reason == "malformed_table"
    assert result.rows == ()
