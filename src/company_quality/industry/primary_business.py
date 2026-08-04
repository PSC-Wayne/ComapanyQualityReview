"""Validation for official-evidence primary-business attribution pilots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import unescape
import re
from typing import Iterable
import unicodedata
from urllib.parse import urlparse


class PrimaryBusinessEvidenceError(ValueError):
    """Raised when a primary-business attribution is unsupported or ambiguous."""


@dataclass(frozen=True, slots=True)
class AnnualReportDocument:
    security_code: str
    report_year: int
    document_filename: str
    available_at: datetime
    source_url: str


@dataclass(frozen=True, slots=True)
class ReportedRevenueCategory:
    category: str
    revenue_share_pct: float
    node_code: str | None
    page: int
    source_text: str

    @property
    def summary(self) -> str:
        """Backward-compatible evidence text name used by the #183 contract."""
        return self.source_text


@dataclass(frozen=True, slots=True)
class ProductRevenueExtraction:
    status: str
    rows: tuple[ReportedRevenueCategory, ...]
    reason: str | None = None


_CATEGORY_HEADERS = ("產品別", "產品類別", "產品項目", "產品名稱")
_SHARE_HEADERS = ("營業收入比重", "營業收入占比", "營收比重", "營收占比")
_TOTAL_LABELS = {"合計", "總計"}
_SHARE_ROW = re.compile(
    r"^(?P<category>.+?)\s+(?P<share>\S+)\s*[%％]$"
)


