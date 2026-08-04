"""Reproducible F000 PIT multi-label upside tracer-bullet.

The experiment is intentionally research-only.  It compares the fixed pooled-industry
ridge model with one fixed challenger that adds train-time, multi-hot TPEx value-chain
node effects.  Node memberships are partial-pooled by the same ridge penalty and never
expand an issuer/security/decision observation into multiple model rows.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from company_quality.lab.official_benchmarks import (
    TPEX_TOTAL_RETURN_URL,
    TWSE_TOTAL_RETURN_URL,
)


_SHA = re.compile(r"^[0-9a-f]{64}$")
_KEY = ["issuer_id", "security_code", "market", "decision_date"]
_OBSERVATION_KEY = ["issuer_id", "security_code", "decision_date"]
_FIXED_DATES = [f"{year}-06-30" for year in range(2014, 2023)]
_ELIGIBLE_DATES = [f"{year}-06-30" for year in range(2016, 2022)]
_EXCLUDED_DATES = {
    "2014-06-30": "NO_PRE_DECISION_SNAPSHOT",
    "2015-06-30": "NO_PRE_DECISION_SNAPSHOT",
    "2022-06-30": "STALE_AUDIT_ONLY",
}
_BASELINE_ID = "frozen_pooled_industry_ridge_full_v1"
_CHALLENGER_ID = "f000_multilabel_partial_pooling_ridge_v1"
_RIDGE_PENALTY = 1000.0
_TAIPEI = ZoneInfo("Asia/Taipei")


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _instant(value: object) -> datetime:
    stamp = datetime.fromisoformat(str(value))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        stamp = stamp.replace(tzinfo=_TAIPEI)
    return stamp


def _validate_labels(labels: pd.DataFrame) -> pd.DataFrame:
    required = {
        *_KEY,
        "result_end_date",
        "fully_observed",
        "actual_total_return",
        "official_benchmark_return",
        "official_excess_return",
        "outperformed_official_market",
        "official_benchmark_source_ref",
        "same_market_median_return",
        "generation_id",
        "official_industry_code",
    }
    missing = required - set(labels.columns)
    if missing:
        raise ValueError("official labels missing: " + ", ".join(sorted(missing)))
    frame = labels.loc[
        labels["fully_observed"].astype(bool)
        & labels["actual_total_return"].notna()
        & labels["official_benchmark_return"].notna()
        & labels["official_excess_return"].notna()
        & labels["official_industry_code"].astype(str).eq("25")
    ].copy()
    if frame.empty:
        raise ValueError("no fully observed official-industry-code-25 labels")
    if frame.duplicated(_OBSERVATION_KEY).any():
        raise ValueError("labels must contain exactly one row per issuer/security/decision")
    expected_sources = {"TWSE": TWSE_TOTAL_RETURN_URL, "TPEx": TPEX_TOTAL_RETURN_URL}
    mismatched = [
        market not in expected_sources or expected_sources[market] != str(source)
        for market, source in zip(
            frame["market"].astype(str),
            frame["official_benchmark_source_ref"],
            strict=True,
        )
    ]
    if any(mismatched):
        raise ValueError("official total-return benchmark market/source mismatch")
    actual_excess = (
        frame["actual_total_return"].astype(float)
        - frame["official_benchmark_return"].astype(float)
    )
    if not np.allclose(
        actual_excess,
        frame["official_excess_return"].astype(float),
        atol=1e-8,
        rtol=0.0,
    ):
        raise ValueError("official excess-return label mismatch")
    generations = set(frame["generation_id"].astype(str))
    if len(generations) != 1:
        raise ValueError("labels must bind one generation")
    frame["decision_date"] = frame["decision_date"].astype(str)
    return frame


def _mapping_contract(mapping: pd.DataFrame) -> pd.DataFrame:
    required = {
        "decision_date",
        "snapshot_timestamp",
        "status",
        "snapshot_age_days",
        "fresh_within_365d",
    }
    missing = required - set(mapping.columns)
    if missing:
        raise ValueError("snapshot mapping missing: " + ", ".join(sorted(missing)))
    frame = mapping.copy()
    frame["decision_date"] = frame["decision_date"].astype(str)
    if frame.duplicated("decision_date").any() or sorted(frame["decision_date"]) != _FIXED_DATES:
        raise ValueError("snapshot mapping must contain exactly 2014-2022 decisions")
    status = dict(zip(frame["decision_date"], frame["status"].astype(str), strict=True))
    if any(status[day] != reason for day, reason in _EXCLUDED_DATES.items()):
        raise ValueError("missing/stale snapshot audit status mismatch")
    for _, row in frame.iterrows():
        day = str(row["decision_date"])
        if day not in _ELIGIBLE_DATES:
            continue
        if str(row["status"]) != "AVAILABLE" or not bool(row["fresh_within_365d"]):
            raise ValueError("2016-2021 decisions require fresh AVAILABLE snapshots")
        age = int(cast(int, row["snapshot_age_days"]))
        if age < 0 or age > 365:
            raise ValueError("fresh snapshot age must be within 0..365 days")
        snapshot = datetime.strptime(str(row["snapshot_timestamp"]).split(".")[0], "%Y%m%d%H%M%S")
        if snapshot.date() >= datetime.fromisoformat(day).date():
            raise ValueError("snapshot must be strictly pre-decision")
    return frame


def _memberships(
    memberships: pd.DataFrame,
    mapping: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    required = {
        "decision_date",
        "snapshot_timestamp",
        "snapshot_age_days",
        "fresh_within_365d",
        "chain_code",
        "node_code",
        "security_code",
    }
    missing = required - set(memberships.columns)
    if missing:
        raise ValueError("F000 memberships missing: " + ", ".join(sorted(missing)))
    raw = memberships.copy()
    raw["decision_date"] = raw["decision_date"].astype(str)
    raw["security_code"] = raw["security_code"].astype(str)
    raw["node_code"] = raw["node_code"].astype(str)
    if set(raw["chain_code"].astype(str)) != {"F000"}:
        raise ValueError("only F000 memberships allowed")
    fresh = raw.loc[
        raw["decision_date"].isin(_ELIGIBLE_DATES)
        & raw["fresh_within_365d"].astype(bool)
    ].copy()
    before = len(fresh)
    fresh = fresh.drop_duplicates(
        ["decision_date", "snapshot_timestamp", "security_code", "node_code"]
    )
    eligible_mapping = mapping.loc[
        mapping["decision_date"].isin(_ELIGIBLE_DATES),
        ["decision_date", "snapshot_timestamp", "snapshot_age_days"],
    ].copy()
    for column in ("snapshot_timestamp", "snapshot_age_days"):
        fresh[column] = fresh[column].astype(str).str.removesuffix(".0")
        eligible_mapping[column] = eligible_mapping[column].astype(str).str.removesuffix(".0")
    checked = fresh.merge(
        eligible_mapping,
        on=["decision_date", "snapshot_timestamp", "snapshot_age_days"],
        how="inner",
        validate="many_to_one",
    )
    if len(checked) != len(fresh):
        raise ValueError("membership rows do not bind the audited fresh snapshot mapping")
    if set(checked["decision_date"]) != set(_ELIGIBLE_DATES):
        raise ValueError("fresh memberships required for every 2016-2021 decision")
    return checked, {
        "raw_membership_row_count": len(raw),
        "fresh_membership_row_count": len(checked),
        "duplicate_membership_rows_removed": before - len(checked),
    }


def _feature_matrix(
    features: pd.DataFrame,
    *,
    prefix: str,
    scope: str | None = None,
    core_contract: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    required = {*_KEY, "metric_id", "metric_value", "metric_available_at", "evidence_family_id"}
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"{prefix} features missing: " + ", ".join(sorted(missing)))
    admitted = features.copy()
    if scope is not None:
        if "model_scope" not in admitted:
            raise ValueError(f"{prefix} model_scope required")
        admitted = admitted.loc[admitted["model_scope"].astype(str).eq(scope)]
    if core_contract:
        admitted = admitted.loc[
            ~admitted["metric_id"].astype(str).eq("management_delivery_ratio")
            & ~admitted["evidence_family_id"].astype(str).eq("people:management_delivery")
            & ~admitted["evidence_family_id"].astype(str).str.startswith(("technical:", "chip:"))
        ]
    admitted = admitted.loc[
        admitted["metric_value"].notna() & admitted["metric_available_at"].notna()
    ].copy()
    admitted["decision_date"] = admitted["decision_date"].astype(str)
    available = admitted["metric_available_at"].map(_instant)
    decision_end = admitted["decision_date"].map(
        lambda value: datetime.fromisoformat(value).replace(
            hour=23, minute=59, second=59, tzinfo=_TAIPEI
        )
    )
    admitted = admitted.loc[available <= decision_end]
    conflicts = admitted.groupby([*_KEY, "metric_id"])["metric_value"].nunique(dropna=True)
    if (conflicts > 1).any():
        raise ValueError(f"conflicting PIT {prefix} feature values")
    admitted["feature_id"] = prefix + "__" + admitted["metric_id"].astype(str)
    matrix = admitted.pivot_table(
        index=_KEY,
        columns="feature_id",
        values="metric_value",
        aggfunc="first",
    ).reset_index()
    matrix.columns.name = None
    ids = sorted(column for column in matrix if column not in _KEY)
    if not ids:
        raise ValueError(f"no admitted {prefix} features")
    return matrix, ids


def _ridge_predict(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    fields: list[str],
    target: str,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    active = [field for field in fields if train[field].notna().sum() >= 2]
    if not active:
        raise ValueError("no train-observed model features")
    x_train = train[active].astype(float)
    medians = x_train.median(axis=0)
    x_train = x_train.fillna(medians)
    x_holdout = holdout[active].astype(float).fillna(medians)
    means = x_train.mean(axis=0).to_numpy(float)
    scales = np.asarray(x_train.std(axis=0, ddof=0), dtype=float).copy()
    scales[(scales == 0) | ~np.isfinite(scales)] = 1.0
    train_design = np.column_stack([
        np.ones(len(train)), (x_train.to_numpy(float) - means) / scales
    ])
    holdout_design = np.column_stack([
        np.ones(len(holdout)), (x_holdout.to_numpy(float) - means) / scales
    ])
    raw_y = train[target].to_numpy(float)
    lower, upper = np.quantile(raw_y, [0.025, 0.975])
    y = np.clip(raw_y, lower, upper)
    penalty = np.eye(train_design.shape[1]) * _RIDGE_PENALTY
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        train_design.T @ train_design + penalty,
        train_design.T @ y,
    )
    train_prediction = train_design @ coefficients
    return holdout_design @ coefficients, raw_y - train_prediction, active


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
    return float(wins / (len(positives) * len(negatives)))


def _probabilities(prediction: np.ndarray, residuals: np.ndarray) -> np.ndarray:
    return np.asarray([np.mean(value + residuals > 0) for value in prediction], dtype=float)


def _metric_block(frame: pd.DataFrame, *, linear_mae: float) -> dict[str, object]:
    actual = frame["actual_total_return"].to_numpy(float)
    p50 = frame["predicted_p50_return"].to_numpy(float)
    naive = frame["naive_p50_return"].to_numpy(float)
    direction = float(np.mean(
        (frame["positive_return_probability"].to_numpy(float) >= 0.5) == (actual > 0)
    ))
    naive_direction = float(np.mean((naive > 0) == (actual > 0)))
    mae = float(np.mean(np.abs(actual - p50)))
    naive_mae = float(np.mean(np.abs(actual - naive)))
    spearman = float(pd.Series(actual).rank().corr(pd.Series(p50).rank()))
    auc = _auc(
        (frame["official_excess_return"].to_numpy(float) > 0).astype(int),
        frame["outperform_probability"].to_numpy(float),
    )
    coverage = float(np.mean(
        (actual >= frame["predicted_p10_return"].to_numpy(float))
        & (actual <= frame["predicted_p90_return"].to_numpy(float))
    ))
    direction_pp = 100.0 * (direction - naive_direction)
    metrics: dict[str, object] = {
        "n": len(frame),
        "mae": mae,
        "naive_mae": naive_mae,
        "linear_mae": linear_mae,
        "spearman": spearman if np.isfinite(spearman) else None,
        "direction": direction,
        "naive_direction": naive_direction,
        "direction_pp": direction_pp,
        "auc": auc,
        "coverage": coverage,
    }
    gates = {
        "mae_5pct_better_than_naive_and_linear": (
            mae <= 0.95 * naive_mae and mae <= 0.95 * linear_mae
        ),
        "spearman_at_least_0_10": metrics["spearman"] is not None and spearman >= 0.10,
        "direction_improvement_at_least_5pp": direction_pp >= 5.0,
        "auc_at_least_0_62": auc is not None and auc >= 0.62,
        "interval_coverage_0_75_to_0_85": 0.75 <= coverage <= 0.85,
    }
    return {"metrics": metrics, "gates": gates, "all_gates_pass": all(gates.values())}


def build_f000_multilabel_comparison(
    labels: pd.DataFrame,
    features: pd.DataFrame,
    trends: pd.DataFrame,
    valuation: pd.DataFrame,
    market_features: pd.DataFrame,
    memberships: pd.DataFrame,
    snapshot_mapping: pd.DataFrame,
    *,
    producer_candidate_sha: str,
    input_artifact_shas: dict[str, str],
    minimum_train_observations: int = 250,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build the fixed pre-OOS baseline/challenger comparison on common F000 rows."""
    expected_shas = {
        "labels", "features", "trends", "valuation", "market_features",
        "memberships", "snapshot_mapping",
    }
    if not _SHA.fullmatch(producer_candidate_sha):
        raise ValueError("producer candidate SHA required")
    if set(input_artifact_shas) != expected_shas or any(
        not _SHA.fullmatch(value) for value in input_artifact_shas.values()
    ):
        raise ValueError("exact input artifact SHAs required")
    if minimum_train_observations < 4:
        raise ValueError("minimum_train_observations must be at least four")

    outcomes = _validate_labels(labels)
    mapping = _mapping_contract(snapshot_mapping)
    member_rows, membership_audit = _memberships(memberships, mapping)
    unique_memberships = member_rows.loc[:, ["decision_date", "security_code", "node_code"]]
    observation_nodes = unique_memberships.groupby(
        ["decision_date", "security_code"], sort=True
    )["node_code"].agg(lambda values: tuple(sorted(set(values)))).reset_index(name="node_codes")

    covered = outcomes.loc[outcomes["decision_date"].isin(_ELIGIBLE_DATES)].merge(
        observation_nodes,
        on=["decision_date", "security_code"],
        how="inner",
        validate="one_to_one",
    )
    if covered.empty or covered.duplicated(_OBSERVATION_KEY).any():
        raise ValueError("unique issuer/security/decision F000 observations required")

    matrices: list[pd.DataFrame] = []
    feature_ids: list[str] = []
    for source, prefix, scope, core_contract in (
        (features, "core", None, True),
        (trends, "trend", "upside_only", False),
        (valuation, "valuation", "upside_only", False),
        (market_features, "context", "upside_only", False),
    ):
        matrix, ids = _feature_matrix(
            source, prefix=prefix, scope=scope, core_contract=core_contract
        )
        matrices.append(matrix)
        feature_ids.extend(ids)
    data = covered
    for matrix in matrices:
        data = data.merge(matrix, on=_KEY, how="left", validate="one_to_one")
    data["decision"] = pd.to_datetime(data["decision_date"])

    missingness = {
        feature: float(data[feature].isna().mean()) for feature in sorted(feature_ids)
    }
    predictions: list[pd.DataFrame] = []
    windows: list[dict[str, object]] = []
    for holdout_value in sorted(data["decision"].unique()):
        holdout_date = cast(pd.Timestamp, pd.Timestamp(holdout_value))
        train_cutoff = holdout_date - pd.DateOffset(months=12)
        train = data.loc[data["decision"] < train_cutoff].copy()
        holdout = data.loc[data["decision"] == holdout_date].copy()
        if len(train) < minimum_train_observations or holdout.empty:
            continue
        train_nodes = sorted({node for nodes in train["node_codes"] for node in nodes})
        node_fields = [f"node__{node}" for node in train_nodes]
        for frame in (train, holdout):
            node_sets = frame["node_codes"]
            counts = node_sets.map(len).astype(float)
            for node, field in zip(train_nodes, node_fields, strict=True):
                frame[field] = [
                    (1.0 / count if node in nodes else 0.0)
                    for nodes, count in zip(node_sets, counts, strict=True)
                ]

        candidate_fields = {
            _BASELINE_ID: feature_ids,
            _CHALLENGER_ID: [*feature_ids, *node_fields],
        }
        active_by_candidate: dict[str, list[str]] = {}
        for candidate_id, fields in candidate_fields.items():
            return_prediction, return_residuals, active = _ridge_predict(
                train, holdout, fields, "actual_total_return"
            )
            excess_prediction, excess_residuals, _ = _ridge_predict(
                train, holdout, fields, "official_excess_return"
            )
            quantiles = np.quantile(return_residuals, [0.1, 0.5, 0.9])
            result = holdout.loc[:, [
                *_KEY,
                "result_end_date",
                "actual_total_return",
                "official_benchmark_return",
                "official_excess_return",
                "official_benchmark_source_ref",
                "same_market_median_return",
                "generation_id",
            ]].copy()
            result["candidate_id"] = candidate_id
            result["predicted_p10_return"] = return_prediction + quantiles[0]
            result["predicted_p50_return"] = return_prediction + quantiles[1]
            result["predicted_p90_return"] = return_prediction + quantiles[2]
            result["positive_return_probability"] = _probabilities(
                return_prediction, return_residuals
            )
            result["outperform_probability"] = _probabilities(
                excess_prediction, excess_residuals
            )
            result["naive_p50_return"] = float(train["actual_total_return"].median())
            result["trained_through"] = str(train["decision_date"].max())
            result["star"] = np.nan
            predictions.append(result)
            active_by_candidate[candidate_id] = active
        windows.append({
            "holdout_date": holdout_date.date().isoformat(),
            "train_start": str(train["decision_date"].min()),
            "train_end": str(train["decision_date"].max()),
            "train_observation_count": len(train),
            "holdout_observation_count": len(holdout),
            "train_market_count": int(train["market"].nunique()),
            "train_node_count": len(train_nodes),
            "baseline_active_feature_count": len(active_by_candidate[_BASELINE_ID]),
            "challenger_active_feature_count": len(active_by_candidate[_CHALLENGER_ID]),
        })
    if not predictions:
        raise ValueError("insufficient fresh temporal history for fixed F000 holdouts")
    rows = pd.concat(predictions, ignore_index=True)
    if rows.duplicated(["candidate_id", *_OBSERVATION_KEY]).any():
        raise ValueError("model candidates duplicated an issuer/security/decision observation")
    counts = rows.groupby("candidate_id").size()
    if counts.nunique() != 1:
        raise ValueError("baseline and challenger must use identical observations")

    baseline_rows = rows.loc[rows["candidate_id"].eq(_BASELINE_ID)]
    baseline_mae = float(np.mean(np.abs(
        baseline_rows["actual_total_return"].to_numpy(float)
        - baseline_rows["predicted_p50_return"].to_numpy(float)
    )))
    comparisons = {
        candidate_id: _metric_block(candidate, linear_mae=baseline_mae)
        for candidate_id, candidate in rows.groupby("candidate_id", sort=True)
    }
    baseline_metrics = cast(dict[str, object], comparisons[_BASELINE_ID]["metrics"])
    challenger_metrics = cast(dict[str, object], comparisons[_CHALLENGER_ID]["metrics"])
    deltas = {
        metric: float(cast(float, challenger_metrics[metric]) - cast(float, baseline_metrics[metric]))
        for metric in ("mae", "spearman", "direction", "direction_pp", "auc", "coverage")
        if challenger_metrics[metric] is not None and baseline_metrics[metric] is not None
    }

    label_counts = outcomes.groupby("decision_date").size().to_dict()
    covered_counts = covered.groupby("decision_date").size().to_dict()
    per_date = [
        {
            "decision_date": day,
            "label_observation_count": int(label_counts.get(day, 0)),
            "covered_observation_count": int(covered_counts.get(day, 0)),
            "coverage": (
                float(covered_counts.get(day, 0) / label_counts[day])
                if label_counts.get(day, 0) else 0.0
            ),
            "node_count": int(unique_memberships.loc[
                unique_memberships["decision_date"].eq(day), "node_code"
            ].nunique()),
        }
        for day in _FIXED_DATES
    ]
    node_sizes = unique_memberships.groupby("node_code")["security_code"].nunique()
    report: dict[str, object] = {
        "schema_version": "F000PITMultiLabelUpsideComparison.v1",
        "status": "research_only",
        "publishable": False,
        "formal_stars_enabled": False,
        "final_oos_read": False,
        "route_key": "official_industry_code=25",
        "market_used_as_route_key": False,
        "market_used_as_model_feature": False,
        "official_market_benchmark_labels_retained": True,
        "observation_key": list(_OBSERVATION_KEY),
        "duplicate_candidate_observation_count": 0,
        "eligible_decision_dates": list(_ELIGIBLE_DATES),
        "excluded_decision_dates": dict(_EXCLUDED_DATES),
        "fixed_model_contract": {
            "baseline_candidate_id": _BASELINE_ID,
            "challenger_candidate_id": _CHALLENGER_ID,
            "ridge_penalty": _RIDGE_PENALTY,
            "membership_encoding": "equal_weight_multi_hot_per_observation",
            "partial_pooling": "ridge_shrunk_node_effects_around_pooled_industry_model",
            "minimum_train_observations": minimum_train_observations,
            "gate_tuning_performed": False,
        },
        "baseline_feature_ids": sorted(feature_ids),
        "node_coverage": {
            **membership_audit,
            "covered_observation_count": len(covered),
            "unique_security_count": int(covered["security_code"].nunique()),
            "multi_label_observation_count": int(covered["node_codes"].map(len).gt(1).sum()),
            "node_count": int(unique_memberships["node_code"].nunique()),
            "node_sample_count_min": int(node_sizes.min()),
            "node_sample_count_median": float(node_sizes.median()),
            "node_sample_count_max": int(node_sizes.max()),
            "coverage_by_decision": per_date,
        },
        "missingness_by_feature": missingness,
        "temporal_windows": windows,
        "comparisons": comparisons,
        "ablation": {
            "definition": "challenger minus frozen pooled-industry baseline on identical rows",
            "challenger_minus_baseline": deltas,
        },
        "holdout_observation_count_per_candidate": int(counts.iloc[0]),
        "input_artifact_shas": dict(sorted(input_artifact_shas.items())),
        "generation_id": str(outcomes["generation_id"].iloc[0]),
        "producer_candidate_sha": producer_candidate_sha,
    }
    return rows, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--trends", required=True, type=Path)
    parser.add_argument("--valuation", required=True, type=Path)
    parser.add_argument("--market-features", required=True, type=Path)
    parser.add_argument("--memberships", required=True, type=Path)
    parser.add_argument("--snapshot-mapping", required=True, type=Path)
    parser.add_argument("--predictions-output", required=True, type=Path)
    parser.add_argument("--report-output", required=True, type=Path)
    args = parser.parse_args()
    paths = {
        "labels": args.labels,
        "features": args.features,
        "trends": args.trends,
        "valuation": args.valuation,
        "market_features": args.market_features,
        "memberships": args.memberships,
        "snapshot_mapping": args.snapshot_mapping,
    }
    rows, report = build_f000_multilabel_comparison(
        pd.read_parquet(args.labels),
        pd.read_parquet(args.features),
        pd.read_parquet(args.trends),
        pd.read_parquet(args.valuation),
        pd.read_parquet(args.market_features),
        pd.read_parquet(args.memberships),
        pd.read_csv(args.snapshot_mapping),
        producer_candidate_sha=_file_sha(Path(__file__)),
        input_artifact_shas={name: _file_sha(path) for name, path in paths.items()},
    )
    args.predictions_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(args.predictions_output, index=False)
    args.report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
