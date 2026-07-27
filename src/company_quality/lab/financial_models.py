"""Financial-institution-only PIT features and independent candidate validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Literal

import numpy as np
import pandas as pd


FinancialSubtype = Literal["bank", "life_insurer", "securities"]
_SCOPES = ("quality_only", "upside_only", "downside_only")
_ALLOWED: dict[str, tuple[str, ...]] = {
    "bank": (
        "capital_adequacy_ratio",
        "tier1_capital_ratio",
        "common_equity_ratio",
        "nonperforming_loan_ratio",
        "loan_loss_coverage_ratio",
        "return_on_assets",
        "return_on_equity",
        "liquidity_coverage_ratio",
        "net_stable_funding_ratio",
    ),
    "life_insurer": (
        "risk_based_capital_ratio",
        "equity_to_investment_assets",
        "return_on_assets",
        "return_on_equity",
    ),
    "securities": (
        "capital_adequacy_ratio",
        "liquid_capital_ratio",
        "return_on_assets",
        "return_on_equity",
    ),
}
_FORBIDDEN_GENERIC = {
    "free_cash_flow",
    "free_cash_flow_trend",
    "debt_ratio",
    "debt_ratio_improvement",
    "current_ratio",
    "liquidity_improvement",
}
_CBC_BANK_SOURCE = (
    "https://www.cbc.gov.tw/public/data/OpenData/金檢處/主要財務及營運比率.csv"
)


@dataclass(frozen=True, slots=True)
class FinancialCandidateResult:
    financial_subtype: str
    model_scope: str
    model_id: str
    status: str
    train_observations: int
    validation_observations: int
    final_oos_observations: int
    baseline_validation_mae: float | None
    candidate_validation_mae: float | None
    final_oos_mae: float | None
    admitted_metric_ids: list[str]
    all_company_fallback_model_id: None = None


def inspect_current_cbc_bank_csv(
    payload: bytes,
    *,
    retrieved_at: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Parse current official bank ratios as display evidence, never historic PIT training."""
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = payload.decode("cp950")
    frame = pd.read_csv(BytesIO(decoded.encode("utf-8")), encoding="utf-8", dtype=str)
    required = {"日期", "銀行名稱/項目(單位：％，倍)"}
    if not required.issubset(frame.columns):
        raise ValueError("unexpected CBC bank-ratio columns")
    metric_tokens = {
        "自有資本比率": "capital_adequacy_ratio",
        "第一類資本比率": "tier1_capital_ratio",
        "普通股權益比率": "common_equity_ratio",
        "逾放比率": "nonperforming_loan_ratio",
        "備抵呆帳占逾期放款": "loan_loss_coverage_ratio",
        "稅前淨利占平均資產": "return_on_assets",
        "稅前淨利占平均權益": "return_on_equity",
        "流動性覆蓋比率": "liquidity_coverage_ratio",
        "淨穩定資金比率": "net_stable_funding_ratio",
    }
    columns: dict[str, str] = {}
    for token, metric_id in metric_tokens.items():
        matches = [column for column in frame.columns if token in str(column)]
        if matches:
            columns[matches[0]] = metric_id
    rows: list[dict[str, object]] = []
    for item in frame.to_dict(orient="records"):
        for column, metric_id in columns.items():
            raw_value = item.get(column)
            try:
                numeric_value = float(str(raw_value))
            except (TypeError, ValueError):
                numeric_value = None
            rows.append({
                "period": str(item["日期"]),
                "institution_name": str(item["銀行名稱/項目(單位：％，倍)"]),
                "financial_subtype": "bank",
                "metric_id": metric_id,
                "metric_value": numeric_value,
                "available_at": retrieved_at,
                "historical_pit_eligible": False,
                "source_authority": "Central Bank of the Republic of China (Taiwan)",
                "source_ref": _CBC_BANK_SOURCE,
            })
    output = pd.DataFrame(rows)
    report = {
        "schema_version": "CurrentOfficialFinancialDisplayEvidence.v1",
        "status": "current_display_only",
        "historical_pit_eligible": False,
        "reason": "official_dataset_has_no_per-period_publication_lineage",
        "source_ref": _CBC_BANK_SOURCE,
        "source_row_count": int(len(frame)),
        "institution_count": len(
            frame["銀行名稱/項目(單位：％，倍)"].astype(str).unique()
        ),
        "metric_ids": sorted(set(columns.values())),
    }
    return output, report


