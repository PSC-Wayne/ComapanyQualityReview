"""Materialize PIT downside constructs and execute blocked-safe real T22 calibration."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from company_quality.calibration import (
    AdmittedMetric,
    CandidateObservation,
    LeakageChecks,
    build_calibration_validation_report,
    build_candidate_score_matrix,
)
from company_quality.policies.candidate import (
    AntiDoubleCountPolicy,
    BombPolicy,
    CandidatePolicyBundle,
    DownsideBucketPolicy,
    DownsideComponentWeights,
    PillarWeights,
    QualityBand,
    QualityPolicy,
    UpsideBucketPolicy,
)


PILLARS = (
    "audit_reliability",
    "earnings_capital_efficiency",
    "cash_balance_allocation",
    "business_moat",
    "governance",
    "people_adaptability",
)
_TAIPEI = "Asia/Taipei"


def _wide(path: Path) -> pd.DataFrame:
    frame = pd.read_feather(path).set_index("date").sort_index()
    frame.columns = [str(column).split()[0] for column in frame.columns]
    return frame.loc[:, ~frame.columns.duplicated(keep="last")]


def _aware(value: object) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        return result.tz_localize(_TAIPEI)
    return result.tz_convert(_TAIPEI)


def _latest_financial(
    frame: pd.DataFrame,
    disclosure: pd.DataFrame,
    code: str,
    decision: pd.Timestamp,
) -> tuple[float | None, pd.Timestamp | None, str | None]:
    if code not in frame or code not in disclosure:
        return None, None, None
    available = pd.to_datetime(disclosure[code], errors="coerce")
    admitted = available[(available.notna()) & (available.map(_aware) <= decision)]
    for period in reversed(admitted.index):
        if period not in frame.index:
            continue
        raw = frame.loc[period, code]
        if isinstance(raw, pd.Series):
            raw = raw.dropna().iloc[-1] if raw.notna().any() else np.nan
        if pd.notna(raw):
            timestamp = _aware(admitted.loc[period])
            return float(raw), timestamp, str(pd.Timestamp(period).date())
    return None, None, None


def _trailing_mdd(
    series: pd.Series, decision: pd.Timestamp
) -> tuple[float | None, pd.Timestamp | None, pd.Timestamp | None]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    index = pd.DatetimeIndex(numeric.index)
    if index.tz is None:
        index = index.tz_localize(_TAIPEI)
    else:
        index = index.tz_convert(_TAIPEI)
    numeric.index = index
    admitted = numeric.loc[numeric.index <= decision].tail(252)
    if len(admitted) < 120:
        return None, None, None
    drawdown = 1.0 - admitted / admitted.cummax()
    return float(drawdown.max()), admitted.index[0], admitted.index[-1]


def _percentile_risk(
    frame: pd.DataFrame, column: str, *, ascending: bool = True
) -> pd.Series:
    return frame.groupby("decision_date")[column].rank(
        pct=True, method="average", ascending=ascending
    )


def build_pit_downside_constructs(
    labels: pd.DataFrame,
    adjusted_close: pd.DataFrame,
    disclosure: pd.DataFrame,
    debt_ratio: pd.DataFrame,
    current_ratio: pd.DataFrame,
    free_cash_flow: pd.DataFrame,
    regulatory_events: pd.DataFrame,
    *,
    regulatory_source_start: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Create lineage-bound construct inputs; this does not claim full T18 readiness."""
    disclosure = disclosure.set_index("date").sort_index()
    disclosure = disclosure.loc[:, ~disclosure.columns.duplicated(keep="last")]
    adjusted_close = adjusted_close.copy()
    adjusted_close.columns = [str(column).split()[0] for column in adjusted_close.columns]
    adjusted_close = adjusted_close.loc[:, ~adjusted_close.columns.duplicated(keep="last")]
    regulatory_events = regulatory_events.copy()
    regulatory_events.index = pd.to_datetime(regulatory_events.index)
    source_start = _aware(regulatory_source_start)
    rows: list[dict[str, object]] = []

    for label in labels.itertuples(index=False):
        code = str(label.security_code)
        decision = _aware(f"{label.decision_date}T23:59:59+08:00")
        debt, debt_at, debt_period = _latest_financial(
            debt_ratio, disclosure, code, decision
        )
        current, current_at, current_period = _latest_financial(
            current_ratio, disclosure, code, decision
        )
        fcf, fcf_at, fcf_period = _latest_financial(
            free_cash_flow, disclosure, code, decision
        )
        mdd, mdd_start, mdd_end = (
            _trailing_mdd(adjusted_close[code], decision)
            if code in adjusted_close
            else (None, None, None)
        )
        window_start = decision - pd.DateOffset(years=3)
        event_window_covered = source_start <= window_start
        event_sum: float | None = None
        if event_window_covered:
            if code in regulatory_events:
                values = pd.to_numeric(regulatory_events[code], errors="coerce")
                event_sum = float(values.loc[
                    (values.index > window_start.tz_localize(None))
                    & (values.index <= decision.tz_localize(None))
                ].fillna(0).sum())
            else:
                event_sum = 0.0
        financial_available = [
            item for item in (debt_at, current_at, fcf_at) if item is not None
        ]
        available_values = [
            *financial_available,
            *(item for item in (mdd_end,) if item is not None),
            *(decision for _ in range(1) if event_window_covered),
        ]
        rows.append({
            "issuer_id": str(label.issuer_id),
            "security_code": code,
            "market": str(label.market),
            "decision_date": str(label.decision_date),
            "adverse_outcome": bool(label.adverse_outcome),
            "adverse_event_date": label.adverse_event_date,
            "fully_observed": bool(label.fully_observed),
            "label_available_at": str(label.label_available_at),
            "generation_id": str(label.generation_id),
            "debt_ratio": debt,
            "current_ratio": current,
            "free_cash_flow": fcf,
            "trailing_252d_mdd": mdd,
            "regulatory_event_amount_3y": event_sum,
            "regulatory_window_covered": event_window_covered,
            "construct_available_at": (
                max(available_values).isoformat() if available_values else None
            ),
            "mdd_evidence_id": (
                f"finlab:etl:adj_close:{code}:{mdd_start.date()}:{mdd_end.date()}"
                if mdd is not None and mdd_start is not None and mdd_end is not None
                else None
            ),
            "debt_evidence_id": (
                f"finlab:fundamental_features:負債比率:{code}:{debt_period}"
                if debt is not None else None
            ),
            "current_evidence_id": (
                f"finlab:fundamental_features:流動比率:{code}:{current_period}"
                if current is not None else None
            ),
            "fcf_evidence_id": (
                f"finlab:fundamental_features:自由現金流量:{code}:{fcf_period}"
                if fcf is not None else None
            ),
            "event_evidence_id": (
                f"finlab:information_violation_cases:裁罰金額萬元:{code}:"
                f"{window_start.date()}:{decision.date()}"
                if event_window_covered else None
            ),
        })

    frame = pd.DataFrame(rows)
    frame["debt_risk"] = _percentile_risk(frame, "debt_ratio")
    frame["current_ratio_risk"] = _percentile_risk(
        frame, "current_ratio", ascending=False
    )
    frame["fcf_risk"] = _percentile_risk(
        frame, "free_cash_flow", ascending=False
    )
    permanent_inputs = ["debt_risk", "current_ratio_risk", "fcf_risk"]
    frame["permanent_capital_loss_vulnerability"] = frame[
        permanent_inputs
    ].mean(axis=1, skipna=True)
    frame.loc[
        frame[permanent_inputs].notna().sum(axis=1) < 2,
        "permanent_capital_loss_vulnerability",
    ] = np.nan
    frame["maximum_drawdown_vulnerability"] = frame["trailing_252d_mdd"]
    frame["material_adverse_event_vulnerability"] = np.nan
    for _, group in frame.loc[frame["regulatory_window_covered"]].groupby(
        "decision_date"
    ):
        positive = group["regulatory_event_amount_3y"] > 0
        frame.loc[group.index, "material_adverse_event_vulnerability"] = 0.0
        if positive.any():
            frame.loc[
                group.index[positive], "material_adverse_event_vulnerability"
            ] = group.loc[positive, "regulatory_event_amount_3y"].rank(
                pct=True, method="average"
            )
    frame["construct_complete"] = frame[[
        "maximum_drawdown_vulnerability",
        "permanent_capital_loss_vulnerability",
        "material_adverse_event_vulnerability",
    ]].notna().all(axis=1)
    complete = frame.loc[frame["construct_complete"]]
    report = {
        "schema_version": "RealPITDownsideConstructInputs.v1",
        "status": "EXECUTED_NON_PUBLISHABLE_LINEAGE_BOUND",
        "publishable": False,
        "formal_T18_status": "BLOCKED_MISSING_RISK_STRESS_AND_BOMB_CONTRACTS",
        "observation_count": int(len(frame)),
        "complete_construct_count": int(len(complete)),
        "complete_construct_coverage": float(len(complete) / len(frame)) if len(frame) else 0,
        "regulatory_source_start": source_start.isoformat(),
        "regulatory_complete_window_count": int(frame["regulatory_window_covered"].sum()),
        "construct_lineage": {
            "maximum_drawdown_vulnerability": "FinLab pre-adjusted total-return close; trailing 252 sessions; minimum 120",
            "permanent_capital_loss_vulnerability": "same-date percentile ranks of PIT-admitted debt ratio, current ratio and free cash flow; at least two inputs",
            "material_adverse_event_vulnerability": "prior-three-year information-violation penalty amount; zero admitted only when source window is complete",
        },
        "missing_contracts": [
            "T18 causal risk register",
            "T18 bear/base/bull stress pack",
            "authoritative current-relevance Bomb event admission",
        ],
    }
    return frame, report


