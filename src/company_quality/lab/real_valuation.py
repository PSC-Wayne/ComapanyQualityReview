"""Point-in-time valuation features for the research-only upside challenger."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast
import json

import numpy as np
import pandas as pd


_FINANCIAL_TOKENS = ("金融", "銀行", "保險", "證券")
_RAW_METRICS = (
    "earnings_yield",
    "book_yield",
    "free_cash_flow_yield",
    "revenue_yield_ttm",
)


class ValuationAliasConflict(ValueError):
    pass


def _load_wide(path: Path) -> pd.DataFrame:
    frame = pd.read_feather(path) if path.suffix == ".feather" else pd.read_pickle(path)
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    return frame.loc[:, ~frame.columns.duplicated(keep="last")]


def _column(
    frame: pd.DataFrame,
    code: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.Series:
    exact = [column for column in frame.columns if str(column) == code]
    aliases = exact or [column for column in frame.columns if str(column).split()[0] == code]
    if not aliases:
        return pd.Series(dtype=float)
    values = frame.loc[(frame.index > start) & (frame.index <= end), aliases].apply(
        pd.to_numeric, errors="coerce"
    )
    if (values.nunique(axis=1, dropna=True) > 1).any():
        raise ValuationAliasConflict(
            f"conflicting valuation aliases for security {code}"
        )
    return values.bfill(axis=1).iloc[:, 0].dropna().sort_index()


def _safe_column(
    frame: pd.DataFrame,
    code: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.Series, str | None]:
    try:
        return _column(frame, code, start=start, end=end), None
    except ValuationAliasConflict:
        return pd.Series(dtype=float), "conflicting_alias_values"


def _last(series: pd.Series, decision: pd.Timestamp) -> tuple[float | None, pd.Timestamp | None]:
    if series.empty:
        return None, None
    admitted = series.loc[series.index <= decision]
    if admitted.empty:
        return None, None
    return float(admitted.iloc[-1]), pd.Timestamp(admitted.index[-1])


def _row(
    *,
    base: dict[str, object],
    metric_id: str,
    value: float | None,
    available_at: pd.Timestamp | None,
    evidence_id: str | None,
    unavailable_reason: str | None,
) -> dict[str, object]:
    return {
        **base,
        "pillar": "upside_valuation",
        "metric_id": metric_id,
        "direction": "high_good",
        "metric_value": value,
        "evidence_family_id": f"valuation:{metric_id}",
        "metric_available_at": (
            available_at.isoformat() if available_at is not None else None
        ),
        "evidence_id": evidence_id,
        "unavailable_reason": unavailable_reason,
        "model_scope": "upside_only",
    }


def build_pit_valuation_features(
    finlab_db: Path,
    labels: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build valuation yields without exposing them to quality/downside consumers."""
    pe = _load_wide(finlab_db / "price_earning_ratio#本益比.pickle")
    pb = _load_wide(finlab_db / "price_earning_ratio#股價淨值比.feather")
    fcf = _load_wide(finlab_db / "fundamental_features#自由現金流量.feather")
    revenue = _load_wide(finlab_db / "monthly_revenue#當月營收.pickle")
    market_value = _load_wide(finlab_db / "etl#market_value.feather")

    rows: list[dict[str, object]] = []
    for label in labels.itertuples(index=False):
        code = str(label.security_code)
        decision = cast(
            pd.Timestamp,
            cast(pd.Timestamp, pd.Timestamp(str(label.decision_date)))
            + pd.Timedelta(hours=23, minutes=59, seconds=59),
        )
        industry_value = getattr(label, "official_industry", None)
        industry_available_value = getattr(label, "industry_available_at", None)
        industry = None
        if cast(bool, pd.notna(industry_value)) and cast(
            bool, pd.notna(industry_available_value)
        ):
            industry_available_at = cast(
                pd.Timestamp, pd.Timestamp(str(industry_available_value))
            )
            if industry_available_at <= decision:
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
            "industry": industry,
        }
        daily_start = decision - pd.DateOffset(years=1)
        financial_start = decision - pd.DateOffset(years=2)
        revenue_start = decision - pd.DateOffset(months=13)
        market_series, market_reason = _safe_column(
            market_value, code, start=daily_start, end=decision
        )
        pe_series, pe_reason = _safe_column(
            pe, code, start=daily_start, end=decision
        )
        pb_series, pb_reason = _safe_column(
            pb, code, start=daily_start, end=decision
        )
        fcf_series, fcf_source_reason = _safe_column(
            fcf, code, start=financial_start, end=decision
        )
        revenue_series, revenue_reason = _safe_column(
            revenue, code, start=revenue_start, end=decision
        )
        market_cap, market_at = _last(market_series, decision)
        pe_value, pe_at = _last(pe_series, decision)
        pb_value, pb_at = _last(pb_series, decision)
        fcf_value, fcf_at = _last(fcf_series, decision)
        revenue_series = revenue_series.tail(12)

        earnings = 1.0 / pe_value if pe_value is not None and pe_value > 0 else None
        rows.append(_row(
            base=base,
            metric_id="earnings_yield",
            value=earnings,
            available_at=pe_at if earnings is not None else None,
            evidence_id=(f"finlab:price_earning_ratio:本益比:{code}" if earnings is not None else None),
            unavailable_reason=(
                None if earnings is not None else pe_reason or "missing_or_non_positive_pe"
            ),
        ))
        book = 1.0 / pb_value if pb_value is not None and pb_value > 0 else None
        rows.append(_row(
            base=base,
            metric_id="book_yield",
            value=book,
            available_at=pb_at if book is not None else None,
            evidence_id=(f"finlab:price_earning_ratio:股價淨值比:{code}" if book is not None else None),
            unavailable_reason=(
                None if book is not None else pb_reason or "missing_or_non_positive_pb"
            ),
        ))
        fcf_yield = (
            fcf_value * 1000.0 / market_cap
            if industry is not None
            and not financial
            and fcf_value is not None
            and market_cap is not None
            and market_cap > 0
            else None
        )
        fcf_reason = (
            "pit_industry_unavailable"
            if industry is None
            else "not_applicable_financial_industry"
            if financial
            else None
            if fcf_yield is not None
            else fcf_source_reason or market_reason or "missing_fcf_or_market_value"
        )
        rows.append(_row(
            base=base,
            metric_id="free_cash_flow_yield",
            value=fcf_yield,
            available_at=(
                max(fcf_at, market_at)
                if fcf_yield is not None and fcf_at is not None and market_at is not None
                else None
            ),
            evidence_id=(
                f"finlab:fundamental_features:自由現金流量+etl:market_value:{code}"
                if fcf_yield is not None else None
            ),
            unavailable_reason=fcf_reason,
        ))
        revenue_yield = (
            float(revenue_series.sum()) * 1000.0 / market_cap
            if len(revenue_series) == 12 and market_cap is not None and market_cap > 0
            else None
        )
        rows.append(_row(
            base=base,
            metric_id="revenue_yield_ttm",
            value=revenue_yield,
            available_at=(
                max(pd.Timestamp(revenue_series.index[-1]), market_at)
                if revenue_yield is not None and market_at is not None
                else None
            ),
            evidence_id=(
                f"finlab:monthly_revenue:當月營收_ttm+etl:market_value:{code}"
                if revenue_yield is not None else None
            ),
            unavailable_reason=(
                None
                if revenue_yield is not None
                else revenue_reason
                or market_reason
                or "incomplete_ttm_revenue_or_market_value"
            ),
        ))

    frame = pd.DataFrame(rows)
    relative_rows: list[dict[str, object]] = []
    for (decision_date, industry, metric_id), group in frame.groupby(
        ["decision_date", "industry", "metric_id"], dropna=False, sort=False
    ):
        valid = (
            group.loc[group["metric_value"].notna()]
            if cast(bool, pd.notna(industry))
            else group.iloc[0:0]
        )
        ranks = valid["metric_value"].rank(pct=True, method="average") if len(valid) >= 2 else pd.Series(dtype=float)
        group_available = (
            pd.to_datetime(valid["metric_available_at"]).max()
            if len(valid) >= 2 else None
        )
        for index, source in group.iterrows():
            value = float(ranks.loc[index]) if index in ranks.index else None
            if value is not None:
                reason = None
            elif cast(bool, pd.isna(industry)):
                reason = "pit_industry_unavailable"
            elif cast(bool, pd.notna(source["unavailable_reason"])):
                reason = str(source["unavailable_reason"])
            else:
                reason = "industry_sample_insufficient"
            relative_rows.append(_row(
                base={
                    "issuer_id": source["issuer_id"],
                    "security_code": source["security_code"],
                    "market": source["market"],
                    "decision_date": decision_date,
                    "generation_id": source["generation_id"],
                    "industry": industry if pd.notna(industry) else None,
                },
                metric_id=f"industry_relative_{metric_id}",
                value=value,
                available_at=(pd.Timestamp(group_available) if value is not None else None),
                evidence_id=(
                    f"label:pit_official_industry:{industry}:{metric_id}:{decision_date}"
                    if value is not None else None
                ),
                unavailable_reason=reason,
            ))
    result = pd.concat([frame, pd.DataFrame(relative_rows)], ignore_index=True)
    result["metric_value"] = pd.to_numeric(result["metric_value"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    report = {
        "schema_version": "PITValuationFeatures.v1",
        "status": "research_only",
        "publishable": False,
        "rating_disposition": "NO_RATING_NOT_APPLICABLE",
        "model_scope": "upside_only",
        "observation_count": int(
            labels[["issuer_id", "decision_date"]].drop_duplicates().shape[0]
        ),
        "metric_row_count": int(len(result)),
        "available_metric_count": int(result["metric_value"].notna().sum()),
        "pit_industry_missing_observation_count": int(
            frame.loc[frame["industry"].isna(), ["issuer_id", "decision_date"]]
            .drop_duplicates()
            .shape[0]
        ),
        "financial_fcf_exclusion_count": int(
            (
                (result["metric_id"] == "free_cash_flow_yield")
                & (result["unavailable_reason"] == "not_applicable_financial_industry")
            ).sum()
        ),
        "metric_ids": [
            *_RAW_METRICS,
            *(f"industry_relative_{item}" for item in _RAW_METRICS),
        ],
    }
    return result, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--finlab-db", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    frame, report = build_pit_valuation_features(
        args.finlab_db, pd.read_parquet(args.labels)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
