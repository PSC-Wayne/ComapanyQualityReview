"""PIT growth/deterioration trends and independent three-model ablations."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd


_MODEL_SCOPES = ("quality_only", "upside_only", "downside_only")
_FINANCIAL_TOKENS = ("金融", "銀行", "保險", "證券")
_RAW_METRICS = (
    "revenue_acceleration",
    "gross_margin_trend",
    "operating_margin_trend",
    "roe_trend",
    "cash_flow_conversion_trend",
    "free_cash_flow_trend",
    "debt_ratio_improvement",
    "liquidity_improvement",
)
_MISSING_SUPPRESSION_THRESHOLD = 0.5
_OBSERVATION_KEY = ["issuer_id", "security_code", "market", "decision_date"]


@dataclass(frozen=True, slots=True)
class ModelAblation:
    model_scope: str
    target: str
    holdout_dates: list[str]
    baseline_mean_absolute_error: float
    admitted_metric_ids: list[str]
    rejected_metric_ids: list[str]
    metric_comparisons: list[dict[str, object]]
    mean_confidence: float
    suppressed_observation_count: int


def _load_wide(path: Path) -> pd.DataFrame:
    frame = pd.read_feather(path) if path.suffix == ".feather" else pd.read_pickle(path)
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def _series(
    frame: pd.DataFrame,
    code: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.Series, str | None]:
    exact = [column for column in frame.columns if str(column) == code]
    aliases = exact or [column for column in frame.columns if str(column).split()[0] == code]
    if not aliases:
        return pd.Series(dtype=float), "missing_source_series"
    values = frame.loc[(frame.index > start) & (frame.index <= end), aliases].apply(
        pd.to_numeric, errors="coerce"
    )
    if (values.nunique(axis=1, dropna=True) > 1).any():
        return pd.Series(dtype=float), "conflicting_alias_values"
    return values.bfill(axis=1).iloc[:, 0].dropna().sort_index(), None


def _eight_period_change(
    series: pd.Series,
    *,
    normalize: bool = False,
) -> tuple[float | None, pd.Timestamp | None, str | None]:
    window = series.tail(8)
    if len(window) < 8:
        return None, None, "insufficient_8_period_history"
    prior = float(window.iloc[:4].mean())
    recent = float(window.iloc[4:].mean())
    value = recent - prior
    if normalize:
        denominator = abs(prior)
        if denominator <= 1e-12:
            return None, None, "zero_prior_period_denominator"
        value /= denominator
    if not np.isfinite(value):
        return None, None, "non_finite_trend"
    return value, cast(pd.Timestamp, pd.Timestamp(window.index[-1])), None


def _raw_row(
    base: dict[str, object],
    metric_id: str,
    value: float | None,
    available_at: pd.Timestamp | None,
    reason: str | None,
) -> dict[str, object]:
    return {
        **base,
        "model_scope": "shared_raw",
        "metric_id": metric_id,
        "metric_value": value,
        "metric_available_at": available_at.isoformat() if available_at is not None else None,
        "evidence_family_id": f"financial_trend:{metric_id}",
        "evidence_id": (
            f"finlab:pit_financial_trend:{base['security_code']}:{metric_id}"
            if value is not None
            else None
        ),
        "unavailable_reason": reason,
    }


def _model_rows(raw: dict[str, object]) -> list[dict[str, object]]:
    raw_value = raw["metric_value"]
    rows: list[dict[str, object]] = []
    for scope in _MODEL_SCOPES:
        value = None
        if raw_value is not None:
            numeric = float(raw_value)
            if scope == "quality_only":
                value = numeric
            elif scope == "upside_only":
                value = max(numeric, 0.0)
            else:
                value = max(-numeric, 0.0)
        prefix = scope.removesuffix("_only")
        suffix = "deterioration" if scope == "downside_only" else "trend"
        rows.append({
            **raw,
            "model_scope": scope,
            "metric_id": f"{prefix}__{raw['metric_id']}__{suffix}",
            "metric_value": value,
            "evidence_family_id": f"financial_trend:{prefix}:{raw['metric_id']}",
        })
    return rows


def build_pit_trend_features(
    finlab_db: Path,
    labels: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build shared raw trends plus independent quality/upside/downside transforms."""
    sources = {
        "gross_margin_trend": _load_wide(finlab_db / "fundamental_features#營業毛利率.feather"),
        "operating_margin_trend": _load_wide(finlab_db / "fundamental_features#營業利益率.feather"),
        "roe_trend": _load_wide(finlab_db / "fundamental_features#ROE稅後.feather"),
        "free_cash_flow_trend": _load_wide(finlab_db / "fundamental_features#自由現金流量.feather"),
        "debt_ratio_improvement": _load_wide(finlab_db / "fundamental_features#負債比率.feather"),
        "liquidity_improvement": _load_wide(finlab_db / "fundamental_features#流動比率.feather"),
    }
    revenue = _load_wide(finlab_db / "monthly_revenue#當月營收.pickle")
    output: list[dict[str, object]] = []
    for label in labels.itertuples(index=False):
        code = str(label.security_code)
        decision = cast(pd.Timestamp, pd.Timestamp(str(label.decision_date))) + pd.Timedelta(
            hours=23, minutes=59, seconds=59
        )
        industry = None
        industry_value = getattr(label, "official_industry", None)
        industry_available = getattr(label, "industry_available_at", None)
        if cast(bool, pd.notna(industry_value)) and cast(bool, pd.notna(industry_available)):
            available = cast(pd.Timestamp, pd.Timestamp(str(industry_available)))
            if available <= decision:
                industry = str(industry_value)
        financial = bool(
            industry and any(token in industry for token in _FINANCIAL_TOKENS)
        )
        base = {
            "issuer_id": str(label.issuer_id),
            "security_code": code,
            "market": str(label.market),
            "decision_date": str(label.decision_date),
            "generation_id": str(label.generation_id),
        }
        raw_rows: list[dict[str, object]] = []

        revenue_series, revenue_reason = _series(
            revenue, code, decision - pd.DateOffset(months=19), decision
        )
        yoy = revenue_series.pct_change(12, fill_method=None).replace(
            [np.inf, -np.inf], np.nan
        ).dropna().tail(6)
        revenue_value = None
        revenue_available = None
        if len(yoy) == 6:
            revenue_value = float(yoy.iloc[3:].mean() - yoy.iloc[:3].mean())
            revenue_available = cast(pd.Timestamp, pd.Timestamp(yoy.index[-1]))
        raw_rows.append(_raw_row(
            base,
            "revenue_acceleration",
            revenue_value,
            revenue_available,
            None if revenue_value is not None else revenue_reason or "insufficient_18_month_revenue_history",
        ))

        for metric_id, frame in sources.items():
            series, source_reason = _series(
                frame, code, decision - pd.DateOffset(years=3), decision
            )
            normalize = metric_id == "free_cash_flow_trend"
            value, available_at, trend_reason = _eight_period_change(
                series, normalize=normalize
            )
            if metric_id == "debt_ratio_improvement" and value is not None:
                value = -value
            if metric_id == "free_cash_flow_trend":
                if industry is None:
                    value, available_at, trend_reason = None, None, "pit_industry_unavailable"
                elif financial:
                    value, available_at, trend_reason = (
                        None,
                        None,
                        "not_applicable_financial_industry",
                    )
            raw_rows.append(_raw_row(
                base,
                metric_id,
                value,
                available_at,
                None if value is not None else source_reason or trend_reason,
            ))

        raw_rows.append(_raw_row(
            base,
            "cash_flow_conversion_trend",
            None,
            None,
            "missing_operating_cash_flow_or_net_income_authority",
        ))
        for raw in raw_rows:
            output.append(raw)
            output.extend(_model_rows(raw))

    frame = pd.DataFrame(output)
    observations = int(labels[["issuer_id", "decision_date"]].drop_duplicates().shape[0])
    report = {
        "schema_version": "PITFinancialTrendFeatures.v1",
        "status": "research_only",
        "publishable": False,
        "observation_count": observations,
        "metric_row_count": int(len(frame)),
        "raw_metric_ids": list(_RAW_METRICS),
        "model_scopes": list(_MODEL_SCOPES),
        "available_raw_metric_count": int(
            frame.loc[frame["model_scope"] == "shared_raw", "metric_value"].notna().sum()
        ),
        "missing_suppression_threshold": _MISSING_SUPPRESSION_THRESHOLD,
        "excluded_feature_families": [
            "management_delivery",
            "management_continuity",
            "succession_planning",
            "technical",
            "chip",
        ],
    }
    return frame, report


