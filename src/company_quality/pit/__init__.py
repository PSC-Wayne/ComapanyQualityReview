"""Point-in-time admission for versioned research facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Sequence
from zoneinfo import ZoneInfo

Disposition = Literal["admitted", "blocked_conflict", "blocked_unavailable"]
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class FactCandidate:
    fact_id: str
    fact_type: str
    value: Any
    unit: str | None
    effective_at: str
    announced_at: str | None
    available_at: str
    retrieved_at: str
    valid_from: str
    valid_to: str | None
    authority_rank: int
    append_sequence: int
    version_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class FactAdmission:
    fact_id: str
    fact_type: str
    value: Any | None
    unit: str | None
    effective_at: str | None
    announced_at: str | None
    available_at: str | None
    retrieved_at: str | None
    valid_from: str | None
    valid_to: str | None
    authority_rank: int
    append_sequence: int | None
    version_id: str | None
    source_id: str | None
    disposition: Disposition
    failure_reason: str | None
    admission_coverage: float


@dataclass(frozen=True, slots=True)
class AdmittedFactSet:
    decision_time: str
    facts: tuple[FactAdmission, ...]
    schema_version: Literal["AdmittedFactSet.v1"] = "AdmittedFactSet.v1"
    policy_version: Literal["pit-admission.v1"] = "pit-admission.v1"
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )


def _instant(value: str) -> datetime:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise ValueError(f"expected timezone-aware RFC3339 instant: {value!r}")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"expected timezone-aware RFC3339 instant: {value!r}")
    return parsed.astimezone(_TAIPEI)


def _normalized(value: str) -> str:
    parsed = _instant(value)
    return parsed.isoformat(
        timespec="microseconds" if parsed.microsecond else "seconds"
    )


def _available(value: str) -> tuple[datetime, str]:
    if _DATE_ONLY.fullmatch(value):
        source_date = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=_TAIPEI)
        admitted_at = source_date + timedelta(days=1)
        return admitted_at, admitted_at.isoformat(timespec="seconds")
    parsed = _instant(value)
    return parsed, parsed.isoformat(
        timespec="microseconds" if parsed.microsecond else "seconds"
    )


def _active(candidate: FactCandidate, decision_time: datetime) -> bool:
    available_at, _ = _available(candidate.available_at)
    valid_from = _instant(candidate.valid_from)
    valid_to = _instant(candidate.valid_to) if candidate.valid_to is not None else None
    return (
        available_at <= decision_time
        and valid_from <= decision_time
        and (valid_to is None or decision_time < valid_to)
    )


def _validate(candidates: Sequence[FactCandidate]) -> None:
    seen: set[tuple[str, int, int]] = set()
    for candidate in candidates:
        if candidate.authority_rank < 0 or candidate.append_sequence < 0:
            raise ValueError("authority_rank and append_sequence must be non-negative")
        key = (
            candidate.fact_id,
            candidate.authority_rank,
            candidate.append_sequence,
        )
        if key in seen:
            raise ValueError(
                "append_sequence must be unique within one fact and authority history"
            )
        seen.add(key)
        _instant(candidate.effective_at)
        if candidate.announced_at is not None:
            _instant(candidate.announced_at)
        _available(candidate.available_at)
        _instant(candidate.retrieved_at)
        valid_from = _instant(candidate.valid_from)
        if candidate.valid_to is not None and _instant(candidate.valid_to) <= valid_from:
            raise ValueError("valid_to must be later than valid_from")


def _admitted(candidate: FactCandidate) -> FactAdmission:
    _, available_at = _available(candidate.available_at)
    return FactAdmission(
        fact_id=candidate.fact_id,
        fact_type=candidate.fact_type,
        value=candidate.value,
        unit=candidate.unit,
        effective_at=_normalized(candidate.effective_at),
        announced_at=(
            _normalized(candidate.announced_at)
            if candidate.announced_at is not None
            else None
        ),
        available_at=available_at,
        retrieved_at=_normalized(candidate.retrieved_at),
        valid_from=_normalized(candidate.valid_from),
        valid_to=(
            _normalized(candidate.valid_to) if candidate.valid_to is not None else None
        ),
        authority_rank=candidate.authority_rank,
        append_sequence=candidate.append_sequence,
        version_id=candidate.version_id,
        source_id=candidate.source_id,
        disposition="admitted",
        failure_reason=None,
        admission_coverage=1.0,
    )


def _blocked(
    candidate: FactCandidate,
    disposition: Literal["blocked_conflict", "blocked_unavailable"],
    reason: str,
) -> FactAdmission:
    _, available_at = _available(candidate.available_at)
    return FactAdmission(
        fact_id=candidate.fact_id,
        fact_type=candidate.fact_type,
        value=None,
        unit=candidate.unit,
        effective_at=_normalized(candidate.effective_at),
        announced_at=(
            _normalized(candidate.announced_at)
            if candidate.announced_at is not None
            else None
        ),
        available_at=available_at,
        retrieved_at=_normalized(candidate.retrieved_at),
        valid_from=_normalized(candidate.valid_from),
        valid_to=(
            _normalized(candidate.valid_to) if candidate.valid_to is not None else None
        ),
        authority_rank=candidate.authority_rank,
        append_sequence=candidate.append_sequence,
        version_id=candidate.version_id,
        source_id=candidate.source_id,
        disposition=disposition,
        failure_reason=reason,
        admission_coverage=0.0,
    )


def admit_facts(
    candidates: Sequence[FactCandidate], decision_time: str
) -> AdmittedFactSet:
    """Select only facts knowable at decision_time, without authority fallback."""
    decision = _instant(decision_time)
    normalized_time = decision.isoformat(
        timespec="microseconds" if decision.microsecond else "seconds"
    )
    _validate(candidates)

    grouped: dict[str, list[FactCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.fact_id, []).append(candidate)

    admissions: list[FactAdmission] = []
    for fact_id in sorted(grouped):
        history = grouped[fact_id]
        best_rank = min(candidate.authority_rank for candidate in history)
        authoritative = [
            candidate for candidate in history if candidate.authority_rank == best_rank
        ]
        active = [
            candidate for candidate in authoritative if _active(candidate, decision)
        ]

        if not active:
            representative = max(authoritative, key=lambda item: item.append_sequence)
            admissions.append(
                _blocked(representative, "blocked_unavailable", "not_yet_available")
            )
        elif len(active) > 1:
            representative = min(active, key=lambda item: item.append_sequence)
            admissions.append(
                _blocked(
                    representative,
                    "blocked_conflict",
                    "unresolved_same_rank_conflict",
                )
            )
        else:
            admissions.append(_admitted(active[0]))

    return AdmittedFactSet(normalized_time, tuple(admissions))
