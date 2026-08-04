"""Reusable no-fallback F000 primary-business PIT materialization."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Protocol

import pandas as pd

from company_quality.industry.primary_business import (
    AnnualReportDocument,
    build_primary_business_pit_observation,
    extract_product_revenue_evidence,
)
from company_quality.sources.mops_annual_reports import (
    AnnualReportProbe,
    AnnualReportSourceState,
)

_KEY = ["issuer_id", "security_code", "decision_date"]


class AnnualReportAcquirer(Protocol):
    def acquire(
        self, security_code: str, report_year: int, decision_date: str
    ) -> AnnualReportProbe: ...


PageTextProvider = Callable[[Path], Iterable[tuple[int, str]]]


def _eligible(labels: pd.DataFrame, decisions: tuple[str, ...]) -> pd.DataFrame:
    required = set(_KEY) | {
        "market", "fully_observed", "actual_total_return",
        "official_benchmark_return", "official_excess_return", "official_industry_code",
    }
    if missing := required - set(labels.columns):
        raise ValueError("labels missing: " + ", ".join(sorted(missing)))
    frame = labels.copy()
    for column in _KEY:
        frame[column] = frame[column].astype(str)
    frame = frame.loc[
        frame["decision_date"].isin(decisions)
        & frame["official_industry_code"].astype(str).eq("25")
        & frame["fully_observed"].astype(bool)
        & frame[["actual_total_return", "official_benchmark_return", "official_excess_return"]]
        .notna().all(axis=1),
        _KEY + ["market"],
    ].copy()
    if frame.duplicated(_KEY).any():
        raise ValueError("eligible observations must be unique")
    return frame


def _candidates(memberships: pd.DataFrame, decisions: tuple[str, ...]) -> pd.DataFrame:
    required = {
        "decision_date", "security_code", "chain_code", "node_code", "node_name",
        "fresh_within_365d", "snapshot_timestamp", "snapshot_age_days", "source_url",
    }
    if missing := required - set(memberships.columns):
        raise ValueError("memberships missing: " + ", ".join(sorted(missing)))
    frame = memberships.copy()
    frame["decision_date"] = frame["decision_date"].astype(str)
    frame["security_code"] = frame["security_code"].astype(str)
    return frame.loc[
        frame["decision_date"].isin(decisions)
        & frame["chain_code"].astype(str).eq("F000")
        & frame["fresh_within_365d"].astype(bool)
    ].drop_duplicates(["decision_date", "security_code", "node_code"])


def _excluded(
    row: pd.Series, candidate_nodes: list[dict[str, str]], probe: AnnualReportProbe,
    status: str,
) -> dict[str, object]:
    return {
        "issuer_id": str(row["issuer_id"]), "security_code": str(row["security_code"]),
        "market": str(row["market"]), "decision_date": str(row["decision_date"]),
        "candidate_nodes": candidate_nodes, "status": status, "primary_child": None,
        "reported_revenue_share_pct": None, "evidence": None, "model_excluded": True,
        "current_backfill_used": False, "fallback_used": False,
        "source_state": probe.state.value, "source_detail": probe.detail,
    }


def _summary(observations: list[dict[str, object]]) -> dict[str, object]:
    counts = Counter(str(row["status"]) for row in observations)
    by_year_market: list[dict[str, object]] = []
    keys = sorted({(str(row["decision_date"])[:4], str(row["market"])) for row in observations})
    for year, market in keys:
        rows = [row for row in observations if str(row["decision_date"]).startswith(year) and row["market"] == market]
        item: dict[str, object] = {"decision_year": year, "market": market, "attempted_count": len(rows)}
        item.update({name: sum(row["status"] == name for row in rows) for name in sorted(counts)})
        by_year_market.append(item)
    nodes = Counter(
        str(row["primary_child"]["node_code"])
        for row in observations
        if isinstance(row.get("primary_child"), dict)
    )
    return {
        "attempted_count": len(observations),
        **{f"{name}_count": count for name, count in sorted(counts.items())},
        "excluded_count": sum(bool(row["model_excluded"]) for row in observations),
        "coverage_by_year_market": by_year_market,
        "attributed_by_node": [
            {"node_code": code, "attributed_count": count} for code, count in sorted(nodes.items())
        ],
    }


def materialize_primary_business_pit(
    *,
    labels: pd.DataFrame,
    memberships: pd.DataFrame,
    decision_dates: Iterable[str],
    acquirer: AnnualReportAcquirer,
    page_text_provider: PageTextProvider,
) -> dict[str, object]:
    decisions = tuple(sorted(set(decision_dates)))
    if not decisions:
        raise ValueError("decision dates required")
    eligible = _eligible(labels, decisions)
    candidates = _candidates(memberships, decisions)
    universe = eligible.merge(
        candidates[["security_code", "decision_date"]].drop_duplicates(),
        on=["security_code", "decision_date"], how="inner", validate="one_to_one",
    ).sort_values(["decision_date", "security_code"])
    observations: list[dict[str, object]] = []
    for _, row in universe.iterrows():
        admitted = candidates.loc[
            candidates["security_code"].eq(str(row["security_code"]))
            & candidates["decision_date"].eq(str(row["decision_date"]))
        ]
        candidate_nodes = [
            {"node_code": str(item.node_code), "node_name": str(item.node_name)}
            for item in admitted[["node_code", "node_name"]].sort_values("node_code").itertuples(index=False)
        ]
        decision = str(row["decision_date"])
        probe = acquirer.acquire(str(row["security_code"]), int(decision[:4]) - 1, decision)
        if probe.state is AnnualReportSourceState.SOURCE_UNAVAILABLE:
            observations.append(_excluded(row, candidate_nodes, probe, "source_unavailable"))
            continue
        if probe.state is AnnualReportSourceState.DOCUMENT_NOT_LISTED:
            observations.append(_excluded(row, candidate_nodes, probe, "document_not_listed"))
            continue
        if probe.document is None or probe.pdf_path is None:
            raise ValueError("AVAILABLE probe requires document and PDF path")
        extraction = extract_product_revenue_evidence(
            pages=page_text_provider(probe.pdf_path), candidate_nodes=candidate_nodes
        )
        document = AnnualReportDocument(
            security_code=probe.document.security_code,
            report_year=probe.document.report_year,
            document_filename=probe.document.filename,
            available_at=datetime.fromisoformat(probe.document.available_at),
            source_url=probe.document.listing_url,
        )
        observation = build_primary_business_pit_observation(
            issuer_id=str(row["issuer_id"]), security_code=str(row["security_code"]),
            market=str(row["market"]), decision_date=decision,
            candidate_nodes=candidate_nodes, document=document, categories=extraction.rows,
        )
        observation["source_state"] = probe.state.value
        observation["extraction_reason"] = extraction.reason
        observations.append(observation)
    payload: dict[str, object] = {
        "schema_version": "TPExF000PrimaryBusinessPIT.v2",
        "status": "RESEARCH_MATERIALIZATION_NO_FALLBACK",
        "decision_dates": list(decisions),
        "current_fill_used": False, "fallback_used": False, "pooling_used": False,
        "final_oos_read": False, "observations": observations,
        "summary": _summary(observations),
    }
    return payload


__all__ = ["PageTextProvider", "materialize_primary_business_pit"]
