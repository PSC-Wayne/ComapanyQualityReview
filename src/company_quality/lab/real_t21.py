"""Execute compact real T21 headline labels from FinLab adjusted total return."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Mapping, cast

import pandas as pd

from company_quality.lab.cohort import AdverseControlCohort
from company_quality.lab.official_benchmarks import (
    TPEX_TOTAL_RETURN_URL,
    TWSE_TOTAL_RETURN_URL,
)
from company_quality.lab.outcome_labels import (
    DailyClose,
    OfficialMarketTotalReturnInput,
    OfficialTotalReturnPoint,
    PITWealthInput,
    build_outcome_label_set,
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _series(path: Path) -> pd.Series:
    frame = pd.read_parquet(path)
    if len(frame.columns) != 1:
        raise ValueError(f"official total-return index must have one column: {path}")
    return frame.iloc[:, 0]


def _cohort(payload: dict[str, object]) -> AdverseControlCohort:
    return cast(AdverseControlCohort, SimpleNamespace(
        schema_version=payload["schema_version"],
        issuer_ids=tuple(cast(list[str], payload["issuer_ids"])),
        cohort_asof=payload["cohort_asof"],
    ))


def _official_benchmark(
    market: Literal["TWSE", "TPEx"],
    series: pd.Series,
) -> OfficialMarketTotalReturnInput:
    source_ref = TWSE_TOTAL_RETURN_URL if market == "TWSE" else TPEX_TOTAL_RETURN_URL
    cleaned = series.dropna().sort_index()
    if cleaned.empty:
        raise ValueError(f"{market} official total-return index is empty")
    evidence_id = f"official:{market}:total-return-index"

    def point(index: object, value: object) -> OfficialTotalReturnPoint:
        effective_on = pd.Timestamp(str(index)).date()
        return OfficialTotalReturnPoint(
            effective_on=effective_on.isoformat(),
            value=Decimal(str(value)),
            available_at=(
                f"{(effective_on + timedelta(days=1)).isoformat()}T00:00:00+08:00"
            ),
            evidence_ids=(evidence_id,),
        )

    points = tuple(
        point(index, value)
        for index, value in cleaned.items()
        if Decimal(str(value)) > 0
    )
    return OfficialMarketTotalReturnInput(
        market=market,
        series_ref=source_ref,
        points=points,
        complete_through=points[-1].effective_on,
        evidence_ids=(evidence_id,),
    )


def build_real_t21(
    t20_payload: dict[str, object],
    adjusted_close: pd.DataFrame,
    identity: pd.DataFrame,
    materializer_report: dict[str, object],
    official_total_return: Mapping[str, pd.Series],
    eligible_observations: pd.DataFrame | None = None,
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
    if set(official_total_return) != {"TWSE", "TPEx"}:
        raise ValueError("both TWSE and TPEx official total-return indices required")
    benchmarks = {
        market: _official_benchmark(
            market,
            official_total_return[market],
        )
        for market in ("TWSE", "TPEx")
    }
    identity_by_code = {
        str(row.security_code): row for row in identity.itertuples(index=False)
    }
    eligible_keys: set[tuple[str, str, str]] | None = None
    if eligible_observations is not None:
        required = {"market", "security_code", "decision_date"}
        missing = sorted(required - set(eligible_observations.columns))
        if missing:
            raise ValueError(
                "eligible observation columns missing: " + ",".join(missing)
            )
        eligible_keys = set(zip(
            eligible_observations["market"].astype(str),
            eligible_observations["security_code"].astype(str),
            eligible_observations["decision_date"].astype(str),
            strict=True,
        ))
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
            listed_on = (
                datetime.fromisoformat(str(member["listed_on"])).date()
                if eligible_keys is None else None
            )
            delisted_on = (
                datetime.fromisoformat(str(member["delisted_on"])).date()
                if eligible_keys is None and member.get("delisted_on")
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
                if eligible_keys is not None and (
                    market, code, decision_date
                ) not in eligible_keys:
                    continue
                if eligible_keys is None:
                    if listed_on is None:
                        raise ValueError("cohort member listed_on required")
                    if decision < listed_on or (
                        delisted_on is not None and decision >= delisted_on
                    ):
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
                    market=market,
                    official_market_total_return=benchmarks[market],
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
                    "result_end_date": result.twelve_month_return.result_end_date,
                    "actual_total_return": result.twelve_month_return.actual_total_return,
                    "official_benchmark_return": (
                        result.twelve_month_return.official_benchmark_return
                    ),
                    "official_excess_return": result.twelve_month_return.official_excess_return,
                    "positive_return": result.twelve_month_return.positive_return,
                    "outperformed_official_market": (
                        result.twelve_month_return.outperformed_official_market
                    ),
                    "return_label_status": result.twelve_month_return.status,
                    "official_benchmark_source_ref": (
                        result.twelve_month_return.official_benchmark_source_ref
                    ),
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
    if not frame.empty:
        frame["same_market_median_return"] = frame.groupby(
            ["market", "decision_date"]
        )["actual_total_return"].transform("median")
        frame["same_market_median_source_ref"] = (
            "generation://" + frame["generation_id"].astype(str)
            + "/" + frame["market"].astype(str)
            + "/" + frame["decision_date"].astype(str) + "/median"
        )
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
    parser.add_argument("--twse-total-return-index", required=True, type=Path)
    parser.add_argument("--tpex-total-return-index", required=True, type=Path)
    parser.add_argument("--trading-universe", type=Path)
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
        {
            "TWSE": _series(args.twse_total_return_index),
            "TPEx": _series(args.tpex_total_return_index),
        },
        (
            pd.read_parquet(args.trading_universe)
            if args.trading_universe is not None else None
        ),
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
