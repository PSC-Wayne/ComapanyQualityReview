from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import jsonschema
import pandas as pd

from company_quality.lab.official_benchmarks import (
    TPEX_TOTAL_RETURN_URL,
    TWSE_TOTAL_RETURN_URL,
)
from company_quality.lab.pre_oos_readiness import assess_pre_oos_readiness


ROOT = Path(__file__).parents[2]


def _labels() -> pd.DataFrame:
    rows = []
    refs = {
        "TWSE": TWSE_TOTAL_RETURN_URL,
        "TPEx": TPEX_TOTAL_RETURN_URL,
    }
    for year in range(2017, 2021):
        for market, code in (("TWSE", "2330"), ("TPEx", "6488")):
            rows.append({
                "issuer_id": "issuer-shared-across-securities",
                "security_code": code,
                "market": market,
                "decision_date": f"{year}-06-30",
                "result_end_date": f"{year + 1}-06-30",
                "generation_id": "real-pre-oos-g1",
                "actual_total_return": 0.1 + (year - 2017) * 0.01,
                "official_benchmark_return": 0.05,
                "official_benchmark_source_ref": refs[market],
            })
    return pd.DataFrame(rows)


def _candidates(labels: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candidate_id, offset in (("ridge", 0.01), ("robust", -0.01)):
        for label in labels.to_dict("records"):
            p50 = float(label["actual_total_return"]) + offset
            rows.append({
                **label,
                "candidate_id": candidate_id,
                "trained_through": f"{int(str(label['decision_date'])[:4]) - 2}-06-29",
                "predicted_p10_return": p50 - 0.2,
                "predicted_p50_return": p50,
                "predicted_p90_return": p50 + 0.2,
                "positive_return_probability": 0.65,
                "outperform_probability": 0.60,
                "data_completeness": 0.9,
                "industry_train_observations": 600,
            })
    return pd.DataFrame(rows)


def test_ready_only_with_four_years_both_official_markets_and_two_candidates() -> None:
    labels = _labels()
    report = assess_pre_oos_readiness(
        labels, _candidates(labels), final_oos_start="2023-01-01"
    )

    assert report.ready_for_pre_oos_freeze is True
    assert report.blockers == []
    assert report.label_years == [2017, 2018, 2019, 2020]
    assert report.markets == ["TPEx", "TWSE"]
    assert report.candidate_ids == ["ridge", "robust"]
    assert report.final_oos_rows_read is False
    assert report.final_oos_record_written is False

    schema = json.loads((
        ROOT / "src/company_quality/lab/contracts/PreOOSReadinessReport.schema.json"
    ).read_text())
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(asdict(report))


def test_legacy_real_labels_fail_closed_without_required_return_contract() -> None:
    legacy = pd.DataFrame({
        "issuer_id": ["issuer-1"],
        "security_code": ["2330"],
        "market": ["TWSE"],
        "decision_date": ["2022-06-30"],
        "generation_id": ["legacy-g"],
        "fully_observed": [True],
    })
    report = assess_pre_oos_readiness(
        legacy, None, final_oos_start="2025-01-01"
    )

    assert report.ready_for_pre_oos_freeze is False
    assert "candidate_rows_missing" in report.blockers
    assert any(item.startswith("label_columns_missing:") for item in report.blockers)
    assert "selection_years_below_4:1" in report.blockers
    assert "markets_missing:TPEx" in report.blockers
    assert report.final_oos_rows_read is False


def test_candidate_mismatch_and_non_official_benchmark_fail_closed() -> None:
    labels = _labels()
    labels.loc[labels["market"].eq("TPEx"), "official_benchmark_source_ref"] = (
        "generation://same-market-median"
    )
    candidates = _candidates(labels)
    candidates = candidates.drop(
        candidates.loc[candidates["candidate_id"].eq("robust")].index[0]
    )
    report = assess_pre_oos_readiness(
        labels, candidates, final_oos_start="2023-01-01"
    )

    assert report.ready_for_pre_oos_freeze is False
    assert "official_benchmark_source_invalid:TPEx" in report.blockers
    assert "candidate_observation_sets_differ" in report.blockers
    assert "candidate_rows_do_not_cover_all_labels" not in report.blockers


def test_pre_oos_boundary_and_training_leakage_are_rejected_without_oos_record() -> None:
    labels = _labels()
    labels.loc[labels.index[-1], "result_end_date"] = "2023-01-01"
    candidates = _candidates(labels)
    candidates.loc[candidates.index[0], "trained_through"] = candidates.loc[
        candidates.index[0], "decision_date"
    ]
    report = assess_pre_oos_readiness(
        labels, candidates, final_oos_start="2023-01-01"
    )

    assert report.ready_for_pre_oos_freeze is False
    assert "label_results_not_complete_before_final_oos" in report.blockers
    assert "candidate_results_not_complete_before_final_oos" in report.blockers
    assert "candidate_training_cutoff_leaks_labels" in report.blockers
    assert report.final_oos_record_written is False
