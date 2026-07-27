"""Materialize real point-in-time six-pillar feature inputs from FinLab cache."""

from __future__ import annotations

import argparse
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd


PILLARS = (
    "audit_reliability",
    "earnings_capital_efficiency",
    "cash_balance_allocation",
    "business_moat",
    "governance",
    "people_adaptability",
)


def _load_wide(path: Path) -> pd.DataFrame:
    frame = pd.read_feather(path) if path.suffix == ".feather" else pd.read_pickle(path)
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def _column(frame: pd.DataFrame, code: str) -> pd.Series:
    exact = [column for column in frame.columns if str(column) == code]
    candidates = exact or [
        column for column in frame.columns if str(column).split()[0] == code
    ]
    if not candidates:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[candidates[-1]], errors="coerce").dropna()


def _last(series: pd.Series, decision: pd.Timestamp) -> tuple[float | None, pd.Timestamp | None]:
    admitted = series.loc[series.index <= decision]
    if admitted.empty:
        return None, None
    return float(admitted.iloc[-1]), pd.Timestamp(admitted.index[-1])


def _metric(
    base: dict[str, object], pillar: str, metric_id: str, direction: str,
    value: float | None, family: str, available: pd.Timestamp | None,
    evidence: str | None,
) -> dict[str, object]:
    return {
        **base,
        "pillar": pillar,
        "metric_id": metric_id,
        "direction": direction,
        "metric_value": value,
        "evidence_family_id": family,
        "metric_available_at": available.isoformat() if available is not None else None,
        "evidence_id": evidence,
    }


