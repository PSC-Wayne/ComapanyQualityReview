"""Govern explicit PIT-admitted downside and stress assumptions for T18."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Mapping, Sequence, cast

from company_quality.pit import AdmittedFactSet, FactAdmission


class DownsideAssumptionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ConstructInput:
    name: Literal[
        "maximum_drawdown_vulnerability",
        "permanent_capital_loss_vulnerability",
        "material_adverse_event_vulnerability",
    ]
    raw_value: Decimal | None
    evidence_ids: tuple[str, ...]
    state: Literal["present", "missing"]


@dataclass(frozen=True, slots=True)
class RiskAssumption:
    cause: str
    exposure: str
    transmission_path: str
    buffer: str | None
    indicator: str
    severity: Literal["low", "medium", "high", "critical"]
    trigger: str
    threshold: Decimal | None
    evidence_id: str
    fact_id: str


@dataclass(frozen=True, slots=True)
class StressAssumption:
    scenario: Literal["bear", "base", "bull"]
    assumption_ids: tuple[str, ...]
    equity_value_change_pct: Decimal
    liquidity_state: Literal["adequate", "tight", "insolvent"]
    fact_id: str


@dataclass(frozen=True, slots=True)
class BombEventAssumption:
    event_id: str
    event_type: Literal[
        "formal_adverse_opinion",
        "formal_disclaimer",
        "confirmed_fraud",
        "default",
        "insolvency",
        "major_regulatory_action",
        "other_governed",
    ]
    authoritative: bool
    material: bool
    current_relevance: bool
    authority_source_id: str
    effective_at: str
    expires_at: str | None
    evidence_ids: tuple[str, ...]
    fact_id: str


@dataclass(frozen=True, slots=True)
class DownsideAssumptionBundle:
    status: Literal["ready", "blocked"]
    constructs: tuple[ConstructInput, ...]
    risk_items: tuple[RiskAssumption, ...]
    stress_assumptions: tuple[StressAssumption, ...]
    bomb_event: BombEventAssumption | None
    missing_reasons: dict[str, str]
    evidence_ids: tuple[str, ...]
    authority_source_ids: tuple[str, ...]
    coverage: Decimal
    available_at: str | None
    generation_id: str
    producer_candidate_sha: str
    publication_status: Literal["NON_PUBLISHABLE_CANDIDATE"] = (
        "NON_PUBLISHABLE_CANDIDATE"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["DownsideAssumptionBundle.v1"] = (
        "DownsideAssumptionBundle.v1"
    )
    source_version: Literal["AdmittedFactSet.v1"] = "AdmittedFactSet.v1"
    formula_version: Literal["explicit-downside-assumptions.v1"] = (
        "explicit-downside-assumptions.v1"
    )
    model_version: Literal["no-derived-risk-model.v1"] = (
        "no-derived-risk-model.v1"
    )


_CONSTRUCTS = (
    "maximum_drawdown_vulnerability",
    "permanent_capital_loss_vulnerability",
    "material_adverse_event_vulnerability",
)
_SCENARIOS = ("bear", "base", "bull")


def _instant(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise DownsideAssumptionError(f"invalid {field}")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DownsideAssumptionError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise DownsideAssumptionError(f"{field} must be timezone-aware")
    return result


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DownsideAssumptionError(f"invalid {field}")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise DownsideAssumptionError(f"invalid {field}")
    return value.strip()


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise DownsideAssumptionError(f"invalid {field}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DownsideAssumptionError(f"invalid {field}") from exc
    if not result.is_finite() or not Decimal("-1e18") <= result <= Decimal("1e18"):
        raise DownsideAssumptionError(f"invalid {field}")
    return result


def _ids(value: object, field: str, known: set[str], maximum: int) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DownsideAssumptionError(f"invalid {field}")
    result = tuple(_text(item, field, 4096) for item in value)
    if not result or len(result) > maximum or len(set(result)) != len(result):
        raise DownsideAssumptionError(f"invalid {field}")
    if not set(result).issubset(known):
        raise DownsideAssumptionError(f"unbound {field}")
    return result


def _selected(admitted: AdmittedFactSet, fact_type: str) -> FactAdmission | None:
    if any(
        fact.fact_type == fact_type and fact.disposition == "blocked_conflict"
        for fact in admitted.facts
    ):
        raise DownsideAssumptionError(f"unresolved conflict for {fact_type}")
    candidates = [
        fact for fact in admitted.facts
        if fact.fact_type == fact_type and fact.disposition == "admitted"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda fact: (_instant(fact.effective_at, fact.fact_id), fact.fact_id))
    latest_time = _instant(candidates[-1].effective_at, candidates[-1].fact_id)
    latest = [
        fact for fact in candidates
        if _instant(fact.effective_at, fact.fact_id) == latest_time
    ]
    fingerprints = {repr(sorted(_mapping(fact.value, fact.fact_id).items())) for fact in latest}
    if len(fingerprints) != 1:
        raise DownsideAssumptionError(f"conflicting latest {fact_type} facts")
    return min(latest, key=lambda fact: fact.fact_id)


def _risk_item(fact: FactAdmission, known: set[str]) -> RiskAssumption:
    value = _mapping(fact.value, fact.fact_id)
    evidence_id = _text(value.get("evidence_id"), "risk evidence_id", 128)
    if evidence_id not in known:
        raise DownsideAssumptionError("unbound risk evidence_id")
    severity = value.get("severity")
    if severity not in {"low", "medium", "high", "critical"}:
        raise DownsideAssumptionError("invalid risk severity")
    buffer_raw = value.get("buffer")
    threshold_raw = value.get("threshold")
    return RiskAssumption(
        _text(value.get("cause"), "risk cause", 256),
        _text(value.get("exposure"), "risk exposure", 256),
        _text(value.get("transmission_path"), "risk transmission_path", 512),
        None if buffer_raw is None else _text(buffer_raw, "risk buffer", 256),
        _text(value.get("indicator"), "risk indicator", 256),
        cast(Literal["low", "medium", "high", "critical"], severity),
        _text(value.get("trigger"), "risk trigger", 256),
        None if threshold_raw is None else _decimal(threshold_raw, "risk threshold"),
        evidence_id,
        fact.fact_id,
    )


def build_downside_assumption_bundle(
    admitted: AdmittedFactSet,
    *,
    generation_id: str,
    producer_candidate_sha: str,
) -> DownsideAssumptionBundle:
    if admitted.schema_version != "AdmittedFactSet.v1":
        raise DownsideAssumptionError("BLOCKED_CONTRACT: expected AdmittedFactSet.v1")
    if not generation_id.strip() or len(generation_id) > 128:
        raise DownsideAssumptionError("invalid generation_id")
    if len(producer_candidate_sha) != 40 or any(
        char not in "0123456789abcdef" for char in producer_candidate_sha
    ):
        raise DownsideAssumptionError("invalid producer_candidate_sha")
    decision = _instant(admitted.decision_time, "decision_time")
    known = {fact.fact_id for fact in admitted.facts if fact.disposition == "admitted"}
    used: dict[str, FactAdmission] = {}
    missing: dict[str, str] = {}

    constructs: list[ConstructInput] = []
    for name in _CONSTRUCTS:
        fact = _selected(admitted, f"downside.construct.{name}")
        if fact is None:
            constructs.append(ConstructInput(name, None, (), "missing"))
            missing[f"construct.{name}"] = "missing_explicit_pit_assumption"
            continue
        value = _mapping(fact.value, fact.fact_id)
        evidence_ids = _ids(value.get("evidence_ids"), f"{name} evidence_ids", known, 64)
        constructs.append(
            ConstructInput(name, _decimal(value.get("raw_value"), f"{name} raw_value"), evidence_ids, "present")
        )
        used[fact.fact_id] = fact
        used.update({item: next(f for f in admitted.facts if f.fact_id == item) for item in evidence_ids})

    risk_items: list[RiskAssumption] = []
    if any(
        fact.fact_type == "downside.risk_item" and fact.disposition == "blocked_conflict"
        for fact in admitted.facts
    ):
        raise DownsideAssumptionError("unresolved conflict for downside.risk_item")
    for fact in admitted.facts:
        if fact.fact_type != "downside.risk_item" or fact.disposition != "admitted":
            continue
        try:
            item = _risk_item(fact, known)
        except DownsideAssumptionError:
            missing[f"risk.{fact.fact_id}"] = "incomplete_or_invalid_causal_chain"
            continue
        risk_items.append(item)
        used[fact.fact_id] = fact
        used[item.evidence_id] = next(
            item_fact for item_fact in admitted.facts
            if item_fact.fact_id == item.evidence_id
        )
    risk_items.sort(key=lambda item: (item.severity, item.cause, item.fact_id))
    if len(risk_items) > 100:
        raise DownsideAssumptionError("risk item count exceeds 100")
    if not risk_items:
        missing["risk_items"] = "no_complete_causal_risk_item"

    stresses: list[StressAssumption] = []
    for scenario in _SCENARIOS:
        fact = _selected(admitted, f"downside.stress.{scenario}")
        if fact is None:
            missing[f"stress.{scenario}"] = "missing_explicit_pit_assumption"
            continue
        value = _mapping(fact.value, fact.fact_id)
        assumption_ids = _ids(
            value.get("assumption_ids"), f"{scenario} assumption_ids", known, 32
        )
        liquidity = value.get("liquidity_state")
        if liquidity not in {"adequate", "tight", "insolvent"}:
            raise DownsideAssumptionError(f"invalid {scenario} liquidity_state")
        stresses.append(
            StressAssumption(
                scenario,
                assumption_ids,
                _decimal(value.get("equity_value_change_pct"), f"{scenario} equity change"),
                cast(Literal["adequate", "tight", "insolvent"], liquidity),
                fact.fact_id,
            )
        )
        used[fact.fact_id] = fact
        used.update({item: next(f for f in admitted.facts if f.fact_id == item) for item in assumption_ids})

    bomb = None
    bomb_fact = _selected(admitted, "downside.bomb_event")
    if bomb_fact is not None:
        value = _mapping(bomb_fact.value, bomb_fact.fact_id)
        event_type = value.get("event_type")
        allowed = {
            "formal_adverse_opinion", "formal_disclaimer", "confirmed_fraud",
            "default", "insolvency", "major_regulatory_action", "other_governed",
        }
        if event_type not in allowed:
            raise DownsideAssumptionError("invalid bomb event_type")
        if not all(isinstance(value.get(field), bool) for field in ("authoritative", "material", "current_relevance")):
            raise DownsideAssumptionError("bomb flags must be booleans")
        source_id = _text(value.get("authority_source_id"), "authority_source_id", 128)
        if bomb_fact.source_id != source_id:
            raise DownsideAssumptionError("bomb authority source does not match PIT source")
        effective = _instant(value.get("effective_at"), "bomb effective_at")
        expires_raw = value.get("expires_at")
        expires = None if expires_raw is None else _instant(expires_raw, "bomb expires_at")
        if effective > decision or (expires is not None and expires <= effective):
            raise DownsideAssumptionError("invalid bomb event interval")
        if value.get("current_relevance") is True and expires is not None and expires <= decision:
            raise DownsideAssumptionError("expired bomb cannot be currently relevant")
        evidence_ids = _ids(value.get("evidence_ids"), "bomb evidence_ids", known, 32)
        bomb = BombEventAssumption(
            _text(value.get("event_id"), "bomb event_id", 128),
            cast(
                Literal[
                    "formal_adverse_opinion", "formal_disclaimer", "confirmed_fraud",
                    "default", "insolvency", "major_regulatory_action", "other_governed",
                ],
                event_type,
            ),
            cast(bool, value["authoritative"]),
            cast(bool, value["material"]),
            cast(bool, value["current_relevance"]),
            source_id, effective.isoformat(), None if expires is None else expires.isoformat(),
            evidence_ids, bomb_fact.fact_id,
        )
        used[bomb_fact.fact_id] = bomb_fact
        used.update({item: next(f for f in admitted.facts if f.fact_id == item) for item in evidence_ids})

    status = "ready" if len(stresses) == 3 and risk_items else "blocked"
    covered = sum(item.state == "present" for item in constructs) + bool(risk_items) + len(stresses)
    available = max(
        (_instant(fact.available_at, f"{fact.fact_id} available_at") for fact in used.values()),
        default=None,
    )
    return DownsideAssumptionBundle(
        status=status,
        constructs=tuple(constructs),
        risk_items=tuple(risk_items),
        stress_assumptions=tuple(stresses),
        bomb_event=bomb,
        missing_reasons=missing,
        evidence_ids=tuple(sorted(used)),
        authority_source_ids=tuple(sorted({fact.source_id for fact in used.values() if fact.source_id})),
        coverage=Decimal(covered) / Decimal(7),
        available_at=None if available is None else available.isoformat(),
        generation_id=generation_id,
        producer_candidate_sha=producer_candidate_sha,
    )


__all__ = [
    "DownsideAssumptionBundle",
    "DownsideAssumptionError",
    "build_downside_assumption_bundle",
]
