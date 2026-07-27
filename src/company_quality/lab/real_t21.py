"""Execute compact real T21 headline labels from FinLab adjusted total return."""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pandas as pd

from company_quality.lab.cohort import AdverseControlCohort
from company_quality.lab.outcome_labels import (
    DailyClose,
    PITWealthInput,
    build_outcome_label_set,
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _cohort(payload: dict[str, object]) -> AdverseControlCohort:
    return cast(AdverseControlCohort, SimpleNamespace(
        schema_version=payload["schema_version"],
        issuer_ids=tuple(cast(list[str], payload["issuer_ids"])),
        cohort_asof=payload["cohort_asof"],
    ))


def build_real_t21(
    t20_payload: dict[str, object],
    adjusted_close: pd.DataFrame,
    identity: pd.DataFrame,
    materializer_report: dict[str, object],
    *,
    decision_dates: tuple[str, ...],
    source_root: Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    materialized_at = str(materializer_report["materialized_at"])
    producer_shas = {
        "T20": _sha(source_root / "lab/real_t20.py"),
        "PITWealthInput": _sha(source_root / "lab/finlab_materializer.py"),
    }
    candidate_sha = _sha(source_root / "lab/outcome_labels/__init__.py")
    generation_id = str(t20_payload["generation_id"])
    identity_by_code = {
        str(row.security_code): row for row in identity.itertuples(index=False)
    }
    rows: list[dict[str, object]] = []
    attempted = 0
    cohorts = t20_payload["cohorts"]
    if not isinstance(cohorts, dict):
        raise ValueError("real T20 cohort payload drifted")

    for market in ("TWSE", "TPEx"):
        raw_cohort = cohorts[market]
        if not isinstance(raw_cohort, dict):
            raise ValueError("real T20 market cohort payload drifted")
        cohort = _cohort(raw_cohort)
        members = raw_cohort["members"]
        if not isinstance(members, list):
            raise ValueError("real T20 cohort members drifted")
        for member in members:
            if not isinstance(member, dict):
                raise ValueError("real T20 member drifted")
            code = str(member["security_code"])
            issuer_id = str(member["issuer_id"])
            if code not in adjusted_close.columns or code not in identity_by_code:
                continue
            series = adjusted_close[code].dropna()
            if series.empty:
                continue
            evidence_id = f"finlab:etl:adj_close:{code}"
            closes = tuple(
                DailyClose(
                    effective_on=index.date().isoformat(),
                    unadjusted_close=Decimal(str(value)),
                    available_at=materialized_at,
                    evidence_ids=(evidence_id,),
                )
                for index, value in series.items()
                if Decimal(str(value)) > 0
            )
            if not closes:
                continue
            listed_on = datetime.fromisoformat(str(member["listed_on"])).date()
            delisted_on = (
                datetime.fromisoformat(str(member["delisted_on"])).date()
                if member.get("delisted_on")
                else None
            )
            wealth = PITWealthInput(
                issuer_id=issuer_id,
                wealth_series_ref=f"finlab://etl/adj_close/{code}",
                daily_closes=closes,
                corporate_actions=(),
                suspension_intervals=(),
                unresolved_missing_dates=(),
                governed_events=(),
                complete_through=closes[-1].effective_on,
                evidence_ids=(evidence_id,),
                price_basis="pre_adjusted_total_return",
            )
            for decision_date in decision_dates:
                decision = datetime.fromisoformat(decision_date).date()
                if decision < listed_on or (delisted_on is not None and decision >= delisted_on):
                    continue
                if decision < datetime.fromisoformat(closes[0].effective_on).date():
                    continue
                attempted += 1
                result = build_outcome_label_set(
                    cohort,
                    wealth,
                    issuer_id=issuer_id,
                    decision_time=f"{decision_date}T23:59:59+08:00",
                    base_label_version="1.0.0",
                    producer_shas=producer_shas,
                    generation_id=generation_id,
                    producer_candidate_sha=candidate_sha,
                )
                adverse_episodes = [
                    item for item in result.drawdown_episodes
                    if item.maximum_drawdown_pct < Decimal("-50")
                ]
                rows.append({
                    "issuer_id": issuer_id,
                    "security_code": code,
                    "market": market,
                    "decision_date": decision_date,
                    "adverse_outcome": bool(result.adverse_labels),
                    "adverse_labels_json": json.dumps(
                        result.adverse_labels, ensure_ascii=False
                    ),
                    "adverse_event_date": (
                        min(item.trough_date for item in adverse_episodes)
                        if adverse_episodes else None
                    ),
                    "maximum_drawdown_pct": (
                        min(
                            item.maximum_drawdown_pct
                            for item in result.drawdown_episodes
                        )
                        if result.drawdown_episodes else Decimal("0")
                    ),
                    "fully_observed": result.censoring_state == "fully_observed",
                    "censoring_state": result.censoring_state,
                    "label_coverage": result.label_coverage,
                    "label_available_at": result.available_at,
                    "formula_version": result.formula_version,
                    "generation_id": result.generation_id,
                })

    frame = pd.DataFrame(rows)
    fully_observed = int(frame["fully_observed"].sum()) if not frame.empty else 0
    adverse = int(
        frame.loc[frame["fully_observed"], "adverse_outcome"].sum()
    ) if not frame.empty else 0
    report = {
        "schema_version": "RealT21LabelIndex.v1",
        "status": "EXECUTED_NON_PUBLISHABLE",
        "publishable": False,
        "decision_dates": list(decision_dates),
        "attempted_label_count": attempted,
        "label_count": len(frame),
        "fully_observed_count": fully_observed,
        "adverse_fully_observed_count": adverse,
        "fully_observed_coverage": fully_observed / attempted if attempted else 0,
        "producer_shas": producer_shas,
        "producer_candidate_sha": candidate_sha,
        "generation_id": generation_id,
    }
    return frame, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--t20", required=True, type=Path)
    parser.add_argument("--adjusted-close", required=True, type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--materializer-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--decision-dates",
        default="2022-06-30,2023-06-30,2024-06-30",
    )
    args = parser.parse_args()
    frame, report = build_real_t21(
        json.loads(args.t20.read_text()),
        pd.read_parquet(args.adjusted_close),
        pd.read_parquet(args.identity),
        json.loads(args.materializer_report.read_text()),
        decision_dates=tuple(args.decision_dates.split(",")),
        source_root=Path(__file__).parents[1],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
