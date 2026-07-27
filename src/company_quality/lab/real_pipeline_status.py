"""Build an honest NON_PUBLISHABLE status report for the real T20-T22 path."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Mapping

import pandas as pd


def build_real_pipeline_status(
    materializer_report: Mapping[str, object],
    identity: pd.DataFrame,
) -> dict[str, object]:
    identity_report = materializer_report.get("official_identity")
    if not isinstance(identity_report, dict):
        raise ValueError("materializer official_identity report missing")
    required = {
        "security_code", "market", "identity_status", "legal_identity_resolved",
        "listed_on", "delisted_on",
    }
    if not required.issubset(identity.columns):
        raise ValueError("official_identity parquet schema drifted")

    delisted = identity[identity["delisted_on"].notna()]
    legal_gaps = identity[~identity["legal_identity_resolved"].astype(bool)]
    listing_date_gaps = delisted[delisted["listed_on"].isna()]
    gap_columns = ["security_code", "market", "identity_status"]

    t20_status = str(identity_report.get("t20_status"))
    t20_blockers: list[str] = []
    if len(legal_gaps):
        t20_blockers.append(
            "Immutable official legal identity is unresolved for affected delisted securities."
        )
    if len(listing_date_gaps):
        t20_blockers.append(
            "Official exchange listing dates are unavailable for affected delisted securities."
        )
    if len(delisted):
        t20_blockers.append(
            "A complete governed adverse/non-adverse classification of official delisting reasons is not materialized."
        )

    price_ready_value = materializer_report.get("ready_security_count", 0)
    security_count_value = materializer_report.get("security_count", 0)
    if not isinstance(price_ready_value, int) or not isinstance(
        security_count_value, int
    ):
        raise ValueError("materializer security counts drifted")
    price_ready = price_ready_value
    security_count = security_count_value
    report = {
        "schema_version": "RealPipelineExecutionReport.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authorization_scope": (
            "real T20-T22 pipeline; NON_PUBLISHABLE report only; no T23, no freeze, no rating"
        ),
        "execution_status": "BLOCKED_INPUT_DATA" if t20_blockers else "READY_FOR_T20",
        "publishable": False,
        "rating_disposition": "NO_RATING_NOT_APPLICABLE",
        "t23_started": False,
        "freeze_created": False,
        "rating_created": False,
        "real_data_inventory": {
            "security_count": security_count,
            "price_ready_count": price_ready,
            "price_ready_coverage": price_ready / security_count if security_count else 0,
            "security_membership_coverage": identity_report.get(
                "security_membership_coverage"
            ),
            "legal_identity_coverage": identity_report.get("legal_identity_coverage"),
            "legal_identity_gap_count": len(legal_gaps),
            "legal_identity_gap_status_counts": {
                str(key): int(value)
                for key, value in legal_gaps["identity_status"].value_counts().items()
            },
            "delisted_security_count": len(delisted),
            "delisted_listing_date_gap_count": len(listing_date_gaps),
        },
        "stage_results": {
            "T20": {
                "status": t20_status,
                "output": None,
                "blockers": t20_blockers,
                "affected_legal_identity_gaps": legal_gaps[gap_columns].to_dict(
                    "records"
                ),
                "affected_listing_date_gaps": listing_date_gaps[
                    ["security_code", "market"]
                ].to_dict("records"),
            },
            "T21": {
                "status": "BLOCKED_UPSTREAM_T20",
                "output": None,
                "price_input_status": (
                    "READY" if price_ready == security_count and security_count else "BLOCKED"
                ),
                "blockers": [
                    "No admitted real T20 cohort exists.",
                    "FinLab adjusted close is materialized, but no same-generation governed T21 label inputs exist for the admitted cohort.",
                ],
            },
            "T22": {
                "status": "BLOCKED_UPSTREAM_T21_AND_FEATURES",
                "output": None,
                "calibration_validation_report": None,
                "candidate_observation_count": 0,
                "blockers": [
                    "No real T21 OutcomeLabelSet observations exist.",
                    "No same-generation real T09/T10/T13/T14/T16/T17/T18/T19 candidate observations exist.",
                ],
            },
        },
        "execution_disposition": "STOP_BEFORE_T23",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materializer-report", required=True, type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    materializer_report = json.loads(args.materializer_report.read_text())
    identity = pd.read_parquet(args.identity)
    report = build_real_pipeline_status(materializer_report, identity)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "execution_status": report["execution_status"],
        "t20_status": materializer_report["official_identity"]["t20_status"],
        "legal_identity_gap_count": int(
            (~identity["legal_identity_resolved"].astype(bool)).sum()
        ),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
