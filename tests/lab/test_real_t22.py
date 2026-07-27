from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from company_quality.lab.real_t22 import (
    _evaluation_policy,
    build_pit_downside_constructs,
    evaluate_downside_construct_calibration,
    execute_real_t22_calibration,
)


PILLARS = (
    "audit_reliability",
    "earnings_capital_efficiency",
    "cash_balance_allocation",
    "business_moat",
    "governance",
    "people_adaptability",
)


def _sha_inputs() -> dict[str, str | None]:
    return {
        ticket: str((index % 9) + 1) * 64
        for index, ticket in enumerate(
            ("T09", "T10", "T13", "T14", "T16", "T17", "T18", "T19", "T21")
        )
    }


def _labels(codes=("1001", "1002"), decisions=("2022-06-30",)):
    rows = []
    for decision in decisions:
        for index, code in enumerate(codes):
            rows.append({
                "issuer_id": f"issuer-{code}",
                "security_code": code,
                "market": "TWSE",
                "decision_date": decision,
                "adverse_outcome": index == 0,
                "adverse_event_date": (
                    (date.fromisoformat(decision) + timedelta(days=100)).isoformat()
                    if index == 0 else None
                ),
                "fully_observed": True,
                "label_available_at": "2026-01-01T00:00:00+00:00",
                "generation_id": "real-generation",
            })
    return pd.DataFrame(rows)


def _financial(values):
    return pd.DataFrame(
        {code: [value] for code, value in values.items()},
        index=pd.DatetimeIndex(["2022-03-31"], name="date"),
    )


def test_constructs_are_pit_lineage_bound_and_zero_requires_full_window() -> None:
    labels = _labels()
    price_dates = pd.bdate_range("2021-12-01", "2022-06-30")
    adjusted = pd.DataFrame({
        "1001": np.linspace(100, 50, len(price_dates)),
        "1002": np.linspace(100, 110, len(price_dates)),
    }, index=price_dates)
    disclosure = pd.DataFrame({
        "date": [pd.Timestamp("2022-03-31")],
        "1001": [pd.Timestamp("2022-05-15")],
        "1002": [pd.Timestamp("2022-05-15")],
    })
    events = pd.DataFrame(
        {"1001": [10.0], "1002": [0.0]},
        index=pd.DatetimeIndex(["2021-01-01"], name="date"),
    )
    rows, report = build_pit_downside_constructs(
        labels, adjusted, disclosure,
        _financial({"1001": 80, "1002": 20}),
        _financial({"1001": 50, "1002": 200}),
        _financial({"1001": -10, "1002": 20}),
        events,
        regulatory_source_start="2019-01-01T00:00:00+08:00",
    )
    assert report["complete_construct_count"] == 2
    assert report["formal_T18_status"] == (
        "BLOCKED_MISSING_RISK_STRESS_AND_BOMB_CONTRACTS"
    )
    risky = rows.loc[rows["security_code"] == "1001"].iloc[0]
    safe = rows.loc[rows["security_code"] == "1002"].iloc[0]
    assert risky["maximum_drawdown_vulnerability"] > safe[
        "maximum_drawdown_vulnerability"
    ]
    assert risky["permanent_capital_loss_vulnerability"] > safe[
        "permanent_capital_loss_vulnerability"
    ]
    assert risky["material_adverse_event_vulnerability"] == 1
    assert safe["material_adverse_event_vulnerability"] == 0
    assert "2022-03-31" in risky["debt_evidence_id"]
    assert risky["event_evidence_id"].startswith(
        "finlab:information_violation_cases:裁罰金額萬元:1001"
    )

    incomplete, incomplete_report = build_pit_downside_constructs(
        labels, adjusted, disclosure,
        _financial({"1001": 80, "1002": 20}),
        _financial({"1001": 50, "1002": 200}),
        _financial({"1001": -10, "1002": 20}),
        events,
        regulatory_source_start="2021-01-01T00:00:00+08:00",
    )
    assert incomplete["material_adverse_event_vulnerability"].isna().all()
    assert incomplete_report["complete_construct_count"] == 0


