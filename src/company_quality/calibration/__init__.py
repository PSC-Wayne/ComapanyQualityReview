"""PIT candidate score matrix and non-publishable temporal calibration report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import re
from typing import Literal, Mapping, Sequence

from company_quality.policies.candidate import CandidatePolicyBundle


class CalibrationError(RuntimeError):
    pass


Pillar = Literal[
    "audit_reliability", "earnings_capital_efficiency",
    "cash_balance_allocation", "business_moat", "governance",
    "people_adaptability",
]
Direction = Literal["high_good", "low_good"]
_PILLARS: tuple[Pillar, ...] = (
    "audit_reliability", "earnings_capital_efficiency",
    "cash_balance_allocation", "business_moat", "governance",
    "people_adaptability",
)
_REQUIRED_SHAS = {
    "T09", "T10", "T13", "T14", "T16", "T17", "T18", "T19", "T21"
}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_Q = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class AdmittedMetric:
    pillar: Pillar
    metric_id: str
    evidence_family_id: str
    value: Decimal | None
    direction: Direction
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateObservation:
    issuer_id: str
    decision_date: str
    metrics: tuple[AdmittedMetric, ...]
    upside_decimal: Decimal | None
    downside_constructs: tuple[Decimal, Decimal, Decimal]
    bomb_materiality: Decimal
    adverse_outcome: bool
    adverse_event_date: str | None
    fully_observed: bool
    stress_period: bool
    survivorship_admitted: bool
    feature_available_at: str
    label_available_at: str
    generation_id: str


@dataclass(frozen=True, slots=True)
class CandidateScoreRow:
    issuer_id: str
    decision_date: str
    pillar_scores: dict[str, Decimal]
    pillar_coverages: dict[str, Decimal]
    quality_score: Decimal
    raw_adverse_risk: Decimal
    upside_decimal: Decimal | None
    downside_composite: Decimal
    bomb_materiality: Decimal
    adverse_outcome: bool
    adverse_event_date: str | None
    fully_observed: bool
    stress_period: bool
    generation_id: str


@dataclass(frozen=True, slots=True)
class Window:
    start: str
    end: str
    issuer_count: int


@dataclass(frozen=True, slots=True)
class Metrics:
    auc: Decimal | None
    brier: Decimal | None
    calibration_error: Decimal | None
    precision_at_top: Decimal | None


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    bucket: str
    predicted: Decimal
    observed: Decimal
    count: int


@dataclass(frozen=True, slots=True)
class ChallengerResult:
    challenger_id: str
    metrics_hash: str
    verdict: Literal["better", "worse", "inconclusive"]


@dataclass(frozen=True, slots=True)
class ThresholdCandidates:
    quality_bands: tuple[Decimal, ...]
    upside_stars: tuple[Decimal, Decimal, Decimal, Decimal]
    downside_faces: tuple[Decimal, Decimal, Decimal, Decimal]
    bomb_materiality: Decimal
    upside_status: Literal["evaluated", "blocked_missing_T17"] = "evaluated"
    quality_status: Literal["evaluated", "diagnostic_only_blocked_T14"] = "evaluated"


@dataclass(frozen=True, slots=True)
class LeakageChecks:
    pit_join_pass: bool
    purge_pass: bool
    embargo_pass: bool
    survivorship_pass: bool
    same_generation_pass: bool


@dataclass(frozen=True, slots=True)
class ErrorAnalysis:
    false_positives: int
    false_negatives: int
    false_signal_rate: Decimal | None
    mean_adverse_lead_days: Decimal | None


@dataclass(frozen=True, slots=True)
class StabilityChecks:
    calibration_monotonic: bool
    stress_auc: Decimal | None
    stress_period_count: int


@dataclass(frozen=True, slots=True)
class CalibrationValidationReport:
    policy_version: str
    train_windows: tuple[Window, ...]
    holdout_windows: tuple[Window, ...]
    purge_days: Literal[365]
    embargo_days: Literal[30]
    metrics: Metrics
    calibration_curves: tuple[CalibrationBucket, ...]
    champion_verdict: Literal["pass", "fail", "blocked"]
    challenger_results: tuple[ChallengerResult, ...]
    threshold_candidates: ThresholdCandidates
    leakage_checks: LeakageChecks
    error_analysis: ErrorAnalysis
    stability_checks: StabilityChecks
    validation_coverage: Decimal
    failure_reasons: dict[str, str]
    input_producer_shas: dict[str, str | None]
    generation_id: str
    producer_candidate_sha: str
    publishable: Literal[False] = False
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["CalibrationValidationReport.v1"] = (
        "CalibrationValidationReport.v1"
    )
    source_version: Literal[
        "T09+T10+T13+T14+T16+T17+T18+CandidatePolicyBundle.v1+OutcomeLabelSet.v1"
    ] = "T09+T10+T13+T14+T16+T17+T18+CandidatePolicyBundle.v1+OutcomeLabelSet.v1"
    formula_version: Literal["winsor-family-rank-expanding-isotonic.v1"] = (
        "winsor-family-rank-expanding-isotonic.v1"
    )
    model_version: Literal["train-only-pava-adverse-risk.v1"] = (
        "train-only-pava-adverse-risk.v1"
    )


def _day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CalibrationError(f"invalid {field}") from exc


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CalibrationError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise CalibrationError(f"{field} must be timezone-aware")
    return result


def _quantile(values: Sequence[Decimal], q: Decimal) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise CalibrationError("empty quantile input")
    position = q * Decimal(len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - Decimal(low)
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def _valid_input_shas(
    values: Mapping[str, str | None], *, allow_missing_t17: bool
) -> bool:
    if set(values) != _REQUIRED_SHAS:
        return False
    return all(
        (key == "T17" and value is None and allow_missing_t17)
        or (isinstance(value, str) and _SHA.fullmatch(value) is not None)
        for key, value in values.items()
    )


def _rank(values: Mapping[str, Decimal], low_q: Decimal, high_q: Decimal) -> dict[str, Decimal]:
    lower = _quantile(tuple(values.values()), low_q)
    upper = _quantile(tuple(values.values()), high_q)
    clipped = {key: min(max(value, lower), upper) for key, value in values.items()}
    ordered = sorted(clipped.values())
    result: dict[str, Decimal] = {}
    for key, value in clipped.items():
        positions = [index for index, item in enumerate(ordered) if item == value]
        average = Decimal(sum(positions)) / Decimal(len(positions))
        result[key] = (
            Decimal("0.5") if len(ordered) == 1
            else average / Decimal(len(ordered) - 1)
        )
    return result


def build_candidate_score_matrix(
    observations: Sequence[CandidateObservation],
    policy: CandidatePolicyBundle,
    *,
    input_producer_shas: Mapping[str, str | None],
) -> tuple[CandidateScoreRow, ...]:
    if policy.schema_version != "CandidatePolicyBundle.v1":
        raise CalibrationError("BLOCKED_CONTRACT: T19 schema mismatch")
    if not _valid_input_shas(
        input_producer_shas,
        allow_missing_t17=all(item.upside_decimal is None for item in observations),
    ):
        raise CalibrationError("BLOCKED_CONTRACT: exact T09..T21 producer SHAs required")
    if not observations:
        raise CalibrationError("candidate observations required")
    generations = {item.generation_id for item in observations}
    if len(generations) != 1 or next(iter(generations)) != policy.generation_id:
        raise CalibrationError("same-generation binding failed")
    keys = {(item.decision_date, item.issuer_id) for item in observations}
    if len(keys) != len(observations):
        raise CalibrationError("duplicate issuer decision observation")
    for item in observations:
        decision = _day(item.decision_date, "decision_date")
        feature_at = _instant(item.feature_available_at, "feature_available_at")
        label_at = _instant(item.label_available_at, "label_available_at")
        if feature_at.date() > decision:
            raise CalibrationError("PIT feature join failed")
        if label_at < feature_at:
            raise CalibrationError("label availability precedes feature availability")
        if not item.survivorship_admitted:
            raise CalibrationError("survivorship admission failed")

    by_date = {item.decision_date for item in observations}
    scores: dict[tuple[str, str, str], Decimal] = {}
    coverages: dict[tuple[str, str, str], Decimal] = {}
    for decision in by_date:
        cohort = [item for item in observations if item.decision_date == decision]
        if len(cohort) < policy.quality_policy.minimum_cohort_size:
            raise CalibrationError("insufficient same-date cohort for winsor rank")
        expected_by_pillar: dict[str, set[tuple[str, str]]] = {name: set() for name in _PILLARS}
        for item in cohort:
            seen: set[tuple[str, str]] = set()
            for metric in item.metrics:
                identity = (metric.pillar, metric.metric_id)
                if identity in seen:
                    raise CalibrationError("duplicate metric per observation")
                seen.add(identity)
                if not metric.metric_id or not metric.evidence_family_id:
                    raise CalibrationError("metric identity/family required")
                if metric.value is not None and not metric.evidence_ids:
                    raise CalibrationError("present metric requires evidence")
                expected_by_pillar[metric.pillar].add(
                    (metric.metric_id, metric.evidence_family_id)
                )
        for pillar in _PILLARS:
            expected = expected_by_pillar[pillar]
            if not expected:
                raise CalibrationError(f"missing expected metrics for pillar {pillar}")
            metric_ids = {metric_id for metric_id, _ in expected}
            for metric_id in metric_ids:
                available_values: dict[str, Decimal] = {}
                directions: set[str] = set()
                for item in cohort:
                    matches = [
                        metric for metric in item.metrics
                        if metric.pillar == pillar and metric.metric_id == metric_id
                    ]
                    if len(matches) != 1:
                        continue
                    metric = matches[0]
                    directions.add(metric.direction)
                    if metric.value is not None:
                        available_values[item.issuer_id] = metric.value
                if len(directions) != 1:
                    raise CalibrationError("metric direction conflict")
                if len(available_values) < policy.quality_policy.minimum_cohort_size:
                    continue
                ranks = _rank(
                    available_values,
                    policy.quality_policy.winsor_lower_quantile,
                    policy.quality_policy.winsor_upper_quantile,
                )
                invert = next(iter(directions)) == "low_good"
                for issuer, value in ranks.items():
                    scores[(decision, issuer, f"{pillar}:{metric_id}")] = (
                        Decimal("1") - value if invert else value
                    )

            for item in cohort:
                present = {
                    metric_id: scores[(decision, item.issuer_id, f"{pillar}:{metric_id}")]
                    for metric_id in metric_ids
                    if (decision, item.issuer_id, f"{pillar}:{metric_id}") in scores
                }
                coverage = Decimal(len(present)) / Decimal(len(metric_ids))
                coverages[(decision, item.issuer_id, pillar)] = coverage
                if present:
                    scores[(decision, item.issuer_id, pillar)] = (
                        sum(present.values()) / Decimal(len(present))
                    )

    weights = policy.pillar_weights
    weight_map = {
        "audit_reliability": weights.audit_reliability,
        "earnings_capital_efficiency": weights.earnings_capital_efficiency,
        "cash_balance_allocation": weights.cash_balance_allocation,
        "business_moat": weights.business_moat,
        "governance": weights.governance,
        "people_adaptability": weights.people_adaptability,
    }
    downside_weights = policy.downside_bucket_policy.component_weights
    rows: list[CandidateScoreRow] = []
    for item in observations:
        pillar_values = {
            pillar: scores[(item.decision_date, item.issuer_id, pillar)]
            for pillar in _PILLARS
            if (item.decision_date, item.issuer_id, pillar) in scores
        }
        if len(pillar_values) != len(_PILLARS):
            continue
        if not all(Decimal("0") <= value <= Decimal("1") for value in item.downside_constructs):
            raise CalibrationError("downside constructs must be normalised 0..1")
        if not Decimal("0") <= item.bomb_materiality <= Decimal("1"):
            raise CalibrationError("bomb materiality outside 0..1")
        quality = sum(
            pillar_values[pillar] * weight_map[pillar] for pillar in _PILLARS
        ) * Decimal("100")
        downside = (
            item.downside_constructs[0] * downside_weights.maximum_drawdown_vulnerability
            + item.downside_constructs[1] * downside_weights.permanent_capital_loss_vulnerability
            + item.downside_constructs[2] * downside_weights.material_adverse_event_vulnerability
        ) * Decimal("100")
        rows.append(CandidateScoreRow(
            issuer_id=item.issuer_id,
            decision_date=item.decision_date,
            pillar_scores={key: value * Decimal("100") for key, value in pillar_values.items()},
            pillar_coverages={
                key: coverages[(item.decision_date, item.issuer_id, key)]
                for key in _PILLARS
            },
            quality_score=quality,
            raw_adverse_risk=Decimal("1") - quality / Decimal("100"),
            upside_decimal=item.upside_decimal,
            downside_composite=downside,
            bomb_materiality=item.bomb_materiality,
            adverse_outcome=item.adverse_outcome,
            adverse_event_date=item.adverse_event_date,
            fully_observed=item.fully_observed,
            stress_period=item.stress_period,
            generation_id=item.generation_id,
        ))
    if not rows:
        raise CalibrationError("no fully covered six-pillar candidate rows")
    return tuple(sorted(rows, key=lambda row: (row.decision_date, row.issuer_id)))


def _fit_isotonic(rows: Sequence[CandidateScoreRow]) -> tuple[tuple[Decimal, Decimal], ...]:
    grouped: list[list[Decimal | int]] = []
    by_score: dict[Decimal, list[CandidateScoreRow]] = {}
    for row in rows:
        by_score.setdefault(row.raw_adverse_risk, []).append(row)
    for score in sorted(by_score):
        tied = by_score[score]
        grouped.append([score, score, sum(int(row.adverse_outcome) for row in tied), len(tied)])
        while len(grouped) >= 2:
            left = Decimal(int(grouped[-2][2])) / Decimal(int(grouped[-2][3]))
            right = Decimal(int(grouped[-1][2])) / Decimal(int(grouped[-1][3]))
            if left <= right:
                break
            second = grouped.pop()
            first = grouped.pop()
            grouped.append([
                first[0], second[1], int(first[2]) + int(second[2]),
                int(first[3]) + int(second[3]),
            ])
    fitted: list[tuple[Decimal, Decimal]] = []
    for lower, upper, positives, count in grouped:
        fitted.append((Decimal(str(upper)), Decimal(int(positives)) / Decimal(int(count))))
    return tuple(fitted)


def _predict(model: Sequence[tuple[Decimal, Decimal]], value: Decimal) -> Decimal:
    for upper, probability in model:
        if value <= upper:
            return probability
    return model[-1][1]


def _auc(actual: Sequence[bool], predicted: Sequence[Decimal]) -> Decimal | None:
    positives = [index for index, value in enumerate(actual) if value]
    negatives = [index for index, value in enumerate(actual) if not value]
    if not positives or not negatives:
        return None
    credit = Decimal("0")
    for positive in positives:
        for negative in negatives:
            if predicted[positive] > predicted[negative]:
                credit += 1
            elif predicted[positive] == predicted[negative]:
                credit += Decimal("0.5")
    return credit / Decimal(len(positives) * len(negatives))


def _metrics(
    rows: Sequence[CandidateScoreRow], predictions: Sequence[Decimal]
) -> tuple[Metrics, tuple[CalibrationBucket, ...], ErrorAnalysis, StabilityChecks]:
    actual = [row.adverse_outcome for row in rows]
    count = len(rows)
    brier = sum(
        (prediction - Decimal(int(outcome))) ** 2
        for prediction, outcome in zip(predictions, actual)
    ) / Decimal(count)
    buckets: list[CalibrationBucket] = []
    for number in range(10):
        lower = Decimal(number) / Decimal("10")
        upper = Decimal(number + 1) / Decimal("10")
        indices = [
            index for index, value in enumerate(predictions)
            if lower <= value < upper or (number == 9 and value == 1)
        ]
        if not indices:
            continue
        buckets.append(CalibrationBucket(
            bucket=f"{number * 10:02d}-{(number + 1) * 10:02d}%",
            predicted=sum(predictions[index] for index in indices) / Decimal(len(indices)),
            observed=sum(Decimal(int(actual[index])) for index in indices) / Decimal(len(indices)),
            count=len(indices),
        ))
    calibration_error = sum(
        abs(bucket.predicted - bucket.observed) * Decimal(bucket.count)
        for bucket in buckets
    ) / Decimal(count)
    top_count = max(1, (count + 9) // 10)
    top_indices = sorted(range(count), key=lambda index: predictions[index], reverse=True)[:top_count]
    precision_top = sum(Decimal(int(actual[index])) for index in top_indices) / Decimal(top_count)
    predicted_positive = [value >= Decimal("0.5") for value in predictions]
    fp = sum(1 for prediction, outcome in zip(predicted_positive, actual) if prediction and not outcome)
    fn = sum(1 for prediction, outcome in zip(predicted_positive, actual) if not prediction and outcome)
    positives_called = sum(predicted_positive)
    lead_days = [
        (_day(row.adverse_event_date or "", "adverse_event_date") - _day(row.decision_date, "decision_date")).days
        for row, prediction in zip(rows, predicted_positive)
        if prediction and row.adverse_outcome and row.adverse_event_date is not None
    ]
    monotonic = all(
        buckets[index].observed <= buckets[index + 1].observed
        for index in range(len(buckets) - 1)
    )
    stress_indices = [index for index, row in enumerate(rows) if row.stress_period]
    stress_auc = _auc(
        [actual[index] for index in stress_indices],
        [predictions[index] for index in stress_indices],
    ) if stress_indices else None
    return (
        Metrics(_auc(actual, predictions), brier, calibration_error, precision_top),
        tuple(buckets),
        ErrorAnalysis(
            fp, fn,
            Decimal(fp) / Decimal(positives_called) if positives_called else None,
            Decimal(sum(lead_days)) / Decimal(len(lead_days)) if lead_days else None,
        ),
        StabilityChecks(monotonic, stress_auc, len(stress_indices)),
    )


def build_calibration_validation_report(
    rows: Sequence[CandidateScoreRow],
    policy: CandidatePolicyBundle,
    *,
    total_candidate_count: int,
    leakage_checks: LeakageChecks,
    input_producer_shas: Mapping[str, str | None],
    generation_id: str,
    producer_candidate_sha: str,
) -> CalibrationValidationReport:
    if not _SEMVER.fullmatch(policy.policy_version):
        raise CalibrationError("policy_version must be semver")
    if policy.publishable:
        raise CalibrationError("T19 candidate policy must be non-publishable")
    if not _valid_input_shas(
        input_producer_shas,
        allow_missing_t17=all(row.upside_decimal is None for row in rows),
    ):
        raise CalibrationError("BLOCKED_CONTRACT: exact producer SHAs required")
    if not generation_id or not _SHA.fullmatch(producer_candidate_sha):
        raise CalibrationError("generation and producer SHA required")
    if generation_id != policy.generation_id:
        raise CalibrationError("policy generation mismatch")
    if any(row.generation_id != generation_id for row in rows):
        raise CalibrationError("same-generation row binding failed")
    if total_candidate_count < len(rows) or total_candidate_count <= 0:
        raise CalibrationError("invalid total candidate count")
    observed = [row for row in rows if row.fully_observed]
    years = sorted({_day(row.decision_date, "decision_date").year for row in observed})
    train_windows: list[Window] = []
    holdout_windows: list[Window] = []
    holdout_rows: list[CandidateScoreRow] = []
    predictions: list[Decimal] = []
    purge_pass = True
    embargo_pass = True
    for year in years[1:]:
        holdout = [row for row in observed if _day(row.decision_date, "decision_date").year == year]
        if not holdout:
            continue
        holdout_start = date(year, 1, 1)
        train_cutoff = holdout_start - timedelta(days=365)
        train = [row for row in observed if _day(row.decision_date, "decision_date") < train_cutoff]
        if not train:
            continue
        model = _fit_isotonic(train)
        holdout_rows.extend(holdout)
        predictions.extend(_predict(model, row.raw_adverse_risk) for row in holdout)
        train_windows.append(Window(
            min(row.decision_date for row in train),
            max(row.decision_date for row in train), len({row.issuer_id for row in train}),
        ))
        holdout_windows.append(Window(
            min(row.decision_date for row in holdout),
            max(row.decision_date for row in holdout), len({row.issuer_id for row in holdout}),
        ))
        purge_pass = purge_pass and all(
            _day(row.decision_date, "train decision") < train_cutoff for row in train
        )
        if len(holdout_windows) > 1:
            previous_end = _day(holdout_windows[-2].end, "previous holdout end")
            embargo_end = previous_end + timedelta(days=30)
            embargo_pass = embargo_pass and not any(
                previous_end < _day(row.decision_date, "train decision") <= embargo_end
                for row in train
            )
    if not holdout_rows:
        raise CalibrationError("insufficient temporal history for holdout")
    metrics, curves, error_analysis, stability = _metrics(holdout_rows, predictions)
    leakage = LeakageChecks(
        leakage_checks.pit_join_pass,
        leakage_checks.purge_pass and purge_pass,
        leakage_checks.embargo_pass and embargo_pass,
        leakage_checks.survivorship_pass,
        leakage_checks.same_generation_pass,
    )
    coverage = Decimal(len(observed)) / Decimal(total_candidate_count)
    failures: dict[str, str] = {}
    final_year = max(_day(row.decision_date, "holdout decision").year for row in holdout_rows)
    final_holdout = [
        row for row in holdout_rows
        if _day(row.decision_date, "holdout decision").year == final_year
    ]
    adverse_count = sum(row.adverse_outcome for row in final_holdout)
    holdout_issuer_count = len({row.issuer_id for row in final_holdout})
    pooled_adverse_count = sum(row.adverse_outcome for row in holdout_rows)
    prevalence = Decimal(pooled_adverse_count) / Decimal(len(holdout_rows))
    naive_brier = prevalence * (Decimal("1") - prevalence)
    top_lift_pass = (
        metrics.precision_at_top is not None
        and (prevalence == 0 or metrics.precision_at_top >= prevalence * Decimal("2"))
    )
    leakage_pass = all((
        leakage.pit_join_pass, leakage.purge_pass, leakage.embargo_pass,
        leakage.survivorship_pass, leakage.same_generation_pass,
    ))
    sample_pass = holdout_issuer_count >= 100 and adverse_count >= 10
    stress_available = stability.stress_auc is not None
    if not leakage_pass:
        failures["leakage"] = "one_or_more_leakage_checks_failed"
    if not sample_pass:
        failures["sample"] = "final_holdout_requires_100_issuers_and_10_adverse_events"
    if coverage < Decimal("0.85"):
        failures["coverage"] = "validation_coverage_below_0.85"
    if policy.failure_reasons or policy.policy_coverage < Decimal("1"):
        failures["policy"] = "candidate_policy_incomplete"
    if not stress_available:
        failures["stress"] = "stress_auc_unavailable"
    blocked = bool(failures)
    performance_pass = all((
        metrics.auc is not None and metrics.auc >= Decimal("0.65"),
        metrics.brier is not None and metrics.brier < naive_brier,
        metrics.calibration_error is not None
        and metrics.calibration_error <= Decimal("0.10"),
        top_lift_pass,
        stability.calibration_monotonic,
        stability.stress_auc is not None and stability.stress_auc >= Decimal("0.60"),
    ))
    verdict: Literal["pass", "fail", "blocked"] = (
        "blocked" if blocked else ("pass" if performance_pass else "fail")
    )
    quality_thresholds = tuple(band.lower for band in policy.quality_policy.bands)
    challenger_results = tuple(
        ChallengerResult(
            challenger_id=challenger,
            metrics_hash=sha256(json.dumps({
                "challenger_id": challenger,
                "status": "unconfigured_candidate",
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            verdict="inconclusive",
        )
        for challenger in policy.challenger_ids
    )
    return CalibrationValidationReport(
        policy_version=policy.policy_version,
        train_windows=tuple(train_windows),
        holdout_windows=tuple(holdout_windows),
        purge_days=365,
        embargo_days=30,
        metrics=metrics,
        calibration_curves=curves,
        champion_verdict=verdict,
        challenger_results=challenger_results,
        threshold_candidates=ThresholdCandidates(
            quality_bands=quality_thresholds,
            upside_stars=policy.upside_bucket_policy.thresholds,
            downside_faces=policy.downside_bucket_policy.composite_thresholds,
            bomb_materiality=Decimal("1"),
        ),
        leakage_checks=leakage,
        error_analysis=error_analysis,
        stability_checks=stability,
        validation_coverage=coverage,
        failure_reasons=failures,
        input_producer_shas=dict(sorted(input_producer_shas.items())),
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
    )


__all__ = [
    "AdmittedMetric", "CalibrationError", "CalibrationValidationReport",
    "CandidateObservation", "CandidateScoreRow", "LeakageChecks",
    "build_candidate_score_matrix",
    "build_calibration_validation_report",
]
