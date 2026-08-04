"""Validation for official-evidence primary-business attribution pilots."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse


class PrimaryBusinessEvidenceError(ValueError):
    """Raised when a primary-business attribution is unsupported or ambiguous."""


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


__all__ = ["PrimaryBusinessEvidenceError", "validate_primary_business_pilot"]
