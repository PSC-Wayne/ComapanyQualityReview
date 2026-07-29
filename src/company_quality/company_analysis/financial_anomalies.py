"""Cross-period balance-sheet anomaly detection and note explanation checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

import fitz

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.company_analysis.contracts import EvidenceCitation, Finding
from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle
from company_quality.sources.financial import FinancialArtifact


ExplanationStatus = Literal[
    "explained",
    "partially_explained",
    "unexplained_in_available_filings",
    "blocked_by_missing_evidence",
]
_Q = Decimal("0.0001")
_COMPONENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("不動產、廠房及設備", ("不動產、廠房及設備", "未完工程")),
    ("使用權資產", ("使用權資產", "租賃")),
    ("採用權益法之投資", ("採用權益法", "關聯企業", "合資")),
    ("投資性不動產淨額", ("投資性不動產",)),
    ("無形資產", ("無形資產", "商譽")),
    ("遞延所得稅資產", ("遞延所得稅資產",)),
    ("其他非流動資產", ("其他非流動資產",)),
)
_STRONG_CAUSAL_TERMS = (
    "主要係", "係因", "增加係", "減少係", "主因", "因收購", "因企業合併",
    "因重分類", "因新建", "因增建", "因購置", "因匯率", "因減損",
)


@dataclass(frozen=True, slots=True)
class FinancialAnomalyAnalysis:
    citations: tuple[EvidenceCitation, ...]
    findings: tuple[Finding, ...]
    limitations: tuple[str, ...]
    headline: str | None


class _Rows(HTMLParser):
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
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


@dataclass(frozen=True, slots=True)
class _Snapshot:
    period: str
    artifact: FinancialArtifact
    rows: dict[str, tuple[str, ...]]
    noncurrent: Decimal
    total_assets: Decimal
    components: dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class _Candidate:
    previous: _Snapshot
    current: _Snapshot
    growth: Decimal
    share_change: Decimal
    delta_share: Decimal
    contributor: str | None
    contributor_delta: Decimal | None


def _number(value: str) -> Decimal:
    return Decimal(value.replace(",", "").replace("$", "").strip())


def _period_rank(period: str) -> int:
    year, quarter = period.split("Q", 1)
    return int(year) * 4 + int(quarter)


def _balance_artifact(bundle: CompanyEvidenceBundle, period: str) -> FinancialArtifact | None:
    item = next((row for row in bundle.periods if row.period == period), None)
    if item is None or item.financial is None:
        return None
    return next(
        (artifact for artifact in item.financial.artifacts if artifact.report == "balance"),
        None,
    )


def _artifact_rows(artifact: FinancialArtifact) -> dict[str, tuple[str, ...]]:
    body = artifact.path.read_bytes()
    if sha256(body).hexdigest() != artifact.content_sha256:
        raise RuntimeError("balance artifact content hash mismatch")
    parser = _Rows()
    parser.feed(body.decode("utf-8", "replace"))
    return {
        row[0]: tuple(row)
        for row in parser.rows
        if len(row) >= 3 and row[0]
    }


def _find_row(rows: dict[str, tuple[str, ...]], label: str) -> tuple[str, ...] | None:
    if label in rows:
        return rows[label]
    return next((row for key, row in rows.items() if label in key), None)


def _snapshots(bundle: CompanyEvidenceBundle) -> tuple[_Snapshot, ...]:
    result: list[_Snapshot] = []
    for period in sorted((item.period for item in bundle.periods), key=_period_rank):
        artifact = _balance_artifact(bundle, period)
        if artifact is None:
            continue
        rows = _artifact_rows(artifact)
        noncurrent_row = _find_row(rows, "非流動資產合計")
        total_row = _find_row(rows, "資產總額")
        if noncurrent_row is None or total_row is None:
            continue
        components: dict[str, Decimal] = {}
        for label, _ in _COMPONENTS:
            row = _find_row(rows, label)
            if row is not None:
                components[label] = _number(row[1])
        result.append(
            _Snapshot(
                period=period,
                artifact=artifact,
                rows=rows,
                noncurrent=_number(noncurrent_row[1]),
                total_assets=_number(total_row[1]),
                components=components,
            )
        )
    return tuple(result)


def _candidates(snapshots: tuple[_Snapshot, ...]) -> tuple[_Candidate, ...]:
    result: list[_Candidate] = []
    for previous, current in zip(snapshots, snapshots[1:]):
        if previous.noncurrent == 0 or previous.total_assets == 0 or current.total_assets == 0:
            continue
        delta = current.noncurrent - previous.noncurrent
        growth = delta / abs(previous.noncurrent) * 100
        prior_share = previous.noncurrent / previous.total_assets * 100
        current_share = current.noncurrent / current.total_assets * 100
        share_change = current_share - prior_share
        delta_share = abs(delta) / current.total_assets * 100
        if abs(growth) < 20 or (delta_share < 5 and abs(share_change) < 5):
            continue
        component_deltas = {
            label: current.components[label] - previous.components[label]
            for label in current.components.keys() & previous.components.keys()
        }
        contributor = max(component_deltas, key=lambda key: abs(component_deltas[key]), default=None)
        result.append(
            _Candidate(
                previous=previous,
                current=current,
                growth=growth,
                share_change=share_change,
                delta_share=delta_share,
                contributor=contributor,
                contributor_delta=component_deltas.get(contributor) if contributor else None,
            )
        )
    result.sort(key=lambda item: (abs(item.share_change), abs(item.growth)), reverse=True)
    return tuple(result[:3])


def _html_citation(snapshot: _Snapshot, label: str, slug: str) -> EvidenceCitation:
    row = _find_row(snapshot.rows, label)
    if row is None:
        raise RuntimeError(f"balance row missing: {label}")
    return EvidenceCitation(
        evidence_id=f"{snapshot.artifact.artifact_id}:anomaly:{slug}",
        source_id=snapshot.artifact.artifact_id,
        source_tier="official",
        url=snapshot.artifact.official_url,
        content_sha256=snapshot.artifact.content_sha256,
        period=snapshot.period,
        available_at=snapshot.artifact.available_at,
        page=None,
        coordinate=None,
        verbatim_excerpt=" | ".join(row),
        source_format="html",
        locator=f"table-row:{row[0]}",
    )


def _audit_for_period(
    bundle: CompanyEvidenceBundle, period: str
) -> AuditFilingInventory | None:
    item = next((row for row in bundle.periods if row.period == period), None)
    if item is None:
        return None
    audit = item.audit
    if audit is None or audit.pdf_path is None or audit.pdf_sha256 is None:
        return None
    return audit


def _note_assessment(
    audit: AuditFilingInventory | None,
    contributor: str | None,
    slug: str,
) -> tuple[ExplanationStatus, EvidenceCitation | None, str]:
    if audit is None or contributor is None or audit.pdf_source_url is None:
        return "blocked_by_missing_evidence", None, "同期間查核／核閱PDF或主要貢獻科目缺漏"
    assert audit.pdf_path is not None and audit.pdf_sha256 is not None
    body = audit.pdf_path.read_bytes() if audit.pdf_path is not None else b""
    if sha256(body).hexdigest() != audit.pdf_sha256:
        return "blocked_by_missing_evidence", None, "PDF hash驗證失敗"
    document = fitz.open(stream=body, filetype="pdf")
    try:
        searchable_pages = sum(bool(page.get_text().strip()) for page in document)
        coverage = searchable_pages / len(document) if document else 0
        if coverage < 0.50:
            return "blocked_by_missing_evidence", None, "PDF可搜尋文字coverage不足50%"
        keywords = next((terms for label, terms in _COMPONENTS if label == contributor), (contributor,))
        partial: EvidenceCitation | None = None
        for page_index, page in enumerate(document):
            blocks = [
                (fitz.Rect(block[:4]), " ".join(str(block[4]).split()))
                for block in page.get_text("blocks")
                if str(block[4]).strip()
            ]
            for index, (_, text) in enumerate(blocks):
                if not any(keyword in text for keyword in keywords):
                    continue
                selected = blocks[max(0, index - 1) : min(len(blocks), index + 8)]
                excerpt = " ".join(item[1] for item in selected).strip()[:3900]
                rectangle = selected[0][0]
                for block, _ in selected[1:]:
                    rectangle |= block
                width, height = float(page.rect.width), float(page.rect.height)
                coordinate = (
                    Decimal(str(max(0.0, rectangle.x0 / width))).quantize(_Q),
                    Decimal(str(max(0.0, rectangle.y0 / height))).quantize(_Q),
                    Decimal(str(min(1.0, rectangle.x1 / width))).quantize(_Q),
                    Decimal(str(min(1.0, rectangle.y1 / height))).quantize(_Q),
                )
                citation = EvidenceCitation(
                    evidence_id=f"{audit.market}:{audit.security_code}:{audit.period}:pdf:anomaly:{slug}",
                    source_id=f"{audit.market}:{audit.security_code}:{audit.period}:audit-pdf",
                    source_tier="official",
                    url=audit.pdf_source_url,
                    content_sha256=audit.pdf_sha256,
                    period=audit.period,
                    available_at=audit.available_at,
                    page=page_index + 1,
                    coordinate=coordinate,
                    verbatim_excerpt=excerpt,
                    source_format="pdf",
                    locator=None,
                )
                if any(term in excerpt for term in _STRONG_CAUSAL_TERMS):
                    return "explained", citation, "相關附註含變動原因或交易說明"
                if partial is None:
                    partial = citation
        if partial is not None:
            return "partially_explained", partial, "找到相關科目附註，但附近沒有充分因果說明"
        if coverage >= 0.80:
            return "unexplained_in_available_filings", None, "可搜尋PDF中未找到主要貢獻科目的相關說明"
        return "blocked_by_missing_evidence", None, "PDF可搜尋文字coverage不足80%，無法判定沒有說明"
    finally:
        document.close()


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):+}%"


def _bn(value: Decimal) -> str:
    return f"{(value / Decimal('1000000')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}億元"


def analyze_financial_anomalies(bundle: CompanyEvidenceBundle) -> FinancialAnomalyAnalysis:
    snapshots = _snapshots(bundle)
    candidates = _candidates(snapshots)
    if not candidates:
        return FinancialAnomalyAnalysis(
            citations=(),
            findings=(),
            limitations=("未發現同時達到20%變動且占總資產5%的非流動資產候選異常。",),
            headline=None,
        )
    citations: list[EvidenceCitation] = []
    findings: list[Finding] = []
    limitations: list[str] = []
    insufficiently_explained = 0
    for index, candidate in enumerate(candidates, 1):
        slug = f"{candidate.current.period}-{index}"
        current_nc = _html_citation(candidate.current, "非流動資產合計", f"{slug}-current-nca")
        prior_nc = _html_citation(candidate.previous, "非流動資產合計", f"{slug}-prior-nca")
        current_total = _html_citation(candidate.current, "資產總額", f"{slug}-current-assets")
        citations.extend((current_nc, prior_nc, current_total))
        evidence_ids = [current_nc.evidence_id, prior_nc.evidence_id, current_total.evidence_id]
        if candidate.contributor is not None:
            current_component = _html_citation(
                candidate.current, candidate.contributor, f"{slug}-current-component"
            )
            prior_component = _html_citation(
                candidate.previous, candidate.contributor, f"{slug}-prior-component"
            )
            citations.extend((current_component, prior_component))
            evidence_ids.extend((current_component.evidence_id, prior_component.evidence_id))
        status, note_citation, reason = _note_assessment(
            _audit_for_period(bundle, candidate.current.period),
            candidate.contributor,
            slug,
        )
        if note_citation is not None:
            citations.append(note_citation)
            evidence_ids.append(note_citation.evidence_id)
        if status in ("partially_explained", "unexplained_in_available_filings"):
            insufficiently_explained += 1
        contributor_text = (
            f"主要可量化貢獻科目為{candidate.contributor}（變動{_bn(candidate.contributor_delta or Decimal(0))}）"
            if candidate.contributor is not None
            else "無法由可得子科目辨識主要貢獻"
        )
        fact_id = f"downside:noncurrent-anomaly:{slug}"
        findings.append(
            Finding(
                finding_id=fact_id,
                kind="fact",
                direction="support",
                statement=(
                    f"{candidate.previous.period}至{candidate.current.period}非流動資產由"
                    f"{_bn(candidate.previous.noncurrent)}變為{_bn(candidate.current.noncurrent)}，"
                    f"變動{_pct(candidate.growth)}，占總資產比重變動{_pct(candidate.share_change)}；"
                    f"{contributor_text}。附註說明狀態：{status}（{reason}）。"
                ),
                materiality=Decimal("0.90") if status == "unexplained_in_available_filings" else Decimal("0.75"),
                evidence_ids=tuple(evidence_ids),
                supporting_finding_ids=(),
                counter_finding_ids=(),
                counter_evidence_reason=None,
            )
        )
        findings.append(
            Finding(
                finding_id=f"downside:noncurrent-anomaly-assessment:{slug}",
                kind="judgement",
                direction="context",
                statement=(
                    "此異常不能單獨推定財報錯誤或舞弊；若屬unexplained，應要求公司以資產取得、企業合併、"
                    "重分類、匯率或其他官方證據補充說明。若後續文件仍無法勾稽，維持red flag。"
                ),
                materiality=Decimal("0.85"),
                evidence_ids=(),
                supporting_finding_ids=(fact_id,),
                counter_finding_ids=(),
                counter_evidence_reason="尚未取得管理層對此特定跨期變動的直接回覆。",
            )
        )
        if status == "blocked_by_missing_evidence":
            limitations.append(f"{candidate.current.period}異常說明檢查被文件coverage阻擋：{reason}。")
    headline = (
        f"偵測到{len(candidates)}個重大非流動資產跨期變動，其中{insufficiently_explained}個在現有可搜尋財報中未找到充分因果說明。"
    )
    return FinancialAnomalyAnalysis(
        citations=tuple(citations),
        findings=tuple(findings),
        limitations=tuple(limitations),
        headline=headline,
    )


__all__ = [
    "ExplanationStatus",
    "FinancialAnomalyAnalysis",
    "analyze_financial_anomalies",
]
