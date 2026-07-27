import json
from dataclasses import asdict, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from company_quality.calibration import (
    AdmittedMetric,
    CalibrationError,
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


def sha(char: str) -> str:
    return char * 64


def producer_shas():
    return {
        ticket: sha(str((index % 9) + 1))
        for index, ticket in enumerate(
            ("T09", "T10", "T13", "T14", "T16", "T17", "T18", "T19", "T21")
        )
    }


def leakage_checks():
    return LeakageChecks(True, True, True, True, True)


def policy() -> CandidatePolicyBundle:
    return CandidatePolicyBundle(
        pillar_weights=PillarWeights(),
        quality_policy=QualityPolicy(
            normalisation="winsor_rank",
            winsor_lower_quantile=Decimal("0.05"),
            winsor_upper_quantile=Decimal("0.95"),
            cohort_locator="PeerOutlookEvidence.peer_ids+issuer_id",
            minimum_cohort_size=5,
            tie_method="average_percentile_rank",
            insufficient_cohort_disposition="NULL_BLOCKED_NO_FALLBACK",
            bands=(
                QualityBand(Decimal("0"), Decimal("50"), "weak"),
                QualityBand(Decimal("50"), Decimal("60"), "below_average"),
                QualityBand(Decimal("60"), Decimal("70"), "average"),
                QualityBand(Decimal("70"), Decimal("80"), "good"),
                QualityBand(Decimal("80"), Decimal("90"), "strong"),
                QualityBand(Decimal("90"), Decimal("100"), "exceptional"),
            ),
        ),
        upside_bucket_policy=UpsideBucketPolicy(
            horizon_months=12,
            sensitivity_horizons_months=(24, 36),
            return_unit="decimal_return",
            thresholds=(Decimal("0"), Decimal("0.10"), Decimal("0.20"), Decimal("0.30")),
            audit_gate_contract="AuditGateDecision.v1",
        ),
        downside_bucket_policy=DownsideBucketPolicy(
            horizon_months=12,
            component_weights=DownsideComponentWeights(
                Decimal("0.4"), Decimal("0.35"), Decimal("0.25"), Decimal("1")
            ),
            composite_thresholds=(
                Decimal("20"), Decimal("40"), Decimal("60"), Decimal("80")
            ),
            construct_names=(
                "maximum_drawdown_vulnerability",
                "permanent_capital_loss_vulnerability",
                "material_adverse_event_vulnerability",
            ),
        ),
        anti_double_count_policy=AntiDoubleCountPolicy(
            version="1.0.0",
            evidence_family_policy_locator=(
                "AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership"
            ),
            evidence_family_policy_canonicalization="RFC8785_JCS",
            evidence_family_policy_sha256=sha("a"),
            evidence_family_ownership=(),
        ),
        bomb_policy=BombPolicy(
            allowed_event_types=(
                "formal_adverse_opinion", "formal_disclaimer", "confirmed_fraud",
                "default", "insolvency", "major_regulatory_action", "other_governed",
            ),
            requires_authoritative=True,
            requires_material=True,
            requires_current_relevance=True,
        ),
        champion_id="champion-v1",
        challenger_ids=("challenger-robust-z",),
        policy_version="1.0.0",
        publishable=False,
        policy_coverage=Decimal("1"),
        failure_reasons={},
        input_producer_shas={"T07": sha("1"), "T09": sha("2"), "T10": sha("3"), "T11": sha("4"), "T12": sha("5"), "T13": sha("6"), "T14": sha("7"), "T16": sha("8"), "T17": sha("9"), "T18": sha("a")},
        available_at="2019-01-01T00:00:00+08:00",
        generation_id="r9",
        producer_candidate_sha=sha("b"),
    )


PILLARS = (
    "audit_reliability", "earnings_capital_efficiency",
    "cash_balance_allocation", "business_moat", "governance",
    "people_adaptability",
)


def observations(*, missing_one=False):
    result = []
    for decision in (date(2019, 6, 30), date(2021, 6, 30), date(2022, 6, 30)):
        for index in range(120):
            metrics = []
            for pillar in PILLARS:
                low_good = pillar == "governance"
                value = Decimal(119 - index if low_good else index)
                if missing_one and decision.year == 2022 and index == 119 and pillar == "business_moat":
                    value = None
                metrics.append(AdmittedMetric(
                    pillar=pillar,
                    metric_id=f"{pillar}:metric",
                    evidence_family_id=f"family:{pillar}",
                    value=value,
                    direction="low_good" if low_good else "high_good",
                    evidence_ids=() if value is None else (f"e:{decision}:{index}:{pillar}",),
                ))
            adverse = index < 20
            result.append(CandidateObservation(
                issuer_id=f"issuer-{index:03d}",
                decision_date=decision.isoformat(),
                metrics=tuple(metrics),
                upside_decimal=Decimal(index) / Decimal("100"),
                downside_constructs=(
                    Decimal(119 - index) / Decimal(119),
                    Decimal(119 - index) / Decimal(119),
                    Decimal(119 - index) / Decimal(119),
                ),
                bomb_materiality=Decimal("1") if index == 0 else Decimal("0"),
                adverse_outcome=adverse,
                adverse_event_date=(decision + timedelta(days=100)).isoformat() if adverse else None,
                fully_observed=True,
                stress_period=index < 40,
                survivorship_admitted=True,
                feature_available_at=f"{decision.isoformat()}T00:00:00+08:00",
                label_available_at=f"{(decision + timedelta(days=366)).isoformat()}T00:00:00+08:00",
                generation_id="r9",
            ))
    return result


def test_six_pillar_family_ranks_and_low_good_direction() -> None:
    rows = build_candidate_score_matrix(
        observations(), policy(), input_producer_shas=producer_shas()
    )
    low_quality = next(
        row for row in rows if row.decision_date == "2022-06-30" and row.issuer_id == "issuer-000"
    )
    high_quality = next(
        row for row in rows if row.decision_date == "2022-06-30" and row.issuer_id == "issuer-119"
    )
    assert len(rows) == 360
    assert set(high_quality.pillar_scores) == set(PILLARS)
    assert all(value == Decimal("1") for value in high_quality.pillar_coverages.values())
    assert high_quality.quality_score > low_quality.quality_score
    assert high_quality.raw_adverse_risk < low_quality.raw_adverse_risk
    assert high_quality.pillar_scores["governance"] > low_quality.pillar_scores["governance"]


def test_missing_pillar_does_not_redistribute_weight() -> None:
    rows = build_candidate_score_matrix(
        observations(missing_one=True), policy(), input_producer_shas=producer_shas()
    )
    assert len(rows) == 359
    assert not any(
        row.decision_date == "2022-06-30" and row.issuer_id == "issuer-119"
        for row in rows
    )


def test_missing_metric_is_not_imputed_and_available_metrics_are_reweighted() -> None:
    source = observations()
    expanded = []
    for item in source:
        extra = tuple(
            AdmittedMetric(
                pillar=metric.pillar,
                metric_id=f"{metric.metric_id}:second",
                evidence_family_id=metric.evidence_family_id,
                value=(
                    None
                    if item.decision_date == "2022-06-30"
                    and item.issuer_id == "issuer-119"
                    and metric.pillar == "business_moat"
                    else metric.value
                ),
                direction=metric.direction,
                evidence_ids=(
                    ()
                    if item.decision_date == "2022-06-30"
                    and item.issuer_id == "issuer-119"
                    and metric.pillar == "business_moat"
                    else tuple(f"{value}:second" for value in metric.evidence_ids)
                ),
            )
            for metric in item.metrics
        )
        expanded.append(replace(item, metrics=(*item.metrics, *extra)))

    rows = build_candidate_score_matrix(
        expanded, policy(), input_producer_shas=producer_shas()
    )
    target = next(
        row for row in rows
        if row.decision_date == "2022-06-30" and row.issuer_id == "issuer-119"
    )
    assert len(rows) == 360
    assert target.pillar_coverages["business_moat"] == Decimal("0.5")


def test_expanding_purged_train_only_isotonic_pass_report() -> None:
    rows = build_candidate_score_matrix(
        observations(), policy(), input_producer_shas=producer_shas()
    )
    report = build_calibration_validation_report(
        rows, policy(), total_candidate_count=len(rows),
        leakage_checks=leakage_checks(),
        input_producer_shas=producer_shas(), generation_id="r9",
        producer_candidate_sha=sha("c"),
    )
    assert report.purge_days == 365
    assert report.embargo_days == 30
    assert len(report.train_windows) == 2
    assert len(report.holdout_windows) == 2
    assert report.metrics.auc == Decimal("1")
    assert report.metrics.brier == Decimal("0")
    assert report.metrics.precision_at_top == Decimal("1")
    assert report.champion_verdict == "pass"
    assert report.leakage_checks.pit_join_pass is True
    assert report.leakage_checks.purge_pass is True
    assert report.leakage_checks.embargo_pass is True
    assert report.stability_checks.stress_auc == Decimal("1")
    assert report.error_analysis.false_positives == 0
    assert report.error_analysis.false_negatives == 0
    assert report.error_analysis.mean_adverse_lead_days == Decimal("100")
    assert report.threshold_candidates.bomb_materiality == Decimal("1")
    assert report.challenger_results[0].verdict == "inconclusive"
    assert report.publishable is False


def test_coverage_and_sample_shortfall_block_not_fail() -> None:
    rows = build_candidate_score_matrix(
        observations(), policy(), input_producer_shas=producer_shas()
    )
    report = build_calibration_validation_report(
        rows, policy(), total_candidate_count=500,
        leakage_checks=leakage_checks(),
        input_producer_shas=producer_shas(), generation_id="r9",
        producer_candidate_sha=sha("c"),
    )
    assert report.champion_verdict == "blocked"
    assert report.failure_reasons["coverage"] == "validation_coverage_below_0.85"

    leaked = build_calibration_validation_report(
        rows, policy(), total_candidate_count=len(rows),
        leakage_checks=LeakageChecks(False, True, True, True, True),
        input_producer_shas=producer_shas(), generation_id="r9",
        producer_candidate_sha=sha("c"),
    )
    assert leaked.champion_verdict == "blocked"
    assert leaked.failure_reasons["leakage"] == "one_or_more_leakage_checks_failed"


def test_pit_survivorship_generation_and_sha_fail_closed() -> None:
    source = observations()
    source[0] = replace(source[0], survivorship_admitted=False)
    with pytest.raises(CalibrationError, match="survivorship admission"):
        build_candidate_score_matrix(source, policy(), input_producer_shas=producer_shas())

    source = observations()
    source[0] = replace(source[0], feature_available_at="2019-07-01T00:00:00+08:00")
    with pytest.raises(CalibrationError, match="PIT feature join"):
        build_candidate_score_matrix(source, policy(), input_producer_shas=producer_shas())

    bad_shas = producer_shas()
    bad_shas.pop("T21")
    with pytest.raises(CalibrationError, match="exact T09..T21"):
        build_candidate_score_matrix(observations(), policy(), input_producer_shas=bad_shas)


def test_closed_schema_accepts_report_and_rejects_publication_field() -> None:
    rows = build_candidate_score_matrix(
        observations(), policy(), input_producer_shas=producer_shas()
    )
    report = build_calibration_validation_report(
        rows, policy(), total_candidate_count=len(rows),
        leakage_checks=leakage_checks(),
        input_producer_shas=producer_shas(), generation_id="r9",
        producer_candidate_sha=sha("c"),
    )
    schema_path = (
        Path(__file__).parents[2]
        / "src/company_quality/calibration/contracts/CalibrationValidationReport.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(report), default=float))
    validator.validate(payload)
    payload["final_rating"] = "A"
    assert next(validator.iter_errors(payload)).validator == "additionalProperties"
