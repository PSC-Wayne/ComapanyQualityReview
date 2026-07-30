"""Cross-period balance-sheet anomaly detection and note explanation checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Mapping, Sequence

import fitz

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.company_analysis.contracts import EvidenceCitation, Finding
from company_quality.company_analysis.evidence_bundle import CompanyEvidenceBundle
from company_quality.sources.financial import FinancialArtifact


ExplanationStatus = Literal[
    "explained",
    "partially_explained",
    "unexplained_in_available_evidence",
    "blocked_by_missing_evidence",
]
AnomalyFamily = Literal[
    "material_asset_or_liability_change",
    "expense_increase",
    "three_statement_inconsistency",
    "one_off_gain_or_loss",
    "related_party_activity",
    "reclassification_or_accounting_change",
]
StatementScope = Literal["balance", "income", "expense", "cash_flow"]
EvidenceRole = Literal["support", "counter"]
Severity = Literal["medium", "high"]
Confidence = Literal["low", "medium", "high"]
_REQUIRED_EXPLANATION_FAMILIES = frozenset(
    {"three_statements", "notes", "material_events", "admitted_news"}
)
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


@dataclass(frozen=True, slots=True)
class FinancialChangeObservation:
    """Locked statement values supplied to deterministic anomaly selection."""

    candidate_id: str
    family: AnomalyFamily
    account: str
    statement_scope: StatementScope
    period: str
    baseline_period: str
    current_value: Decimal
    baseline_value: Decimal
    scale_value: Decimal
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnomalyEvidence:
    source_family: str
    evidence_id: str
    text: str
    role: EvidenceRole


@dataclass(frozen=True, slots=True)
class FinancialAnomalyFinding(Finding):
    """One independently displayed anomaly; deliberately has no composite score."""

    family: AnomalyFamily
    explanation_status: ExplanationStatus
    severity: Severity
    confidence: Confidence
    evidence: tuple[str, ...]
    counterevidence: tuple[str, ...]
    monitoring: str
    invalidation: str
    relative_change: Decimal | None
    absolute_materiality: Decimal
    direction_event: str | None

    @property
    def candidate_id(self) -> str:
        return self.finding_id


def _direction_event(current: Decimal, baseline: Decimal) -> str:
    if baseline == 0:
        return "zero_baseline_increase" if current > 0 else "zero_baseline_decrease"
    if baseline < 0 <= current:
        return "negative_to_positive"
    if current < baseline:
        return "negative_baseline_decrease"
    return "negative_baseline_increase"


def _explanation(
    observation: FinancialChangeObservation,
    evidence_by_family: Mapping[str, Sequence[AnomalyEvidence]],
) -> tuple[ExplanationStatus, tuple[AnomalyEvidence, ...]]:
    relevant = tuple(
        item
        for items in evidence_by_family.values()
        for item in items
        if observation.account in item.text or observation.family in item.text
    )
    supporting = tuple(item for item in relevant if item.role == "support")
    if any(term in item.text for item in supporting for term in _STRONG_CAUSAL_TERMS):
        return "explained", relevant
    if supporting:
        return "partially_explained", relevant
    if _REQUIRED_EXPLANATION_FAMILIES.issubset(evidence_by_family):
        return "unexplained_in_available_evidence", relevant
    return "blocked_by_missing_evidence", relevant


def detect_financial_anomaly_candidates(
    observations: Sequence[FinancialChangeObservation],
    *,
    evidence_by_family: Mapping[str, Sequence[AnomalyEvidence]],
) -> tuple[FinancialAnomalyFinding, ...]:
    """Apply the 30%/1% gate and classify explanations across collected sources."""

    result: list[FinancialAnomalyFinding] = []
    for observation in observations:
        if observation.scale_value <= 0:
            continue
        delta = observation.current_value - observation.baseline_value
        absolute_materiality = abs(delta) / observation.scale_value
        if absolute_materiality < Decimal("0.01"):
            continue
        if observation.baseline_value > 0:
            relative_change: Decimal | None = abs(delta) / observation.baseline_value
            direction_event = None
            if relative_change < Decimal("0.30"):
                continue
        else:
            relative_change = None
            direction_event = _direction_event(
                observation.current_value, observation.baseline_value
            )
        status, relevant = _explanation(observation, evidence_by_family)
        severity: Severity = "high" if absolute_materiality >= Decimal("0.05") else "medium"
        confidence: Confidence = (
            "low"
            if status == "blocked_by_missing_evidence"
            else "medium" if status == "partially_explained" else "high"
        )
        support = tuple(item.evidence_id for item in relevant if item.role == "support")
        counter = tuple(item.text for item in relevant if item.role == "counter") or (
            "目前可得來源未提供足以排除或確認此變動的具體反證。",
        )
        relative_text = (
            f"relative_change={relative_change}"
            if relative_change is not None
            else f"direction_event={direction_event}; ordinary_growth_rate=not_applicable"
        )
        statement = (
            f"{observation.account}由{observation.baseline_value}變為"
            f"{observation.current_value}；{relative_text}；"
            f"absolute_materiality={absolute_materiality}；status={status}。"
            "此狀態只描述現有證據能否解釋變動，不推定不實、隱匿或其他不當行為。"
        )
        result.append(
            FinancialAnomalyFinding(
                finding_id=observation.candidate_id,
                kind="fact",
                direction="support",
                statement=statement,
                materiality=min(absolute_materiality, Decimal("1")),
                evidence_ids=observation.evidence_ids,
                supporting_finding_ids=(),
                counter_finding_ids=(),
                counter_evidence_reason=None,
                family=observation.family,
                explanation_status=status,
                severity=severity,
                confidence=confidence,
                evidence=(*observation.evidence_ids, *support),
                counterevidence=counter,
                monitoring=f"監控{observation.account}後續期間金額、占比及來源說明是否一致。",
                invalidation=f"若同issuer、同期間官方證據可直接勾稽{observation.account}變動金額與原因，失效或降級此項。",
                relative_change=relative_change,
                absolute_materiality=absolute_materiality,
                direction_event=direction_event,
            )
        )
    return tuple(result)


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
    growth: Decimal | None
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
        if previous.total_assets == 0 or current.total_assets == 0:
            continue
        delta = current.noncurrent - previous.noncurrent
        growth = (
            delta / previous.noncurrent * 100
            if previous.noncurrent > 0
            else None
        )
        prior_share = previous.noncurrent / previous.total_assets * 100
        current_share = current.noncurrent / current.total_assets * 100
        share_change = current_share - prior_share
        delta_share = abs(delta) / current.total_assets * 100
        if delta_share < 1 or (growth is not None and abs(growth) < 30):
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
    result.sort(
        key=lambda item: (item.delta_share, abs(item.growth or Decimal("0"))),
        reverse=True,
    )
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
            return "unexplained_in_available_evidence", None, "可搜尋PDF中未找到主要貢獻科目的相關說明"
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
            limitations=("未發現同時達到30%變動且占總資產1%的非流動資產候選異常。",),
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
        if status in ("partially_explained", "unexplained_in_available_evidence"):
            insufficiently_explained += 1
        contributor_text = (
            f"主要可量化貢獻科目為{candidate.contributor}（變動{_bn(candidate.contributor_delta or Decimal(0))}）"
            if candidate.contributor is not None
            else "無法由可得子科目辨識主要貢獻"
        )
        fact_id = f"downside:noncurrent-anomaly:{slug}"
        relative_text = (
            f"變動{_pct(candidate.growth)}"
            if candidate.growth is not None
            else (
                "普通成長率不適用；方向事件="
                + _direction_event(
                    candidate.current.noncurrent, candidate.previous.noncurrent
                )
            )
        )
        severity: Severity = "high" if candidate.delta_share >= 5 else "medium"
        confidence: Confidence = (
            "low"
            if status == "blocked_by_missing_evidence"
            else "medium" if status == "partially_explained" else "high"
        )
        findings.append(
            FinancialAnomalyFinding(
                finding_id=fact_id,
                kind="fact",
                direction="support",
                statement=(
                    f"{candidate.previous.period}至{candidate.current.period}非流動資產由"
                    f"{_bn(candidate.previous.noncurrent)}變為{_bn(candidate.current.noncurrent)}，"
                    f"{relative_text}，絕對變動占總資產{candidate.delta_share.quantize(Decimal('0.1'))}%；"
                    f"{contributor_text}。status={status}（{reason}）。"
                    "此狀態只描述現有證據能否解釋變動，不構成任何不當行為判定。"
                ),
                materiality=min(candidate.delta_share / 100, Decimal("1")),
                evidence_ids=tuple(evidence_ids),
                supporting_finding_ids=(),
                counter_finding_ids=(),
                counter_evidence_reason=None,
                family="material_asset_or_liability_change",
                explanation_status=status,
                severity=severity,
                confidence=confidence,
                evidence=tuple(evidence_ids),
                counterevidence=(
                    "目前可得來源未提供足以排除或確認此變動的具體反證。",
                ),
                monitoring="監控主要貢獻科目後續金額、占總資產比重及跨來源說明是否一致。",
                invalidation="若同issuer、同期間官方三表、附註、重大訊息或已准入新聞可直接勾稽變動金額與原因，失效或降級此項。",
                relative_change=(
                    abs(candidate.growth) / 100
                    if candidate.growth is not None
                    else None
                ),
                absolute_materiality=candidate.delta_share / 100,
                direction_event=(
                    None
                    if candidate.growth is not None
                    else _direction_event(
                        candidate.current.noncurrent, candidate.previous.noncurrent
                    )
                ),
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
    "AnomalyEvidence",
    "ExplanationStatus",
    "FinancialAnomalyFinding",
    "FinancialAnomalyAnalysis",
    "FinancialChangeObservation",
    "analyze_financial_anomalies",
    "detect_financial_anomaly_candidates",
]
