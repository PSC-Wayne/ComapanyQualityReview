from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import jsonschema
import numpy as np
import pandas as pd
import pytest

from company_quality.lab.model_competition import (
    evaluate_frozen_final_oos,
    freeze_pre_oos_candidate,
    to_frozen_research_upside_core_result,
)


ROOT = Path(__file__).parents[2]


def _rows(*, final=False):
    records = []
    dates = ["2018-06-30", "2019-06-30", "2020-06-30", "2021-06-30"]
    if final:
        dates = ["2023-06-30"]
    for candidate in ("good", "bad") if not final else ("good",):
        sequence = 0
        for year_index, decision in enumerate(dates):
            for offset in range(30 if not final else 100):
                x = ((offset + year_index) % 21 - 10) / 10.0
                good = candidate == "good"
                p50 = x + 0.02 if good else -x
                probability = 1.0 / (1.0 + np.exp(-4.0 * (x if good else -x)))
                trained = (
                    "2021-06-29" if final
                    else f"{int(decision[:4]) - 2}-06-30"
                )
                result_end = (
                    pd.Timestamp(decision) + pd.DateOffset(years=1)
                ).date().isoformat()
                records.append({
                    "candidate_id": candidate,
                    "issuer_id": f"issuer-{sequence // 2:04d}",
                    "security_code": f"code-{sequence:04d}",
                    "market": "TWSE",
                    "decision_date": decision,
                    "result_end_date": result_end,
                    "trained_through": trained,
                    "generation_id": "g1",
                    "actual_total_return": x,
                    "official_benchmark_return": 0.0,
                    "predicted_p10_return": p50 - 0.2,
                    "predicted_p50_return": p50,
                    "predicted_p90_return": p50 + 0.2,
                    "positive_return_probability": probability,
                    "outperform_probability": probability,
                    "data_completeness": 0.9,
                    "industry_train_observations": 600,
                    "linear_feature_x": float(offset % 2),
                })
                sequence += 1
    return pd.DataFrame(records)


def test_pre_oos_selects_unique_champion_learns_weights_and_freezes() -> None:
    freeze = freeze_pre_oos_candidate(_rows(), final_oos_start="2023-01-01")

    assert freeze.champion_candidate_id == "good"
    assert freeze.selection_years == [2020, 2021]
    assert set(freeze.star_weights) == {
        "official_outperform_probability", "predicted_p50_return", "confidence"
    }
    assert all(value > 0 for value in freeze.star_weights.values())
    assert sum(freeze.star_weights.values()) == pytest.approx(1.0)
    assert freeze.publishable is False
    assert freeze.formal_stars_enabled is False
    assert [item["baseline_id"] for item in freeze.fixed_baselines] == [
        "no_company_data_temporal_median", "same_data_normalized_linear"
    ]

    schema = json.loads(
        (ROOT / "src/company_quality/lab/contracts/FrozenPreOOSCandidate.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(asdict(freeze))


def test_final_oos_can_only_consume_frozen_champion_and_never_emits_formal_star() -> None:
    pre_oos = _rows()
    freeze = freeze_pre_oos_candidate(pre_oos, final_oos_start="2023-01-01")
    final = _rows(final=True)
    result = evaluate_frozen_final_oos(final, freeze)

    assert set(result["result_status"]) == {"research_only"}
    assert bool(result["star"].isna().all())
    assert bool(result["research_star_score"].between(0, 5).all())
    core = to_frozen_research_upside_core_result(result.iloc[0], freeze)
    assert core.status == "research_only"
    assert core.stars is None
    assert core.confidence is not None

    with pytest.raises(ValueError, match="final OOS rows"):
        freeze_pre_oos_candidate(
            pd.concat([pre_oos, final], ignore_index=True),
            final_oos_start="2023-01-01",
        )
    leaky_label = pre_oos.copy()
    leaky_label.loc[leaky_label.index[0], "result_end_date"] = "2023-01-01"
    with pytest.raises(ValueError, match="outcome labels"):
        freeze_pre_oos_candidate(leaky_label, final_oos_start="2023-01-01")
    wrong = final.copy()
    wrong["candidate_id"] = "bad"
    with pytest.raises(ValueError, match="frozen champion"):
        evaluate_frozen_final_oos(wrong, freeze)


def test_high_predicted_return_does_not_raise_confidence() -> None:
    freeze = freeze_pre_oos_candidate(_rows(), final_oos_start="2023-01-01")
    final = _rows(final=True).iloc[:2].copy()
    final.loc[final.index[0], [
        "predicted_p10_return", "predicted_p50_return", "predicted_p90_return"
    ]] = [-0.2, 0.0, 0.2]
    final.loc[final.index[1], [
        "predicted_p10_return", "predicted_p50_return", "predicted_p90_return"
    ]] = [0.8, 1.0, 1.2]
    result = evaluate_frozen_final_oos(final, freeze)

    assert result["confidence"].iloc[0] == pytest.approx(result["confidence"].iloc[1])
    assert result["research_star_score"].iloc[1] > result["research_star_score"].iloc[0]


def test_exact_tie_and_candidate_observation_mismatch_fail_closed() -> None:
    rows = _rows()
    good = rows.loc[rows["candidate_id"].eq("good")]
    tied = pd.concat([
        good,
        good.assign(candidate_id="equal"),
    ], ignore_index=True)
    with pytest.raises(ValueError, match="no unique"):
        freeze_pre_oos_candidate(tied, final_oos_start="2023-01-01")

    missing = rows.drop(rows.loc[rows["candidate_id"].eq("bad")].index[0])
    with pytest.raises(ValueError, match="identical pre-OOS"):
        freeze_pre_oos_candidate(missing, final_oos_start="2023-01-01")


def test_freeze_requires_same_data_linear_baseline_features() -> None:
    rows = _rows().drop(columns=["linear_feature_x"])

    with pytest.raises(ValueError, match="same-data linear baseline features"):
        freeze_pre_oos_candidate(rows, final_oos_start="2023-01-01")


def test_freeze_rejects_candidate_that_does_not_beat_fixed_baselines() -> None:
    rows = _rows()
    median = float(np.median(rows["actual_total_return"].to_numpy(float)))
    rows["predicted_p10_return"] = median - 0.2
    rows["predicted_p50_return"] = median
    rows["predicted_p90_return"] = median + 0.2

    with pytest.raises(ValueError, match="no-company baseline"):
        freeze_pre_oos_candidate(rows, final_oos_start="2023-01-01")