def build_real_features(
    finlab_db: Path,
    labels: pd.DataFrame,
    rd_ratio_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    disclosure_raw = pd.read_feather(
        finlab_db / "etl#financial_statements_disclosure_dates.feather"
    ).set_index("date")
    disclosure_raw = disclosure_raw.loc[
        :, ~disclosure_raw.columns.duplicated(keep="last")
    ]
    deadline_raw = pd.read_feather(
        finlab_db / "etl#financial_statements_deadline.feather"
    ).set_index("date")
    deadline_raw = deadline_raw.loc[:, ~deadline_raw.columns.duplicated(keep="last")]
    feature_names = {
        "roe_after_tax": finlab_db / "fundamental_features#ROE稅後.feather",
        "gross_margin": finlab_db / "fundamental_features#營業毛利率.feather",
        "operating_margin": finlab_db / "fundamental_features#營業利益率.feather",
    }
    features = {}
    for name, path in feature_names.items():
        frame = pd.read_feather(path).set_index("date")
        features[name] = frame.loc[:, ~frame.columns.duplicated(keep="last")]
    rd_ratio = None
    if rd_ratio_path is not None:
        frame = pd.read_feather(rd_ratio_path).set_index("date")
        rd_ratio = frame.loc[:, ~frame.columns.duplicated(keep="last")]
    revenue = _load_wide(finlab_db / "monthly_revenue#當月營收.pickle")
    pledge = _load_wide(
        finlab_db / "internal_equity_pledge#董監設質股數占比.feather"
    )
    dividends = pd.read_feather(finlab_db / "board_dividend_announcement.feather")
    dividends["available_date"] = pd.to_datetime(
        dividends["董事會決議（擬議）股利分派日"]
    ).fillna(pd.to_datetime(dividends["股東會日期"]))
    dividends["cash_dividend"] = (
        pd.to_numeric(dividends["盈餘分配之現金股利(元/股)"], errors="coerce").fillna(0)
        + pd.to_numeric(dividends["法定盈餘公積發放之現金(元/股)"], errors="coerce").fillna(0)
        + pd.to_numeric(dividends["資本公積發放之現金(元/股)"], errors="coerce").fillna(0)
    )

    quarterly_count = min(len(frame) for frame in features.values())
    disclosure_tail = disclosure_raw.tail(quarterly_count)
    deadline_tail = deadline_raw.tail(quarterly_count)
    output: list[dict[str, object]] = []

    for label in labels.itertuples(index=False):
        code = str(label.security_code)
        decision = pd.Timestamp(label.decision_date)
        base = {
            "issuer_id": str(label.issuer_id),
            "security_code": code,
            "market": str(label.market),
            "decision_date": str(label.decision_date),
            "adverse_outcome": bool(label.adverse_outcome),
            "adverse_event_date": label.adverse_event_date,
            "fully_observed": bool(label.fully_observed),
            "label_available_at": str(label.label_available_at),
            "generation_id": str(label.generation_id),
        }

        disclosure = pd.to_datetime(
            disclosure_tail[code], errors="coerce"
        ) if code in disclosure_tail else pd.Series(dtype="datetime64[ns]")
        deadlines = pd.to_datetime(
            deadline_tail[code], errors="coerce"
        ) if code in deadline_tail else pd.Series(dtype="datetime64[ns]")
        admitted = disclosure[(disclosure.notna()) & (disclosure <= decision)]
        recent = admitted.tail(8)
        audit_value = None
        audit_available = None
        if not recent.empty:
            paired_deadlines = deadlines.reindex(recent.index)
            valid = paired_deadlines.notna()
            if valid.any():
                audit_value = float(
                    (recent[valid] <= paired_deadlines[valid]).sum() / valid.sum()
                )
                audit_available = pd.Timestamp(recent.max())
        output.append(_metric(
            base, "audit_reliability", "on_time_filing_ratio_8q", "high_good",
            audit_value, "audit:timeliness", audit_available,
            f"finlab:etl:financial_statements_disclosure_dates:{code}" if audit_value is not None else None,
        ))

        for metric_id, family in (
            ("roe_after_tax", "capital_efficiency"),
            ("gross_margin", "earnings_outcomes"),
            ("operating_margin", "earnings_outcomes"),
        ):
            frame = features[metric_id]
            value = None
            available = None
            if code in frame and not admitted.empty:
                valid_periods = [period for period in admitted.index if period in frame.index]
                for period in reversed(valid_periods):
                    raw = frame.loc[period, code]
                    if isinstance(raw, pd.Series):
                        raw = raw.dropna().iloc[-1] if raw.notna().any() else np.nan
                    if pd.notna(raw):
                        value = float(raw)
                        available = pd.Timestamp(disclosure.at[period])
                        break
            output.append(_metric(
                base, "earnings_capital_efficiency", metric_id, "high_good",
                value, family, available,
                f"finlab:fundamental_features:{metric_id}:{code}" if value is not None else None,
            ))

        rd_value = None
        rd_available = None
        if rd_ratio is not None and code in rd_ratio and not admitted.empty:
            valid_periods = [period for period in admitted.index if period in rd_ratio.index]
            for period in reversed(valid_periods):
                raw = rd_ratio.loc[period, code]
                if isinstance(raw, pd.Series):
                    raw = raw.dropna().iloc[-1] if raw.notna().any() else np.nan
                if pd.notna(raw):
                    rd_value = float(raw)
                    rd_available = pd.Timestamp(disclosure.at[period])
                    break
        output.append(_metric(
            base, "people_adaptability", "research_development_ratio", "high_good",
            rd_value, "adaptability:rd", rd_available,
            f"finlab:fundamental_features:研究發展費用率:{code}" if rd_value is not None else None,
        ))

        company_dividends = dividends.loc[
            (dividends["stock_id"].astype(str) == code)
            & dividends["available_date"].notna()
            & (dividends["available_date"] <= decision)
            & (dividends["available_date"] > decision - pd.DateOffset(years=3))
        ]
        cash_value = None
        cash_available = None
        if not company_dividends.empty:
            annual = company_dividends.groupby(
                company_dividends["available_date"].dt.year
            )["cash_dividend"].sum()
            cash_value = float((annual > 0).sum() / 3)
            cash_available = pd.Timestamp(company_dividends["available_date"].max())
        output.append(_metric(
            base, "cash_balance_allocation", "positive_cash_dividend_year_ratio_3y",
            "high_good", cash_value, "capital_allocation", cash_available,
            f"finlab:board_dividend_announcement:{code}" if cash_value is not None else None,
        ))

        revenue_series = _column(revenue, code)
        admitted_revenue = revenue_series.loc[
            (revenue_series.index <= decision)
            & (revenue_series.index > decision - pd.DateOffset(months=37))
        ]
        yoy = admitted_revenue.pct_change(12, fill_method=None).replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        business_value = float(yoy.std(ddof=0)) if len(yoy) >= 12 else None
        business_available = (
            pd.Timestamp(admitted_revenue.index[-1])
            if business_value is not None else None
        )
        output.append(_metric(
            base, "business_moat", "revenue_yoy_volatility_24m", "low_good",
            business_value, "business:revenue_stability", business_available,
            f"finlab:monthly_revenue:{code}" if business_value is not None else None,
        ))

        pledge_series = _column(pledge, code)
        pledge_series.index = pledge_series.index + pd.Timedelta(days=31)
        governance_value, governance_available = _last(pledge_series, decision)
        output.append(_metric(
            base, "governance", "director_supervisor_pledge_ratio", "low_good",
            governance_value, "governance:pledged_shares", governance_available,
            f"finlab:internal_equity_pledge:{code}" if governance_value is not None else None,
        ))

        output.append(_metric(
            base, "people_adaptability", "management_delivery_ratio", "high_good",
            None, "people:management_delivery", None, None,
        ))

    frame = pd.DataFrame(output)
    available_counts = {
        pillar: int(frame.loc[frame["pillar"] == pillar, "metric_value"].notna().sum())
        for pillar in PILLARS
    }
    observation_count = int(labels[["issuer_id", "decision_date"]].drop_duplicates().shape[0])
    blockers = {
        "people_adaptability_management": "no authoritative PIT management delivery or succession evidence",
        "T16_T19": "formal candidate observations require governed downside constructs",
    }
    report = {
        "schema_version": "RealPITFeatureInputs.v1",
        "status": "EXECUTED_WITH_NULL_AUTHORITY_GAPS",
        "publishable": False,
        "observation_count": observation_count,
        "metric_row_count": len(frame),
        "available_metric_counts": available_counts,
        "blockers": blockers,
        "source_root": str(finlab_db),
        "source_files": [
            "etl#financial_statements_disclosure_dates.feather",
            "etl#financial_statements_deadline.feather",
            *(path.name for path in feature_names.values()),
            "monthly_revenue#當月營收.pickle",
            "board_dividend_announcement.feather",
            "internal_equity_pledge#董監設質股數占比.feather",
            *(str(rd_ratio_path) for _ in range(1) if rd_ratio_path is not None),
        ],
    }
    return frame, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--finlab-db", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--rd-ratio", type=Path)
    args = parser.parse_args()
    frame, report = build_real_features(
        args.finlab_db, pd.read_parquet(args.labels), args.rd_ratio
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
