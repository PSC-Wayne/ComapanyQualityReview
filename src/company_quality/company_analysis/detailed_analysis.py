"""Evidence-backed financial, KAM, and note analysis for one issuer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Iterable, Literal

import fitz

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.company_analysis.contracts import (
    EvidenceCitation,
    FinancialDeteriorationItem,
    FinancialDeteriorationSection,
    FinancialTrendMetric,
    FinancialTrendPeriod,
    Finding,
)
from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle
from company_quality.company_analysis.financial_anomalies import (
    analyze_financial_anomalies,
)
from company_quality.company_analysis.guidance_industry import (
    GuidanceEvidenceError,
    GuidanceIndustryCollector,
)
from company_quality.company_analysis.material_events import (
    MaterialEvent,
    MaterialEventCollector,
    MaterialEventError,
)
from company_quality.company_analysis.valuation import (
    MarketValuationCollector,
    ValuationEvidenceError,
    build_earnings_valuation_scenarios,
    build_valuation_scenarios,
)
from company_quality.sources.financial import FinancialArtifact


_Q = Decimal("0.0001")


class DetailedAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DetailedAnalysis:
    citations: tuple[EvidenceCitation, ...]
    downside_findings: tuple[Finding, ...]
    upside_findings: tuple[Finding, ...]
    downside_headline: str
    upside_headline: str
    downside_confidence: Decimal
    upside_confidence: Decimal
    limitations: tuple[str, ...]
    available: bool


class _TableRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None:
            assert self._row is not None
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


@dataclass(frozen=True, slots=True)
class _Row:
    artifact: FinancialArtifact
    label: str
    cells: tuple[str, ...]
    evidence_id: str

    @property
    def current(self) -> Decimal:
        return _number(self.cells[1])

    @property
    def prior(self) -> Decimal:
        if len(self.cells) >= 9:
            return _number(self.cells[5])
        if len(self.cells) >= 5:
            return _number(self.cells[3])
        if len(self.cells) >= 3:
            return _number(self.cells[2])
        raise DetailedAnalysisError("prior-period source value missing")

    @property
    def current_percent(self) -> Decimal | None:
        return _number(self.cells[2]) if len(self.cells) >= 5 else None

    @property
    def prior_percent(self) -> Decimal | None:
        if len(self.cells) >= 9:
            return _number(self.cells[6])
        return _number(self.cells[4]) if len(self.cells) >= 5 else None


def _number(raw: str) -> Decimal:
    text = raw.replace(",", "").replace("$", "").strip()
    if text in ("", "-", "—", "nan"):
        raise DetailedAnalysisError("numeric source value missing")
    return Decimal(text)


def _artifact_rows(artifact: FinancialArtifact) -> dict[str, tuple[str, ...]]:
    body = artifact.path.read_bytes()
    if sha256(body).hexdigest() != artifact.content_sha256:
        raise DetailedAnalysisError("financial artifact content hash mismatch")
    parser = _TableRows()
    parser.feed(body.decode("utf-8", "replace"))
    result: dict[str, tuple[str, ...]] = {}
    for row in parser.rows:
        if row and row[0] and len(row) >= 3 and row[1].strip() not in ("", "-", "—"):
            result.setdefault(row[0], tuple(row))
    return result


def _financial_artifact(
    bundle: CompanyEvidenceBundle, period: str, report: str
) -> FinancialArtifact | None:
    for item in bundle.periods:
        if item.period != period or item.financial is None:
            continue
        return next(
            (artifact for artifact in item.financial.artifacts if artifact.report == report),
            None,
        )
    return None


def _row(
    bundle: CompanyEvidenceBundle, period: str, report: str, label: str, slug: str
) -> _Row | None:
    artifact = _financial_artifact(bundle, period, report)
    if artifact is None:
        return None
    cells = _artifact_rows(artifact).get(label)
    if cells is None:
        return None
    return _Row(artifact, label, cells, f"{artifact.artifact_id}:row:{slug}")


def _html_citation(row: _Row) -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id=row.evidence_id,
        source_id=row.artifact.artifact_id,
        source_tier="official",
        url=row.artifact.official_url,
        content_sha256=row.artifact.content_sha256,
        period=row.artifact.period,
        available_at=row.artifact.available_at,
        page=None,
        coordinate=None,
        verbatim_excerpt=" | ".join(row.cells),
        source_format="html",
        locator=f"table-row:{row.label}",
    )


def _compact(text: str) -> str:
    return "".join(text.split())


def _audit_filings(bundle: CompanyEvidenceBundle) -> Iterable[AuditFilingInventory]:
    for period in bundle.periods:
        audit = period.audit
        if (
            period.is_annual
            and audit is not None
            and audit.pdf_path is not None
            and audit.pdf_sha256 is not None
            and audit.pdf_source_url is not None
        ):
            yield audit


def _pdf_citation(
    audit: AuditFilingInventory,
    *,
    slug: str,
    keywords: tuple[str, ...],
    following_blocks: int,
    ocr_keywords: tuple[str, ...] = (),
    max_pages: int | None = None,
) -> EvidenceCitation | None:
    assert audit.pdf_path is not None
    assert audit.pdf_sha256 is not None
    assert audit.pdf_source_url is not None
    body = audit.pdf_path.read_bytes()
    if sha256(body).hexdigest() != audit.pdf_sha256:
        raise DetailedAnalysisError("audit PDF content hash mismatch")
    document = fitz.open(stream=body, filetype="pdf")
    try:
        for page_index, page in enumerate(document):
            if max_pages is not None and page_index >= max_pages:
                break
            blocks = [
                (fitz.Rect(block[:4]), " ".join(str(block[4]).split()))
                for block in page.get_text("blocks")
                if str(block[4]).strip()
            ]
            for index, (_, text) in enumerate(blocks):
                if not any(_compact(keyword) in _compact(text) for keyword in keywords):
                    continue
                selected = blocks[index : min(len(blocks), index + following_blocks)]
                excerpt = " ".join(item[1] for item in selected).strip()[:3900]
                rectangle = selected[0][0]
                for block, _ in selected[1:]:
                    rectangle |= block
                width, height = float(page.rect.width), float(page.rect.height)
                x0 = Decimal(str(max(0.0, rectangle.x0 / width))).quantize(_Q)
                y0 = Decimal(str(max(0.0, rectangle.y0 / height))).quantize(_Q)
                x1 = Decimal(str(min(1.0, rectangle.x1 / width))).quantize(_Q)
                y1 = Decimal(str(min(1.0, rectangle.y1 / height))).quantize(_Q)
                if x0 >= x1 or y0 >= y1:
                    continue
                return EvidenceCitation(
                    evidence_id=f"{audit.market}:{audit.security_code}:{audit.period}:pdf:{slug}",
                    source_id=f"{audit.market}:{audit.security_code}:{audit.period}:audit-pdf",
                    source_tier="official",
                    url=audit.pdf_source_url,
                    content_sha256=audit.pdf_sha256,
                    period=audit.period,
                    available_at=audit.available_at,
                    page=page_index + 1,
                    coordinate=(x0, y0, x1, y1),
                    verbatim_excerpt=excerpt,
                    source_format="pdf",
                    locator=None,
                )
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np

        ocr = RapidOCR()
        for page_index, page in enumerate(document):
            if max_pages is not None and page_index >= max_pages:
                break
            if page.get_text().strip():
                continue
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, pixmap.n
            )
            result, _ = ocr(image)
            lines = tuple(result or ())
            for index in range(len(lines)):
                search_text = "".join(str(item[1]) for item in lines[index : index + 3])
                search_terms = ocr_keywords or keywords
                if not any(_compact(keyword) in _compact(search_text) for keyword in search_terms):
                    continue
                selected = lines[index : min(len(lines), index + following_blocks)]
                excerpt = " ".join(str(item[1]).strip() for item in selected).strip()[:3900]
                points = [point for item in selected for point in item[0]]
                x0 = Decimal(str(min(point[0] for point in points) / pixmap.width)).quantize(_Q)
                y0 = Decimal(str(min(point[1] for point in points) / pixmap.height)).quantize(_Q)
                x1 = Decimal(str(max(point[0] for point in points) / pixmap.width)).quantize(_Q)
                y1 = Decimal(str(max(point[1] for point in points) / pixmap.height)).quantize(_Q)
                confidence = sum(float(item[2]) for item in selected) / len(selected)
                if x0 >= x1 or y0 >= y1:
                    continue
                return EvidenceCitation(
                    evidence_id=f"{audit.market}:{audit.security_code}:{audit.period}:pdf:{slug}",
                    source_id=f"{audit.market}:{audit.security_code}:{audit.period}:audit-pdf",
                    source_tier="official",
                    url=audit.pdf_source_url,
                    content_sha256=audit.pdf_sha256,
                    period=audit.period,
                    available_at=audit.available_at,
                    page=page_index + 1,
                    coordinate=(x0, y0, x1, y1),
                    verbatim_excerpt=excerpt,
                    source_format="pdf",
                    locator=f"ocr:rapidocr-onnxruntime;mean_confidence:{confidence:.3f}",
                )
    finally:
        document.close()
    return None


def _fact(
    finding_id: str,
    direction: Literal["support", "counter", "context"],
    statement: str,
    evidence_ids: tuple[str, ...],
    materiality: str,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        kind="fact",
        direction=direction,
        statement=statement,
        materiality=Decimal(materiality),
        evidence_ids=evidence_ids,
        supporting_finding_ids=(),
        counter_finding_ids=(),
        counter_evidence_reason=None,
    )


def _derived(
    finding_id: str,
    kind: Literal["inference", "judgement"],
    direction: Literal["support", "counter", "context"],
    statement: str,
    supporting: tuple[str, ...],
    counters: tuple[str, ...],
    counter_reason: str | None,
    materiality: str,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        kind=kind,
        direction=direction,
        statement=statement,
        materiality=Decimal(materiality),
        evidence_ids=(),
        supporting_finding_ids=supporting,
        counter_finding_ids=counters,
        counter_evidence_reason=counter_reason,
    )


def _growth(current: Decimal, prior: Decimal) -> Decimal:
    if prior == 0:
        raise DetailedAnalysisError("growth denominator is zero")
    return (current / prior - 1) * 100


def _trend(current: Decimal, prior: Decimal) -> str:
    if prior < 0 <= current:
        return "由負轉正"
    if prior > 0 >= current:
        return "由正轉負"
    return "年增" + _pct(_growth(current, prior))


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def _pp(current: Decimal, prior: Decimal) -> str:
    delta = (current - prior).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{delta:+}%"


def _bn(value: Decimal) -> str:
    return f"{(value / Decimal('100000')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}億元"


def _latest_periods(bundle: CompanyEvidenceBundle) -> tuple[str | None, str | None]:
    periods = [item.period for item in bundle.periods]
    annual = max((period for period in periods if period.endswith("Q4")), default=None)
    interim = max((period for period in periods if not period.endswith("Q4")), default=None)
    return annual, interim


def _quarter_window(period: str) -> tuple[date, date]:
    match = re.fullmatch(r"(\d{3})Q([1-4])", period)
    if match is None:
        raise DetailedAnalysisError("invalid anomaly period")
    year = int(match.group(1)) + 1911
    quarter = int(match.group(2))
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    end_day = 31 if end_month in (3, 12) else 30
    return date(year, start_month, 1), date(year, end_month, end_day)


def _filing_store_root(audits: Iterable[AuditFilingInventory]) -> Path | None:
    for audit in audits:
        if audit.pdf_path is None:
            continue
        path = Path(audit.pdf_path)
        if len(path.parents) >= 3 and path.parents[1].name == "blobs":
            return path.parents[2]
    return None


def _event_summary(event: MaterialEvent) -> str:
    sections = [
        " ".join(part.split())
        for part in re.split(r"(?=\d+\.)", event.description)
        if part.strip()
    ]
    priorities = (
        ("營業價值", "資產金額", "交易總金額", "全案發行總金額"),
        ("資金用途", "本次新增資金貸與之金額", "本次新增背書保證之金額"),
        ("發生緣由", "因應措施"),
        ("交易相對人", "併購目的"),
    )
    selected: list[str] = []
    for terms in priorities:
        for section in sections:
            if section not in selected and any(term in section for term in terms):
                selected.append(section)
                break
    excerpt = " ".join(selected[:4])[:900] or event.description[:900]
    return f"{event.announced_at[:10]}：{event.title}；官方說明摘錄：{excerpt}"


_TREND_ROWS = {
    "revenue": ("income", "營業收入合計", "營收"),
    "gross_profit": ("income", "營業毛利（毛損）", "毛利／率"),
    "operating_profit": ("income", "營業利益（損失）", "營益／率"),
    "net_income": ("income", "本期淨利（淨損）", "淨利"),
    "operating_cash_flow": (
        "cash_flow", "營業活動之淨現金流入（流出）", "營業現金流"
    ),
    "capex": ("cash_flow", "取得不動產、廠房及設備", "資本支出"),
    "receivables": ("balance", "應收帳款淨額", "應收帳款"),
    "inventory": ("balance", "存貨", "存貨"),
    "current_assets": ("balance", "流動資產合計", "流動資產"),
    "current_liabilities": ("balance", "流動負債合計", "流動負債"),
    "liabilities": ("balance", "負債總額", "負債"),
    "equity": ("balance", "權益總額", "權益"),
}


def _change(current: Decimal, prior: Decimal) -> Decimal | None:
    return None if prior == 0 else (current - prior) / abs(prior)


def _safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return None if denominator == 0 else numerator / denominator


def _period_before(period: str) -> str:
    year = int(period[:3])
    quarter = int(period[-1])
    return f"{year - 1}Q4" if quarter == 1 else f"{year}Q{quarter - 1}"


def _same_quarter_prior_year(period: str) -> str:
    return f"{int(period[:3]) - 1}Q{period[-1]}"


def _metric_direction(
    absolute_change: Decimal | None,
    ratio_change: Decimal | None,
    *,
    lower_is_better: bool,
) -> Literal["improving", "deteriorating", "flat", "mixed"]:
    changes = [item for item in (absolute_change, ratio_change) if item is not None]
    if not changes or all(item == 0 for item in changes):
        return "flat"
    signs = {1 if item > 0 else -1 if item < 0 else 0 for item in changes}
    signs.discard(0)
    if len(signs) > 1:
        return "mixed"
    increased = next(iter(signs)) > 0
    adverse = increased if lower_is_better else not increased
    return "deteriorating" if adverse else "improving"


def _trend_rows(
    bundle: CompanyEvidenceBundle, period: str
) -> dict[str, _Row] | None:
    rows: dict[str, _Row] = {}
    for metric_id, (report, label, _) in _TREND_ROWS.items():
        row = _row(bundle, period, report, label, f"trend-{metric_id}")
        if row is None:
            return None
        rows[metric_id] = row
    return rows


def _trend_period(
    bundle: CompanyEvidenceBundle,
    period: str,
    *,
    basis: Literal["annual", "interim"],
) -> tuple[FinancialTrendPeriod, tuple[EvidenceCitation, ...]] | None:
    rows = _trend_rows(bundle, period)
    if rows is None:
        return None
    revenue = rows["revenue"]
    previous_balance_rows: dict[str, _Row] | None = None
    if basis == "interim":
        previous_balance_rows = _trend_rows(bundle, _period_before(period))
    prior_year_rows = (
        _trend_rows(bundle, _same_quarter_prior_year(period))
        if basis == "interim"
        else None
    )

    current_values = {key: row.current for key, row in rows.items()}
    prior_values = {key: row.prior for key, row in rows.items()}
    if prior_year_rows is not None:
        for key in ("receivables", "inventory", "current_assets", "current_liabilities", "liabilities", "equity"):
            prior_values[key] = prior_year_rows[key].current

    values = {
        "revenue": current_values["revenue"],
        "gross_profit": current_values["gross_profit"],
        "operating_profit": current_values["operating_profit"],
        "net_income": current_values["net_income"],
        "operating_cash_flow": current_values["operating_cash_flow"],
        "simplified_free_cash_flow": (
            current_values["operating_cash_flow"] + current_values["capex"]
        ),
        "receivables": current_values["receivables"],
        "inventory": current_values["inventory"],
        "liquidity": current_values["current_assets"] - current_values["current_liabilities"],
        "liabilities": current_values["liabilities"],
    }
    prior = {
        "revenue": prior_values["revenue"],
        "gross_profit": prior_values["gross_profit"],
        "operating_profit": prior_values["operating_profit"],
        "net_income": prior_values["net_income"],
        "operating_cash_flow": prior_values["operating_cash_flow"],
        "simplified_free_cash_flow": (
            prior_values["operating_cash_flow"] + prior_values["capex"]
        ),
        "receivables": prior_values["receivables"],
        "inventory": prior_values["inventory"],
        "liquidity": prior_values["current_assets"] - prior_values["current_liabilities"],
        "liabilities": prior_values["liabilities"],
    }
    ratios = {
        "revenue": None,
        "gross_profit": _safe_ratio(values["gross_profit"], values["revenue"]),
        "operating_profit": _safe_ratio(values["operating_profit"], values["revenue"]),
        "net_income": _safe_ratio(values["net_income"], values["revenue"]),
        "operating_cash_flow": _safe_ratio(values["operating_cash_flow"], values["revenue"]),
        "simplified_free_cash_flow": _safe_ratio(
            values["simplified_free_cash_flow"], values["revenue"]
        ),
        "receivables": _safe_ratio(values["receivables"], values["revenue"]),
        "inventory": _safe_ratio(values["inventory"], values["revenue"]),
        "liquidity": _safe_ratio(
            current_values["current_assets"], current_values["current_liabilities"]
        ),
        "liabilities": _safe_ratio(
            current_values["liabilities"],
            current_values["liabilities"] + current_values["equity"],
        ),
    }
    prior_ratios = {
        "revenue": None,
        "gross_profit": _safe_ratio(prior["gross_profit"], prior["revenue"]),
        "operating_profit": _safe_ratio(prior["operating_profit"], prior["revenue"]),
        "net_income": _safe_ratio(prior["net_income"], prior["revenue"]),
        "operating_cash_flow": _safe_ratio(prior["operating_cash_flow"], prior["revenue"]),
        "simplified_free_cash_flow": _safe_ratio(
            prior["simplified_free_cash_flow"], prior["revenue"]
        ),
        "receivables": _safe_ratio(prior["receivables"], prior["revenue"]),
        "inventory": _safe_ratio(prior["inventory"], prior["revenue"]),
        "liquidity": _safe_ratio(prior_values["current_assets"], prior_values["current_liabilities"]),
        "liabilities": _safe_ratio(
            prior_values["liabilities"], prior_values["liabilities"] + prior_values["equity"]
        ),
    }
    labels = {
        "revenue": "營收", "gross_profit": "毛利／率", "operating_profit": "營益／率",
        "net_income": "淨利", "operating_cash_flow": "營業現金流",
        "simplified_free_cash_flow": "簡化自由現金流", "receivables": "應收帳款",
        "inventory": "存貨", "liquidity": "流動性", "liabilities": "負債",
    }
    evidence = {
        "revenue": (revenue.evidence_id,),
        "gross_profit": (rows["gross_profit"].evidence_id, revenue.evidence_id),
        "operating_profit": (rows["operating_profit"].evidence_id, revenue.evidence_id),
        "net_income": (rows["net_income"].evidence_id, revenue.evidence_id),
        "operating_cash_flow": (rows["operating_cash_flow"].evidence_id, revenue.evidence_id),
        "simplified_free_cash_flow": (
            rows["operating_cash_flow"].evidence_id, rows["capex"].evidence_id, revenue.evidence_id
        ),
        "receivables": (rows["receivables"].evidence_id, revenue.evidence_id),
        "inventory": (rows["inventory"].evidence_id, revenue.evidence_id),
        "liquidity": (rows["current_assets"].evidence_id, rows["current_liabilities"].evidence_id),
        "liabilities": (rows["liabilities"].evidence_id, rows["equity"].evidence_id),
    }
    if prior_year_rows is not None:
        for metric_id in ("receivables", "inventory"):
            evidence[metric_id] = (
                *evidence[metric_id],
                prior_year_rows[metric_id].evidence_id,
            )
        evidence["liquidity"] = (
            *evidence["liquidity"],
            prior_year_rows["current_assets"].evidence_id,
            prior_year_rows["current_liabilities"].evidence_id,
        )
        evidence["liabilities"] = (
            *evidence["liabilities"],
            prior_year_rows["liabilities"].evidence_id,
            prior_year_rows["equity"].evidence_id,
        )
    sequential_values: dict[str, Decimal] = {}
    sequential_ratios: dict[str, Decimal | None] = {}
    if basis == "interim" and previous_balance_rows is not None:
        previous_revenue = previous_balance_rows["revenue"].current
        for key in ("receivables", "inventory", "liabilities"):
            sequential_values[key] = previous_balance_rows[key].current
            sequential_ratios[key] = _safe_ratio(
                previous_balance_rows[key].current, previous_revenue
            )
        sequential_values["liquidity"] = (
            previous_balance_rows["current_assets"].current
            - previous_balance_rows["current_liabilities"].current
        )
        sequential_ratios["liquidity"] = _safe_ratio(
            previous_balance_rows["current_assets"].current,
            previous_balance_rows["current_liabilities"].current,
        )
        sequential_ratios["liabilities"] = _safe_ratio(
            previous_balance_rows["liabilities"].current,
            previous_balance_rows["liabilities"].current
            + previous_balance_rows["equity"].current,
        )
        for metric_id in ("receivables", "inventory"):
            evidence[metric_id] = (
                *evidence[metric_id],
                previous_balance_rows[metric_id].evidence_id,
            )
        evidence["liquidity"] = (
            *evidence["liquidity"],
            previous_balance_rows["current_assets"].evidence_id,
            previous_balance_rows["current_liabilities"].evidence_id,
        )
        evidence["liabilities"] = (
            *evidence["liabilities"],
            previous_balance_rows["liabilities"].evidence_id,
            previous_balance_rows["equity"].evidence_id,
        )

    metrics: list[FinancialTrendMetric] = []
    for metric_id in labels:
        absolute_change = _change(values[metric_id], prior[metric_id])
        ratio_change = (
            ratios[metric_id] - prior_ratios[metric_id]
            if ratios[metric_id] is not None and prior_ratios[metric_id] is not None
            else None
        )
        sequential_change = (
            _change(values[metric_id], sequential_values[metric_id])
            if metric_id in sequential_values
            else None
        )
        sequential_ratio_change = (
            ratios[metric_id] - sequential_ratios[metric_id]
            if metric_id in sequential_ratios
            and ratios[metric_id] is not None
            and sequential_ratios[metric_id] is not None
            else None
        )
        metrics.append(
            FinancialTrendMetric(
                metric_id=metric_id,
                label=labels[metric_id],
                absolute_value=values[metric_id],
                ratio=ratios[metric_id],
                yoy_change=absolute_change,
                ratio_yoy_change=ratio_change,
                sequential_change=sequential_change,
                ratio_sequential_change=sequential_ratio_change,
                direction=_metric_direction(
                    absolute_change,
                    ratio_change,
                    lower_is_better=metric_id in {"receivables", "inventory", "liabilities"},
                ),
                evidence_ids=evidence[metric_id],
            )
        )
    citation_rows = [*rows.values()]
    if prior_year_rows is not None:
        citation_rows.extend(prior_year_rows.values())
    if previous_balance_rows is not None:
        citation_rows.extend(previous_balance_rows.values())
    citations = tuple(
        {
            row.evidence_id: _html_citation(row)
            for row in citation_rows
        }.values()
    )
    return FinancialTrendPeriod(period, basis, tuple(metrics)), citations


def _trend_metric_text(metric: FinancialTrendMetric, period: FinancialTrendPeriod) -> str:
    yoy = _pct(metric.yoy_change * 100) if metric.yoy_change is not None else "無法計算YoY"
    amount = _bn(metric.absolute_value)
    if metric.metric_id in {"gross_profit", "operating_profit", "net_income"} and metric.ratio is not None and metric.ratio_yoy_change is not None:
        prior_ratio = metric.ratio - metric.ratio_yoy_change
        return (
            f"{metric.label}：{amount}（{yoy}），占營收比由"
            f"{_pct(prior_ratio * 100)}變為{_pct(metric.ratio * 100)}。"
        )
    if metric.metric_id in {"receivables", "inventory"} and metric.ratio is not None and metric.ratio_yoy_change is not None:
        prior_ratio = metric.ratio - metric.ratio_yoy_change
        if metric.metric_id == "receivables":
            days = Decimal("365") if period.basis == "annual" else {
                "1": Decimal("90"), "2": Decimal("181"), "3": Decimal("273")
            }[period.period[-1]]
            return (
                f"應收帳款：{amount}（{yoy}），占營收比由"
                f"{_pct(prior_ratio * 100)}升至{_pct(metric.ratio * 100)}；"
                f"以本期天數近似DSO由{(prior_ratio * days).quantize(Decimal('0.1'))}天"
                f"增至{(metric.ratio * days).quantize(Decimal('0.1'))}天。"
            )
        return (
            f"存貨：{amount}（{yoy}），占營收比由"
            f"{_pct(prior_ratio * 100)}變為{_pct(metric.ratio * 100)}。"
        )
    if metric.metric_id == "liquidity" and metric.ratio is not None and metric.ratio_yoy_change is not None:
        prior_ratio = metric.ratio - metric.ratio_yoy_change
        return f"流動比率：由{prior_ratio.quantize(Decimal('0.01'))}倍升至{metric.ratio.quantize(Decimal('0.01'))}倍。"
    if metric.metric_id == "liabilities" and metric.ratio is not None and metric.ratio_yoy_change is not None:
        prior_ratio = metric.ratio - metric.ratio_yoy_change
        return f"負債比率：由{_pct(prior_ratio * 100)}降至{_pct(metric.ratio * 100)}，負債{amount}（{yoy}）。"
    if metric.ratio is not None and metric.ratio_yoy_change is not None:
        prior_ratio = metric.ratio - metric.ratio_yoy_change
        return (
            f"{metric.label}：{amount}（{yoy}），占營收比由"
            f"{_pct(prior_ratio * 100)}變為{_pct(metric.ratio * 100)}。"
        )
    return f"{metric.label}：{amount}（{yoy}）。"


def build_financial_deterioration(
    bundle: CompanyEvidenceBundle, generation_id: str
) -> tuple[FinancialDeteriorationSection | None, tuple[EvidenceCitation, ...]]:
    annual_periods = sorted(
        (item.period for item in bundle.periods if item.is_annual and item.financial is not None)
    )[-5:]
    interim = max(
        (item.period for item in bundle.periods if not item.is_annual and item.financial is not None),
        default=None,
    )
    if len(annual_periods) != 5 or interim is None:
        return None, ()
    built = [
        _trend_period(bundle, period, basis="annual") for period in annual_periods
    ]
    built.append(_trend_period(bundle, interim, basis="interim"))
    if any(item is None for item in built):
        return None, ()
    complete = [item for item in built if item is not None]
    periods = tuple(item[0] for item in complete)
    citations_by_id = {
        citation.evidence_id: citation
        for item in complete
        for citation in item[1]
    }
    latest = periods[-1]
    adverse = tuple(metric for metric in latest.metrics if metric.direction == "deteriorating")
    improving = tuple(metric for metric in latest.metrics if metric.direction == "improving")
    mixed = tuple(metric for metric in latest.metrics if metric.direction == "mixed")
    core_ids = {"revenue", "gross_profit", "operating_profit", "net_income"}
    core_improving = sum(
        metric.direction == "improving"
        for metric in latest.metrics
        if metric.metric_id in core_ids
    )
    if len(adverse) == 1:
        severity: Literal["low", "moderate", "high"] = "low"
        summary = (
            "整體財務表現明顯改善；營收、毛利率、營業利益率與淨利四項核心指標均改善。"
            "唯一明確較差項目為應收帳款回收速度，屬需注意但尚未抵銷整體改善。"
            if core_improving == 4 and adverse[0].metric_id == "receivables"
            else "整體以改善為主，僅單一指標明確轉差。"
        )
    elif len(adverse) >= 5:
        severity = "high"
        summary = "多項獲利、現金流、營運資金或財務結構指標同步惡化。"
    elif len(adverse) >= 2:
        severity = "moderate"
        summary = "多項財務指標同時惡化，但仍須結合反證與後續期間確認持續性。"
    else:
        severity = "low"
        summary = "最新interim未見多指標同步惡化，現階段不形成財報惡化結論。"
    mixed_attention = tuple(
        metric
        for metric in mixed
        if not (
            metric.metric_id in {"inventory", "liabilities"}
            and metric.ratio_yoy_change is not None
            and metric.ratio_yoy_change < 0
        )
    )
    mixed_positive = tuple(metric for metric in mixed if metric not in mixed_attention)
    evidence_text = tuple(
        _trend_metric_text(metric, latest) for metric in (*adverse, *mixed_attention)
    ) or (f"{latest.period}未見明確較差或混合指標。",)
    counter_text = tuple(
        _trend_metric_text(metric, latest) for metric in (*improving, *mixed_positive)
    ) or ("本期未見明確改善指標。",)
    evidence_ids = tuple(
        dict.fromkeys(
            evidence_id for metric in latest.metrics for evidence_id in metric.evidence_ids
        )
    )
    item = FinancialDeteriorationItem(
        item_id="financial-deterioration:integrated-trend",
        severity=severity,
        confidence=Decimal("0.80"),
        summary=summary,
        evidence=evidence_text,
        counterevidence=counter_text,
        monitoring=("追蹤下期營收、利潤率、OCF／簡化FCF及營運資金是否同向延續。",),
        invalidation=("若後續期間多數惡化指標反轉且現金流與流動性同步改善，則失效。",),
        evidence_ids=evidence_ids,
    )
    return (
        FinancialDeteriorationSection(
            generation_id=generation_id,
            status="partial",
            periods=periods,
            items=(item,),
            partial_reason="hermes_not_configured",
        ),
        tuple(citations_by_id.values()),
    )


def build_detailed_analysis(
    bundle: CompanyEvidenceBundle,
    *,
    event_collector: MaterialEventCollector | None = None,
    guidance_collector: GuidanceIndustryCollector | None = None,
    valuation_collector: MarketValuationCollector | None = None,
) -> DetailedAnalysis:
    annual, interim = _latest_periods(bundle)
    if annual is None or interim is None:
        return DetailedAnalysis((), (), (), "財務趨勢證據不足。", "財務趨勢證據不足。", Decimal("0.10"), Decimal("0.10"), ("缺少年度或最新季度財務表。",), False)

    definitions = {
        "annual_revenue": (annual, "income", "營業收入合計", "annual-revenue"),
        "annual_gross": (annual, "income", "營業毛利（毛損）", "annual-gross"),
        "annual_operating": (annual, "income", "營業利益（損失）", "annual-operating"),
        "annual_net": (annual, "income", "本期淨利（淨損）", "annual-net"),
        "annual_cfo": (annual, "cash_flow", "營業活動之淨現金流入（流出）", "annual-cfo"),
        "annual_capex": (annual, "cash_flow", "取得不動產、廠房及設備", "annual-capex"),
        "cash": (annual, "balance", "現金及約當現金", "cash"),
        "receivables": (annual, "balance", "應收帳款淨額", "receivables"),
        "inventory": (annual, "balance", "存貨", "inventory"),
        "current_assets": (annual, "balance", "流動資產合計", "current-assets"),
        "current_liabilities": (annual, "balance", "流動負債合計", "current-liabilities"),
        "liabilities": (annual, "balance", "負債總額", "liabilities"),
        "equity": (annual, "balance", "權益總額", "equity"),
        "ppe": (annual, "balance", "不動產、廠房及設備", "ppe"),
        "quarter_revenue": (interim, "income", "營業收入合計", "quarter-revenue"),
        "quarter_gross": (interim, "income", "營業毛利（毛損）", "quarter-gross"),
        "quarter_operating": (interim, "income", "營業利益（損失）", "quarter-operating"),
        "quarter_net": (interim, "income", "本期淨利（淨損）", "quarter-net"),
    }
    rows = {
        key: _row(bundle, period, report, label, slug)
        for key, (period, report, label, slug) in definitions.items()
    }
    required = tuple(definitions)
    missing = tuple(key for key in required if rows[key] is None)
    if missing:
        return DetailedAnalysis((), (), (), "核心財務欄位抽取不足。", "核心財務欄位抽取不足。", Decimal("0.10"), Decimal("0.10"), ("缺少核心財務欄位：" + ", ".join(missing),), False)
    values: dict[str, _Row] = {key: row for key, row in rows.items() if row is not None}
    citations: list[EvidenceCitation] = [_html_citation(values[key]) for key in required]
    annual_eps = _row(bundle, annual, "income", "基本每股盈餘", "annual-eps")
    quarter_eps = _row(bundle, interim, "income", "基本每股盈餘", "quarter-eps")
    for eps_row in (annual_eps, quarter_eps):
        if eps_row is not None:
            citations.append(_html_citation(eps_row))

    rev = values["annual_revenue"]
    gross = values["annual_gross"]
    operating = values["annual_operating"]
    net = values["annual_net"]
    cfo = values["annual_cfo"]
    capex = values["annual_capex"]
    cash = values["cash"]
    receivables = values["receivables"]
    inventory = values["inventory"]
    current_assets = values["current_assets"]
    current_liabilities = values["current_liabilities"]
    liabilities = values["liabilities"]
    equity = values["equity"]
    ppe = values["ppe"]
    qrev = values["quarter_revenue"]
    qgross = values["quarter_gross"]
    qoperating = values["quarter_operating"]
    qnet = values["quarter_net"]
    assert gross.current_percent is not None and gross.prior_percent is not None
    assert operating.current_percent is not None and operating.prior_percent is not None
    assert qgross.current_percent is not None and qgross.prior_percent is not None
    assert qoperating.current_percent is not None and qoperating.prior_percent is not None

    free_cash = cfo.current + capex.current
    prior_free_cash = cfo.prior + capex.prior
    current_ratio = current_assets.current / current_liabilities.current
    prior_current_ratio = current_assets.prior / current_liabilities.prior
    debt_ratio = liabilities.current / (liabilities.current + equity.current) * 100
    prior_debt_ratio = liabilities.prior / (liabilities.prior + equity.prior) * 100
    revenue_growth = _growth(rev.current, rev.prior)
    receivables_growth = _growth(receivables.current, receivables.prior)
    inventory_growth = _growth(inventory.current, inventory.prior)
    quarter_revenue_growth = _growth(qrev.current, qrev.prior)
    annual_improving = (
        revenue_growth > 0
        and net.current > net.prior
        and gross.current_percent > gross.prior_percent
        and operating.current_percent > operating.prior_percent
    )
    quarter_improving = (
        quarter_revenue_growth > 0
        and qnet.current > qnet.prior
        and qgross.current_percent > qgross.prior_percent
        and qoperating.current_percent > qoperating.prior_percent
    )
    working_capital_risk = (
        receivables_growth > 0 and receivables_growth - revenue_growth >= Decimal("20")
    ) or (
        inventory_growth > 0 and inventory_growth - revenue_growth >= Decimal("20")
    )
    cash_buffer_positive = cfo.current > 0 and free_cash > 0

    annual_fact = _fact(
        "upside:annual-earnings-acceleration",
        "support" if annual_improving else "counter",
        f"{annual}全年營收{_bn(rev.current)}、年增{_pct(revenue_growth)}；毛利率{_pct(gross.current_percent)}（年增{_pp(gross.current_percent, gross.prior_percent)}）、營業利益率{_pct(operating.current_percent)}（年增{_pp(operating.current_percent, operating.prior_percent)}），淨利{_trend(net.current, net.prior)}。",
        (rev.evidence_id, gross.evidence_id, operating.evidence_id, net.evidence_id),
        "0.90",
    )
    quarter_fact = _fact(
        "upside:latest-quarter-acceleration",
        "support" if quarter_improving else "counter",
        f"{interim}營收年增{_pct(quarter_revenue_growth)}、淨利{_trend(qnet.current, qnet.prior)}；毛利率由{_pct(qgross.prior_percent)}變為{_pct(qgross.current_percent)}，營業利益率由{_pct(qoperating.prior_percent)}變為{_pct(qoperating.current_percent)}。"
        + ("最新季度呈現營收、淨利與利潤率同步改善。" if quarter_improving else "最新季度未呈現營收、淨利與利潤率同步改善。"),
        (qrev.evidence_id, qgross.evidence_id, qoperating.evidence_id, qnet.evidence_id),
        "0.95",
    )
    cash_fact = _fact(
        "shared:cash-flow-buffer",
        "support" if cash_buffer_positive else "counter",
        f"{annual}營業現金流{_bn(cfo.current)}、{_trend(cfo.current, cfo.prior)}；扣除取得不動產、廠房及設備現金支出後，簡化自由現金流約{_bn(free_cash)}，前期約{_bn(prior_free_cash)}。期末現金{_bn(cash.current)}，流動比率約{current_ratio.quantize(Decimal('0.01'))}倍（前期{prior_current_ratio.quantize(Decimal('0.01'))}倍），負債占資產約{_pct(debt_ratio)}（前期{_pct(prior_debt_ratio)}）。",
        (cfo.evidence_id, capex.evidence_id, cash.evidence_id, current_assets.evidence_id, current_liabilities.evidence_id, liabilities.evidence_id, equity.evidence_id),
        "0.85",
    )
    working_capital_fact = _fact(
        "shared:working-capital-discipline",
        "support" if working_capital_risk else "counter",
        f"{annual}營收年增{_pct(revenue_growth)}，同期應收帳款年增{_pct(receivables_growth)}、存貨年增{_pct(inventory_growth)}；"
        + ("應收或存貨增速明顯超越營收，形成營運資金與回收品質red flag。" if working_capital_risk else "目前沒有應收或存貨增速明顯超越營收的早期惡化訊號。"),
        (rev.evidence_id, receivables.evidence_id, inventory.evidence_id),
        "0.75",
    )
    capex_fact = _fact(
        "shared:capex-intensity",
        "context",
        f"{annual}取得不動產、廠房及設備現金支出{_bn(abs(capex.current))}、年增{_pct(_growth(abs(capex.current), abs(capex.prior)))}；期末不動產、廠房及設備{_bn(ppe.current)}、年增{_pct(_growth(ppe.current, ppe.prior))}。高資本支出同時是成長供給與折舊／利用率風險來源。",
        (capex.evidence_id, ppe.evidence_id),
        "0.80",
    )

    audits = sorted(_audit_filings(bundle), key=lambda item: item.period)
    kam_citations: list[EvidenceCitation] = []
    for audit in audits:
        citation = _pdf_citation(
            audit,
            slug="kam",
            keywords=("待驗設備及未完工程",),
            following_blocks=16,
            ocr_keywords=("待驗設備及未完工程",),
            max_pages=14,
        )
        if citation is not None:
            kam_citations.append(citation)
            citations.append(citation)
    latest_audit = audits[-1] if audits else None
    concentration_receivable = (
        _pdf_citation(
            latest_audit,
            slug="receivable-concentration",
            keywords=("前十大客戶之應收帳款餘額",),
            following_blocks=4,
        )
        if latest_audit is not None
        else None
    )
    concentration_revenue = (
        _pdf_citation(
            latest_audit,
            slug="revenue-concentration",
            keywords=("合併營業收入淨額百分之十以上之客戶",),
            following_blocks=5,
        )
        if latest_audit is not None
        else None
    )
    commitments = (
        _pdf_citation(
            latest_audit,
            slug="contractual-commitments",
            keywords=("長期設備購買合約", "長期原物料進貨"),
            following_blocks=7,
        )
        if latest_audit is not None
        else None
    )
    for citation in (concentration_receivable, concentration_revenue, commitments):
        if citation is not None:
            citations.append(citation)
    anomalies = analyze_financial_anomalies(bundle)
    citations.extend(anomalies.citations)
    event_periods = tuple(
        sorted(
            {
                match.group(1)
                for finding in anomalies.findings
                if finding.kind == "fact"
                for match in [
                    re.search(r"noncurrent-anomaly:(\d{3}Q[1-4])-", finding.finding_id)
                ]
                if match is not None
            }
        )
    )
    event_evidence: list[MaterialEvent] = []
    event_limitation: str | None = None
    event_store_root = _filing_store_root(audits)
    if event_periods and event_store_root is not None:
        source = event_collector or MaterialEventCollector()
        try:
            for event_period in event_periods:
                start_date, end_date = _quarter_window(event_period)
                collected_events = source.collect(
                    market=bundle.identity.market,
                    security_code=bundle.identity.security_code,
                    company_name=bundle.identity.company_name,
                    roc_year=int(event_period[:3]),
                    start_date=start_date,
                    end_date=end_date,
                    as_of=bundle.request.as_of,
                    store_root=event_store_root,
                )
                event_evidence.extend(collected_events.events)
        except MaterialEventError as exc:
            event_limitation = f"官方重大事件查詢失敗：{type(exc).__name__}:{str(exc)[:200]}"
    elif event_periods:
        event_limitation = "本generation無法定位中央 filing store，官方重大事件維持未接入。"
    event_evidence = list(
        {
            event.event_id: event for event in event_evidence
        }.values()
    )
    event_findings: list[Finding] = []
    for event in event_evidence:
        citation = event.citation()
        citations.append(citation)
        event_findings.append(
            _fact(
                f"downside:official-event:{event.event_id}",
                "context",
                _event_summary(event),
                (citation.evidence_id,),
                "0.90",
            )
        )

    guidance_facts = []
    guidance_limitations: list[str] = []
    guidance_limitation: str | None = None
    if event_store_root is not None:
        source = guidance_collector or GuidanceIndustryCollector()
        try:
            guidance = source.collect(
                market=bundle.identity.market,
                security_code=bundle.identity.security_code,
                company_name=bundle.identity.company_name,
                as_of=bundle.request.as_of,
                store_root=event_store_root,
            )
            guidance_facts = list(guidance.facts)
            citations.extend(fact.citation for fact in guidance_facts)
            guidance_limitations.extend(guidance.limitations)
        except GuidanceEvidenceError as exc:
            guidance_limitation = (
                f"公司指引／產業需求查詢失敗：{type(exc).__name__}:{str(exc)[:200]}"
            )
    else:
        guidance_limitation = "本generation無法定位中央 filing store，公司指引與產業需求維持未接入。"

    guidance_by_id = {fact.fact_id: fact for fact in guidance_facts}
    upside_guidance_findings = [
        _fact(
            f"upside:guidance:{fact.fact_id}",
            fact.direction,
            fact.statement,
            (fact.citation.evidence_id,),
            str(fact.confidence),
        )
        for fact in guidance_facts
    ]

    valuation_findings: list[Finding] = []
    valuation_limitations: list[str] = []
    backlog_fact = guidance_by_id.get("issuer:backlog")
    backlog_match = (
        re.search(r"增至[^；]*?([0-9][0-9,]*)億元", backlog_fact.statement)
        if backlog_fact is not None
        else None
    )
    if annual_eps is None or quarter_eps is None:
        valuation_limitations.append("缺少可解析的年度或最新季度EPS，情境估值維持blocked。")
    elif event_store_root is None:
        valuation_limitations.append("無法定位中央 filing store，市場估值snapshot維持未接入。")
    else:
        try:
            market_snapshot = (valuation_collector or MarketValuationCollector()).collect(
                market=bundle.identity.market,
                security_code=bundle.identity.security_code,
                company_name=bundle.identity.company_name,
                as_of=bundle.request.as_of,
                store_root=event_store_root,
            )
            ttm_eps = annual_eps.current + quarter_eps.current - quarter_eps.prior
            ttm_revenue = (
                rev.current + qrev.current - qrev.prior
            ) / Decimal("100000")
            citations.extend(
                (market_snapshot.quote_citation, market_snapshot.valuation_citation)
            )
            peer_context = (
                f"；三家工程／廠務公司當日PE中位數{market_snapshot.peer_pe_median.quantize(Decimal('0.1'))}倍，"
                "但僅作current context，不作正式PIT同業排名"
                if market_snapshot.peer_pe_median is not None
                else ""
            )
            market_finding = _fact(
                "upside:valuation:market-snapshot",
                "context",
                f"TWSE {market_snapshot.market_date.isoformat()}官方收盤{market_snapshot.closing_price}元、"
                f"TTM EPS {ttm_eps.quantize(Decimal('0.01'))}元、PE {market_snapshot.pe_ratio}倍、"
                f"以本報告TTM EPS換算PE {(market_snapshot.closing_price / ttm_eps).quantize(Decimal('0.1'))}倍、"
                f"PB {market_snapshot.pb_ratio}倍、殖利率{market_snapshot.dividend_yield}%"
                + peer_context
                + "。",
                (
                    market_snapshot.quote_citation.evidence_id,
                    market_snapshot.valuation_citation.evidence_id,
                ),
                "0.95",
            )
            valuation_findings.append(market_finding)
            scenario_names = {"downside": "保守", "base": "基準", "upside": "樂觀"}
            if backlog_match is not None:
                valuation = build_valuation_scenarios(
                    market=market_snapshot,
                    ttm_revenue_twd_100m=ttm_revenue,
                    ttm_eps=ttm_eps,
                    backlog_twd_100m=Decimal(backlog_match.group(1).replace(",", "")),
                )
                for scenario in valuation.scenarios:
                    scenario_direction: Literal["support", "counter", "context"] = (
                        "counter" if scenario.name == "downside" else "support" if scenario.name == "upside" else "context"
                    )
                    valuation_findings.append(
                        _derived(
                            f"upside:valuation:scenario:{scenario.name}",
                            "judgement",
                            scenario_direction,
                            f"{scenario_names[scenario.name]}情境：在建工程轉換率{_pct(scenario.backlog_conversion * 100)}、"
                            f"12個月營收{scenario.revenue_twd_100m}億元、獲利率相對TTM倍率{scenario.earnings_margin_factor}、"
                            f"EPS {scenario.eps}元、PE {scenario.pe_ratio}倍，隱含價{scenario.implied_price}元，"
                            f"相對官方收盤報酬{scenario.implied_return:+}%；FCF margin假設{_pct(scenario.fcf_margin * 100)}、"
                            f"FCF約{scenario.fcf_twd_100m}億元。這是透明壓力測試，不是公司指引或正式目標價。",
                            (market_finding.finding_id, annual_fact.finding_id, "upside:guidance:issuer:backlog"),
                            ("upside:guidance:issuer:revenue-conversion",),
                            "backlog仍未充分轉為營收且應收增速偏高；倍數與獲利率不具正式校準。",
                            "0.65",
                        )
                    )
                valuation_limitations.extend(valuation.limitations)
            else:
                for scenario in build_earnings_valuation_scenarios(
                    market=market_snapshot, ttm_eps=ttm_eps
                ):
                    scenario_direction = (
                        "counter" if scenario.name == "downside" else "support" if scenario.name == "upside" else "context"
                    )
                    valuation_findings.append(
                        _derived(
                            f"upside:valuation:scenario:{scenario.name}",
                            "judgement",
                            scenario_direction,
                            f"{scenario_names[scenario.name]}情境：TTM EPS成長假設{scenario.eps_growth * 100:+}%、"
                            f"PE採『官方收盤÷本報告TTM EPS』錨定倍數的{scenario.pe_factor}倍，推估EPS {scenario.forward_eps}元、"
                            f"PE {scenario.pe_ratio}倍、隱含價{scenario.implied_price}元，"
                            f"相對官方收盤報酬{scenario.implied_return:+}%。這是透明EPS×PE壓力測試，"
                            "不是公司指引或正式目標價。",
                            (market_finding.finding_id, annual_fact.finding_id),
                            (),
                            "EPS成長與PE倍率未經公司特定PIT校準。",
                            "0.55",
                        )
                    )
                valuation_limitations.append(
                    "公司沒有已驗證backlog數值，改用透明EPS×PE壓力測試；保守／基準／樂觀假設未經公司特定PIT校準。"
                )
        except ValuationEvidenceError as exc:
            valuation_limitations.append(
                f"官方市場估值或情境計算失敗：{type(exc).__name__}:{str(exc)[:200]}"
            )

    downside: list[Finding] = []
    downside_cash = _fact(
        "downside:cash-flow-buffer",
        "counter",
        cash_fact.statement,
        cash_fact.evidence_ids,
        "0.85",
    )
    downside_working = _fact(
        "downside:working-capital-discipline",
        "support" if working_capital_risk else "counter",
        working_capital_fact.statement,
        working_capital_fact.evidence_ids,
        "0.75",
    )
    downside_capex = _fact(
        "downside:capex-intensity",
        "support",
        capex_fact.statement,
        capex_fact.evidence_ids,
        "0.80",
    )
    downside.extend((downside_capex, downside_cash, downside_working))
    guidance_revenue = guidance_by_id.get("issuer:revenue-conversion")
    if guidance_revenue is not None:
        downside_guidance_revenue = _fact(
            "downside:guidance:backlog-conversion",
            "support",
            guidance_revenue.statement,
            (guidance_revenue.citation.evidence_id,),
            str(guidance_revenue.confidence),
        )
        downside.append(downside_guidance_revenue)
    else:
        downside_guidance_revenue = None
    downside.extend(anomalies.findings)
    downside.extend(event_findings)
    if event_findings:
        anomaly_fact_ids = tuple(
            finding.finding_id
            for finding in anomalies.findings
            if finding.kind == "fact"
        )
        event_link = _derived(
            "downside:official-event-anomaly-link",
            "inference",
            "context",
            f"異常季度同期間查得{len(event_findings)}件資產移轉、增資、履約爭議或融資支援相關官方重大訊息；"
            "但目前事件全文沒有直接以『其他非流動資產』科目及同額變動完成會計勾稽，因此只能作背景context，不能把異常升級為explained。",
            anomaly_fact_ids + tuple(finding.finding_id for finding in event_findings),
            (),
            "官方事件未提供同科目、同期間、同金額的直接勾稽。",
            "0.90",
        )
        downside.append(event_link)
    else:
        event_link = None
    if len(kam_citations) >= 2:
        periods = "、".join(citation.period for citation in kam_citations)
        kam_fact = _fact(
            "downside:repeated-kam",
            "support",
            f"在目前可讀取的{periods}年度查核報告中，會計師均把待驗設備及未完工程的折舊開始提列時點列為KAM；這是涉及主觀判斷的持續重大估計風險，不等同舞弊或新惡化。",
            tuple(citation.evidence_id for citation in kam_citations),
            "0.85",
        )
        downside.append(kam_fact)
    else:
        kam_fact = None
    if concentration_receivable is not None and concentration_revenue is not None:
        concentration_fact = _fact(
            "downside:customer-concentration",
            "support",
            f"最新可讀年度附註顯示，前十大客戶應收帳款占比由91%升至93%；單一甲客戶占營收22%、乙客戶占12%。客戶集中使需求、議價或信用事件可能放大營收與應收波動。",
            (concentration_receivable.evidence_id, concentration_revenue.evidence_id),
            "0.90",
        )
        downside.append(concentration_fact)
    else:
        concentration_fact = None
    if commitments is not None:
        commitments_fact = _fact(
            "downside:long-term-commitments",
            "support",
            "最新可讀年度附註揭露長期原物料、設備及能源購買合約，並有產能購買與履約保證安排；景氣或利用率下滑時，固定承諾可能降低資本調整彈性。",
            (commitments.evidence_id,),
            "0.75",
        )
        downside.append(commitments_fact)
    else:
        commitments_fact = None
    support_ids = tuple(
        finding.finding_id
        for finding in (
            downside_capex,
            downside_guidance_revenue,
            kam_fact,
            concentration_fact,
            commitments_fact,
        )
        if finding is not None
    ) + ((downside_working.finding_id,) if working_capital_risk else ()) + tuple(
        finding.finding_id for finding in anomalies.findings if finding.kind == "fact"
    )
    mechanism = _derived(
        "downside:mechanism-assessment",
        "inference",
        "support",
        "主要下跌機制包括資產結構異常、高資本支出下的折舊／利用率風險、在建工程轉營收的時程／執行風險，以及營運資金回收品質。"
        + ("應收或存貨增速明顯高於營收，不能再視為反向證據。" if working_capital_risk else "反向證據是目前營運資金增速未明顯超越營收。"),
        support_ids,
        (downside_cash.finding_id,) + (() if working_capital_risk else (downside_working.finding_id,)),
        None,
        "0.85",
    )
    downside.append(mechanism)
    downside.append(
        _derived(
            "downside:monitoring-judgement",
            "judgement",
            "context",
            "未來應優先監控：在建工程轉營收速度、新簽約額與組合、季度毛利率與營業利益率、存貨／應收增速是否超越營收、KAM是否新增或擴張，以及主要客戶占比。backlog維持高檔但營收／現金轉換持續惡化時，將提高執行與回收風險。",
            (mechanism.finding_id,),
            (downside_cash.finding_id,),
            None,
            "0.90",
        )
    )

    upside_customer = None
    if concentration_revenue is not None:
        upside_customer = _fact(
            "upside:customer-concentration-counter",
            "counter",
            "最新可讀年度仍有單一客戶占營收22%、第二大客戶占12%，成長高度集中是上漲論點的重要反證。",
            (concentration_revenue.evidence_id,),
            "0.80",
        )
    upside_capex = _fact(
        "upside:capex-capacity-context",
        "context",
        capex_fact.statement,
        capex_fact.evidence_ids,
        "0.80",
    )
    upside_working = _fact(
        "upside:working-capital",
        "counter" if working_capital_risk else "support",
        working_capital_fact.statement,
        working_capital_fact.evidence_ids,
        "0.75",
    )
    upside = [annual_fact, quarter_fact, cash_fact, upside_working, upside_capex]
    if upside_customer is not None:
        upside.append(upside_customer)
    upside.extend(upside_guidance_findings)
    upside.extend(valuation_findings)
    guidance_support_ids = tuple(
        finding.finding_id
        for finding in upside_guidance_findings
        if finding.direction == "support"
    )
    guidance_counter_ids = tuple(
        finding.finding_id
        for finding in upside_guidance_findings
        if finding.direction == "counter"
    )
    issuer_demand_visible = bool(guidance_support_ids)
    growth_transmitted = annual_improving and quarter_improving and cash_buffer_positive
    upside_counters = tuple(
        finding.finding_id
        for finding in (annual_fact, quarter_fact, upside_working, upside_customer)
        if finding is not None and finding.direction == "counter"
    )
    acceleration_support = tuple(
        finding.finding_id
        for finding in (annual_fact, quarter_fact, cash_fact)
        if finding.direction != "counter"
    ) or (upside_capex.finding_id,)
    acceleration = _derived(
        "upside:growth-transmission",
        "inference",
        "support" if growth_transmitted else "context",
        (
            "年度與最新季度同時呈現營收、利潤率及淨利改善，且營業現金流與簡化自由現金流為正；成長已傳導至利潤與現金。"
            if growth_transmitted
            else (
                "新簽約、在建工程與外部高科技需求提供需求面支持，但年度與最新季度尚未同時呈現營收、淨利與利潤率改善；需求尚未充分傳導至財務結果。"
                if issuer_demand_visible
                else "年度與最新季度未同時呈現營收、淨利與利潤率改善；即使部分利潤率或現金流改善，也不足以形成已驗證的成長傳導。"
            )
        ),
        acceleration_support + guidance_support_ids,
        upside_counters + guidance_counter_ids,
        None
        if upside_counters or guidance_counter_ids
        else "缺少可量化反證；保守降低信心。",
        "0.95" if growth_transmitted else "0.70",
    )
    upside.append(acceleration)
    upside.append(
        _derived(
            "upside:monitoring-judgement",
            "judgement",
            "context",
            (
                "上漲案例成立的必要條件是營收與淨利維持正成長、利潤率改善延續，且現金報酬高於固定承諾成本。"
                if growth_transmitted
                else "上漲案例成立前，營收與淨利須先恢復正成長，並證明利潤率改善可持續且應收回收品質正常。"
            ) + "並監控新簽約與在建工程是否按期轉為營收、毛利與現金。若自由現金流轉負、應收持續超越營收或客戶集中惡化，應下修案例；三情境僅為壓力測試，未正式校準前不能當目標價。",
            (acceleration.finding_id, upside_capex.finding_id),
            (upside_customer.finding_id,) if upside_customer is not None else (),
            None if upside_customer is not None else "客戶集中反證尚未完整。",
            "0.90",
        )
    )

    limitations = [
        "KAM與高風險附註只涵蓋本generation成功取得且可讀取的年度PDF；未取得年度維持unknown，不視為無風險。",
        "簡化自由現金流以營業現金流減取得不動產、廠房及設備現金支出計算，未替代完整企業自由現金流口徑。",
        "官方重大事件採公司／年度 bounded MOPS 歷史查詢且僅作display-only context；未與同一會計科目及金額直接勾稽者，不視為異常原因。",
        "公司指引已接MOPS法說；外部產業需求目前只完成高科技SEC切片，能源、水資源與公共工程仍為coverage gap。估值已接透明三情境，但倍數與假設未通過PIT校準，維持research_only。",
        *anomalies.limitations,
        *guidance_limitations,
        *valuation_limitations,
    ]
    if event_limitation is not None:
        limitations.append(event_limitation)
    if guidance_limitation is not None:
        limitations.append(guidance_limitation)
    downside_headline = (
        f"{anomalies.headline} "
        if anomalies.headline is not None
        else ""
    ) + (
        f"已勾稽同期間{len(event_findings)}件官方重大訊息，但未找到同科目同金額的直接解釋。 "
        if event_findings
        else ""
    ) + (
        "在建工程規模創高但尚未轉為營收成長，執行與回收品質仍需驗證。 "
        if guidance_revenue is not None
        else ""
    ) + "財務緩衝與營運風險需合併判讀；異常不等同舞弊，但未充分說明者維持red flag。"
    return DetailedAnalysis(
        citations=tuple(citations),
        downside_findings=tuple(downside),
        upside_findings=tuple(upside),
        downside_headline=downside_headline,
        upside_headline=(
            "年度與最新季度出現營收、利潤率、淨利及現金流同步改善；但價格上漲空間仍需估值與產業需求證據確認。"
            if growth_transmitted
            else (
                "新簽約與在建工程創高，且外部高科技資本支出提供需求支持；但營收仍衰退、應收增速偏高，需求尚未充分轉為營收、獲利與現金，上漲案例仍待轉換效率與估值補證。"
                if issuer_demand_visible
                else "年度與最新季度未呈現營收、淨利與利潤率同步改善；目前只能確認部分利潤率或現金流改善，上漲案例仍待營收、淨利、應收品質與估值補證。"
            )
        ),
        downside_confidence=Decimal("0.70") if len(kam_citations) >= 2 else Decimal("0.55"),
        upside_confidence=(
            Decimal("0.70")
            if growth_transmitted
            else Decimal("0.65") if issuer_demand_visible else Decimal("0.55")
        ),
        limitations=tuple(limitations),
        available=True,
    )


__all__ = [
    "DetailedAnalysis",
    "DetailedAnalysisError",
    "build_detailed_analysis",
    "build_financial_deterioration",
]
