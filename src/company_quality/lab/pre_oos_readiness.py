"""Fail-closed readiness assessment before any final-OOS data is read."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import pandas as pd

from company_quality.lab.official_benchmarks import (
    TPEX_TOTAL_RETURN_URL,
    TWSE_TOTAL_RETURN_URL,
)


_LABEL_REQUIRED = {
    "issuer_id", "security_code", "market", "decision_date", "result_end_date",
    "generation_id", "actual_total_return", "official_benchmark_return",
    "official_benchmark_source_ref",
}
_CANDIDATE_REQUIRED = {
    "candidate_id", "issuer_id", "security_code", "market", "decision_date",
    "result_end_date", "trained_through", "generation_id", "actual_total_return",
    "official_benchmark_return", "predicted_p10_return", "predicted_p50_return",
    "predicted_p90_return", "positive_return_probability", "outperform_probability",
    "data_completeness", "industry_train_observations",
}
_OFFICIAL_BENCHMARK_REFS = {
    "TWSE": TWSE_TOTAL_RETURN_URL,
    "TPEx": TPEX_TOTAL_RETURN_URL,
}


@dataclass(frozen=True, slots=True)
class PreOOSReadinessReport:
    generation_id: str | None
    final_oos_start: str
    label_years: list[int]
    markets: list[str]
    candidate_ids: list[str]
    label_row_count: int
    candidate_row_count: int
    blockers: list[str]
    ready_for_pre_oos_freeze: bool
    final_oos_rows_read: bool = False
    final_oos_record_written: bool = False
    schema_version: str = "PreOOSReadinessReport.v1"


def _keys(frame: pd.DataFrame) -> set[tuple[str, str, str, str]]:
    return set(zip(
        frame["issuer_id"].astype(str),
        frame["security_code"].astype(str),
        frame["market"].astype(str),
        frame["decision_date"].astype(str),
        strict=True,
    ))


def assess_pre_oos_readiness(
    labels: pd.DataFrame,
    candidate_rows: pd.DataFrame | None,
    *,
    final_oos_start: str,
    minimum_selection_years: int = 4,
) -> PreOOSReadinessReport:
    """Assess only pre-OOS inputs; never accepts or opens a final-OOS input."""
    if minimum_selection_years < 2:
        raise ValueError("minimum_selection_years must be at least two")
    final_start = pd.Timestamp(final_oos_start)
    blockers: list[str] = []
    missing_labels = sorted(_LABEL_REQUIRED - set(labels.columns))
    if labels.empty:
        blockers.append("labels_empty")
    if missing_labels:
        blockers.append("label_columns_missing:" + ",".join(missing_labels))

    generations = (
        sorted(set(labels["generation_id"].astype(str)))
        if "generation_id" in labels else []
    )
    generation = generations[0] if len(generations) == 1 else None
    if len(generations) != 1:
        blockers.append("labels_require_one_generation")

    years: list[int] = []
    markets: list[str] = []
    label_keys: set[tuple[str, str, str, str]] = set()
    if "decision_date" in labels:
        decisions = pd.to_datetime(labels["decision_date"], errors="coerce")
        if decisions.isna().any():
            blockers.append("invalid_label_decision_date")
        else:
            years = sorted(set(decisions.dt.year.astype(int)))
            if len(years) < minimum_selection_years:
                blockers.append(
                    f"selection_years_below_{minimum_selection_years}:{len(years)}"
                )
            if bool((decisions >= final_start).any()):
                blockers.append("labels_cross_final_oos_boundary")
    if "result_end_date" in labels:
        result_ends = pd.to_datetime(labels["result_end_date"], errors="coerce")
        if result_ends.isna().any():
            blockers.append("invalid_label_result_end_date")
        elif bool((result_ends >= final_start).any()):
            blockers.append("label_results_not_complete_before_final_oos")
    if "market" in labels:
        markets = sorted(set(labels["market"].astype(str)))
        missing_markets = sorted({"TWSE", "TPEx"} - set(markets))
        if missing_markets:
            blockers.append("markets_missing:" + ",".join(missing_markets))
    if not missing_labels:
        label_keys = _keys(labels)
        if bool(labels[list(_LABEL_REQUIRED)].isna().to_numpy().any()):
            blockers.append("required_label_values_missing")
        for market, expected_ref in _OFFICIAL_BENCHMARK_REFS.items():
            rows = labels.loc[labels["market"].astype(str).eq(market)]
            if not rows.empty and set(rows["official_benchmark_source_ref"].astype(str)) != {
                expected_ref
            }:
                blockers.append(f"official_benchmark_source_invalid:{market}")

    candidate_ids: list[str] = []
    candidate_count = 0
    if candidate_rows is None:
        blockers.append("candidate_rows_missing")
    else:
        candidate_count = len(candidate_rows)
        missing_candidates = sorted(_CANDIDATE_REQUIRED - set(candidate_rows.columns))
        if candidate_rows.empty:
            blockers.append("candidate_rows_empty")
        if missing_candidates:
            blockers.append(
                "candidate_columns_missing:" + ",".join(missing_candidates)
            )
        if "candidate_id" in candidate_rows:
            candidate_ids = sorted(set(candidate_rows["candidate_id"].astype(str)))
            if len(candidate_ids) < 2:
                blockers.append("at_least_two_pre_oos_candidates_required")
        if not missing_candidates and not candidate_rows.empty:
            candidate_generations = set(candidate_rows["generation_id"].astype(str))
            if generation is None or candidate_generations != {generation}:
                blockers.append("candidate_label_generation_mismatch")
            expected: set[tuple[str, str, str, str]] | None = None
            for candidate_id, rows in candidate_rows.groupby("candidate_id", sort=True):
                row_keys = _keys(rows)
                if expected is None:
                    expected = row_keys
                elif row_keys != expected:
                    blockers.append("candidate_observation_sets_differ")
                    break
            if expected != label_keys:
                blockers.append("candidate_rows_do_not_cover_all_labels")
            decisions = pd.to_datetime(candidate_rows["decision_date"], errors="coerce")
            results = pd.to_datetime(candidate_rows["result_end_date"], errors="coerce")
            trained = pd.to_datetime(candidate_rows["trained_through"], errors="coerce")
            if decisions.isna().any() or results.isna().any() or trained.isna().any():
                blockers.append("invalid_candidate_dates")
            else:
                if bool((decisions >= final_start).any()):
                    blockers.append("candidate_rows_cross_final_oos_boundary")
                if bool((results >= final_start).any()):
                    blockers.append("candidate_results_not_complete_before_final_oos")
                if bool((trained >= decisions - pd.DateOffset(months=12)).any()):
                    blockers.append("candidate_training_cutoff_leaks_labels")
            if bool((candidate_rows["predicted_p10_return"] > candidate_rows["predicted_p50_return"]).any()) or bool(
                (candidate_rows["predicted_p50_return"] > candidate_rows["predicted_p90_return"]).any()
            ):
                blockers.append("candidate_prediction_intervals_unordered")

    blockers = sorted(set(blockers))
    return PreOOSReadinessReport(
        generation_id=generation,
        final_oos_start=final_oos_start,
        label_years=years,
        markets=markets,
        candidate_ids=candidate_ids,
        label_row_count=len(labels),
        candidate_row_count=candidate_count,
        blockers=blockers,
        ready_for_pre_oos_freeze=not blockers,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--final-oos-start", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = assess_pre_oos_readiness(
        pd.read_parquet(args.labels),
        pd.read_parquet(args.candidates) if args.candidates is not None else None,
        final_oos_start=args.final_oos_start,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(report), ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PreOOSReadinessReport", "assess_pre_oos_readiness"]
