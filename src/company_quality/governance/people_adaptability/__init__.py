"""Governance, people and adaptability candidate from PIT-admitted facts."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Mapping, Sequence

from company_quality.facts.financial import CanonicalFinancialFacts
from company_quality.pit import AdmittedFactSet, FactAdmission

_ROLE = {"chair", "ceo", "cfo", "other_key"}
_DEPENDENCY = {"low", "medium", "high", "unknown"}
_PERCENT_TYPES = {
    "governance.board_independence_pct": "board_independence_pct",
    "governance.pledged_share_pct": "pledged_share_pct",
    "governance.related_party_ratio": "related_party_ratio",
}


class GovernancePeopleError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GovernanceSignals:
    board_independence_pct: Decimal | None
    pledged_share_pct: Decimal | None
    related_party_ratio: Decimal | None
    regulatory_events_5y: int | None


@dataclass(frozen=True, slots=True)
class KeyPerson:
    role: Literal["chair", "ceo", "cfo", "other_key"]
    tenure_years: Decimal | None
    evidence_id: str


@dataclass(frozen=True, slots=True)
class Succession:
    plan_disclosed: bool | None
    key_person_dependency: Literal["low", "medium", "high", "unknown"]
    evidence_id: str | None


@dataclass(frozen=True, slots=True)
class Adaptability:
    rd_to_sales: Decimal | None
    capability_investments: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CommitmentDelivery:
    commitment_id: str
    commitment: str
    commitment_evidence_id: str
    deliveries: tuple[str, ...]
    delivery_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualitativeSignal:
    statement: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class ExcludedClaim:
    evidence_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class GovernancePeopleCandidate:
    governance_signals: GovernanceSignals
    key_people: tuple[KeyPerson, ...]
    succession: Succession
    alignment_signals: tuple[QualitativeSignal, ...]
    adaptability: Adaptability
    commitment_delivery_ledger: tuple[CommitmentDelivery, ...]
    excluded_claims: tuple[ExcludedClaim, ...]
    evidence_family_ids: tuple[str, ...]
    metric_lineage: dict[str, tuple[str, ...]]
    unavailable_reasons: dict[str, str]
    coverage: Decimal
    confidence: Decimal
    candidate_score: None
    available_at: str | None
    generation_id: str
    producer_candidate_sha: str
    status: Literal["NON_PUBLISHABLE_CANDIDATE"] = "NON_PUBLISHABLE_CANDIDATE"
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["GovernancePeopleCandidate.v1"] = (
        "GovernancePeopleCandidate.v1"
    )
    source_version: Literal["AdmittedFactSet.v1+CanonicalFinancialFacts.v1"] = (
        "AdmittedFactSet.v1+CanonicalFinancialFacts.v1"
    )
    formula_version: Literal["governance-people-raw-candidate.v1"] = (
        "governance-people-raw-candidate.v1"
    )
    model_version: Literal["governance-people-candidate-1.0.0"] = (
        "governance-people-candidate-1.0.0"
    )


def _instant(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise GovernancePeopleError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GovernancePeopleError(f"{field} must be timezone-aware")
    return parsed


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _value_fingerprint(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), _value_fingerprint(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_value_fingerprint(item) for item in value)
    return repr(value)


def _latest(facts: Sequence[FactAdmission], fact_type: str) -> FactAdmission | None:
    selected = [fact for fact in facts if fact.fact_type == fact_type]
    if not selected:
        return None
    latest_time = max(_instant(fact.effective_at or "", "fact effective_at") for fact in selected)
    latest = [fact for fact in selected if _instant(fact.effective_at or "", "fact effective_at") == latest_time]
    values = {_value_fingerprint(fact.value) for fact in latest}
    if len(values) != 1:
        raise GovernancePeopleError(f"conflicting latest {fact_type} facts")
    return min(latest, key=lambda fact: fact.fact_id)


def _financial_value(financials: CanonicalFinancialFacts, concept: str):
    matches = [fact for fact in financials.facts if fact.concept_id == concept]
    if len(matches) > 1:
        raise GovernancePeopleError(f"duplicate canonical concept: {concept}")
    return matches[0] if matches else None


def build_governance_people_candidate(
    admitted: AdmittedFactSet,
    financials: CanonicalFinancialFacts,
    *,
    generation_id: str,
    producer_candidate_sha: str,
) -> GovernancePeopleCandidate:
    if admitted.schema_version != "AdmittedFactSet.v1":
        raise GovernancePeopleError("expected AdmittedFactSet.v1")
    if financials.schema_version != "CanonicalFinancialFacts.v1":
        raise GovernancePeopleError("expected CanonicalFinancialFacts.v1")
    if not generation_id.strip() or len(generation_id) > 128:
        raise GovernancePeopleError("invalid generation_id")
    if len(producer_candidate_sha) != 40 or any(c not in "0123456789abcdef" for c in producer_candidate_sha):
        raise GovernancePeopleError("invalid producer_candidate_sha")
    decision = _instant(admitted.decision_time, "decision_time")
    admitted_facts = tuple(fact for fact in admitted.facts if fact.disposition == "admitted")
    excluded: list[ExcludedClaim] = []
    lineage: dict[str, tuple[str, ...]] = {}
    reasons: dict[str, str] = {}

    percentages: dict[str, Decimal | None] = {}
    for fact_type, output_name in _PERCENT_TYPES.items():
        fact = _latest(admitted_facts, fact_type)
        value = _decimal(fact.value) if fact else None
        if value is not None and not Decimal("0") <= value <= Decimal("100"):
            excluded.append(ExcludedClaim(fact.fact_id, "percentage_outside_0_100"))
            value = None
        percentages[output_name] = value
        if fact and value is not None:
            lineage[output_name] = (fact.fact_id,)
        else:
            reasons[output_name] = "missing_verified_governance_fact"

    try:
        five_year_cutoff = decision.replace(year=decision.year - 5)
    except ValueError:
        five_year_cutoff = decision.replace(year=decision.year - 5, day=calendar.monthrange(decision.year - 5, decision.month)[1])
    regulatory = tuple(
        fact for fact in admitted_facts
        if fact.fact_type == "governance.regulatory_event"
        and five_year_cutoff <= _instant(fact.effective_at or "", "regulatory effective_at") <= decision
    )
    regulatory_complete = _latest(
        admitted_facts, "governance.regulatory_history_complete"
    )
    regulatory_count = (
        len(regulatory)
        if regulatory_complete is not None and regulatory_complete.value is True
        else None
    )
    lineage["regulatory_events_5y"] = tuple(
        sorted(
            [fact.fact_id for fact in regulatory]
            + ([regulatory_complete.fact_id] if regulatory_complete else [])
        )
    )
    if regulatory_count is None:
        reasons["regulatory_events_5y"] = (
            "regulatory_history_completeness_unverified"
        )

    alignment_signals: list[QualitativeSignal] = []
    for fact in admitted_facts:
        if fact.fact_type != "governance.incentive_alignment":
            continue
        statement = fact.value if isinstance(fact.value, str) else None
        if statement is None or not statement.strip() or len(statement.strip()) > 512:
            excluded.append(
                ExcludedClaim(fact.fact_id, "invalid_incentive_alignment_claim")
            )
            continue
        alignment_signals.append(QualitativeSignal(statement.strip(), fact.fact_id))
    alignment_signals.sort(key=lambda item: item.evidence_id)
    lineage["alignment_signals"] = tuple(
        item.evidence_id for item in alignment_signals
    )

    people: list[KeyPerson] = []
    for fact in admitted_facts:
        if fact.fact_type != "people.key_person":
            continue
        value = _mapping(fact.value)
        role = value.get("role") if value else None
        tenure = _decimal(value.get("tenure_years")) if value else None
        if role not in _ROLE or (tenure is not None and not Decimal("0") <= tenure <= Decimal("100")):
            excluded.append(ExcludedClaim(fact.fact_id, "invalid_key_person_claim"))
            continue
        people.append(KeyPerson(role, tenure, fact.fact_id))
    people.sort(key=lambda item: (item.role, item.evidence_id))
    if len(people) > 32:
        raise GovernancePeopleError("key people exceed the 32-item limit")
    if not people:
        reasons["key_people"] = "missing_verified_key_people"

    plan_fact = _latest(admitted_facts, "succession.plan_disclosed")
    dependency_fact = _latest(admitted_facts, "succession.key_person_dependency")
    plan = plan_fact.value if plan_fact and isinstance(plan_fact.value, bool) else None
    dependency = dependency_fact.value if dependency_fact and dependency_fact.value in _DEPENDENCY else "unknown"
    succession_ids = tuple(
        fact.fact_id
        for fact, valid in (
            (plan_fact, plan is not None),
            (dependency_fact, dependency != "unknown"),
        )
        if fact is not None and valid
    )
    if plan is None:
        reasons["succession.plan_disclosed"] = "missing_verified_succession_disclosure"
        if plan_fact is not None:
            excluded.append(ExcludedClaim(plan_fact.fact_id, "invalid_succession_plan"))
    if dependency == "unknown":
        reasons["succession.key_person_dependency"] = "dependency_unknown"
        if dependency_fact is not None:
            excluded.append(
                ExcludedClaim(dependency_fact.fact_id, "invalid_dependency_claim")
            )

    investments: list[str] = []
    investment_ids: list[str] = []
    for fact in admitted_facts:
        if fact.fact_type != "adaptability.capability_investment":
            continue
        if not isinstance(fact.value, str) or not fact.value.strip() or len(fact.value.strip()) > 256:
            excluded.append(ExcludedClaim(fact.fact_id, "invalid_capability_investment"))
            continue
        investments.append(fact.value.strip())
        investment_ids.append(fact.fact_id)
    if len(investments) > 32:
        raise GovernancePeopleError("capability investments exceed the 32-item limit")

    rd_fact = _latest(admitted_facts, "adaptability.rd_expense")
    revenue_fact = _financial_value(financials, "income.revenue")
    rd_to_sales: Decimal | None = None
    rd_ids: tuple[str, ...] = ()
    if rd_fact and revenue_fact and isinstance(rd_fact.value, Mapping):
        amount = _decimal(rd_fact.value.get("amount"))
        period_end = rd_fact.value.get("period_end")
        if (
            amount is not None
            and period_end == revenue_fact.period_end
            and rd_fact.unit == revenue_fact.unit
            and revenue_fact.value not in (None, Decimal("0"))
        ):
            rd_to_sales = amount / revenue_fact.value
            rd_ids = (rd_fact.fact_id, revenue_fact.fact_id)
    if rd_to_sales is None:
        reasons["adaptability.rd_to_sales"] = "missing_period_aligned_rd_or_revenue"
    lineage["adaptability.rd_to_sales"] = rd_ids

    commitments: dict[str, tuple[str, str]] = {}
    deliveries: dict[str, list[tuple[str, str]]] = {}
    for fact in admitted_facts:
        value = _mapping(fact.value)
        if fact.fact_type == "management.commitment" and value:
            commitment_id, text = value.get("commitment_id"), value.get("text")
            if isinstance(commitment_id, str) and isinstance(text, str) and commitment_id.strip() and text.strip():
                normalized = commitment_id.strip()
                candidate = (text.strip(), fact.fact_id)
                if (
                    normalized in commitments
                    and commitments[normalized][0] != candidate[0]
                ):
                    raise GovernancePeopleError(
                        "conflicting management commitments"
                    )
                if (
                    normalized not in commitments
                    or candidate[1] < commitments[normalized][1]
                ):
                    commitments[normalized] = candidate
            else:
                excluded.append(ExcludedClaim(fact.fact_id, "invalid_management_commitment"))
        elif fact.fact_type == "management.delivery" and value:
            commitment_id, text = value.get("commitment_id"), value.get("text")
            if isinstance(commitment_id, str) and isinstance(text, str) and commitment_id.strip() and text.strip():
                deliveries.setdefault(commitment_id.strip(), []).append((text.strip(), fact.fact_id))
            else:
                excluded.append(ExcludedClaim(fact.fact_id, "invalid_management_delivery"))
    ledger = tuple(CommitmentDelivery(
        commitment_id=commitment_id,
        commitment=commitments[commitment_id][0],
        commitment_evidence_id=commitments[commitment_id][1],
        deliveries=tuple(text for text, _ in sorted(deliveries.get(commitment_id, []))),
        delivery_evidence_ids=tuple(eid for _, eid in sorted(deliveries.get(commitment_id, []))),
    ) for commitment_id in sorted(commitments))
    orphan_ids = sorted(set(deliveries) - set(commitments))
    excluded.extend(ExcludedClaim(eid, "delivery_without_admitted_commitment") for key in orphan_ids for _, eid in deliveries[key])

    relevant_families = {
        "governance:board", "governance:alignment", "governance:regulatory",
        "people:key_people", "people:succession", "adaptability:rd",
        "adaptability:capability", "management:commitment_delivery",
    }
    covered: set[str] = set()
    if percentages["board_independence_pct"] is not None:
        covered.add("governance:board")
    if alignment_signals or any(
        percentages[key] is not None
        for key in ("pledged_share_pct", "related_party_ratio")
    ):
        covered.add("governance:alignment")
    if regulatory_count is not None:
        covered.add("governance:regulatory")
    if people:
        covered.add("people:key_people")
    if succession_ids:
        covered.add("people:succession")
    if rd_to_sales is not None:
        covered.add("adaptability:rd")
    if investments:
        covered.add("adaptability:capability")
    if ledger:
        covered.add("management:commitment_delivery")
    used_facts = [fact for fact in admitted_facts if fact.fact_id in {
        evidence for ids in lineage.values() for evidence in ids
    } or fact.fact_id in {person.evidence_id for person in people} or fact.fact_id in succession_ids or fact.fact_id in investment_ids or any(fact.fact_id == item.commitment_evidence_id or fact.fact_id in item.delivery_evidence_ids for item in ledger)]
    used_times = [
        _instant(fact.available_at or "", "fact available_at")
        for fact in used_facts
    ]
    if rd_to_sales is not None and revenue_fact is not None:
        used_times.append(
            _instant(revenue_fact.available_at, "financial fact available_at")
        )
    available_at = max(used_times).isoformat() if used_times else None
    coverage = Decimal(len(covered)) / Decimal(len(relevant_families))
    reasons["candidate_score"] = "calibration_pending_t23"
    return GovernancePeopleCandidate(
        governance_signals=GovernanceSignals(
            **percentages, regulatory_events_5y=regulatory_count
        ),
        key_people=tuple(people),
        succession=Succession(plan, dependency, succession_ids[0] if succession_ids else None),
        alignment_signals=tuple(alignment_signals),
        adaptability=Adaptability(rd_to_sales, tuple(investments[:32]), tuple(sorted(set(investment_ids) | set(rd_ids)))),
        commitment_delivery_ledger=ledger,
        excluded_claims=tuple(sorted(excluded, key=lambda item: item.evidence_id)),
        evidence_family_ids=tuple(sorted(covered or {"governance_people:uncovered"})),
        metric_lineage=lineage,
        unavailable_reasons=reasons,
        coverage=coverage,
        confidence=coverage,
        candidate_score=None,
        available_at=available_at,
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
    )