def _normalized_exact_name(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _is_revenue_table_header(line: str) -> bool:
    compact = _normalized_exact_name(line)
    return any(label in compact for label in _CATEGORY_HEADERS) and any(
        label in compact for label in _SHARE_HEADERS
    )


def _parse_revenue_table(
    *,
    page: int,
    lines: list[str],
    header_index: int,
    node_code_by_name: dict[str, str | None],
) -> tuple[ReportedRevenueCategory, ...] | None:
    parsed: list[tuple[str, str, Decimal, str]] = []
    total: Decimal | None = None
    for source_line in lines[header_index + 1 :]:
        source_text = source_line.strip()
        if not source_text:
            continue
        if re.fullmatch(r"單位\s*[:：]?\s*[%％]", source_text):
            continue
        match = _SHARE_ROW.fullmatch(source_text)
        if match is None:
            return None
        category = match.group("category").strip()
        try:
            share = Decimal(unicodedata.normalize("NFKC", match.group("share")))
        except InvalidOperation:
            return None
        if share < 0 or share > 100:
            return None
        normalized_category = _normalized_exact_name(category)
        if normalized_category in _TOTAL_LABELS:
            total = share
            break
        if not normalized_category or any(
            normalized_category == existing
            for existing, _, _, _ in parsed
        ):
            return None
        parsed.append((normalized_category, category, share, source_line))

    if not parsed or total is None:
        return None
    tolerance = Decimal("0.05")
    row_total = sum((share for _, _, share, _ in parsed), Decimal("0"))
    if abs(total - Decimal("100")) > tolerance or abs(row_total - total) > tolerance:
        return None

    rows: list[ReportedRevenueCategory] = []
    for normalized_category, category, share, source_text in parsed:
        rows.append(
            ReportedRevenueCategory(
                category=category,
                revenue_share_pct=float(share),
                node_code=node_code_by_name.get(normalized_category),
                page=page,
                source_text=source_text,
            )
        )
    return tuple(rows)


def extract_product_revenue_evidence(
    *,
    pages: Iterable[tuple[int, str]],
    candidate_nodes: Iterable[dict[str, str]],
) -> ProductRevenueExtraction:
    """Extract one explicit, reconciled product-revenue composition table.

    Mapping is deliberately limited to a unique normalized exact node-name match.
    The caller supplies PDF page text; this function performs no PDF or OCR work.
    """
    node_codes_by_name: dict[str, list[str]] = {}
    for candidate in candidate_nodes:
        code = str(candidate.get("node_code", "")).strip()
        name = str(candidate.get("node_name", "")).strip()
        if not code or not name:
            raise PrimaryBusinessEvidenceError(
                "decision-time TPEx candidate nodes require node_code and node_name"
            )
        node_codes_by_name.setdefault(_normalized_exact_name(name), []).append(code)
    if not node_codes_by_name:
        raise PrimaryBusinessEvidenceError("decision-time TPEx candidate nodes required")
    node_code_by_name = {
        name: codes[0] if len(codes) == 1 else None
        for name, codes in node_codes_by_name.items()
    }

    page_rows = list(pages)
    for page, text in page_rows:
        if not isinstance(page, int) or page <= 0 or not isinstance(text, str):
            raise PrimaryBusinessEvidenceError(
                "annual-report pages require positive page numbers and text"
            )
    if not any(text.strip() for _, text in page_rows):
        return ProductRevenueExtraction("missing_evidence", (), "no_text")

    detected: list[tuple[ReportedRevenueCategory, ...] | None] = []
    for page, text in page_rows:
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if _is_revenue_table_header(line):
                detected.append(
                    _parse_revenue_table(
                        page=page,
                        lines=lines,
                        header_index=index,
                        node_code_by_name=node_code_by_name,
                    )
                )
    if not detected:
        return ProductRevenueExtraction("missing_evidence", (), "no_table")
    if len(detected) != 1 or detected[0] is None:
        return ProductRevenueExtraction("missing_evidence", (), "malformed_table")
    return ProductRevenueExtraction("extracted", detected[0])


def _official_mops_locator(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "doc.twse.com.tw":
        raise PrimaryBusinessEvidenceError("official MOPS document locator required")


def _decode_mops_listing(body: bytes) -> str:
    for encoding in ("big5", "utf-8"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PrimaryBusinessEvidenceError("MOPS annual-report listing encoding is unsupported")


def parse_mops_annual_report_listing(
    body: bytes,
    *,
    security_code: str,
    source_url: str,
) -> tuple[AnnualReportDocument, ...]:
    """Parse official F04 annual-report rows without downloading short-lived PDFs."""
    _official_mops_locator(source_url)
    text = _decode_mops_listing(body)
    documents: dict[tuple[str, datetime], AnnualReportDocument] = {}
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.IGNORECASE | re.DOTALL):
        filename_match = re.search(
            rf"(\d{{4}}_{re.escape(security_code)}_\d{{8}}F04\.pdf)", row, flags=re.IGNORECASE
        )
        if filename_match is None:
            continue
        date_match = re.search(
            r"(\d{3})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})", unescape(row)
        )
        if date_match is None:
            raise PrimaryBusinessEvidenceError("MOPS annual-report row has no upload time")
        roc_year, month, day, hour, minute, second = map(int, date_match.groups())
        available_at = datetime(
            roc_year + 1911, month, day, hour, minute, second,
            tzinfo=timezone(timedelta(hours=8)),
        )
        filename = filename_match.group(1)
        document = AnnualReportDocument(
            security_code=security_code,
            report_year=int(filename[:4]),
            document_filename=filename,
            available_at=available_at,
            source_url=source_url,
        )
        documents[(filename, available_at)] = document
    return tuple(sorted(documents.values(), key=lambda item: (item.available_at, item.document_filename)))


def select_pre_decision_annual_report(
    documents: Iterable[AnnualReportDocument], *, decision_date: str
) -> AnnualReportDocument | None:
    try:
        decision = date.fromisoformat(decision_date)
    except ValueError as exc:
        raise PrimaryBusinessEvidenceError("invalid decision date") from exc
    if decision.isoformat() != decision_date:
        raise PrimaryBusinessEvidenceError("invalid decision date")
    cutoff = datetime.combine(
        decision, datetime.max.time(), tzinfo=timezone(timedelta(hours=8))
    )
    eligible = [document for document in documents if document.available_at <= cutoff]
    return max(eligible, key=lambda item: (item.available_at, item.document_filename), default=None)


def _document_dict(document: AnnualReportDocument) -> dict[str, object]:
    payload = asdict(document)
    payload["available_at"] = document.available_at.isoformat()
    return payload


def build_primary_business_pit_observation(
    *,
    issuer_id: str,
    security_code: str,
    market: str,
    decision_date: str,
    candidate_nodes: list[dict[str, str]],
    document: AnnualReportDocument | None,
    categories: Iterable[ReportedRevenueCategory],
) -> dict[str, object]:
    """Attribute one child only when reported revenue directly supports it."""
    if not issuer_id or not security_code or market not in {"TWSE", "TPEx"}:
        raise PrimaryBusinessEvidenceError("complete issuer/security/market identity required")
    candidate_by_code = {
        str(item.get("node_code", "")): str(item.get("node_name", ""))
        for item in candidate_nodes
        if item.get("node_code") and item.get("node_name")
    }
    if not candidate_by_code:
        raise PrimaryBusinessEvidenceError("decision-time TPEx candidate nodes required")
    selected = list(categories)
    if document is not None and document.security_code != security_code:
        raise PrimaryBusinessEvidenceError("annual-report security identity mismatch")
    for item in selected:
        if not item.category or not item.summary or item.page <= 0:
            raise PrimaryBusinessEvidenceError("complete reported revenue evidence required")
        if not 0 <= item.revenue_share_pct <= 100:
            raise PrimaryBusinessEvidenceError("reported revenue share must be between zero and 100")
        if item.node_code is not None and item.node_code not in candidate_by_code:
            raise PrimaryBusinessEvidenceError("reported category maps outside admitted candidate nodes")

    base: dict[str, object] = {
        "issuer_id": issuer_id,
        "security_code": security_code,
        "market": market,
        "decision_date": decision_date,
        "candidate_nodes": candidate_nodes,
        "current_backfill_used": False,
        "fallback_used": False,
    }
    if document is None:
        return {
            **base, "status": "document_unavailable", "primary_child": None,
            "reported_revenue_share_pct": None, "evidence": None, "model_excluded": True,
        }
    if not selected:
        return {
            **base, "status": "missing_evidence", "primary_child": None,
            "reported_revenue_share_pct": None, "evidence": {"document": _document_dict(document)},
            "model_excluded": True,
        }

    shares: dict[str, float] = {}
    unmapped_max = 0.0
    for item in selected:
        if item.node_code is None:
            unmapped_max = max(unmapped_max, item.revenue_share_pct)
        else:
            shares[item.node_code] = shares.get(item.node_code, 0.0) + item.revenue_share_pct
    ranked = sorted(shares.items(), key=lambda item: (-item[1], item[0]))
    unique_top = bool(ranked) and (len(ranked) == 1 or ranked[0][1] > ranked[1][1])
    attributable = unique_top and ranked[0][1] > unmapped_max
    evidence = {
        "document": _document_dict(document),
        "categories": [asdict(item) for item in selected],
    }
    if not attributable:
        return {
            **base, "status": "ambiguous", "primary_child": None,
            "reported_revenue_share_pct": None, "evidence": evidence, "model_excluded": True,
        }
    node_code, share = ranked[0]
    return {
        **base,
        "status": "attributed",
        "primary_child": {"node_code": node_code, "node_name": candidate_by_code[node_code]},
        "reported_revenue_share_pct": share,
        "evidence": evidence,
        "model_excluded": False,
    }


def validate_primary_business_pilot(payload: dict[str, object]) -> dict[str, int | float | str]:
    if payload.get("schema_version") != "TPExF000PrimaryBusinessPilot.v1":
        raise PrimaryBusinessEvidenceError("unsupported pilot schema")
    rows = payload.get("observations")
    if not isinstance(rows, list) or not rows:
        raise PrimaryBusinessEvidenceError("pilot observations required")

    seen: set[tuple[str, str, str]] = set()
    status_counts = {"attributed": 0, "ambiguous": 0, "missing_evidence": 0}
    markets: set[str] = set()
    nodes: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise PrimaryBusinessEvidenceError("pilot observation must be an object")
        key = (
            str(raw.get("issuer_id", "")),
            str(raw.get("security_code", "")),
            str(raw.get("decision_date", "")),
        )
        if not all(key) or key in seen:
            raise PrimaryBusinessEvidenceError("unique issuer/security/decision required")
        seen.add(key)

        market = str(raw.get("market", ""))
        if market not in {"TWSE", "TPEx"}:
            raise PrimaryBusinessEvidenceError("market is identity metadata and must be TWSE or TPEx")
        markets.add(market)
        candidates = raw.get("candidate_nodes")
        if not isinstance(candidates, list) or not candidates or any(
            not isinstance(item, dict) or not item.get("node_code") or not item.get("node_name")
            for item in candidates
        ):
            raise PrimaryBusinessEvidenceError("official TPEx candidate nodes required")
        candidate_codes = {str(item["node_code"]) for item in candidates}

        evidence = raw.get("evidence")
        if not isinstance(evidence, dict):
            raise PrimaryBusinessEvidenceError("official evidence required")
        source_url = str(evidence.get("source_url", ""))
        if urlparse(source_url).hostname != "doc.twse.com.tw":
            raise PrimaryBusinessEvidenceError("pilot evidence must use the official MOPS document host")
        uploaded_at = datetime.fromisoformat(str(evidence.get("available_at", "")))
        decision = datetime.fromisoformat(str(raw["decision_date"]) + "T23:59:59+08:00")
        if uploaded_at.tzinfo is None or uploaded_at > decision:
            raise PrimaryBusinessEvidenceError("evidence must be available by the decision date")
        if not evidence.get("document_filename") or not evidence.get("page") or not evidence.get("summary"):
            raise PrimaryBusinessEvidenceError("document filename, page and evidence summary required")

        status = str(raw.get("status", ""))
        if status not in status_counts:
            raise PrimaryBusinessEvidenceError("unsupported attribution status")
        status_counts[status] += 1
        primary = raw.get("primary_child")
        share = raw.get("reported_revenue_share_pct")
        if status == "attributed":
            if not isinstance(primary, dict) or str(primary.get("node_code", "")) not in candidate_codes:
                raise PrimaryBusinessEvidenceError("attributed primary child must be an official candidate node")
            if not isinstance(share, (int, float)) or not 0 <= float(share) <= 100:
                raise PrimaryBusinessEvidenceError("attributed row requires a reported revenue share")
            nodes.add(str(primary["node_code"]))
        elif primary is not None or share is not None:
            raise PrimaryBusinessEvidenceError("ambiguous/missing rows cannot claim a primary child or share")

    summary = {
        "observation_count": len(rows),
        "attributed_count": status_counts["attributed"],
        "ambiguous_count": status_counts["ambiguous"],
        "missing_evidence_count": status_counts["missing_evidence"],
        "attributed_coverage": status_counts["attributed"] / len(rows),
        "market_count": len(markets),
        "primary_node_count": len(nodes),
        "scale_recommendation": "CONDITIONAL_SCALE_WITH_EXCLUSION",
    }
    if payload.get("summary") != summary:
        raise PrimaryBusinessEvidenceError("published pilot summary does not match observations")
    if payload.get("current_backfill_used") is not False:
        raise PrimaryBusinessEvidenceError("current classification backfill is prohibited")
    return summary


__all__ = [
    "AnnualReportDocument", "PrimaryBusinessEvidenceError", "ProductRevenueExtraction",
    "ReportedRevenueCategory", "build_primary_business_pit_observation",
    "extract_product_revenue_evidence", "parse_mops_annual_report_listing",
    "select_pre_decision_annual_report", "validate_primary_business_pilot",
]
