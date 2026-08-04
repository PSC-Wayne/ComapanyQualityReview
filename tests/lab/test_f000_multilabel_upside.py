from __future__ import annotations

import pandas as pd
import pytest

from company_quality.lab.f000_multilabel_upside import build_f000_multilabel_comparison
from company_quality.lab.official_benchmarks import (
    TPEX_TOTAL_RETURN_URL,
    TWSE_TOTAL_RETURN_URL,
)


KEY = ["issuer_id", "security_code", "market", "decision_date"]


def _inputs() -> tuple[pd.DataFrame, ...]:
    decisions = [f"{year}-06-30" for year in range(2014, 2023)]
    securities = [("issuer-twse", "1001", "TWSE"), ("issuer-tpex", "7001", "TPEx")]
    labels = pd.DataFrame([
        {
            "issuer_id": issuer,
            "security_code": code,
            "market": market,
            "decision_date": decision,
            "result_end_date": f"{int(decision[:4]) + 1}-06-30",
            "fully_observed": True,
            "actual_total_return": (0.12 if code == "1001" else -0.04) + (int(decision[:4]) - 2014) * 0.01,
            "official_benchmark_return": 0.05 if market == "TWSE" else 0.02,
            "official_excess_return": ((0.12 if code == "1001" else -0.04) + (int(decision[:4]) - 2014) * 0.01) - (0.05 if market == "TWSE" else 0.02),
            "positive_return": code == "1001" or int(decision[:4]) >= 2019,
            "outperformed_official_market": code == "1001",
            "official_benchmark_source_ref": (
                TWSE_TOTAL_RETURN_URL if market == "TWSE" else TPEX_TOTAL_RETURN_URL
            ),
            "same_market_median_return": 0.03,
            "generation_id": "generation-test",
            "official_industry_code": "25",
        }
        for decision in decisions
        for issuer, code, market in securities
    ])

    def feature_rows(metric: str, family: str, *, scope: str | None = None) -> pd.DataFrame:
        rows = []
        for decision in decisions:
            for issuer, code, market in securities:
                row = {
                    "issuer_id": issuer,
                    "security_code": code,
                    "market": market,
                    "decision_date": decision,
                    "metric_id": metric,
                    "metric_value": float(int(code)) / 10000 + int(decision[:4]) - 2014,
                    "metric_available_at": f"{decision}T12:00:00+08:00",
                    "evidence_family_id": family,
                }
                if scope is not None:
                    row["model_scope"] = scope
                rows.append(row)
        return pd.DataFrame(rows)

    core = feature_rows("roe_after_tax", "earnings_outcomes")
    trends = feature_rows("upside__roe_trend__trend", "financial_trend:upside", scope="upside_only")
    valuation = feature_rows("earnings_yield", "valuation:earnings_yield", scope="upside_only")
    context = feature_rows("momentum_12m", "upside_market_context:momentum_12m", scope="upside_only")

    mapped = {
        2014: (None, "NO_PRE_DECISION_SNAPSHOT", None, None),
        2015: (None, "NO_PRE_DECISION_SNAPSHOT", None, None),
        2016: ("20160428062625", "AVAILABLE", 63, True),
        2017: ("20170429232241", "AVAILABLE", 62, True),
        2018: ("20180602123043", "AVAILABLE", 28, True),
        2019: ("20190114171354", "AVAILABLE", 167, True),
        2020: ("20191122225827", "AVAILABLE", 221, True),
        2021: ("20210619002356", "AVAILABLE", 11, True),
        2022: ("20210619002356", "STALE_AUDIT_ONLY", 376, False),
    }
    mapping = pd.DataFrame([
        {
            "decision_date": f"{year}-06-30",
            "snapshot_timestamp": stamp,
            "status": status,
            "snapshot_age_days": age,
            "fresh_within_365d": fresh,
            "membership_rows": 3 if fresh else None,
        }
        for year, (stamp, status, age, fresh) in mapped.items()
    ])
    memberships = pd.DataFrame([
        {
            "decision_date": f"{year}-06-30",
            "snapshot_timestamp": mapped[year][0],
            "snapshot_age_days": mapped[year][2],
            "fresh_within_365d": mapped[year][3],
            "chain_code": "F000",
            "node_code": node,
            "node_name": node,
            "security_code": code,
        }
        for year in range(2016, 2023)
        for code, nodes in (("1001", ("F100", "F200")), ("7001", ("F200",)))
        for node in nodes
    ])
    # Exact duplicate source membership must not duplicate the model observation.
    memberships = pd.concat([memberships, memberships.iloc[[0]]], ignore_index=True)
    return labels, core, trends, valuation, context, memberships, mapping


