"""Build reproducible, research-only pre-OOS upside candidate rows."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import cast

import pandas as pd

from company_quality.lab.real_upside import build_upside_validation


_DEFAULT_PENALTIES = (100.0, 1000.0)


def _file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _adjusted_close(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
        if "date" in frame.columns:
            frame = frame.set_index("date")
    else:
        frame = pd.read_feather(path).set_index("date")
    frame.index = pd.to_datetime(frame.index)
    frame.columns = [str(column).split()[0] for column in frame.columns]
    return frame.loc[:, ~frame.columns.duplicated(keep="last")].sort_index()


def build_pre_oos_candidates(
    labels: pd.DataFrame,
    features: pd.DataFrame,
    adjusted_close: pd.DataFrame,
    valuation_features: pd.DataFrame,
    *,
    producer_candidate_sha: str,
    input_artifact_shas: dict[str, str],
    ridge_penalties: tuple[float, ...] = _DEFAULT_PENALTIES,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build candidates that differ only by a declared ridge penalty."""
    if len(set(ridge_penalties)) < 2:
        raise ValueError("at least two distinct ridge penalties required")
    outputs: list[pd.DataFrame] = []
    reports: list[dict[str, object]] = []
    expected_keys: set[tuple[str, str, str, str]] | None = None
    for penalty in ridge_penalties:
        predictions, report = build_upside_validation(
            labels,
            features,
            adjusted_close,
            valuation_features=valuation_features,
            producer_candidate_sha=producer_candidate_sha,
            input_artifact_shas=input_artifact_shas,
            ridge_penalty=penalty,
        )
        windows = {
            str(item["holdout_start"]): str(item["train_end"])
            for item in cast(list[dict[str, object]], report["temporal_windows"])
        }
        rows = predictions.rename(columns={
            "label_end_date": "result_end_date",
            "market_benchmark_return": "official_benchmark_return",
        }).copy()
        rows["candidate_id"] = f"ridge_penalty_{penalty:g}"
        rows["trained_through"] = rows["decision_date"].astype(str).map(
            lambda value: windows[value]
        )
        linear_fields = [
            column for column in rows if column.startswith("linear_feature_")
        ]
        if not linear_fields:
            raise ValueError("candidate rows require same-data linear features")
        rows["data_completeness"] = rows[linear_fields].notna().mean(axis=1)
        rows["industry_train_observations"] = 0
        keys = set(zip(
            rows["issuer_id"].astype(str),
            rows["security_code"].astype(str),
            rows["market"].astype(str),
            rows["decision_date"].astype(str),
            strict=True,
        ))
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise ValueError("candidate penalties produced different observations")
        outputs.append(rows)
        reports.append({
            "candidate_id": f"ridge_penalty_{penalty:g}",
            "ridge_penalty": penalty,
            "model_version": report["model_version"],
            "feature_ids": report["feature_ids"],
            "holdout_observation_count": report["holdout_observation_count"],
            "metrics": report["metrics"],
        })
    result = pd.concat(outputs, ignore_index=True)
    return result, {
        "schema_version": "RealPreOOSCandidateBuildReport.v1",
        "status": "research_only",
        "publishable": False,
        "candidate_count": len(reports),
        "candidate_row_count": len(result),
        "candidates": reports,
        "input_artifact_shas": dict(sorted(input_artifact_shas.items())),
        "producer_candidate_sha": producer_candidate_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--valuation-features", required=True, type=Path)
    parser.add_argument("--adjusted-close", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    inputs = {
        "T21_labels": _file_sha(args.labels),
        "real_features": _file_sha(args.features),
        "valuation_features": _file_sha(args.valuation_features),
        "adjusted_total_return": _file_sha(args.adjusted_close),
    }
    rows, report = build_pre_oos_candidates(
        pd.read_parquet(args.labels),
        pd.read_parquet(args.features),
        _adjusted_close(args.adjusted_close),
        pd.read_parquet(args.valuation_features),
        producer_candidate_sha=_file_sha(Path(__file__)),
        input_artifact_shas=inputs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(args.output, index=False)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
