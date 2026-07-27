from __future__ import annotations

from typing import Any, cast

import pandas as pd
import pytest

from company_quality.industry.model_route import (
    EffectiveIndustryClassification,
    IndustryModelRouteError,
    route_industry_model,
)
from company_quality.lab.financial_models import (
    inspect_current_cbc_bank_csv,
    validate_financial_candidates,
)


def _record(industry="17"):
    return EffectiveIndustryClassification(
        market="TWSE",
        issuer_id="bank-issuer",
        security_code="bank-code",
        industry_code=industry,
        effective_from="2020-01-01",
        effective_to=None,
        available_at="2020-01-02T00:00:00+08:00",
        classification_version="official-history-v1",
        authority_url="https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        evidence_id="industry:bank-code:v1",
    )


def test_financial_subtypes_get_separate_routes_and_no_general_fallback() -> None:
    candidates = []
    for subtype in ("bank", "life_insurer", "securities"):
        route = route_industry_model(
            generation_id="g1",
            issuer_id="bank-issuer",
            security_code="bank-code",
            market="TWSE",
            decision_date="2021-01-01",
            classifications=(_record(),),
            sample_counts={},
            financial_subtype=subtype,
        )
        assert route.status == "financial_separate_model"
        assert route.financial_subtype == subtype
        assert route.stars_eligible is False
        assert route.all_market_fallback_model_id is None
        candidates.append(route.candidate_model_id)
    assert len(set(candidates)) == 3

    with pytest.raises(IndustryModelRouteError, match="only valid"):
        route_industry_model(
            generation_id="g1",
            issuer_id="bank-issuer",
            security_code="bank-code",
            market="TWSE",
            decision_date="2021-01-01",
            classifications=(_record(industry="24"),),
            sample_counts={},
            financial_subtype="bank",
        )


def _financial_data(train_count=500, oos_count=120):
    labels = []
    features = []
    metrics = {
        "bank": "capital_adequacy_ratio",
        "life_insurer": "risk_based_capital_ratio",
        "securities": "liquid_capital_ratio",
    }
    for subtype_index, (subtype, metric_id) in enumerate(metrics.items()):
        split_sizes = (("train", train_count), ("validation", 100), ("final_oos", oos_count))
        sequence = 0
        for split_index, (split, count) in enumerate(split_sizes):
            decision = f"202{split_index}-06-30"
            for offset in range(count):
                x = ((offset + subtype_index) % 101 - 50) / 50.0
                issuer = f"{subtype}-{sequence:04d}"
                labels.append({
                    "issuer_id": issuer,
                    "security_code": issuer,
                    "market": "TWSE",
                    "decision_date": decision,
                    "generation_id": "g1",
                    "financial_subtype": subtype,
                    "split": split,
                    "actual_total_return": x,
                    "adverse_outcome": int(x < 0),
                })
                features.append({
                    "issuer_id": issuer,
                    "decision_date": decision,
                    "generation_id": "g1",
                    "financial_subtype": subtype,
                    "metric_id": metric_id,
                    "metric_value": x,
                    "available_at": f"202{split_index}-06-29T12:00:00+08:00",
                    "historical_pit_eligible": True,
                    "source_ref": f"https://authority.example/{subtype}",
                })
                sequence += 1
    return pd.DataFrame(labels), pd.DataFrame(features)


def test_three_financial_subtypes_train_validate_and_final_oos_independently() -> None:
    labels, features = _financial_data()
    predictions, report = validate_financial_candidates(labels, features)

    assert report["publishable"] is False
    assert report["generic_company_fallback"] is None
    models = cast(list[dict[str, Any]], report["models"])
    assert len(models) == 9
    assert {item["financial_subtype"] for item in models} == {
        "bank", "life_insurer", "securities"
    }
    assert {item["model_scope"] for item in models} == {
        "quality_only", "upside_only", "downside_only"
    }
    assert all(item["status"] == "research_only" for item in models)
    assert all(item["train_observations"] == 500 for item in models)
    assert all(item["final_oos_observations"] == 120 for item in models)
    assert all(item["candidate_validation_mae"] < item["baseline_validation_mae"] for item in models)
    assert set(predictions["result_status"]) == {"research_only"}
    assert predictions["model_id"].nunique() == 9


def test_sample_gate_and_generic_company_metrics_fail_closed() -> None:
    labels, features = _financial_data(train_count=499, oos_count=100)
    predictions, report = validate_financial_candidates(labels, features)
    assert predictions.empty
    models = cast(list[dict[str, Any]], report["models"])
    assert {item["status"] for item in models} == {
        "industry_sample_insufficient"
    }
    assert all(item["all_company_fallback_model_id"] is None for item in models)

    features.loc[features.index[0], "metric_id"] = "free_cash_flow_trend"
    with pytest.raises(ValueError, match="generic-company"):
        validate_financial_candidates(labels, features)


def test_current_cbc_bank_csv_is_display_only_without_publication_lineage() -> None:
    payload = (
        "日期,銀行名稱/項目(單位：％，倍),自有資本比率-統計專用,逾放比率比率-統計專用\n"
        "2026Q1,測試銀行,15.2,0.12\n"
    ).encode("utf-8-sig")
    facts, report = inspect_current_cbc_bank_csv(
        payload, retrieved_at="2026-07-27T12:00:00+08:00"
    )

    assert report["status"] == "current_display_only"
    assert report["historical_pit_eligible"] is False
    assert report["institution_count"] == 1
    assert set(facts["metric_id"]) == {
        "capital_adequacy_ratio", "nonperforming_loan_ratio"
    }
    assert bool(facts["historical_pit_eligible"].eq(False).all())

    labels, current_only_features = _financial_data()
    current_only_features["historical_pit_eligible"] = False
    predictions, validation = validate_financial_candidates(
        labels, current_only_features
    )
    models = cast(list[dict[str, Any]], validation["models"])
    assert predictions.empty
    assert {item["status"] for item in models} == {"model_not_passed"}