def _build(*, mapping_mutator=None):
    labels, core, trends, valuation, context, memberships, mapping = _inputs()
    if mapping_mutator is not None:
        mapping_mutator(mapping)
    return build_f000_multilabel_comparison(
        labels,
        core,
        trends,
        valuation,
        context,
        memberships,
        mapping,
        producer_candidate_sha="a" * 64,
        input_artifact_shas={name: str(index) * 64 for index, name in enumerate((
            "labels", "features", "trends", "valuation", "market_features",
            "memberships", "snapshot_mapping",
        ), start=1)},
        minimum_train_observations=6,
    )


def test_fixed_pit_multilabel_comparison_is_pooled_unique_and_research_only() -> None:
    rows, report = _build()

    assert report["schema_version"] == "F000PITMultiLabelUpsideComparison.v1"
    assert report["status"] == "research_only"
    assert report["publishable"] is False
    assert report["formal_stars_enabled"] is False
    assert report["final_oos_read"] is False
    assert report["route_key"] == "official_industry_code=25"
    assert report["market_used_as_route_key"] is False
    assert report["market_used_as_model_feature"] is False
    assert report["eligible_decision_dates"] == [
        "2016-06-30", "2017-06-30", "2018-06-30",
        "2019-06-30", "2020-06-30", "2021-06-30",
    ]
    assert report["excluded_decision_dates"] == {
        "2014-06-30": "NO_PRE_DECISION_SNAPSHOT",
        "2015-06-30": "NO_PRE_DECISION_SNAPSHOT",
        "2022-06-30": "STALE_AUDIT_ONLY",
    }
    assert set(rows["candidate_id"]) == {
        "frozen_pooled_industry_ridge_full_v1",
        "f000_multilabel_partial_pooling_ridge_v1",
    }
    assert not rows.duplicated(["candidate_id", *KEY]).any()
    counts = rows.groupby("candidate_id").size()
    assert counts.nunique() == 1
    assert set(rows["market"]) == {"TWSE", "TPEx"}
    assert rows["star"].isna().all()
    assert set(rows["decision_date"]) == {"2020-06-30", "2021-06-30"}
    assert all(window["train_market_count"] == 2 for window in report["temporal_windows"])
    assert all("market" not in item for item in report["baseline_feature_ids"])
    assert report["node_coverage"]["covered_observation_count"] == 12
    assert report["node_coverage"]["multi_label_observation_count"] == 6
    assert report["node_coverage"]["duplicate_membership_rows_removed"] == 1
    assert report["missingness_by_feature"]
    assert set(report["comparisons"]) == {
        "frozen_pooled_industry_ridge_full_v1",
        "f000_multilabel_partial_pooling_ridge_v1",
    }
    challenger = report["comparisons"]["f000_multilabel_partial_pooling_ridge_v1"]
    assert set(challenger["gates"]) == {
        "mae_5pct_better_than_naive_and_linear",
        "spearman_at_least_0_10",
        "direction_improvement_at_least_5pp",
        "auc_at_least_0_62",
        "interval_coverage_0_75_to_0_85",
    }
    assert report["ablation"]["challenger_minus_baseline"]
    assert rows["official_benchmark_return"].notna().all()
    assert rows["official_benchmark_source_ref"].isin(
        [TWSE_TOTAL_RETURN_URL, TPEX_TOTAL_RETURN_URL]
    ).all()


def test_rejects_snapshot_mapping_that_is_not_strictly_pre_decision() -> None:
    def mutate(mapping: pd.DataFrame) -> None:
        mapping.loc[mapping["decision_date"].eq("2021-06-30"), "snapshot_timestamp"] = "20210701000000"

    with pytest.raises(ValueError, match="strictly pre-decision"):
        _build(mapping_mutator=mutate)