def _fit_predict(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    features: list[str],
    target: str,
) -> np.ndarray:
    x_train = pd.DataFrame(train.loc[:, features]).astype(float)
    medians = pd.Series(x_train.median(axis=0), index=features)
    usable = [item for item in features if bool(pd.notna(medians.loc[item]))]
    if not usable:
        return np.repeat(float(pd.Series(train[target]).mean()), len(holdout))
    train_x = pd.DataFrame(x_train.loc[:, usable])
    holdout_x = pd.DataFrame(holdout.loc[:, usable]).astype(float)
    train_missing = train_x.isna().astype(float).to_numpy()
    holdout_missing = holdout_x.isna().astype(float).to_numpy()
    fill_values = {item: float(medians.loc[item]) for item in usable}
    train_array = np.column_stack([
        train_x.fillna(fill_values).to_numpy(float), train_missing
    ])
    holdout_array = np.column_stack([
        holdout_x.fillna(fill_values).to_numpy(float), holdout_missing
    ])
    means = train_array.mean(axis=0)
    scales = train_array.std(axis=0)
    scales[(scales == 0) | ~np.isfinite(scales)] = 1.0
    x = np.column_stack([np.ones(len(train)), (train_array - means) / scales])
    h = np.column_stack([np.ones(len(holdout)), (holdout_array - means) / scales])
    penalty = np.eye(x.shape[1])
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(x.T @ x + penalty, x.T @ train[target].to_numpy(float))
    return h @ coefficients