def _pit_matrix(
    features: pd.DataFrame,
    *,
    scope: str | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    selected = features.copy()
    if scope is not None:
        selected = selected.loc[selected["model_scope"] == scope]
    selected["decision_date"] = selected["decision_date"].astype(str)
    selected["available"] = pd.to_datetime(
        selected["metric_available_at"], errors="coerce"
    )
    decision_end = pd.to_datetime(selected["decision_date"]) + pd.Timedelta(
        hours=23, minutes=59, seconds=59
    )
    selected.loc[
        selected["available"].isna() | (selected["available"] > decision_end),
        "metric_value",
    ] = np.nan
    conflicts = selected.loc[selected["metric_value"].notna()].groupby(
        [*_OBSERVATION_KEY, "metric_id"]
    )["metric_value"].nunique(dropna=True)
    if (conflicts > 1).any():
        raise ValueError("conflicting PIT trend values")
    metric_ids = sorted(selected["metric_id"].astype(str).unique())
    keys = selected[_OBSERVATION_KEY].drop_duplicates()
    values = selected.pivot_table(
        index=_OBSERVATION_KEY,
        columns="metric_id",
        values="metric_value",
        aggfunc="first",
    ).reindex(columns=metric_ids).reset_index()
    matrix = keys.merge(
        values, on=_OBSERVATION_KEY, how="left", validate="one_to_one"
    )
    matrix.columns.name = None
    return matrix, metric_ids


def _base_matrix(features: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    allowed = features.loc[
        ~features["metric_id"].astype(str).eq("management_delivery_ratio")
        & ~features["evidence_family_id"].astype(str).str.startswith(
            ("people:management", "technical:", "chip:")
        )
    ].copy()
    allowed["model_scope"] = "base"
    return _pit_matrix(allowed, scope="base")


def _fit_predict_with_missing(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    feature_ids: list[str],
    target: str,
) -> np.ndarray:
    x_train = train[feature_ids].astype(float)
    medians = x_train.median(axis=0)
    usable = [item for item in feature_ids if pd.notna(medians[item])]
    if not usable:
        return np.repeat(float(train[target].mean()), len(holdout))
    train_values = x_train[usable]
    holdout_values = holdout[usable].astype(float)
    train_missing = train_values.isna().astype(float).to_numpy()
    holdout_missing = holdout_values.isna().astype(float).to_numpy()
    train_filled = train_values.fillna(medians[usable]).to_numpy(float)
    holdout_filled = holdout_values.fillna(medians[usable]).to_numpy(float)
    train_array = np.column_stack([train_filled, train_missing])
    holdout_array = np.column_stack([holdout_filled, holdout_missing])
    means = train_array.mean(axis=0)
    scales = train_array.std(axis=0)
    scales[(scales == 0) | ~np.isfinite(scales)] = 1.0
    train_design = np.column_stack([np.ones(len(train)), (train_array - means) / scales])
    holdout_design = np.column_stack([np.ones(len(holdout)), (holdout_array - means) / scales])
    penalty = np.eye(train_design.shape[1])
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        train_design.T @ train_design + penalty,
        train_design.T @ train[target].to_numpy(float),
    )
    return holdout_design @ coefficients


def _holdout_mae(
    data: pd.DataFrame,
    feature_ids: list[str],
    target: str,
    dates: list[pd.Timestamp],
) -> tuple[float | None, list[str]]:
    actual: list[float] = []
    predicted: list[float] = []
    used_dates: list[str] = []
    for holdout_date in dates:
        train = data.loc[data["decision"] < holdout_date - pd.DateOffset(months=12)]
        holdout = data.loc[data["decision"] == holdout_date]
        if len(train) < 10 or holdout.empty:
            continue
        prediction = _fit_predict_with_missing(train, holdout, feature_ids, target)
        actual.extend(holdout[target].astype(float))
        predicted.extend(prediction)
        used_dates.append(holdout_date.date().isoformat())
    if not actual:
        return None, used_dates
    return float(np.mean(np.abs(np.asarray(actual) - np.asarray(predicted)))), used_dates


def validate_three_model_trends(
    labels: pd.DataFrame,
    base_features: pd.DataFrame,
    trend_features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Run independent temporal ablations with train-only imputation per model."""
    required = {
        "issuer_id",
        "decision_date",
        "generation_id",
        "adverse_outcome",
        "actual_total_return",
    }
    missing = required - set(labels.columns)
    if missing:
        raise ValueError("trend validation labels missing: " + ", ".join(sorted(missing)))
    if len(set(labels["generation_id"].astype(str))) != 1:
        raise ValueError("trend validation requires one generation")
    base_matrix, base_ids = _base_matrix(base_features)
    targets = {
        "quality_only": "quality_safety_target",
        "upside_only": "actual_total_return",
        "downside_only": "adverse_target",
    }
    label_data = labels.copy()
    label_data["decision_date"] = label_data["decision_date"].astype(str)
    label_data["quality_safety_target"] = 1.0 - label_data["adverse_outcome"].astype(float)
    label_data["adverse_target"] = label_data["adverse_outcome"].astype(float)
    outputs: list[pd.DataFrame] = []
    reports: list[ModelAblation] = []

    for scope in _MODEL_SCOPES:
        trend_matrix, trend_ids = _pit_matrix(trend_features, scope=scope)
        data = label_data.merge(
            base_matrix,
            on=_OBSERVATION_KEY,
            how="inner",
            validate="one_to_one",
        ).merge(
            trend_matrix,
            on=_OBSERVATION_KEY,
            how="left",
            validate="one_to_one",
        )
        data["decision"] = pd.to_datetime(data["decision_date"])
        dates = [
            cast(pd.Timestamp, pd.Timestamp(value))
            for value in sorted(data["decision"].unique())
        ][1:]
        target = targets[scope]
        baseline_mae, used_dates = _holdout_mae(data, base_ids, target, dates)
        if baseline_mae is None:
            raise ValueError(f"insufficient earlier holdouts for {scope}")
        admitted: list[str] = []
        comparisons: list[dict[str, object]] = []
        for metric_id in trend_ids:
            challenger_mae, metric_dates = _holdout_mae(
                data, [*base_ids, metric_id], target, dates
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

        scope_outputs: list[pd.DataFrame] = []
        for date_value in used_dates:
            holdout_date = cast(pd.Timestamp, pd.Timestamp(date_value))
            train = data.loc[data["decision"] < holdout_date - pd.DateOffset(months=12)]
            holdout = data.loc[data["decision"] == holdout_date].copy()
            prediction = _fit_predict_with_missing(
                train, holdout, [*base_ids, *admitted], target
            )
            completeness = holdout[trend_ids].notna().mean(axis=1)
            holdout["model_scope"] = scope
            holdout["confidence"] = completeness.astype(float)
            holdout["result_status"] = np.where(
                1.0 - completeness > _MISSING_SUPPRESSION_THRESHOLD,
                "data_insufficient",
                "research_only",
            )
            holdout["predicted_target"] = prediction
            holdout.loc[
                holdout["result_status"] == "data_insufficient", "predicted_target"
            ] = np.nan
            scope_outputs.append(holdout)
        scope_result = pd.concat(scope_outputs, ignore_index=True)
        outputs.append(scope_result)
        reports.append(ModelAblation(
            model_scope=scope,
            target=target,
            holdout_dates=used_dates,
            baseline_mean_absolute_error=baseline_mae,
            admitted_metric_ids=admitted,
            rejected_metric_ids=[item for item in trend_ids if item not in admitted],
            metric_comparisons=comparisons,
            mean_confidence=float(scope_result["confidence"].mean()),
            suppressed_observation_count=int(
                (scope_result["result_status"] == "data_insufficient").sum()
            ),
        ))

    result = pd.concat(outputs, ignore_index=True)
    columns = [
        "issuer_id",
        "security_code",
        "market",
        "decision_date",
        "model_scope",
        "predicted_target",
        "confidence",
        "result_status",
        "generation_id",
    ]
    report = {
        "schema_version": "ThreeModelTrendAblation.v1",
        "status": "research_only",
        "publishable": False,
        "training_imputation": "per_window_training_median_with_missing_indicator",
        "missing_suppression_threshold": _MISSING_SUPPRESSION_THRESHOLD,
        "models": [asdict(item) for item in reports],
    }
    return result.loc[:, columns].copy(), report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--finlab-db", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--base-features", required=True, type=Path)
    parser.add_argument("--features-output", required=True, type=Path)
    parser.add_argument("--predictions-output", required=True, type=Path)
    parser.add_argument("--report-output", required=True, type=Path)
    args = parser.parse_args()
    labels = pd.read_parquet(args.labels)
    features, producer_report = build_pit_trend_features(args.finlab_db, labels)
    predictions, validation_report = validate_three_model_trends(
        labels, pd.read_parquet(args.base_features), features
    )
    report = {"producer": producer_report, "validation": validation_report}
    for path in (args.features_output, args.predictions_output, args.report_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(args.features_output, index=False)
    predictions.to_parquet(args.predictions_output, index=False)
    args.report_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
