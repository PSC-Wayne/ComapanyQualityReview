"""Canonical financial facts parsed from PIT-admitted official MOPS artifacts."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Literal, Sequence

from company_quality.sources.financial import FinancialArtifact, Report

PARSER_VERSION = "mops-html-core-facts.v1"
SCHEMA_VERSION = "CanonicalFinancialFacts.v1"
FORMULA_VERSION = "direct-source-value.v1"
SOURCE_VERSION = "OfficialFinancialArtifacts.v1"
MODEL_VERSION = "no-rating-model.v1"
RATING_DISPOSITION = "NO_RATING_NOT_APPLICABLE"


class SourceIntegrityError(RuntimeError):
    pass


class FinancialFactConflictError(RuntimeError):
    pass


class FinancialFactParseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalFinancialFact:
    fact_id: str
    concept_id: str
    value: Decimal | None
    unit: Literal["TWD_thousands"]
    period_start: str | None
    period_end: str
    source_artifact_id: str
    source_artifact_sha256: str
    source_table_index: int
    source_row_index: int
    source_column_index: int
    source_label: str
    source_value: str
    available_at: str
    lineage_hash: str
    conflict_state: Literal["clear"]
    failure_reason: str | None
    parser_version: Literal["mops-html-core-facts.v1"] = PARSER_VERSION
    formula_version: Literal["direct-source-value.v1"] = FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class CanonicalFinancialFacts:
    status: Literal["available", "partial"]
    facts: tuple[CanonicalFinancialFact, ...]
    missing_concepts: tuple[str, ...]
    fact_coverage: Decimal
    parser_version: Literal["mops-html-core-facts.v1"] = PARSER_VERSION
    formula_version: Literal["direct-source-value.v1"] = FORMULA_VERSION
    source_version: Literal["OfficialFinancialArtifacts.v1"] = SOURCE_VERSION
    model_version: Literal["no-rating-model.v1"] = MODEL_VERSION
    schema_version: Literal["CanonicalFinancialFacts.v1"] = SCHEMA_VERSION
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = RATING_DISPOSITION


@dataclass(frozen=True, slots=True)
class _Cell:
    text: str
    colspan: int


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[_Cell]]] = []
        self._table: list[list[_Cell]] | None = None
        self._row: list[_Cell] | None = None
        self._cell_text: list[str] | None = None
        self._cell_colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            values = dict(attrs)
            try:
                self._cell_colspan = max(1, int(values.get("colspan") or "1"))
            except ValueError:
                self._cell_colspan = 1
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._cell_text is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell_text is not None and self._row is not None:
            text = " ".join("".join(self._cell_text).split())
            self._row.append(_Cell(text, self._cell_colspan))
            self._cell_text = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


_CONCEPTS: dict[Report, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "balance": (
        ("balance.cash_and_cash_equivalents", ("現金及約當現金",)),
        ("balance.accounts_receivable_net", ("應收帳款淨額",)),
        ("balance.inventories", ("存貨",)),
        ("balance.property_plant_equipment", ("不動產、廠房及設備",)),
        ("balance.total_assets", ("資產總額",)),
        ("balance.long_term_borrowings", ("長期借款",)),
        ("balance.total_liabilities", ("負債總額",)),
        ("balance.total_equity", ("權益總額",)),
    ),
    "income": (
        ("income.revenue", ("營業收入合計", "營業收入")),
        ("income.gross_profit", ("營業毛利（毛損）", "營業毛利（毛損）淨額")),
        ("income.operating_income", ("營業利益（損失）",)),
        (
            "income.profit_before_tax",
            (
                "本期稅前淨利（淨損）",
                "繼續營業單位稅前淨利（淨損）",
                "稅前淨利（淨損）",
            ),
        ),
        ("income.net_income", ("本期淨利（淨損）", "繼續營業單位本期淨利（淨損）")),
    ),
    "cash_flow": (
        ("cash_flow.operating_cash_flow", ("營業活動之淨現金流入（流出）",)),
        ("cash_flow.investing_cash_flow", ("投資活動之淨現金流入（流出）",)),
        ("cash_flow.financing_cash_flow", ("籌資活動之淨現金流入（流出）",)),
        ("cash_flow.acquisition_of_ppe", ("取得不動產、廠房及設備",)),
        ("cash_flow.ending_cash", ("期末現金及約當現金餘額",)),
    ),
    "equity_changes": (),
}
_EQUITY_COLUMNS = (
    ("equity.common_stock", "普通股股本"),
    ("equity.total_share_capital", "股本合計"),
    ("equity.capital_surplus", "資本公積"),
    ("equity.retained_earnings", "保留盈餘合計"),
    ("equity.treasury_stock", "庫藏股票"),
    ("equity.owners_equity", "歸屬於母公司業主之權益總計"),
    ("equity.non_controlling_interests", "非控制權益"),
    ("equity.total_equity", "權益總額"),
)
_PERIOD = re.compile(r"^(\d{2,3})Q([1-4])$")


def _expand(row: list[_Cell]) -> list[str]:
    return [cell.text for cell in row for _ in range(cell.colspan)]


def _target_header(report: Report, roc_year: int, quarter: int) -> str:
    end_month = quarter * 3
    end_day = calendar.monthrange(roc_year + 1911, end_month)[1]
    if report == "balance":
        return f"{roc_year}年{end_month:02d}月{end_day:02d}日"
    if report == "income":
        if quarter == 1:
            return f"{roc_year}年01月01日至{roc_year}年03月31日"
        if quarter == 4:
            return f"{roc_year}年度"
        return f"{roc_year}年第{quarter}季"
    if quarter == 4:
        return f"{roc_year}年度"
    return f"{roc_year}年01月01日至{roc_year}年{end_month:02d}月{end_day:02d}日"


def _dates(report: Report, roc_year: int, quarter: int) -> tuple[str | None, str]:
    year = roc_year + 1911
    end_month = quarter * 3
    end = f"{year:04d}-{end_month:02d}-{calendar.monthrange(year, end_month)[1]:02d}"
    if report == "balance":
        return None, end
    start_month = (
        1
        if report == "cash_flow" or (report == "income" and quarter in (1, 4))
        else (quarter - 1) * 3 + 1
    )
    return f"{year:04d}-{start_month:02d}-01", end


def _decimal(raw: str) -> tuple[Decimal | None, str | None]:
    value = raw.strip().replace(",", "")
    if value in ("", "-", "—", "--"):
        return None, "blank_source_value"
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    try:
        return Decimal(value), None
    except InvalidOperation as exc:
        raise FinancialFactParseError(f"invalid numeric source value: {raw}") from exc


def _lineage(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class FinancialFactParser:
    def parse(self, artifacts: Sequence[FinancialArtifact]) -> CanonicalFinancialFacts:
        if not artifacts:
            raise FinancialFactParseError("at least one artifact is required")
        reports = [artifact.report for artifact in artifacts]
        if len(reports) != len(set(reports)):
            raise FinancialFactConflictError("duplicate report artifact")

        facts: list[CanonicalFinancialFact] = []
        missing: list[str] = []
        expected = 0
        covered = 0
        canonical_keys: set[tuple[str, str | None, str]] = set()

        for artifact in artifacts:
            raw = artifact.path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != artifact.content_sha256:
                raise SourceIntegrityError(f"source artifact hash mismatch: {artifact.path}")
            text = raw.decode("utf-8", "replace")
            if "單位：新台幣仟元" not in text:
                raise FinancialFactParseError("unsupported or missing source unit")
            period_match = _PERIOD.fullmatch(artifact.period)
            if period_match is None:
                raise FinancialFactParseError(f"invalid artifact period: {artifact.period}")
            roc_year, quarter = map(int, period_match.groups())
            if artifact.report == "equity_changes":
                expected += len(_EQUITY_COLUMNS)
                equity_facts, equity_missing = self._parse_equity_changes(
                    artifact, text, digest, roc_year, quarter
                )
                for fact in equity_facts:
                    key = (fact.concept_id, fact.period_start, fact.period_end)
                    if key in canonical_keys:
                        raise FinancialFactConflictError(
                            f"duplicate canonical fact: {fact.concept_id}"
                        )
                    canonical_keys.add(key)
                facts.extend(equity_facts)
                covered += sum(item.value is not None for item in equity_facts)
                missing.extend(equity_missing)
                continue
            expected += len(_CONCEPTS[artifact.report])
            parser = _TableParser()
            parser.feed(text)
            table_index, table, header_index = self._financial_table(parser.tables)
            top = _expand(table[header_index])
            sub = _expand(table[header_index + 1])
            target = _target_header(artifact.report, roc_year, quarter)
            columns = [
                index
                for index, heading in enumerate(top)
                if heading == target and index < len(sub) and sub[index] == "金額"
            ]
            if len(columns) != 1:
                raise FinancialFactParseError(
                    f"target amount column is not unique for {artifact.report}: {target}"
                )
            column_index = columns[0]
            period_start, period_end = _dates(artifact.report, roc_year, quarter)
            rows = table[header_index + 2 :]

            for concept_id, aliases in _CONCEPTS[artifact.report]:
                selected: tuple[int, list[_Cell]] | None = None
                for alias in aliases:
                    matches = [
                        (header_index + 2 + offset, row)
                        for offset, row in enumerate(rows)
                        if row and row[0].text == alias
                    ]
                    if len(matches) > 1:
                        raise FinancialFactConflictError(
                            f"duplicate canonical fact source: {concept_id}"
                        )
                    if matches:
                        selected = matches[0]
                        break
                if selected is None:
                    missing.append(concept_id)
                    continue
                row_index, row = selected
                if column_index >= len(row):
                    raise FinancialFactParseError(
                        f"source row lacks target column: {concept_id}"
                    )
                key = (concept_id, period_start, period_end)
                if key in canonical_keys:
                    raise FinancialFactConflictError(
                        f"duplicate canonical fact: {concept_id}"
                    )
                canonical_keys.add(key)
                source_label = row[0].text
                source_value = row[column_index].text
                value, failure_reason = _decimal(source_value)
                if value is not None:
                    covered += 1
                else:
                    missing.append(concept_id)
                lineage_payload = {
                    "concept_id": concept_id,
                    "period_start": period_start,
                    "period_end": period_end,
                    "source_artifact_id": artifact.artifact_id,
                    "source_artifact_sha256": digest,
                    "table": table_index,
                    "row": row_index,
                    "column": column_index,
                    "source_label": source_label,
                    "source_value": source_value,
                    "parser_version": PARSER_VERSION,
                }
                lineage_hash = _lineage(lineage_payload)
                facts.append(
                    CanonicalFinancialFact(
                        fact_id=f"{artifact.issuer_id}:{concept_id}:{period_end}:{lineage_hash[:16]}",
                        concept_id=concept_id,
                        value=value,
                        unit="TWD_thousands",
                        period_start=period_start,
                        period_end=period_end,
                        source_artifact_id=artifact.artifact_id,
                        source_artifact_sha256=digest,
                        source_table_index=table_index,
                        source_row_index=row_index,
                        source_column_index=column_index,
                        source_label=source_label,
                        source_value=source_value,
                        available_at=artifact.available_at,
                        lineage_hash=lineage_hash,
                        conflict_state="clear",
                        failure_reason=failure_reason,
                    )
                )

        coverage = Decimal(covered) / Decimal(expected)
        ordered_facts = tuple(sorted(facts, key=lambda fact: fact.concept_id))
        ordered_missing = tuple(sorted(set(missing)))
        return CanonicalFinancialFacts(
            status="available" if coverage == 1 else "partial",
            facts=ordered_facts,
            missing_concepts=ordered_missing,
            fact_coverage=coverage,
        )

    @staticmethod
    def _parse_equity_changes(
        artifact: FinancialArtifact,
        text: str,
        digest: str,
        roc_year: int,
        quarter: int,
    ) -> tuple[list[CanonicalFinancialFact], list[str]]:
        current_marker = text.find("<b>本期</b>")
        prior_marker = text.find("<b>去年同期</b>")
        if current_marker < 0 or prior_marker <= current_marker:
            raise FinancialFactParseError("equity current/prior table markers missing")
        parser = _TableParser()
        parser.feed(text)
        candidates: list[tuple[int, list[list[_Cell]], int]] = []
        for table_index, table in enumerate(parser.tables):
            for row_index, row in enumerate(table):
                headings = _expand(row)
                if "會計項目" in headings and "權益總額" in headings:
                    candidates.append((table_index, table, row_index))
                    break
        if len(candidates) < 2:
            raise FinancialFactParseError("equity current/prior tables not found")
        table_index, table, header_index = candidates[0]
        headings = _expand(table[header_index])
        ending_rows = [
            (index, _expand(row))
            for index, row in enumerate(table)
            if _expand(row) and _expand(row)[0] == "期末餘額"
        ]
        if len(ending_rows) != 1:
            raise FinancialFactParseError("equity ending balance row is not unique")
        row_index, ending = ending_rows[0]
        year = roc_year + 1911
        end_month = quarter * 3
        period_start = f"{year:04d}-01-01"
        period_end = (
            f"{year:04d}-{end_month:02d}-"
            f"{calendar.monthrange(year, end_month)[1]:02d}"
        )
        result: list[CanonicalFinancialFact] = []
        missing: list[str] = []
        for concept_id, heading in _EQUITY_COLUMNS:
            columns = [index for index, value in enumerate(headings) if value == heading]
            if len(columns) != 1:
                missing.append(concept_id)
                continue
            column_index = columns[0]
            if column_index >= len(ending):
                raise FinancialFactParseError(
                    f"equity ending row lacks target column: {concept_id}"
                )
            source_value = ending[column_index]
            value, failure_reason = _decimal(source_value)
            if value is None:
                missing.append(concept_id)
            lineage_payload = {
                "concept_id": concept_id,
                "period_start": period_start,
                "period_end": period_end,
                "source_artifact_id": artifact.artifact_id,
                "source_artifact_sha256": digest,
                "table": table_index,
                "row": row_index,
                "column": column_index,
                "source_label": heading,
                "source_value": source_value,
                "parser_version": PARSER_VERSION,
            }
            lineage_hash = _lineage(lineage_payload)
            result.append(
                CanonicalFinancialFact(
                    fact_id=f"{artifact.issuer_id}:{concept_id}:{period_end}:{lineage_hash[:16]}",
                    concept_id=concept_id,
                    value=value,
                    unit="TWD_thousands",
                    period_start=period_start,
                    period_end=period_end,
                    source_artifact_id=artifact.artifact_id,
                    source_artifact_sha256=digest,
                    source_table_index=table_index,
                    source_row_index=row_index,
                    source_column_index=column_index,
                    source_label=heading,
                    source_value=source_value,
                    available_at=artifact.available_at,
                    lineage_hash=lineage_hash,
                    conflict_state="clear",
                    failure_reason=failure_reason,
                )
            )
        return result, missing

    @staticmethod
    def _financial_table(
        tables: list[list[list[_Cell]]],
    ) -> tuple[int, list[list[_Cell]], int]:
        matches = []
        for table_index, table in enumerate(tables):
            for row_index, row in enumerate(table):
                if any(cell.text == "會計項目" for cell in row):
                    matches.append((len(table), table_index, table, row_index))
        if not matches:
            raise FinancialFactParseError("financial statement table not found")
        _, table_index, table, header_index = max(matches, key=lambda item: item[0])
        if header_index + 1 >= len(table):
            raise FinancialFactParseError("financial statement amount header missing")
        return table_index, table, header_index
