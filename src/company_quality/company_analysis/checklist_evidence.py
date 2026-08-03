"""Structured audit, KAM, and minimum-note evidence for the authority checklist."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast

import fitz

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.company_analysis.contracts import EvidenceCitation


_NOTE_KEYWORDS = {
    "N01_revenue_recognition": ("收入認列", "收入之認列", "收入認列政策"),
    "N02_receivables": ("應收帳款", "備抵損失"),
    "N03_inventory": ("存貨", "存貨跌價"),
    "N04_contract_assets": ("合約資產",),
    "N05_ppe": ("不動產、廠房及設備",),
    "N06_goodwill_intangibles": ("商譽", "無形資產"),
    "N07_borrowings_bonds": ("借款", "應付公司債"),
    "N08_liquidity": ("流動性風險",),
    "N09_restricted_cash": ("受限制資產", "受限制銀行存款"),
    "N10_related_parties": ("關係人交易", "關係人"),
    "N11_guarantees": ("背書保證", "保證事項"),
    "N12_contingencies_litigation": (
        "或有事項", "重大訴訟", "重大或有負債及未認列之合約承諾",
    ),
    "N13_commitments": (
        "重大承諾", "承諾事項", "重大或有負債及未認列之合約承諾",
    ),
    "N14_income_tax": ("所得稅",),
    "N15_financial_instruments": ("金融工具",),
    "N16_share_based_payments": ("股份基礎給付",),
    "N17_eps": ("每股盈餘",),
    "N18_segments": ("部門資訊", "營運部門"),
    "N19_subsequent_events": ("期後事項", "資產負債表日後事項"),
}


@dataclass(frozen=True, slots=True)
class ChecklistDocumentEvidence:
    audit_opinion_citations: tuple[EvidenceCitation, ...]
    audit_opinion_types: tuple[tuple[str, str], ...]
    going_concern_citations: tuple[EvidenceCitation, ...]
    emphasis_other_citations: tuple[EvidenceCitation, ...]
    kam_citations: tuple[EvidenceCitation, ...]
    audit_text_search_complete_periods: tuple[str, ...]
    note_citations: tuple[tuple[str, EvidenceCitation], ...]
    unreadable_periods: tuple[str, ...]


def _citation(
    audit: AuditFilingInventory,
    *,
    slug: str,
    page_index: int,
    blocks: list[tuple[fitz.Rect, str]],
    index: int,
    following: int,
    page_width: float,
    page_height: float,
) -> EvidenceCitation:
    assert audit.pdf_sha256 is not None
    assert audit.pdf_source_url is not None
    selected = blocks[index : min(len(blocks), index + following)]
    rectangle = selected[0][0]
    for block, _ in selected[1:]:
        rectangle |= block

    x0 = Decimal(str(max(0.0, rectangle.x0 / page_width))).quantize(Decimal("0.0001"))
    y0 = Decimal(str(max(0.0, rectangle.y0 / page_height))).quantize(Decimal("0.0001"))
    x1 = Decimal(str(min(1.0, rectangle.x1 / page_width))).quantize(Decimal("0.0001"))
    y1 = Decimal(str(min(1.0, rectangle.y1 / page_height))).quantize(Decimal("0.0001"))
    return EvidenceCitation(
        evidence_id=f"{audit.market}:{audit.security_code}:{audit.period}:pdf:checklist-{slug}",
        source_id=f"{audit.market}:{audit.security_code}:{audit.period}:audit-pdf",
        source_tier="official",
        url=audit.pdf_source_url,
        content_sha256=audit.pdf_sha256,
        period=audit.period,
        available_at=audit.available_at,
        page=page_index + 1,
        coordinate=(x0, y0, x1, y1),
        verbatim_excerpt=" ".join(text for _, text in selected)[:3900],
        source_format="pdf",
        locator=None,
    )


def _blocks(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    return [
        (fitz.Rect(item[:4]), " ".join(str(item[4]).split()))
        for item in page.get_text("blocks")
        if str(item[4]).strip()
    ]


def _first_match(
    audit: AuditFilingInventory,
    document: fitz.Document,
    *,
    slug: str,
    keywords: tuple[str, ...],
    following: int,
    max_pages: int | None = None,
) -> EvidenceCitation | None:
    for page_index in range(len(document)):
        page = document[page_index]
        if max_pages is not None and page_index >= max_pages:
            break
        blocks = _blocks(page)
        for index, (_, text) in enumerate(blocks):
            compact = "".join(text.split())
            if any("".join(keyword.split()) in compact for keyword in keywords):
                return _citation(
                    audit,
                    slug=slug,
                    page_index=page_index,
                    blocks=blocks,
                    index=index,
                    following=following,
                    page_width=float(page.rect.width),
                    page_height=float(page.rect.height),
                )
    return None


def _first_note_match(
    audit: AuditFilingInventory,
    document: fitz.Document,
    *,
    slug: str,
    keywords: tuple[str, ...],
    following: int,
) -> EvidenceCitation | None:
    """Prefer an actual note heading over incidental table/body mentions."""
    for page_index in range(len(document)):
        page = document[page_index]
        blocks = _blocks(page)
        for index, (_, text) in enumerate(blocks):
            compact = "".join(text.split())
            positions = [
                compact.find("".join(keyword.split()))
                for keyword in keywords
                if "".join(keyword.split()) in compact
            ]
            if not positions or min(positions) > 16:
                continue
            return _citation(
                audit,
                slug=slug,
                page_index=page_index,
                blocks=blocks,
                index=index,
                following=following,
                page_width=float(page.rect.width),
                page_height=float(page.rect.height),
            )
    return None


def _ocr_missing_audit_sections(
    audit: AuditFilingInventory,
    document: fitz.Document,
    *,
    need_opinion: bool,
    need_kam: bool,
) -> tuple[EvidenceCitation | None, EvidenceCitation | None]:
    if not need_opinion and not need_kam:
        return None, None
    from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-not-found]
    import numpy as np

    ocr = RapidOCR()
    opinion: EvidenceCitation | None = None
    kam: EvidenceCitation | None = None
    for page_index in range(min(20, len(document))):
        page = document[page_index]
        if str(page.get_text()).strip():
            continue
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, pixmap.n
        )
        result, _ = ocr(image)
        lines = cast(tuple[Any, ...], tuple(result or ()))
        for index in range(len(lines)):
            search_text = "".join(str(item[1]) for item in lines[index : index + 3])
            compact = "".join(search_text.split())
            targets = []
            if need_opinion and opinion is None and any(
                keyword in compact
                for keyword in (
                    "會計師查核報告", "会计师查核报告",
                    "查核意見", "查核意见", "無保留意見", "无保留意见",
                    "保留意見", "保留意见", "否定意見", "否定意见",
                    "無法表示意見", "无法表示意见",
                )
            ):
                targets.append(("auditor-opinion", 10))
            if need_kam and kam is None and any(
                keyword in compact
                for keyword in ("關鍵查核事項", "關鍵查核事项", "關鍵查核事頂")
            ):
                targets.append(("kam", 20))
            for slug, following in targets:
                selected = lines[index : min(len(lines), index + following)]
                points = [point for item in selected for point in item[0]]
                x0 = Decimal(str(min(point[0] for point in points) / pixmap.width)).quantize(Decimal("0.0001"))
                y0 = Decimal(str(min(point[1] for point in points) / pixmap.height)).quantize(Decimal("0.0001"))
                x1 = Decimal(str(max(point[0] for point in points) / pixmap.width)).quantize(Decimal("0.0001"))
                y1 = Decimal(str(max(point[1] for point in points) / pixmap.height)).quantize(Decimal("0.0001"))
                confidence = sum(float(item[2]) for item in selected) / len(selected)
                citation = EvidenceCitation(
                    evidence_id=f"{audit.market}:{audit.security_code}:{audit.period}:pdf:checklist-{slug}",
                    source_id=f"{audit.market}:{audit.security_code}:{audit.period}:audit-pdf",
                    source_tier="official",
                    url=audit.pdf_source_url or "",
                    content_sha256=audit.pdf_sha256 or "",
                    period=audit.period,
                    available_at=audit.available_at,
                    page=page_index + 1,
                    coordinate=(x0, y0, x1, y1),
                    verbatim_excerpt=" ".join(str(item[1]).strip() for item in selected)[:3900],
                    source_format="pdf",
                    locator=f"ocr:rapidocr-onnxruntime;mean_confidence:{confidence:.3f}",
                )
                if slug == "auditor-opinion":
                    opinion = citation
                else:
                    kam = citation
            if (not need_opinion or opinion is not None) and (not need_kam or kam is not None):
                return opinion, kam
    return opinion, kam


def collect_checklist_document_evidence(
    audits: tuple[AuditFilingInventory, ...],
) -> ChecklistDocumentEvidence:
    annual = tuple(
        sorted(
            (
                item for item in audits
                if item.pdf_path is not None
                and item.pdf_sha256 is not None
                and item.pdf_source_url is not None
            ),
            key=lambda item: item.period,
        )[-3:]
    )
    opinions: list[EvidenceCitation] = []
    opinion_types: list[tuple[str, str]] = []
    going_concern: list[EvidenceCitation] = []
    emphasis_other: list[EvidenceCitation] = []
    kams: list[EvidenceCitation] = []
    text_search_complete: list[str] = []
    notes: list[tuple[str, EvidenceCitation]] = []
    unreadable: list[str] = []
    for position, audit in enumerate(annual):
        assert audit.pdf_path is not None and audit.pdf_sha256 is not None
        body = audit.pdf_path.read_bytes()
        if sha256(body).hexdigest() != audit.pdf_sha256:
            unreadable.append(audit.period)
            continue
        document = fitz.open(stream=body, filetype="pdf")
        try:
            opinion = _first_match(
                audit,
                document,
                slug="auditor-opinion",
                keywords=("查核意見", "無保留意見", "保留意見", "否定意見", "無法表示意見"),
                following=10,
                max_pages=12,
            )
            opinion_type = getattr(audit, "opinion_type", None)
            if opinion_type is not None:
                opinion_types.append((audit.period, str(opinion_type)))
            going_concern_citation = _first_match(
                audit,
                document,
                slug="going-concern",
                keywords=("繼續經營之重大不確定性", "繼續經營存在重大不確定性"),
                following=10,
                max_pages=12,
            )
            if going_concern_citation is not None:
                going_concern.append(going_concern_citation)
            emphasis_citation = _first_match(
                audit,
                document,
                slug="emphasis-other-matters",
                keywords=("強調事項", "其他事項"),
                following=10,
                max_pages=12,
            )
            if emphasis_citation is not None:
                emphasis_other.append(emphasis_citation)
            kam = _first_match(
                audit,
                document,
                slug="kam",
                keywords=("關鍵查核事項",),
                following=20,
                max_pages=20,
            )
            if opinion is None or kam is None:
                ocr_opinion, ocr_kam = _ocr_missing_audit_sections(
                    audit,
                    document,
                    need_opinion=opinion is None,
                    need_kam=kam is None,
                )
                opinion = opinion or ocr_opinion
                kam = kam or ocr_kam
            if opinion is not None:
                opinions.append(opinion)
            if kam is not None:
                kams.append(kam)
            if (
                opinion is not None
                and kam is not None
                and opinion.locator is None
                and kam.locator is None
            ):
                text_search_complete.append(audit.period)
            if position == len(annual) - 1:
                for check_id, keywords in _NOTE_KEYWORDS.items():
                    citation = _first_note_match(
                        audit,
                        document,
                        slug=check_id,
                        keywords=keywords,
                        following=6,
                    )
                    if citation is not None:
                        notes.append((check_id, citation))
        finally:
            document.close()
    return ChecklistDocumentEvidence(
        tuple(opinions),
        tuple(opinion_types),
        tuple(going_concern),
        tuple(emphasis_other),
        tuple(kams),
        tuple(text_search_complete),
        tuple(notes),
        tuple(unreadable),
    )


__all__ = ["ChecklistDocumentEvidence", "collect_checklist_document_evidence"]
