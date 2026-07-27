"""One-shot final-OOS qualification gate for the D08 frozen champion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from company_quality.lab.model_competition import FrozenPreOOSCandidate


_REQUIRED = {
    "candidate_id", "issuer_id", "market", "industry_code", "industry_status",
    "decision_date", "trained_through", "generation_id", "actual_total_return",
    "official_benchmark_return", "predicted_p10_return", "predicted_p50_return",
    "predicted_p90_return", "positive_return_probability", "outperform_probability",
    "star", "result_status", "industry_train_observations",
    "frozen_naive_prediction", "frozen_naive_positive_probability",
    "frozen_linear_prediction", "naive_baseline_id", "linear_baseline_id",
    "baseline_frozen_through",
}


@dataclass(frozen=True, slots=True)
class OneShotOOSGateReport:
    evaluation_key: str
    generation_id: str
    champion_candidate_id: str
    final_oos_start: str
    final_oos_end: str
    overall: dict[str, object]
    markets: list[dict[str, object]]
    eligible_industries: list[dict[str, object]]
    missing_markets: list[str]
    gate_passed: bool
    publication_candidate_eligible: bool
    publishable: bool = False
    formal_stars_emitted: bool = False
    release_authorized: bool = False
    t23_authorized: bool = False
    status: str = "research_only"
    schema_version: str = "OneShotOOSGateReport.v1"


def _auc(actual: np.ndarray, score: np.ndarray) -> float | None:
    positives = score[actual == 1]
    negatives = score[actual == 0]
    if not len(positives) or not len(negatives):
        return None
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives for negative in negatives
    )
    return float(wins / (len(positives) * len(negatives)))


def _metrics(frame: pd.DataFrame, *, scope: str) -> dict[str, object]:
    actual = frame["actual_total_return"].to_numpy(float)
    predicted = frame["predicted_p50_return"].to_numpy(float)
    benchmark = frame["official_benchmark_return"].to_numpy(float)
    naive = frame["frozen_naive_prediction"].to_numpy(float)
    linear = frame["frozen_linear_prediction"].to_numpy(float)
    champion_mae = float(np.mean(np.abs(actual - predicted)))
    naive_mae = float(np.mean(np.abs(actual - naive)))
    linear_mae = float(np.mean(np.abs(actual - linear)))
    mae_improvement = (
        (naive_mae - champion_mae) / naive_mae if naive_mae > 0 else None
    )
    direction = actual > 0
    champion_direction = frame["positive_return_probability"].to_numpy(float) >= 0.5
    naive_direction = (
        frame["frozen_naive_positive_probability"].to_numpy(float) >= 0.5
    )
    champion_direction_accuracy = float(np.mean(direction == champion_direction))
    naive_direction_accuracy = float(np.mean(direction == naive_direction))
    direction_gain = champion_direction_accuracy - naive_direction_accuracy
    raw_rank_correlation = float(
        pd.Series(actual).rank().corr(pd.Series(predicted).rank())
    )
    rank_correlation = (
        raw_rank_correlation if np.isfinite(raw_rank_correlation) else None
    )
    excess = (actual > benchmark).astype(int)
    outperform_auc = _auc(
        excess, frame["outperform_probability"].to_numpy(float)
    )
    coverage = float(np.mean(
        (actual >= frame["predicted_p10_return"].to_numpy(float))
        & (actual <= frame["predicted_p90_return"].to_numpy(float))
    ))
    checks = {
        "minimum_observations": len(frame) >= 100,
        "rank_correlation_at_least_0_10": (
            rank_correlation is not None and rank_correlation >= 0.10
        ),
        "official_outperform_auc_at_least_0_62": (
            outperform_auc is not None and outperform_auc >= 0.62
        ),
        "mae_improvement_at_least_5_percent": (
            mae_improvement is not None and mae_improvement >= 0.05
        ),
        "direction_accuracy_gain_at_least_0_05": direction_gain >= 0.05,
        "p10_p90_coverage_between_0_75_and_0_85": 0.75 <= coverage <= 0.85,
        "beats_no_company_data_baseline": champion_mae < naive_mae,
        "beats_same_data_normalized_linear": champion_mae < linear_mae,
        "industry_train_sample_at_least_500": bool(
            (frame["industry_train_observations"].astype(float) >= 500).all()
        ),
    }
    return {
        "scope": scope,
        "observation_count": len(frame),
        "spearman_rank_correlation": rank_correlation,
        "official_outperform_auc": outperform_auc,
        "champion_mean_absolute_error": champion_mae,
        "naive_mean_absolute_error": naive_mae,
        "normalized_linear_mean_absolute_error": linear_mae,
        "mae_improvement_vs_naive": mae_improvement,
        "champion_direction_accuracy": champion_direction_accuracy,
        "naive_direction_accuracy": naive_direction_accuracy,
        "direction_accuracy_gain": direction_gain,
        "p10_p90_interval_coverage": coverage,
        "checks": checks,
        "passed": all(checks.values()),
    }


def evaluate_one_shot_oos_gate(
    rows: pd.DataFrame,
    freeze: FrozenPreOOSCandidate,
    *,
    evaluation_record_path: Path,
    prior_reports: Sequence[OneShotOOSGateReport] = (),
) -> OneShotOOSGateReport:
    if evaluation_record_path.exists():
        raise ValueError("final OOS was already evaluated; retest is forbidden")
    missing = _REQUIRED - set(rows.columns)
    if missing:
        raise ValueError("final-OOS gate rows missing: " + ", ".join(sorted(missing)))
    if rows.empty:
        raise ValueError("final-OOS rows required")
    evaluation_key = (
        f"{freeze.generation_id}:{freeze.champion_candidate_id}:{freeze.final_oos_start}"
    )
    if any(report.evaluation_key == evaluation_key for report in prior_reports):
        raise ValueError("final OOS was already evaluated; retest is forbidden")
    if set(rows["candidate_id"].astype(str)) != {freeze.champion_candidate_id}:
        raise ValueError("only the D08 frozen champion may enter final OOS")
    if set(rows["generation_id"].astype(str)) != {freeze.generation_id}:
        raise ValueError("freeze/final-OOS generation mismatch")
    if set(rows["result_status"].astype(str)) != {"research_only"} or bool(
        rows["star"].notna().any()
    ):
        raise ValueError("final OOS must remain unpublished before qualification")
    decision = pd.to_datetime(rows["decision_date"])
    trained = pd.to_datetime(rows["trained_through"])
    baseline_frozen = pd.to_datetime(rows["baseline_frozen_through"])
    if bool((decision < pd.Timestamp(freeze.final_oos_start)).any()):
        raise ValueError("rows precede the frozen final-OOS boundary")
    if len(set(decision.dt.year.astype(int))) != 1:
        raise ValueError("one final OOS year required")
    if bool((trained > pd.Timestamp(freeze.frozen_through)).any()):
        raise ValueError("champion was retrained after D08 freeze")
    if bool((baseline_frozen > pd.Timestamp(freeze.frozen_through)).any()):
        raise ValueError("baseline was refit after D08 freeze")
    if set(rows["naive_baseline_id"].astype(str)) != {
        "no_company_data_temporal_median"
    } or set(rows["linear_baseline_id"].astype(str)) != {
        "same_data_normalized_linear"
    }:
        raise ValueError("D08 frozen baseline identities required")

    eligible = rows.loc[rows["industry_status"].astype(str).eq("eligible")].copy()
    overall = _metrics(eligible, scope="overall") if not eligible.empty else {
        "scope": "overall", "observation_count": 0, "checks": {}, "passed": False
    }
    markets = [
        _metrics(group, scope=f"market:{market}")
        for market, group in eligible.groupby("market", sort=True)
    ]
    present_markets = set(eligible["market"].astype(str))
    missing_markets = sorted({"TWSE", "TPEx"} - present_markets)
    industries = [
        _metrics(group, scope=f"industry:{market}:{industry}")
        for (market, industry), group in eligible.groupby(
            ["market", "industry_code"], sort=True
        )
    ]
    gate_passed = bool(
        overall["passed"]
        and not missing_markets
        and markets
        and industries
        and all(bool(item["passed"]) for item in markets)
        and all(bool(item["passed"]) for item in industries)
    )
    report = OneShotOOSGateReport(
        evaluation_key=evaluation_key,
        generation_id=freeze.generation_id,
        champion_candidate_id=freeze.champion_candidate_id,
        final_oos_start=str(rows["decision_date"].min()),
        final_oos_end=str(rows["decision_date"].max()),
        overall=overall,
        markets=markets,
        eligible_industries=industries,
        missing_markets=missing_markets,
        gate_passed=gate_passed,
        publication_candidate_eligible=gate_passed,
    )
    try:
        with evaluation_record_path.open("x", encoding="utf-8") as handle:
            json.dump(asdict(report), handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError("final OOS was already evaluated; retest is forbidden") from exc
    return report


__all__ = ["OneShotOOSGateReport", "evaluate_one_shot_oos_gate"]
