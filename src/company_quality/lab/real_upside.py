"""Real, non-publishable 12-month upside-potential candidate validation."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from company_quality.research_snapshot import UpsideCoreResult


_SHA = re.compile(r"^[0-9a-f]{64}$")
_TAIPEI = ZoneInfo("Asia/Taipei")
_EXCLUDED_METRICS = {"management_delivery_ratio"}
_EXCLUDED_FAMILIES = {"people:management_delivery"}


@dataclass(frozen=True, slots=True)
class TemporalWindow:
    train_start: str
    train_end: str
    holdout_start: str
    holdout_end: str
    train_observation_count: int
    holdout_observation_count: int


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _wide(path: Path) -> pd.DataFrame:
    frame = pd.read_feather(path).set_index("date").sort_index()
    frame.columns = [str(column).split()[0] for column in frame.columns]
    return frame.loc[:, ~frame.columns.duplicated(keep="last")]


def _instant(value: object) -> datetime:
    stamp = datetime.fromisoformat(str(value))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        stamp = stamp.replace(tzinfo=_TAIPEI)
    return stamp


def _forward_labels(labels: pd.DataFrame, _adjusted_close: pd.DataFrame) -> pd.DataFrame:
    required = {
        "issuer_id", "security_code", "market", "decision_date", "result_end_date",
        "fully_observed", "actual_total_return", "official_benchmark_return",
        "official_excess_return", "same_market_median_return", "positive_return",
        "outperformed_official_market", "official_benchmark_source_ref",
        "generation_id",
    }
    missing = required - set(labels.columns)
    if missing:
        raise ValueError(
            "official 12-month return labels required: " + ", ".join(sorted(missing))
        )
    frame = labels.loc[
        labels["fully_observed"].astype(bool)
        & labels["actual_total_return"].notna()
        & labels["official_benchmark_return"].notna()
        & labels["official_excess_return"].notna()
    ].copy()
    if frame.empty:
        raise ValueError("no fully observed official 12-month return labels")
    expected_source = {
        "TWSE": "MFI94U",
        "TPEx": "tpex_reward_index",
    }
    if any(
        market not in expected_source
        or expected_source[market] not in str(source)
        for market, source in zip(
            frame["market"].astype(str),
            frame["official_benchmark_source_ref"],
            strict=True,
        )
    ):
        raise ValueError("official total-return benchmark market/source mismatch")
    frame["label_end_date"] = frame["result_end_date"].astype(str)
    frame["market_benchmark_return"] = frame["official_benchmark_return"].astype(float)
    frame["actual_excess_return"] = frame["official_excess_return"].astype(float)
    return frame


def _feature_matrix(features: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    admitted = features.loc[
        features["metric_value"].notna()
        & features["metric_available_at"].notna()
        & ~features["metric_id"].astype(str).isin(tuple(_EXCLUDED_METRICS))
        & ~features["evidence_family_id"].astype(str).isin(tuple(_EXCLUDED_FAMILIES))
        & ~features["evidence_family_id"].astype(str).str.startswith(
            ("technical:", "chip:")
        )
    ].copy()
    admitted["decision_date"] = admitted["decision_date"].astype(str)
    admitted["available"] = admitted["metric_available_at"].map(_instant)
    decision_end = admitted["decision_date"].map(
        lambda value: datetime.fromisoformat(value).replace(
            hour=23, minute=59, second=59, tzinfo=_TAIPEI
        )
    )
    admitted = admitted.loc[admitted["available"] <= decision_end]
    conflicts = admitted.groupby(
        ["issuer_id", "decision_date", "metric_id"]
    )["metric_value"].nunique(dropna=True)
    if (conflicts > 1).any():
        raise ValueError("conflicting PIT feature values")
    pivot = admitted.pivot_table(
        index=["issuer_id", "decision_date"],
        columns="metric_id",
        values="metric_value",
        aggfunc="first",
    ).reset_index()
    pivot.columns.name = None
    feature_ids = sorted(
        column for column in pivot.columns
        if column not in {"issuer_id", "decision_date"}
    )
    if not feature_ids:
        raise ValueError("no admitted upside features")
    return pivot, feature_ids


def _fit_predict(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    feature_ids: list[str],
    target: str,
) -> tuple[np.ndarray, np.ndarray]:
    x_train = train[feature_ids].astype(float)
    medians = x_train.median(axis=0)
    x_train = x_train.fillna(medians)
    x_holdout = holdout[feature_ids].astype(float).fillna(medians)
    means = np.asarray(x_train.mean(axis=0), dtype=float)
    scales = np.asarray(x_train.std(axis=0, ddof=0), dtype=float).copy()
    scales[(scales == 0) | ~np.isfinite(scales)] = 1
    train_array = (x_train.to_numpy(float) - means) / scales
    holdout_array = (x_holdout.to_numpy(float) - means) / scales
    train_design = np.column_stack([np.ones(len(train_array)), train_array])
    holdout_design = np.column_stack([np.ones(len(holdout_array)), holdout_array])
    raw_y = train[target].to_numpy(float)
    lower, upper = np.quantile(raw_y, [0.025, 0.975])
    y = np.clip(raw_y, lower, upper)
    penalty = np.eye(train_design.shape[1])
    penalty[0, 0] = 0
    coefficients = np.linalg.solve(
        train_design.T @ train_design + penalty,
        train_design.T @ y,
    )
    train_prediction = train_design @ coefficients
    return holdout_design @ coefficients, raw_y - train_prediction


def _auc(actual: np.ndarray, score: np.ndarray) -> float | None:
    positives = score[actual == 1]
    negatives = score[actual == 0]
    if not len(positives) or not len(negatives):
        return None
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def _probability(prediction: float, residuals: np.ndarray) -> float:
    return float(np.mean(prediction + residuals > 0))


def _star(probability: float) -> int:
    return min(5, max(1, int(probability * 5) + 1))


def _finite_or_none(value: float | None) -> float | None:
    return value if value is not None and np.isfinite(value) else None


def _holdout_mae(
    data: pd.DataFrame,
    feature_ids: list[str],
    holdout_dates: list[pd.Timestamp],
) -> tuple[float | None, list[str]]:
    actual: list[float] = []
    predicted: list[float] = []
    used: list[str] = []
    for holdout_stamp in holdout_dates:
        train_cutoff = holdout_stamp - pd.DateOffset(months=12)
        train = data.loc[data["decision"] < train_cutoff]
        holdout = data.loc[data["decision"] == holdout_stamp]
        if len(train) < 10 or holdout.empty:
            continue
        if any(train[item].notna().sum() < 2 for item in feature_ids):
            continue
        prediction, _ = _fit_predict(train, holdout, feature_ids, "actual_total_return")
        actual.extend(holdout["actual_total_return"].astype(float))
        predicted.extend(prediction)
        used.append(holdout_stamp.date().isoformat())
    if not actual:
        return None, used
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(predicted)))), used


def _admit_valuation_features(
    outcomes: pd.DataFrame,
    base_matrix: pd.DataFrame,
    base_feature_ids: list[str],
    valuation_features: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], dict[str, object], set[pd.Timestamp]]:
    if set(valuation_features["model_scope"].dropna().astype(str)) != {"upside_only"}:
        raise ValueError("valuation features must be upside_only")
    if not valuation_features["evidence_family_id"].astype(str).str.startswith(
        "valuation:"
    ).all():
        raise ValueError("valuation features require valuation evidence families")
    valuation_matrix, valuation_ids = _feature_matrix(valuation_features)
    base = outcomes.merge(
        base_matrix, on=["issuer_id", "decision_date"], how="inner", validate="one_to_one"
    )
    candidates = base.merge(
        valuation_matrix,
        on=["issuer_id", "decision_date"],
        how="left",
        validate="one_to_one",
    )
    candidates["decision"] = pd.to_datetime(candidates["decision_date"])
    dates = [
        cast(pd.Timestamp, pd.Timestamp(value))
        for value in sorted(candidates["decision"].unique())
    ]
    if len(dates) < 2:
        raise ValueError("valuation challenger requires historical holdouts")
    validation_dates = dates[1:]
    baseline_mae, used_dates = _holdout_mae(
        candidates, base_feature_ids, validation_dates
    )
    if baseline_mae is None:
        raise ValueError("insufficient earlier holdout history for valuation challenger")
    comparisons: list[dict[str, object]] = []
    admitted: list[str] = []
    for metric_id in valuation_ids:
        challenger_mae, metric_dates = _holdout_mae(
            candidates, [*base_feature_ids, metric_id], validation_dates
        )
        gain = (
            baseline_mae - challenger_mae
            if challenger_mae is not None
            else None
        )
        admit = gain is not None and gain > 1e-12 and metric_dates == used_dates
        if admit:
            admitted.append(metric_id)
        comparisons.append({
            "metric_id": metric_id,
            "baseline_mean_absolute_error": baseline_mae,
            "challenger_mean_absolute_error": challenger_mae,
            "mean_absolute_error_gain": gain,
            "admitted": admit,
        })
    combined = base_matrix.merge(
        valuation_matrix.loc[:, ["issuer_id", "decision_date", *admitted]],
        on=["issuer_id", "decision_date"],
        how="left",
        validate="one_to_one",
    )
    report: dict[str, object] = {
        "status": "research_only",
        "publishable": False,
        "earlier_holdout_dates": used_dates,
        "baseline_mean_absolute_error": baseline_mae,
        "admitted_metric_ids": admitted,
        "rejected_metric_ids": [item for item in valuation_ids if item not in admitted],
        "metric_comparisons": comparisons,
    }
    return (
        combined,
        [*base_feature_ids, *admitted],
        report,
        {cast(pd.Timestamp, pd.Timestamp(item)) for item in used_dates},
    )


def build_upside_validation(
    labels: pd.DataFrame,
    features: pd.DataFrame,
    adjusted_close: pd.DataFrame,
    valuation_features: pd.DataFrame | None = None,
    *,
    producer_candidate_sha: str,
    input_artifact_shas: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, object]]:
    if not _SHA.fullmatch(producer_candidate_sha):
        raise ValueError("producer candidate SHA required")
    expected_input_shas = {
        "T21_labels", "real_features", "adjusted_total_return",
        *({"valuation_features"} if valuation_features is not None else set()),
    }
    if set(input_artifact_shas) != expected_input_shas or any(
        not _SHA.fullmatch(value) for value in input_artifact_shas.values()
    ):
        raise ValueError("exact input artifact SHAs required")
    generations = set(labels["generation_id"].astype(str))
    if len(generations) != 1:
        raise ValueError("labels must bind one generation")
    outcomes = _forward_labels(labels, adjusted_close)
    matrix, feature_ids = _feature_matrix(features)
    valuation_report: dict[str, object] = {
        "status": "not_provided",
        "publishable": False,
        "earlier_holdout_dates": [],
        "baseline_mean_absolute_error": None,
        "admitted_metric_ids": [],
        "rejected_metric_ids": [],
        "metric_comparisons": [],
    }
    evaluation_dates: set[pd.Timestamp] | None = None
    if valuation_features is not None:
        matrix, feature_ids, valuation_report, evaluation_dates = _admit_valuation_features(
            outcomes, matrix, feature_ids, valuation_features
        )
    data = outcomes.merge(
        matrix, on=["issuer_id", "decision_date"], how="inner", validate="one_to_one"
    )
    data["decision"] = pd.to_datetime(data["decision_date"])
    predictions: list[pd.DataFrame] = []
    windows: list[TemporalWindow] = []
    for holdout_date in sorted(data["decision"].unique())[1:]:
        holdout_stamp = cast(pd.Timestamp, pd.Timestamp(holdout_date))
        if evaluation_dates is not None and holdout_stamp not in evaluation_dates:
            continue
        train_cutoff = holdout_stamp - pd.DateOffset(months=12)
        train = data.loc[data["decision"] < train_cutoff]
        holdout = data.loc[data["decision"] == holdout_stamp].copy()
        if len(train) < 10 or holdout.empty:
            continue
        return_prediction, return_residuals = _fit_predict(
            train, holdout, feature_ids, "actual_total_return"
        )
        excess_prediction, excess_residuals = _fit_predict(
            train, holdout, feature_ids, "actual_excess_return"
        )
        quantiles = np.quantile(return_residuals, [0.1, 0.5, 0.9])
        holdout["predicted_p10_return"] = return_prediction + quantiles[0]
        holdout["predicted_p50_return"] = return_prediction + quantiles[1]
        holdout["predicted_p90_return"] = return_prediction + quantiles[2]
        holdout["positive_return_probability"] = [
            _probability(value, return_residuals) for value in return_prediction
        ]
        holdout["outperform_probability"] = [
            _probability(value, excess_residuals) for value in excess_prediction
        ]
        holdout["baseline_p50_return"] = float(
            train["actual_total_return"].median()
        )
        holdout["baseline_positive_probability"] = float(
            (train["actual_total_return"] > 0).mean()
        )
        holdout["star"] = np.nan
        predictions.append(holdout)
        windows.append(TemporalWindow(
            train_start=train["decision_date"].min(),
            train_end=train["decision_date"].max(),
            holdout_start=holdout["decision_date"].min(),
            holdout_end=holdout["decision_date"].max(),
            train_observation_count=len(train),
            holdout_observation_count=len(holdout),
        ))
    if not predictions:
        raise ValueError("insufficient temporal history for upside holdout")
    result = pd.concat(predictions, ignore_index=True)
    actual = result["actual_total_return"].to_numpy(float)
    p50 = result["predicted_p50_return"].to_numpy(float)
    excess_actual = (result["actual_excess_return"] > 0).astype(int).to_numpy()
    outperform_probability = result["outperform_probability"].to_numpy(float)
    baseline_p50 = result["baseline_p50_return"].to_numpy(float)
    baseline_positive_probability = result[
        "baseline_positive_probability"
    ].to_numpy(float)
    report: dict[str, object] = {
        "schema_version": "UpsidePotentialValidationReport.v1",
        "source_version": "RealT21LabelIndex.v1+RealPITFeatureMatrix.v1+PITValuationFeatures.v1+pre_adjusted_total_return",
        "model_version": "train_only_ridge_residual_distribution.v1",
        "formula_version": "12m-adjusted-return-official-market-total-return-benchmark.v1",
        "status": "NON_PUBLISHABLE_DIAGNOSTIC_NO_APPROVED_GATE",
        "publishable": False,
        "rating_disposition": "NO_RATING_NOT_APPLICABLE",
        "prediction_target": "12m_adjusted_total_return",
        "benchmark": "official_market_total_return_index",
        "secondary_benchmark": "same_market_decision_date_median_return",
        "valuation_challenger": valuation_report,
        "feature_ids": feature_ids,
        "excluded_feature_families": [
            "management_delivery", "management_continuity", "succession_planning",
            "technical", "chip",
        ],
        "temporal_windows": [asdict(window) for window in windows],
        "label_observation_count": len(outcomes),
        "model_observation_count": len(data),
        "holdout_observation_count": len(result),
        "metrics": {
            "mean_absolute_error": float(np.mean(np.abs(actual - p50))),
            "spearman_rank_correlation": _finite_or_none(float(
                pd.Series(actual).rank().corr(pd.Series(p50).rank())
            )),
            "positive_direction_accuracy": float(np.mean(
                (result["positive_return_probability"].to_numpy() >= 0.5)
                == (actual > 0)
            )),
            "outperform_auc": _finite_or_none(
                _auc(excess_actual, outperform_probability)
            ),
            "p10_p90_interval_coverage": float(np.mean(
                (actual >= result["predicted_p10_return"].to_numpy())
                & (actual <= result["predicted_p90_return"].to_numpy())
            )),
            "naive_median_mean_absolute_error": float(
                np.mean(np.abs(actual - baseline_p50))
            ),
            "naive_positive_direction_accuracy": float(np.mean(
                (baseline_positive_probability >= 0.5) == (actual > 0)
            )),
        },
        "input_artifact_shas": dict(sorted(input_artifact_shas.items())),
        "generation_id": next(iter(generations)),
        "producer_candidate_sha": producer_candidate_sha,
    }
    output_columns = [
        "issuer_id", "security_code", "market", "decision_date", "label_end_date",
        "actual_total_return", "market_benchmark_return", "actual_excess_return",
        "same_market_median_return", "official_benchmark_source_ref",
        "predicted_p10_return", "predicted_p50_return", "predicted_p90_return",
        "positive_return_probability", "outperform_probability", "star",
        "generation_id",
    ]
    return result.loc[:, output_columns].copy(), report


def to_research_upside_core_result(
    prediction: pd.Series,
    report: dict[str, object],
) -> UpsideCoreResult:
    """Map an untouched-holdout row into the same-generation snapshot seam."""
    if report.get("publishable") is not False or cast(
        bool, pd.notna(prediction.get("star"))
    ):
        raise ValueError("only unpublished research upside results may enter this seam")
    if str(prediction["generation_id"]) != str(report["generation_id"]):
        raise ValueError("prediction/report generation mismatch")
    return UpsideCoreResult(
        generation_id=str(prediction["generation_id"]),
        status="research_only",
        positive_return_probability=float(prediction["positive_return_probability"]),
        official_benchmark_outperform_probability=float(
            prediction["outperform_probability"]
        ),
        secondary_market_median_outperform_probability=None,
        p10_return=float(prediction["predicted_p10_return"]),
        p50_return=float(prediction["predicted_p50_return"]),
        p90_return=float(prediction["predicted_p90_return"]),
        p10_price=None,
        p50_price=None,
        p90_price=None,
        stars=None,
        confidence=None,
        model_version=str(report["model_version"]),
        data_as_of=str(prediction["decision_date"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--valuation-features", required=True, type=Path)
    parser.add_argument("--adjusted-close", required=True, type=Path)
    parser.add_argument("--predictions-output", required=True, type=Path)
    parser.add_argument("--report-output", required=True, type=Path)
    args = parser.parse_args()
    source_sha = _file_sha(Path(__file__))
    predictions, report = build_upside_validation(
        pd.read_parquet(args.labels),
        pd.read_parquet(args.features),
        _wide(args.adjusted_close),
        pd.read_parquet(args.valuation_features),
        producer_candidate_sha=source_sha,
        input_artifact_shas={
            "T21_labels": _file_sha(args.labels),
            "real_features": _file_sha(args.features),
            "adjusted_total_return": _file_sha(args.adjusted_close),
            "valuation_features": _file_sha(args.valuation_features),
        },
    )
    args.predictions_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(args.predictions_output, index=False)
    args.report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