def _evaluation_policy(generation_id: str, source_sha: str) -> CandidatePolicyBundle:
    return CandidatePolicyBundle(
        pillar_weights=PillarWeights(),
        quality_policy=QualityPolicy(
            "winsor_rank", Decimal("0.05"), Decimal("0.95"),
            "PeerOutlookEvidence.peer_ids+issuer_id", 5,
            "average_percentile_rank", "NULL_BLOCKED_NO_FALLBACK",
            (
                QualityBand(Decimal("0"), Decimal("50"), "weak"),
                QualityBand(Decimal("50"), Decimal("60"), "below_average"),
                QualityBand(Decimal("60"), Decimal("70"), "average"),
                QualityBand(Decimal("70"), Decimal("80"), "good"),
                QualityBand(Decimal("80"), Decimal("90"), "strong"),
                QualityBand(Decimal("90"), Decimal("100"), "exceptional"),
            ),
        ),
        upside_bucket_policy=UpsideBucketPolicy(
            12, (24, 36), "decimal_return",
            (Decimal("0"), Decimal("0.10"), Decimal("0.20"), Decimal("0.30")),
            "AuditGateDecision.v1",
        ),
        downside_bucket_policy=DownsideBucketPolicy(
            12,
            DownsideComponentWeights(
                Decimal("0.40"), Decimal("0.35"), Decimal("0.25"), Decimal("1")
            ),
            (Decimal("20"), Decimal("40"), Decimal("60"), Decimal("80")),
            (
                "maximum_drawdown_vulnerability",
                "permanent_capital_loss_vulnerability",
                "material_adverse_event_vulnerability",
            ),
        ),
        anti_double_count_policy=AntiDoubleCountPolicy(
            "1.0.0",
            "AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership",
            "RFC8785_JCS", sha256(b"[]").hexdigest(), (),
        ),
        bomb_policy=BombPolicy(
            (
                "formal_adverse_opinion", "formal_disclaimer", "confirmed_fraud",
                "default", "insolvency", "major_regulatory_action", "other_governed",
            ), True, True, True,
        ),
        champion_id="real-t22-evaluation-candidate",
        challenger_ids=("financial-downside-equal-weight",),
        policy_version="1.0.0",
        publishable=False,
        policy_coverage=Decimal("0"),
        failure_reasons={
            "T19": "same_generation_real_candidate_policy_artifact_unavailable"
        },
        input_producer_shas={
            ticket: source_sha
            for ticket in (
                "T07", "T09", "T10", "T11", "T12", "T13", "T14",
                "T16", "T17", "T18",
            )
        },
        available_at=datetime.now(timezone.utc).isoformat(),
        generation_id=generation_id,
        producer_candidate_sha=source_sha,
    )


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _auc(labels: list[bool], scores: list[Decimal]) -> Decimal | None:
    positive = sum(labels)
    negative = len(labels) - positive
    if not positive or not negative:
        return None
    wins = Decimal("0")
    for left, left_score in zip(labels, scores, strict=True):
        if not left:
            continue
        for right, right_score in zip(labels, scores, strict=True):
            if right:
                continue
            wins += (
                Decimal("1") if left_score > right_score
                else Decimal("0.5") if left_score == right_score
                else Decimal("0")
            )
    return wins / Decimal(positive * negative)


