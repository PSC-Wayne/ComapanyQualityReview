import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

from company_quality.facts.financial import (
    FinancialFactConflictError,
    FinancialFactParseError,
    FinancialFactParser,
    SourceIntegrityError,
)
from company_quality.sources.financial import FinancialArtifact


def artifact(tmp_path: Path, report: str, body: str) -> FinancialArtifact:
    path = tmp_path / f"{report}.html"
    raw = body.encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    return FinancialArtifact(
        artifact_id=f"TWSE:2330:115Q2:{report}:{digest[:16]}",
        issuer_id="22099131",
        security_code="2330",
        market="TWSE",
        period="115Q2",
        report=report,
        official_url=f"https://mopsov.twse.com.tw/{report}",
        endpoint_scope="selected_company",
        content_sha256=digest,
        retrieved_at="2026-08-14T18:00:00+08:00",
        available_at="2026-08-14T18:00:00+08:00",
        availability_basis="first_successful_retrieval",
        official_filed_at=None,
        mime_type="text/html",
        path=path,
    )


def table(header: str, rows: list[tuple[str, str]]) -> str:
    data = "".join(f"<tr><td>{label}</td><td>{value}</td></tr>" for label, value in rows)
    return (
        "<html><body>單位：新台幣仟元<table><tr>"
        f"<th>會計項目</th><th>{header}</th></tr>"
        f"<tr><th></th><th>金額</th></tr>{data}</table></body></html>"
    )


def test_parses_core_three_statement_facts_with_source_lineage(tmp_path) -> None:
    balance = artifact(
        tmp_path,
        "balance",
        table(
            "115年06月30日",
            [
                ("現金及約當現金", "1,000"),
                ("應收帳款淨額", "200"),
                ("存貨", "300"),
                ("不動產、廠房及設備", "400"),
                ("資產總額", "2,000"),
                ("長期借款", "500"),
                ("負債總額", "800"),
                ("權益總額", "1,200"),
            ],
        ),
    )
    income = artifact(
        tmp_path,
        "income",
        table(
            "115年第2季",
            [
                ("營業收入合計", "900"),
                ("營業毛利（毛損）", "450"),
                ("營業利益（損失）", "300"),
                ("稅前淨利（淨損）", "280"),
                ("本期淨利（淨損）", "230"),
            ],
        ),
    )
    cash_flow = artifact(
        tmp_path,
        "cash_flow",
        table(
            "115年01月01日至115年06月30日",
            [
                ("營業活動之淨現金流入（流出）", "350"),
                ("投資活動之淨現金流入（流出）", "-200"),
                ("籌資活動之淨現金流入（流出）", "(50)"),
                ("取得不動產、廠房及設備", "-120"),
                ("期末現金及約當現金餘額", "1,000"),
            ],
        ),
    )

    result = FinancialFactParser().parse((balance, income, cash_flow))

    assert result.status == "available"
    assert result.fact_coverage == 1
    assert result.missing_concepts == ()
    facts = {fact.concept_id: fact for fact in result.facts}
    assert str(facts["balance.cash_and_cash_equivalents"].value) == "1000"
    assert str(facts["cash_flow.financing_cash_flow"].value) == "-50"
    assert facts["balance.total_assets"].period_start is None
    assert facts["balance.total_assets"].period_end == "2026-06-30"
    assert facts["income.revenue"].period_start == "2026-04-01"
    assert facts["income.revenue"].period_end == "2026-06-30"
    assert facts["cash_flow.operating_cash_flow"].period_start == "2026-01-01"
    assert facts["cash_flow.operating_cash_flow"].unit == "TWD_thousands"
    assert facts["income.net_income"].source_artifact_id == income.artifact_id
    assert facts["income.net_income"].source_table_index == 0
    assert facts["income.net_income"].source_row_index >= 2
    assert facts["income.net_income"].source_column_index == 1
    assert len(facts["income.net_income"].lineage_hash) == 64
    assert result.parser_version == "mops-html-core-facts.v1"
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"


def test_uses_target_quarter_column_not_ytd_or_comparative_column(tmp_path) -> None:
    body = """
    <html><body>單位：新台幣仟元<table>
      <tr><th>會計項目</th><th colspan="2">115年01月01日至115年06月30日</th><th colspan="2">115年第2季</th><th colspan="2">114年第2季</th></tr>
      <tr><th></th><th>金額</th><th>%</th><th>金額</th><th>%</th><th>金額</th><th>%</th></tr>
      <tr><td>營業收入合計</td><td>1,800</td><td>100</td><td>900</td><td>100</td><td>700</td><td>100</td></tr>
    </table></body></html>
    """

    result = FinancialFactParser().parse((artifact(tmp_path, "income", body),))

    revenue = next(f for f in result.facts if f.concept_id == "income.revenue")
    assert str(revenue.value) == "900"
    assert revenue.source_column_index == 3
    assert revenue.period_start == "2026-04-01"
    assert result.fact_coverage == Decimal("0.2")


def test_missing_concepts_are_explicit_and_not_filled_with_zero(tmp_path) -> None:
    result = FinancialFactParser().parse(
        (artifact(tmp_path, "balance", table("115年06月30日", [("資產總額", "2,000")])),)
    )

    assert result.status == "partial"
    assert result.fact_coverage == Decimal("0.125")
    assert "balance.cash_and_cash_equivalents" in result.missing_concepts
    assert all(fact.value != 0 for fact in result.facts)


def test_source_hash_mismatch_blocks_parsing(tmp_path) -> None:
    source = artifact(tmp_path, "balance", table("115年06月30日", [("資產總額", "2,000")]))
    source.path.write_text("tampered")

    with pytest.raises(SourceIntegrityError, match="hash mismatch"):
        FinancialFactParser().parse((source,))


def test_unknown_source_unit_is_not_silently_coerced(tmp_path) -> None:
    body = table("115年06月30日", [("資產總額", "2,000")]).replace(
        "單位：新台幣仟元", "單位：新台幣元"
    )

    with pytest.raises(FinancialFactParseError, match="source unit"):
        FinancialFactParser().parse((artifact(tmp_path, "balance", body),))


def test_duplicate_canonical_fact_is_blocked(tmp_path) -> None:
    source = artifact(
        tmp_path,
        "balance",
        table("115年06月30日", [("資產總額", "2,000"), ("資產總額", "2,000")]),
    )

    with pytest.raises(FinancialFactConflictError, match="duplicate canonical fact"):
        FinancialFactParser().parse((source,))
