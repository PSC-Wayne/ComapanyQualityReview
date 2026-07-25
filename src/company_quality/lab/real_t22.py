"""Execute the real T22 admission gate and emit an honest non-publishable report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd


PILLARS = (
    "audit_reliability",
    "earnings_capital_efficiency",
    "cash_balance_allocation",
    "business_moat",
    "governance",
    "people_adaptability",
)


def _six_pillar_count(features: pd.DataFrame) -> int:
    available = features.loc[features["metric_value"].notna()]
    if available.empty:
        return 0
    coverage = available.groupby(["issuer_id", "decision_date"])["pillar"].agg(set)
    expected = set(PILLARS)
    return int(sum(pillars == expected for pillars in coverage))


def build_real_t22_report(
    t20: dict[str, Any],
    t21: dict[str, Any],
    feature_report: dict[str, Any],
    features: pd.DataFrame,
) -> dict[str, object]:
    six_pillar = _six_pillar_count(features)
    total = int(feature_report["observation_count"])
    failures: dict[str, str] = {}
    if six_pillar == 0:
        failures["candidate_matrix"] = "no_fully_covered_six_pillar_candidate_rows"
    available_counts = feature_report["available_metric_counts"]
    if isinstance(available_counts, dict) and int(
        available_counts.get("people_adaptability", 0)
    ) == 0:
        failures["people_adaptability"] = (
            "no_authoritative_PIT_management_delivery_or_succession_evidence"
        )
    failures["downside_constructs"] = (
        "governed_PIT_permanent_loss_and_material_event_constructs_unavailable"
    )
    return {
        "schema_version": "RealPipelineExecutionReport.v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authorization_scope": "real T03-T22 execution; no T23, no freeze, no rating",
        "execution_status": "NON_PUBLISHABLE",
        "publishable": False,
        "rating_disposition": "NO_RATING_NOT_APPLICABLE",
        "t23_started": False,
        "freeze_created": False,
        "rating_created": False,
        "scorer_semantics": {
            "within_pillar": "equal_weight_available_metrics",
            "directions": "explicit_high_good_or_low_good",
            "missing_values": "not_imputed; available weights renormalized within pillar",
            "cross_pillar": "all six pillars require at least one available metric",
        },
        "stage_results": {
            "T03_T06": {
                "status": "EXECUTED_WITH_MEMBERSHIP_LEVEL_EXCLUSIONS",
                "membership_level_failure_count": sum(
                    len(values) for values in t20["pre_admission_failures"].values()
                ),
            },
            "T09_T14": {
                "status": str(feature_report["status"]),
                "observation_count": total,
                "available_metric_counts": available_counts,
            },
            "T16_T19": {
                "status": "BLOCKED_INCOMPLETE_CANDIDATE_CONTRACT",
                "fully_covered_six_pillar_count": six_pillar,
                "total_observation_count": total,
            },
            "T20": {
                "status": str(t20["status"]),
                "TWSE_member_count": len(t20["cohorts"]["TWSE"]["issuer_ids"]),
                "TPEx_member_count": len(t20["cohorts"]["TPEx"]["issuer_ids"]),
            },
            "T21": {
                "status": str(t21["status"]),
                "label_count": int(t21["label_count"]),
                "fully_observed_count": int(t21["fully_observed_count"]),
                "adverse_fully_observed_count": int(
                    t21["adverse_fully_observed_count"]
                ),
                "coverage": float(t21["fully_observed_coverage"]),
            },
            "T22": {
                "status": "BLOCKED_INPUT_CONTRACT",
                "calibration_executed": False,
                "publishable": False,
                "failure_reasons": failures,
            },
        },
        "failure_reasons": failures,
        "next_authorized_stage": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--t20", required=True, type=Path)
    parser.add_argument("--t21-report", required=True, type=Path)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--feature-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_real_t22_report(
        json.loads(args.t20.read_text()),
        json.loads(args.t21_report.read_text()),
        json.loads(args.feature_report.read_text()),
        pd.read_parquet(args.features),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "execution_status": report["execution_status"],
        "T22": report["stage_results"]["T22"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