def _observations(
    labels: pd.DataFrame,
    features: pd.DataFrame,
    constructs: pd.DataFrame,
) -> tuple[CandidateObservation, ...]:
    construct_by_key = constructs.set_index(["issuer_id", "decision_date"])
    labels_by_key = labels.set_index(["issuer_id", "decision_date"])
    result: list[CandidateObservation] = []
    for key, group in features.groupby(["issuer_id", "decision_date"], sort=True):
        if key not in construct_by_key.index or key not in labels_by_key.index:
            continue
        construct = construct_by_key.loc[key]
        label = labels_by_key.loc[key]
        if isinstance(construct, pd.DataFrame) or isinstance(label, pd.DataFrame):
            raise ValueError("duplicate issuer decision inputs")
        if not bool(construct["construct_complete"]):
            continue
        metrics: list[AdmittedMetric] = []
        available: list[pd.Timestamp] = []
        for row in group.itertuples(index=False):
            if pd.isna(row.metric_value) or not row.evidence_id or not row.metric_available_at:
                continue
            timestamp = _aware(row.metric_available_at)
            decision = _aware(f"{key[1]}T23:59:59+08:00")
            if timestamp > decision:
                continue
            available.append(timestamp)
            metrics.append(AdmittedMetric(
                pillar=str(row.pillar),
                metric_id=str(row.metric_id),
                evidence_family_id=str(row.evidence_family_id),
                value=_decimal(row.metric_value),
                direction=str(row.direction),
                evidence_ids=(str(row.evidence_id),),
            ))
        if not metrics or not available:
            continue
        result.append(CandidateObservation(
            issuer_id=str(key[0]),
            decision_date=str(key[1]),
            metrics=tuple(metrics),
            upside_decimal=None,
            downside_constructs=(
                _decimal(construct["maximum_drawdown_vulnerability"]),
                _decimal(construct["permanent_capital_loss_vulnerability"]),
                _decimal(construct["material_adverse_event_vulnerability"]),
            ),
            bomb_materiality=Decimal("0"),
            adverse_outcome=bool(label["adverse_outcome"]),
            adverse_event_date=(
                None if pd.isna(label["adverse_event_date"])
                else str(label["adverse_event_date"])
            ),
            fully_observed=bool(label["fully_observed"]),
            stress_period=False,
            survivorship_admitted=True,
            feature_available_at=max(available).isoformat(),
            label_available_at=str(label["label_available_at"]),
            generation_id=str(label["generation_id"]),
        ))
    return tuple(result)