def _calibration_inputs():
    labels = _labels(
        tuple(f"{index:04d}" for index in range(120)),
        ("2022-06-30", "2023-06-30", "2024-06-30"),
    )
    labels["adverse_outcome"] = labels["security_code"].astype(int) < 20
    labels["adverse_event_date"] = labels.apply(
        lambda row: (
            date.fromisoformat(row["decision_date"]) + timedelta(days=100)
        ).isoformat() if row["adverse_outcome"] else None,
        axis=1,
    )
    feature_rows = []
    construct_rows = []
    for label in labels.itertuples(index=False):
        index = int(label.security_code)
        for pillar in PILLARS:
            feature_rows.append({
                "issuer_id": label.issuer_id,
                "decision_date": label.decision_date,
                "pillar": pillar,
                "metric_id": f"{pillar}:metric",
                "metric_value": Decimal(index),
                "direction": "high_good",
                "evidence_family_id": f"family:{pillar}",
                "metric_available_at": f"{label.decision_date}T00:00:00+08:00",
                "evidence_id": f"e:{label.decision_date}:{label.security_code}:{pillar}",
            })
        risk = Decimal(119 - index) / Decimal(119)
        construct_rows.append({
            "issuer_id": label.issuer_id,
            "decision_date": label.decision_date,
            "construct_complete": True,
            "maximum_drawdown_vulnerability": risk,
            "permanent_capital_loss_vulnerability": risk,
            "material_adverse_event_vulnerability": risk,
        })
    return labels, pd.DataFrame(feature_rows), pd.DataFrame(construct_rows)


def test_real_calibration_executes_without_fabricating_t17_or_pass() -> None:
    labels, features, constructs = _calibration_inputs()
    input_shas: dict[str, str | None] = _sha_inputs()
    input_shas["T17"] = None
    policy = _evaluation_policy(
        "real-generation",
        "a" * 64,
        features["evidence_family_id"],
        {
            "real_features": "1" * 64,
            "real_downside_constructs": "2" * 64,
            "policy_definition": "a" * 64,
        },
        "2023-06-30T00:00:00+00:00",
    )
    assert policy.policy_scope == "generation_metric_family_union"
    assert policy.policy_coverage == Decimal("1")
    assert policy.failure_reasons == {}
    families = {
        row.evidence_family_id
        for row in policy.anti_double_count_policy.evidence_family_ownership
    }
    assert set(features["evidence_family_id"]) <= families
    assert len(families) == len(
        policy.anti_double_count_policy.evidence_family_ownership
    )
    report, rows = execute_real_t22_calibration(
        labels, features, constructs,
        input_producer_shas=input_shas,
        producer_candidate_sha="a" * 64,
        policy=policy,
    )
    assert rows
    assert all(row.upside_decimal is None for row in rows)
    assert report.metrics.auc == Decimal("1")
    assert report.champion_verdict == "blocked"
    assert "T17" not in report.failure_reasons
    assert report.threshold_candidates.upside_status == "blocked_missing_T17"
    assert report.threshold_candidates.quality_status == "diagnostic_only_blocked_T14"
    assert report.failure_reasons["T14"].startswith("authoritative_PIT")
    assert "T18" not in report.failure_reasons
    assert "stress" not in report.failure_reasons
    assert report.stability_checks.stress_status == "blocked_missing_authority"
    assert report.publishable is False
    assert report.rating_disposition == "NO_RATING_NOT_APPLICABLE"

    downside_report, validation = evaluate_downside_construct_calibration(
        rows,
        policy,
        total_candidate_count=len(labels),
        input_producer_shas=input_shas,
        generation_id="real-generation",
        producer_candidate_sha="a" * 64,
    )
    assert downside_report.metrics.auc == Decimal("1")
    assert validation["verdict"] == "pass"
    assert validation["stress_pack_status"] == "blocked_missing_authority"
    assert validation["bomb_status"] == "blocked_missing_authority"
