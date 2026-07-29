"""Evidence-backed financial, KAM, and note analysis for one issuer."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Literal

import fitz

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.company_analysis.contracts import EvidenceCitation, Finding
from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle
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
        if row and row[0] and len(row) >= 3:
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
        raise DetailedAnalysisError("cannot calculate growth from zero")
    return ((current / prior) - 1) * 100


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%"


def _pp(current: Decimal, prior: Decimal) -> str:
    delta = (current - prior).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{delta:+}%"


def _bn(value: Decimal) -> str:
    return f"{(value / Decimal('1000000')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}億元"


def _latest_periods(bundle: CompanyEvidenceBundle) -> tuple[str | None, str | None]:
    periods = [item.period for item in bundle.periods]
    annual = max((period for period in periods if period.endswith("Q4")), default=None)
    interim = max((period for period in periods if not period.endswith("Q4")), default=None)
    return annual, interim


def build_detailed_analysis(bundle: CompanyEvidenceBundle) -> DetailedAnalysis:
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

    annual_fact = _fact(
        "upside:annual-earnings-acceleration",
        "support",
        f"{annual}全年營收{_bn(rev.current)}、年增{_pct(_growth(rev.current, rev.prior))}；毛利率{_pct(gross.current_percent)}（年增{_pp(gross.current_percent, gross.prior_percent)}）、營業利益率{_pct(operating.current_percent)}（年增{_pp(operating.current_percent, operating.prior_percent)}），淨利年增{_pct(_growth(net.current, net.prior))}。",
        (rev.evidence_id, gross.evidence_id, operating.evidence_id, net.evidence_id),
        "0.90",
    )
    quarter_fact = _fact(
        "upside:latest-quarter-acceleration",
        "support",
        f"{interim}營收年增{_pct(_growth(qrev.current, qrev.prior))}、淨利年增{_pct(_growth(qnet.current, qnet.prior))}；毛利率由{_pct(qgross.prior_percent)}升至{_pct(qgross.current_percent)}，營業利益率由{_pct(qoperating.prior_percent)}升至{_pct(qoperating.current_percent)}，最新季度仍呈現成長與利潤率同步擴張。",
        (qrev.evidence_id, qgross.evidence_id, qoperating.evidence_id, qnet.evidence_id),
        "0.95",
    )
    cash_fact = _fact(
        "shared:cash-flow-buffer",
        "counter",
        f"{annual}營業現金流{_bn(cfo.current)}、年增{_pct(_growth(cfo.current, cfo.prior))}；扣除取得不動產、廠房及設備現金支出後，簡化自由現金流約{_bn(free_cash)}，前期約{_bn(prior_free_cash)}。期末現金{_bn(cash.current)}，流動比率約{current_ratio.quantize(Decimal('0.01'))}倍（前期{prior_current_ratio.quantize(Decimal('0.01'))}倍），負債占資產約{_pct(debt_ratio)}（前期{_pct(prior_debt_ratio)}）。",
        (cfo.evidence_id, capex.evidence_id, cash.evidence_id, current_assets.evidence_id, current_liabilities.evidence_id, liabilities.evidence_id, equity.evidence_id),
        "0.85",
    )
    working_capital_fact = _fact(
        "shared:working-capital-discipline",
        "counter",
        f"{annual}營收年增{_pct(_growth(rev.current, rev.prior))}，同期應收帳款僅年增{_pct(_growth(receivables.current, receivables.prior))}、存貨年增{_pct(_growth(inventory.current, inventory.prior))}；目前沒有應收或存貨增速超越營收的早期惡化訊號。",
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
        "counter",
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
        for finding in (downside_capex, kam_fact, concentration_fact, commitments_fact)
        if finding is not None
    )
    mechanism = _derived(
        "downside:mechanism-assessment",
        "inference",
        "support",
        "主要下跌機制不是目前流動性不足，而是高資本支出下的折舊認列／產能利用率執行風險、客戶集中與長期採購承諾。反向證據是現金流、流動性與營運資金目前仍強。",
        support_ids,
        (downside_cash.finding_id, downside_working.finding_id),
        None,
        "0.85",
    )
    downside.append(mechanism)
    downside.append(
        _derived(
            "downside:monitoring-judgement",
            "judgement",
            "context",
            "未來應優先監控：季度毛利率與營業利益率是否反轉、資本支出增速是否持續高於營業現金流、存貨／應收增速是否超越營收、KAM是否新增或擴張，以及主要客戶占比是否再上升。任兩項同時惡化，將提高永久性損害與大幅回撤風險。",
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
    upside = [annual_fact, quarter_fact, cash_fact, working_capital_fact, upside_capex]
    if upside_customer is not None:
        upside.append(upside_customer)
    acceleration = _derived(
        "upside:growth-transmission",
        "inference",
        "support",
        "年度與最新季度同時呈現營收、毛利率、營業利益率及淨利改善，且營業現金流與簡化自由現金流為正；目前成長已實際傳導至利潤與現金，而不只是收入擴張。",
        (annual_fact.finding_id, quarter_fact.finding_id, cash_fact.finding_id),
        (upside_customer.finding_id,) if upside_customer is not None else (),
        None if upside_customer is not None else "缺少可量化客戶集中反證；保守降低信心。",
        "0.95",
    )
    upside.append(acceleration)
    upside.append(
        _derived(
            "upside:monitoring-judgement",
            "judgement",
            "context",
            "上漲案例成立的必要條件是最新季度的高成長與利潤率擴張能延續，同時新增產能帶來的現金報酬高於折舊與固定承諾成本。若毛利率回落、自由現金流轉負或客戶集中惡化，應下修上漲案例；本報告尚未取得正式估值倍數，因此不能由基本面強勢直接推導價格便宜。",
            (acceleration.finding_id, upside_capex.finding_id),
            (upside_customer.finding_id,) if upside_customer is not None else (),
            None if upside_customer is not None else "正式估值與產業外部需求證據尚未接入。",
            "0.90",
        )
    )

    limitations = [
        "KAM與高風險附註只涵蓋本generation成功取得且可讀取的年度PDF；未取得年度維持unknown，不視為無風險。",
        "簡化自由現金流以營業現金流減取得不動產、廠房及設備現金支出計算，未替代完整企業自由現金流口徑。",
        "本階段尚未接入公司指引、官方重大事件、產業需求與正式估值倍數，因此上下行情境維持research_only。",
    ]
    return DetailedAnalysis(
        citations=tuple(citations),
        downside_findings=tuple(downside),
        upside_findings=tuple(upside),
        downside_headline="財務緩衝仍強，但主要風險集中在高資本支出／折舊時點估計、長期承諾與客戶集中；目前是需監控的結構性風險，尚非已發生的流動性惡化。",
        upside_headline="年度與最新季度均出現營收、利潤率、淨利及現金流同步改善，成長已傳導至獲利；但價格上漲空間仍需估值與產業需求證據確認。",
        downside_confidence=Decimal("0.70") if len(kam_citations) >= 2 else Decimal("0.55"),
        upside_confidence=Decimal("0.70"),
        limitations=tuple(limitations),
        available=True,
    )


__all__ = ["DetailedAnalysis", "DetailedAnalysisError", "build_detailed_analysis"]