def execute_real_t22_calibration(
    labels: pd.DataFrame,
    features: pd.DataFrame,
    constructs: pd.DataFrame,
    *,
    input_producer_shas: Mapping[str, str | None],
    producer_candidate_sha: str,
):
    generations = set(labels["generation_id"].astype(str))
    if len(generations) != 1:
        raise ValueError("labels must have one generation")
    generation = next(iter(generations))
    policy = _evaluation_policy(generation, producer_candidate_sha)
    observations = _observations(labels, features, constructs)
    rows = build_candidate_score_matrix(
        observations, policy, input_producer_shas=input_producer_shas
    )
    report = build_calibration_validation_report(
        rows, policy,
        total_candidate_count=int(
            labels[["issuer_id", "decision_date"]].drop_duplicates().shape[0]
        ),
        leakage_checks=LeakageChecks(True, True, True, True, True),
        input_producer_shas=input_producer_shas,
        generation_id=generation,
        producer_candidate_sha=producer_candidate_sha,
    )
    failures = dict(report.failure_reasons)
    failures.update({
        "T14": "authoritative_PIT_management_delivery_and_succession_evidence_unavailable",
        "T18": "causal_risk_register_stress_pack_and_bomb_admission_incomplete",
        "stress": "authoritative_stress_period_artifact_unavailable",
    })
    thresholds = replace(
        report.threshold_candidates,
        upside_status="blocked_missing_T17",
        quality_status="diagnostic_only_blocked_T14",
    )
    return replace(
        report,
        champion_verdict="blocked",
        failure_reasons=failures,
        threshold_candidates=thresholds,
    ), rows


