"""Validation for official-evidence primary-business attribution pilots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
import re
from typing import Iterable
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
    summary: str


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
    "AnnualReportDocument", "PrimaryBusinessEvidenceError", "ReportedRevenueCategory",
    "build_primary_business_pit_observation", "parse_mops_annual_report_listing",
    "select_pre_decision_annual_report", "validate_primary_business_pilot",
]
