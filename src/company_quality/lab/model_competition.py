"""Leakage-safe pre-OOS model competition and frozen research star weights."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from company_quality.research_snapshot import UpsideCoreResult


_REQUIRED = {
    "candidate_id", "issuer_id", "security_code", "market", "decision_date",
    "result_end_date", "trained_through", "generation_id", "actual_total_return",
    "official_benchmark_return", "predicted_p10_return", "predicted_p50_return",
    "predicted_p90_return", "positive_return_probability", "outperform_probability",
    "data_completeness", "industry_train_observations",
}
_CONFIDENCE_WEIGHTS = {
    "data_completeness": 0.35,
    "interval_precision": 0.25,
    "industry_sample": 0.20,
    "cross_year_stability": 0.20,
}


@dataclass(frozen=True, slots=True)
class FrozenPreOOSCandidate:
    generation_id: str
    final_oos_start: str
    frozen_through: str
    champion_candidate_id: str
    champion_score: float
    candidate_scores: list[dict[str, object]]
    fixed_baselines: list[dict[str, object]]
    star_weights: dict[str, float]
    confidence_weights: dict[str, float]
    cross_year_stability: float
    selection_row_count: int
    selection_years: list[int]
    status: str = "research_only"
    publishable: bool = False
    formal_stars_enabled: bool = False
    schema_version: str = "FrozenPreOOSCandidate.v1"


def _day(value: object, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    missing = _REQUIRED - set(frame.columns)
    if missing:
        raise ValueError("competition rows missing: " + ", ".join(sorted(missing)))
    if frame.empty:
        raise ValueError("competition rows required")
    generations = set(frame["generation_id"].astype(str))
    if len(generations) != 1:
        raise ValueError("competition requires one generation")
    result = frame.copy()
    result["decision"] = pd.to_datetime(result["decision_date"])
    result["result_end"] = pd.to_datetime(result["result_end_date"])
    result["trained"] = pd.to_datetime(result["trained_through"])
    label_cutoff = result["decision"] - pd.DateOffset(months=12)
    if bool((result["trained"] >= label_cutoff).any()):
        raise ValueError(
            "candidate training cutoff must precede decision by more than 12 months"
        )
    for field in (
        "positive_return_probability", "outperform_probability", "data_completeness"
    ):
        values = result[field].astype(float)
        if bool(((values < 0) | (values > 1)).any()):
            raise ValueError(f"{field} outside 0..1")
    if bool((result["industry_train_observations"].astype(float) < 0).any()):
        raise ValueError("industry sample cannot be negative")
    if bool((result["predicted_p10_return"] > result["predicted_p50_return"]).any()) or bool(
        (result["predicted_p50_return"] > result["predicted_p90_return"]).any()
    ):
        raise ValueError("ordered prediction interval required")
    return result


def _auc(actual: np.ndarray, score: np.ndarray) -> float:
    positives = score[actual == 1]
    negatives = score[actual == 0]
    if not len(positives) or not len(negatives):
        return 0.5
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives for negative in negatives
    )
    return float(wins / (len(positives) * len(negatives)))


def _candidate_score(frame: pd.DataFrame) -> tuple[float, dict[str, object]]:
    actual = frame["actual_total_return"].to_numpy(float)
    prediction = frame["predicted_p50_return"].to_numpy(float)
    excess = (actual > frame["official_benchmark_return"].to_numpy(float)).astype(int)
    probability = frame["outperform_probability"].to_numpy(float)
    mae = float(np.mean(np.abs(actual - prediction)))
    brier = float(np.mean((excess - probability) ** 2))
    auc = _auc(excess, probability)
    score = mae + brier
    return score, {
        "candidate_id": str(frame["candidate_id"].iloc[0]),
        "mean_absolute_error": mae,
        "outperform_brier": brier,
        "outperform_auc": auc,
        "selection_score": score,
        "row_count": len(frame),
    }


def _fit_linear(train: pd.DataFrame, holdout: pd.DataFrame, fields: list[str]) -> np.ndarray:
    x_train = train[fields].astype(float)
    medians = x_train.median(axis=0)
    x_train = x_train.fillna(medians)
    x_holdout = holdout[fields].astype(float).fillna(medians)
    means = x_train.mean(axis=0).to_numpy(float)
    scales = x_train.std(axis=0, ddof=0).to_numpy(float)
    scales[(scales == 0) | ~np.isfinite(scales)] = 1.0
    train_design = np.column_stack([
        np.ones(len(train)), (x_train.to_numpy(float) - means) / scales
    ])
    holdout_design = np.column_stack([
        np.ones(len(holdout)), (x_holdout.to_numpy(float) - means) / scales
    ])
    penalty = np.eye(train_design.shape[1])
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        train_design.T @ train_design + penalty,
        train_design.T @ train["actual_total_return"].to_numpy(float),
    )
    return holdout_design @ coefficients


def _fixed_baselines(rows: pd.DataFrame) -> list[dict[str, object]]:
    feature_ids = sorted(column for column in rows if column.startswith("linear_feature_"))
    identity = [
        "issuer_id", "decision_date", "actual_total_return", "official_benchmark_return",
        *feature_ids,
    ]
    conflicts = rows.groupby(["issuer_id", "decision_date"])[
        ["actual_total_return", "official_benchmark_return", *feature_ids]
    ].nunique(dropna=False)
    if bool((conflicts > 1).any(axis=None)):
        raise ValueError("candidate baselines must share identical observations")
    observations = rows.loc[:, identity].drop_duplicates(
        ["issuer_id", "decision_date"], keep="first"
    )
    if observations.empty:
        raise ValueError("unique baseline observations required")
    observations["decision"] = pd.to_datetime(observations["decision_date"])
    naive_actual: list[float] = []
    naive_predicted: list[float] = []
    benchmark_predicted: list[float] = []
    linear_actual: list[float] = []
    linear_predicted: list[float] = []
    for holdout_date in sorted(observations["decision"].unique())[1:]:
        holdout_stamp = pd.Timestamp(holdout_date)
        train = observations.loc[
            observations["decision"] < holdout_stamp - pd.DateOffset(months=12)
        ]
        holdout = observations.loc[observations["decision"] == holdout_stamp]
        if len(train) < 10 or holdout.empty:
            continue
        actual = holdout["actual_total_return"].to_numpy(float)
        naive_actual.extend(actual)
        naive_predicted.extend(
            np.repeat(float(train["actual_total_return"].median()), len(holdout))
        )
        benchmark_predicted.extend(
            holdout["official_benchmark_return"].to_numpy(float)
        )
        if feature_ids:
            linear_actual.extend(actual)
            linear_predicted.extend(_fit_linear(train, holdout, feature_ids))
    naive_mae = (
        float(np.mean(np.abs(np.asarray(naive_actual) - np.asarray(naive_predicted))))
        if naive_actual else None
    )
    benchmark_guess_mae = (
        float(np.mean(np.abs(np.asarray(naive_actual) - np.asarray(benchmark_predicted))))
        if naive_actual else None
    )
    linear_mae = (
        float(np.mean(np.abs(np.asarray(linear_actual) - np.asarray(linear_predicted))))
        if linear_actual else None
    )
    return [
        {
            "baseline_id": "no_company_data_temporal_median",
            "mean_absolute_error": naive_mae,
            "official_benchmark_guess_mean_absolute_error": benchmark_guess_mae,
            "uses_company_features": False,
            "frozen": True,
        },
        {
            "baseline_id": "same_data_normalized_linear",
            "mean_absolute_error": linear_mae,
            "uses_company_features": True,
            "feature_ids": feature_ids,
            "frozen": True,
        },
    ]


def _stability(frame: pd.DataFrame) -> float:
    yearly = frame.assign(year=frame["decision"].dt.year).groupby("year").apply(
        lambda item: float(np.mean(np.abs(
            item["actual_total_return"].to_numpy(float)
            - item["predicted_p50_return"].to_numpy(float)
        ))),
        include_groups=False,
    )
    return float(1.0 / (1.0 + float(yearly.std(ddof=0)))) if len(yearly) else 0.0


def _confidence(frame: pd.DataFrame, stability: float) -> np.ndarray:
    completeness = frame["data_completeness"].to_numpy(float)
    width = np.maximum(
        frame["predicted_p90_return"].to_numpy(float)
        - frame["predicted_p10_return"].to_numpy(float),
        0.0,
    )
    precision = 1.0 / (1.0 + width)
    sample = np.minimum(
        frame["industry_train_observations"].to_numpy(float) / 500.0, 1.0
    )
    return (
        _CONFIDENCE_WEIGHTS["data_completeness"] * completeness
        + _CONFIDENCE_WEIGHTS["interval_precision"] * precision
        + _CONFIDENCE_WEIGHTS["industry_sample"] * sample
        + _CONFIDENCE_WEIGHTS["cross_year_stability"] * stability
    )


def _learn_star_weights(frame: pd.DataFrame, confidence: np.ndarray) -> dict[str, float]:
    p50_scaled = 1.0 / (
        1.0 + np.exp(-frame["predicted_p50_return"].to_numpy(float))
    )
    x = np.column_stack([
        frame["outperform_probability"].to_numpy(float),
        p50_scaled,
        confidence,
    ])
    design = np.column_stack([np.ones(len(x)), x])
    target = (
        frame["actual_total_return"].to_numpy(float)
        > frame["official_benchmark_return"].to_numpy(float)
    ).astype(float)
    penalty = np.eye(design.shape[1])
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        design.T @ design + penalty, design.T @ target
    )[1:]
    positive = np.maximum(coefficients, 1e-6)
    normalized = positive / positive.sum()
    return dict(zip(
        ("official_outperform_probability", "predicted_p50_return", "confidence"),
        (float(item) for item in normalized),
        strict=True,
    ))


def freeze_pre_oos_candidate(
    rows: pd.DataFrame,
    *,
    final_oos_start: str,
) -> FrozenPreOOSCandidate:
    data = _validate(rows)
    final_start = pd.Timestamp(_day(final_oos_start, "final_oos_start"))
    if bool((data["decision"] >= final_start).any()):
        raise ValueError("final OOS rows cannot enter selection or weight learning")
    if bool((data["result_end"] >= final_start).any()):
        raise ValueError(
            "pre-OOS outcome labels must finish before the final-OOS boundary"
        )
    scores: list[dict[str, object]] = []
    numeric_scores: list[tuple[float, str]] = []
    expected_keys: set[tuple[str, str]] | None = None
    for candidate_id, candidate_rows in data.groupby("candidate_id", sort=True):
        keys = set(zip(
            candidate_rows["issuer_id"].astype(str),
            candidate_rows["decision_date"].astype(str),
            strict=True,
        ))
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise ValueError("all candidates must use identical pre-OOS observations")
        score, detail = _candidate_score(candidate_rows)
        scores.append(detail)
        numeric_scores.append((score, str(candidate_id)))
    numeric_scores.sort()
    if len(numeric_scores) > 1 and abs(numeric_scores[0][0] - numeric_scores[1][0]) <= 1e-12:
        raise ValueError("no unique pre-OOS champion")
    champion_score, champion_id = numeric_scores[0]
    champion = data.loc[data["candidate_id"].astype(str).eq(champion_id)].copy()
    stability = _stability(champion)
    confidence = _confidence(champion, stability)
    weights = _learn_star_weights(champion, confidence)
    return FrozenPreOOSCandidate(
        generation_id=str(data["generation_id"].iloc[0]),
        final_oos_start=final_oos_start,
        frozen_through=str(data["decision_date"].max()),
        champion_candidate_id=champion_id,
        champion_score=champion_score,
        candidate_scores=scores,
        fixed_baselines=_fixed_baselines(data),
        star_weights=weights,
        confidence_weights=dict(_CONFIDENCE_WEIGHTS),
        cross_year_stability=stability,
        selection_row_count=len(champion),
        selection_years=sorted(set(champion["decision"].dt.year.astype(int))),
    )


def evaluate_frozen_final_oos(
    rows: pd.DataFrame,
    freeze: FrozenPreOOSCandidate,
) -> pd.DataFrame:
    data = _validate(rows)
    if set(data["candidate_id"].astype(str)) != {freeze.champion_candidate_id}:
        raise ValueError("final OOS must use only the frozen champion")
    if set(data["generation_id"].astype(str)) != {freeze.generation_id}:
        raise ValueError("freeze/final-OOS generation mismatch")
    if bool((data["decision"] < pd.Timestamp(freeze.final_oos_start)).any()):
        raise ValueError("final OOS rows must begin at the frozen boundary")
    if bool((data["trained"] > pd.Timestamp(freeze.frozen_through)).any()):
        raise ValueError("final OOS model may not train after freeze cutoff")
    confidence = _confidence(data, freeze.cross_year_stability)
    p50 = data["predicted_p50_return"].to_numpy(float)
    p50_scaled = 1.0 / (1.0 + np.exp(-p50))
    research_score = 5.0 * (
        freeze.star_weights["official_outperform_probability"]
        * data["outperform_probability"].to_numpy(float)
        + freeze.star_weights["predicted_p50_return"] * p50_scaled
        + freeze.star_weights["confidence"] * confidence
    )
    result = data.copy()
    result["confidence"] = confidence
    result["research_star_score"] = np.clip(research_score, 0.0, 5.0)
    result["star"] = np.nan
    result["result_status"] = "research_only"
    return result


def to_frozen_research_upside_core_result(
    row: pd.Series,
    freeze: FrozenPreOOSCandidate,
) -> UpsideCoreResult:
    if pd.notna(row.get("star")) or str(row["generation_id"]) != freeze.generation_id:
        raise ValueError("only same-generation unpublished frozen result allowed")
    return UpsideCoreResult(
        generation_id=freeze.generation_id,
        status="research_only",
        positive_return_probability=float(row["positive_return_probability"]),
        official_benchmark_outperform_probability=float(row["outperform_probability"]),
        secondary_market_median_outperform_probability=None,
        p10_return=float(row["predicted_p10_return"]),
        p50_return=float(row["predicted_p50_return"]),
        p90_return=float(row["predicted_p90_return"]),
        p10_price=None,
        p50_price=None,
        p90_price=None,
        stars=None,
        confidence=float(row["confidence"]),
        model_version=f"frozen-pre-oos:{freeze.champion_candidate_id}",
        data_as_of=str(row["decision_date"]),
    )


__all__ = [
    "FrozenPreOOSCandidate",
    "evaluate_frozen_final_oos",
    "freeze_pre_oos_candidate",
    "to_frozen_research_upside_core_result",
]