def validate_financial_candidates(
    labels: pd.DataFrame,
    features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Train bank/insurer/securities and all three scopes independently; never publish."""
    label_required = {
        "issuer_id", "security_code", "market", "decision_date", "generation_id",
        "financial_subtype", "split", "actual_total_return", "adverse_outcome",
    }
    feature_required = {
        "issuer_id", "decision_date", "generation_id", "financial_subtype", "metric_id",
        "metric_value", "available_at", "historical_pit_eligible", "source_ref",
    }
    if label_required - set(labels.columns):
        raise ValueError("financial labels missing required fields")
    if feature_required - set(features.columns):
        raise ValueError("financial features missing required fields")
    generations = set(labels["generation_id"].astype(str)) | set(
        features["generation_id"].astype(str)
    )
    if len(generations) != 1:
        raise ValueError("financial validation requires one generation")
    metric_ids = set(features["metric_id"].astype(str))
    if metric_ids & _FORBIDDEN_GENERIC:
        raise ValueError("generic-company metric forbidden for financial candidates")
    unknown = []
    for _, row in features[["financial_subtype", "metric_id"]].drop_duplicates().iterrows():
        subtype = str(row["financial_subtype"])
        metric_id = str(row["metric_id"])
        if metric_id not in _ALLOWED.get(subtype, ()):
            unknown.append((subtype, metric_id))
    if unknown:
        raise ValueError("metric not allowed for financial subtype")

    selected = features.loc[features["historical_pit_eligible"].eq(True)].copy()
    selected["available"] = pd.to_datetime(selected["available_at"], utc=True, errors="coerce")
    decision_end = pd.to_datetime(selected["decision_date"]).dt.tz_localize(
        "Asia/Taipei"
    ).dt.tz_convert("UTC") + pd.Timedelta(hours=23, minutes=59, seconds=59)
    selected.loc[selected["available"].isna() | (selected["available"] > decision_end), "metric_value"] = np.nan

    outputs: list[pd.DataFrame] = []
    reports: list[FinancialCandidateResult] = []
    for subtype in _ALLOWED:
        subtype_labels = labels.loc[labels["financial_subtype"].eq(subtype)].copy()
        subtype_features = selected.loc[selected["financial_subtype"].eq(subtype)]
        feature_ids = sorted(set(subtype_features["metric_id"].astype(str)))
        keys = subtype_labels[["issuer_id", "decision_date"]].drop_duplicates()
        if feature_ids:
            matrix = subtype_features.pivot_table(
                index=["issuer_id", "decision_date"], columns="metric_id",
                values="metric_value", aggfunc="first",
            ).reindex(columns=feature_ids).reset_index()
            bound_features = keys.merge(
                matrix, on=["issuer_id", "decision_date"], how="left"
            )
        else:
            bound_features = keys
        data = subtype_labels.merge(
            bound_features, on=["issuer_id", "decision_date"], how="left"
        )
        for scope in _SCOPES:
            target = {
                "quality_only": "quality_target",
                "upside_only": "actual_total_return",
                "downside_only": "adverse_target",
            }[scope]
            scoped = data.copy()
            scoped["quality_target"] = 1.0 - scoped["adverse_outcome"].astype(float)
            scoped["adverse_target"] = scoped["adverse_outcome"].astype(float)
            train = scoped.loc[scoped["split"].eq("train")]
            validation = scoped.loc[scoped["split"].eq("validation")]
            final_oos = scoped.loc[scoped["split"].eq("final_oos")]
            status = "research_only"
            baseline_mae = candidate_mae = oos_mae = None
            admitted: list[str] = []
            if len(train) < 500 or len(final_oos) < 100:
                status = "industry_sample_insufficient"
            elif validation.empty or not feature_ids:
                status = "model_not_passed"
            else:
                baseline_prediction = np.repeat(float(train[target].mean()), len(validation))
                candidate_prediction = _fit_predict(train, validation, feature_ids, target)
                baseline_mae = float(np.mean(np.abs(validation[target] - baseline_prediction)))
                candidate_mae = float(np.mean(np.abs(validation[target] - candidate_prediction)))
                if candidate_mae >= baseline_mae:
                    status = "model_not_passed"
                else:
                    admitted = feature_ids
                    oos_prediction = _fit_predict(train, final_oos, feature_ids, target)
                    oos_mae = float(np.mean(np.abs(final_oos[target] - oos_prediction)))
                    completeness = final_oos[feature_ids].notna().mean(axis=1)
                    result = final_oos[[
                        "issuer_id", "security_code", "market", "decision_date", "generation_id"
                    ]].copy()
                    result["financial_subtype"] = subtype
                    result["model_scope"] = scope
                    result["model_id"] = f"financial:{subtype}:{scope}:v1"
                    result["predicted_target"] = oos_prediction
                    result["result_status"] = "research_only"
                    result.loc[completeness < 0.5, "predicted_target"] = np.nan
                    result.loc[completeness < 0.5, "result_status"] = "data_insufficient"
                    outputs.append(result)
            reports.append(FinancialCandidateResult(
                financial_subtype=subtype,
                model_scope=scope,
                model_id=f"financial:{subtype}:{scope}:v1",
                status=status,
                train_observations=len(train),
                validation_observations=len(validation),
                final_oos_observations=len(final_oos),
                baseline_validation_mae=baseline_mae,
                candidate_validation_mae=candidate_mae,
                final_oos_mae=oos_mae,
                admitted_metric_ids=admitted,
            ))
    predictions = pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()
    report = {
        "schema_version": "FinancialCandidateValidation.v1",
        "status": "research_only",
        "publishable": False,
        "minimum_train_observations": 500,
        "minimum_final_oos_observations": 100,
        "training_imputation": "per_training_window_median_with_missing_indicator",
        "generic_company_fallback": None,
        "forbidden_generic_metric_ids": sorted(_FORBIDDEN_GENERIC),
        "models": [asdict(item) for item in reports],
    }
    return predictions, report


__all__ = [
    "FinancialCandidateResult",
    "inspect_current_cbc_bank_csv",
    "validate_financial_candidates",
]