def _file_sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--adjusted-close", required=True, type=Path)
    parser.add_argument("--disclosure", required=True, type=Path)
    parser.add_argument("--debt-ratio", required=True, type=Path)
    parser.add_argument("--current-ratio", required=True, type=Path)
    parser.add_argument("--free-cash-flow", required=True, type=Path)
    parser.add_argument("--regulatory-events", required=True, type=Path)
    parser.add_argument("--regulatory-source-start", required=True)
    parser.add_argument("--construct-rows", required=True, type=Path)
    parser.add_argument("--construct-report", required=True, type=Path)
    parser.add_argument("--calibration-output", required=True, type=Path)
    parser.add_argument("--execution-output", required=True, type=Path)
    args = parser.parse_args()

    labels = pd.read_parquet(args.labels)
    features = pd.read_parquet(args.features)
    constructs, construct_report = build_pit_downside_constructs(
        labels,
        pd.read_feather(args.adjusted_close).set_index("date"),
        pd.read_feather(args.disclosure),
        _wide(args.debt_ratio),
        _wide(args.current_ratio),
        _wide(args.free_cash_flow),
        _wide(args.regulatory_events),
        regulatory_source_start=args.regulatory_source_start,
    )
    args.construct_rows.parent.mkdir(parents=True, exist_ok=True)
    constructs.to_parquet(args.construct_rows, index=False)
    args.construct_report.write_text(
        json.dumps(construct_report, ensure_ascii=False, indent=2) + "\n"
    )
    source_sha = _file_sha(Path(__file__))
    feature_sha = _file_sha(args.features)
    input_shas = {
        "T09": feature_sha, "T10": feature_sha, "T13": feature_sha,
        "T14": feature_sha, "T16": feature_sha,
        "T17": None,
        "T18": _file_sha(args.construct_rows),
        "T19": source_sha,
        "T21": _file_sha(args.labels),
    }
    report, rows = execute_real_t22_calibration(
        labels, features, constructs,
        input_producer_shas=input_shas,
        producer_candidate_sha=source_sha,
    )
    calibration_payload = json.loads(json.dumps(asdict(report), default=float))
    args.calibration_output.write_text(
        json.dumps(calibration_payload, ensure_ascii=False, indent=2) + "\n"
    )
    holdout_dates = {
        row.decision_date
        for row in rows
        if any(window.start <= row.decision_date <= window.end for window in report.holdout_windows)
    }
    holdout_rows = [row for row in rows if row.decision_date in holdout_dates]
    holdout_labels = [row.adverse_outcome for row in holdout_rows]
    diagnostic_auc = {
        "quality_adverse_risk": _auc(
            holdout_labels, [row.raw_adverse_risk for row in holdout_rows]
        ),
        "downside_composite": _auc(
            holdout_labels, [row.downside_composite for row in holdout_rows]
        ),
    }
    market_issuers = labels.groupby("market")["issuer_id"].nunique().to_dict()
    stage_results = {
        "T20": {
            "status": "EXECUTED_UPSTREAM",
            "labelled_issuer_counts": {
                str(market): int(count) for market, count in market_issuers.items()
            },
            "note": "counts here are issuers represented in T21 labels, not full T20 cohort membership",
        },
        "T21": {
            "status": "EXECUTED",
            "label_count": int(len(labels)),
            "fully_observed_count": int(labels["fully_observed"].sum()),
            "adverse_fully_observed_count": int(
                (labels["fully_observed"] & labels["adverse_outcome"]).sum()
            ),
            "coverage": float(labels["fully_observed"].mean()),
        },
        "T09_T14": {
            "status": "EXECUTED_WITH_AUTHORITY_GAPS",
            "metric_row_count": int(len(features)),
            "observation_count": int(
                features[["issuer_id", "decision_date"]].drop_duplicates().shape[0]
            ),
        },
        "T18": construct_report,
        "T22": {
            "status": "CALIBRATION_EXECUTED_BLOCKED",
            "candidate_score_row_count": len(rows),
            "champion_verdict": report.champion_verdict,
            "metrics": calibration_payload["metrics"],
            "same_holdout_diagnostic_auc": json.loads(
                json.dumps(diagnostic_auc, default=float)
            ),
            "section_status": {
                "quality_calibration": "diagnostic_only_blocked_T14",
                "downside_calibration": "diagnostic_only_blocked_T18",
                "upside_stars": "blocked_missing_T17",
            },
            "failure_reasons": report.failure_reasons,
        },
    }
    execution = {
        "schema_version": "RealPipelineExecutionReport.v4",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_status": "NON_PUBLISHABLE",
        "publishable": False,
        "rating_disposition": "NO_RATING_NOT_APPLICABLE",
        "t23_started": False,
        "freeze_created": False,
        "rating_created": False,
        "stage_results": stage_results,
        "execution_disposition": "STOP_BEFORE_T23",
    }
    args.execution_output.write_text(
        json.dumps(execution, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(stage_results["T22"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
