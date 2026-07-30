"""Hermes candidate extraction and deterministic evidence admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
import re
from typing import Literal, Mapping, Protocol, Sequence
from urllib.request import Request, urlopen

from company_quality.company_analysis.contracts import EvidenceCitation


RejectionReason = Literal[
    "malformed_candidate",
    "unknown_evidence",
    "issuer_identity_mismatch",
    "pit_violation",
    "original_text_missing",
    "numeric_value_mismatch",
    "unit_mismatch",
    "period_mismatch",
    "citation_locator_missing",
    "citation_locator_mismatch",
]


@dataclass(frozen=True, slots=True)
class AdmittedHermesCandidate:
    candidate_id: str
    statement: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class RejectedHermesCandidate:
    candidate_id: str
    reason: RejectionReason


@dataclass(frozen=True, slots=True)
class HermesAdmissionResult:
    admitted: tuple[AdmittedHermesCandidate, ...]
    rejected: tuple[RejectedHermesCandidate, ...]


class HermesCandidateAdapter(Protocol):
    def extract_candidates(
        self,
        *,
        issuer_id: str,
        as_of: str,
        generation_id: str,
        citations: Sequence[EvidenceCitation],
        locked_values: Sequence[Mapping[str, object]] = (),
    ) -> Sequence[Mapping[str, object]]: ...

    def judge_kam(
        self,
        *,
        issuer_id: str,
        as_of: str,
        generation_id: str,
        citations: Sequence[EvidenceCitation],
    ) -> Mapping[str, object]: ...


_SYSTEM_PROMPT = """You extract candidate facts from only the supplied evidence JSON.
Do not use tools, external knowledge, memory, or other sources.
Return exactly one JSON object with a candidates array and no markdown.
Each candidate must contain only these string fields: candidate_id, issuer_id,
statement, verbatim_quote, value, unit, period, evidence_id, citation_locator.
Copy verbatim_quote, value, unit, period, evidence_id, and citation_locator exactly
from supplied evidence. Deterministic locked_values are authoritative and must never
be rewritten. Financial-deterioration synthesis must be qualitative, contain no
numbers, and use candidate_id hermes:financial-deterioration:synthesis. If no fully
supported candidate exists, return {\"candidates\": []}."""
_KAM_SYSTEM_PROMPT = """Judge the substance of the supplied annual key audit matters only.
KAM existence is not itself adverse proof. Do not merge KAM with modified opinion,
going concern, emphasis of matter, or auditor change. Return exactly one JSON object
with issuer_id, change_summary, risk_mechanism, counterevidence, severity, confidence,
monitoring, invalidation, and yearly_citations. severity must be one of none, low,
medium, high, critical. confidence must be a decimal string from 0 to 1.
yearly_citations must contain period, evidence_id, verbatim_quote, citation_locator
for every supplied year, copied exactly from supplied evidence. Use no external facts."""
_NUMBER = re.compile(r"(?<![\d.])[-+]?\d[\d,]*(?:\.\d+)?(?![\d.])")


class HermesApiCandidateAdapter:
    """Minimal OpenAI-compatible HTTP adapter for the Hermes API Server."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        session_id: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self.timeout = timeout

    @classmethod
    def from_environment(cls, generation_id: str) -> HermesApiCandidateAdapter | None:
        base_url = os.environ.get(
            "HERMES_API_BASE_URL", "http://127.0.0.1:8642/v1"
        ).strip()
        api_key = (
            os.environ.get("HERMES_API_KEY")
            or os.environ.get("API_SERVER_KEY")
            or ""
        ).strip()
        if not api_key:
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            session_id=f"company-quality-{generation_id}",
        )

    def extract_candidates(
        self,
        *,
        issuer_id: str,
        as_of: str,
        generation_id: str,
        citations: Sequence[EvidenceCitation],
        locked_values: Sequence[Mapping[str, object]] = (),
    ) -> Sequence[Mapping[str, object]]:
        evidence = [
            {
                "issuer_id": issuer_id,
                "evidence_id": item.evidence_id,
                "period": item.period,
                "available_at": item.available_at,
                "citation_locator": _locator(item),
                "verbatim_excerpt": item.verbatim_excerpt,
            }
            for item in citations
        ]
        decoded = self._complete(
            _SYSTEM_PROMPT,
            {
                "issuer_id": issuer_id,
                "as_of": as_of,
                "generation_id": generation_id,
                "evidence": evidence,
                "locked_values": list(locked_values),
            },
        )
        candidates = decoded.get("candidates")
        if not isinstance(candidates, list) or not all(
            isinstance(item, dict) for item in candidates
        ):
            raise ValueError("Hermes response must contain a candidates array")
        return candidates

    def judge_kam(
        self,
        *,
        issuer_id: str,
        as_of: str,
        generation_id: str,
        citations: Sequence[EvidenceCitation],
    ) -> Mapping[str, object]:
        evidence = [
            {
                "issuer_id": issuer_id,
                "evidence_id": item.evidence_id,
                "period": item.period,
                "available_at": item.available_at,
                "citation_locator": _locator(item),
                "verbatim_excerpt": item.verbatim_excerpt,
            }
            for item in citations
        ]
        return self._complete(
            _KAM_SYSTEM_PROMPT,
            {
                "issuer_id": issuer_id,
                "as_of": as_of,
                "generation_id": generation_id,
                "evidence": evidence,
            },
        )

    def _complete(
        self, system_prompt: str, content: Mapping[str, object]
    ) -> Mapping[str, object]:
        payload = {
            "model": "hermes-agent",
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(content, ensure_ascii=False),
                },
            ],
            "stream": False,
            "tools": [],
        }
        endpoint = (
            f"{self.base_url}/chat/completions"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/chat/completions"
        )
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Hermes-Session-Id": self.session_id,
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read())
        message_content = result["choices"][0]["message"]["content"]
        decoded = json.loads(message_content)
        if not isinstance(decoded, dict):
            raise ValueError("Hermes response must contain one JSON object")
        return decoded


@dataclass(frozen=True, slots=True)
class AdmittedKamJudgement:
    change_summary: str
    risk_mechanism: str
    counterevidence: str
    severity: Literal["none", "low", "medium", "high", "critical"]
    confidence: Decimal
    monitoring: str
    invalidation: str


def admit_kam_judgement(
    *,
    candidate: Mapping[str, object],
    issuer_id: str,
    citations: Sequence[EvidenceCitation],
) -> tuple[AdmittedKamJudgement | None, tuple[str, ...]]:
    """Admit a KAM judgement only when all mandatory prose and yearly quotes bind."""

    reasons: list[str] = []
    if candidate.get("issuer_id") != issuer_id:
        reasons.append("issuer_identity_mismatch")
    text_fields = (
        "change_summary",
        "risk_mechanism",
        "counterevidence",
        "monitoring",
        "invalidation",
    )
    values: dict[str, str] = {}
    for field in text_fields:
        value = candidate.get(field)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"{field}_missing")
        else:
            values[field] = value.strip()
    severity = candidate.get("severity")
    if severity not in {"none", "low", "medium", "high", "critical"}:
        reasons.append("severity_invalid")
    try:
        confidence = Decimal(str(candidate.get("confidence")))
        if not Decimal("0") <= confidence <= Decimal("1"):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        confidence = Decimal("0")
        reasons.append("confidence_invalid")

    yearly = candidate.get("yearly_citations")
    supplied = {item.period: item for item in citations}
    seen: set[str] = set()
    if not isinstance(yearly, list):
        reasons.append("yearly_citations_missing")
    else:
        for item in yearly:
            if not isinstance(item, Mapping):
                reasons.append("yearly_citation_malformed")
                continue
            period = item.get("period")
            citation = supplied.get(str(period))
            if citation is None:
                reasons.append("period_mismatch")
                continue
            seen.add(citation.period)
            if item.get("evidence_id") != citation.evidence_id:
                reasons.append("unknown_evidence")
            quote = item.get("verbatim_quote")
            if not isinstance(quote, str) or quote not in citation.verbatim_excerpt:
                reasons.append("original_text_missing")
            if item.get("citation_locator") != _locator(citation):
                reasons.append("citation_locator_mismatch")
        if seen != set(supplied):
            reasons.append("yearly_citations_incomplete")
    unique_reasons = tuple(dict.fromkeys(reasons))
    if unique_reasons:
        return None, unique_reasons
    return (
        AdmittedKamJudgement(
            change_summary=values["change_summary"],
            risk_mechanism=values["risk_mechanism"],
            counterevidence=values["counterevidence"],
            severity=severity,  # type: ignore[arg-type]
            confidence=confidence,
            monitoring=values["monitoring"],
            invalidation=values["invalidation"],
        ),
        (),
    )


def _instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timezone-aware instant required")
    return result


def _locator(citation: EvidenceCitation) -> str:
    if citation.source_format == "pdf":
        return f"page:{citation.page}"
    return citation.locator or ""


def _candidate_id(candidate: Mapping[str, object]) -> str:
    value = candidate.get("candidate_id")
    return value.strip() if isinstance(value, str) and value.strip() else "unknown"


def _reject(
    candidate: Mapping[str, object], reason: RejectionReason
) -> RejectedHermesCandidate:
    return RejectedHermesCandidate(_candidate_id(candidate), reason)


def admit_hermes_candidates(
    *,
    candidates: Sequence[Mapping[str, object]],
    issuer_id: str,
    as_of: str,
    citations: Sequence[EvidenceCitation],
) -> HermesAdmissionResult:
    """Admit candidates only when every identity/PIT/text/value/citation check passes."""

    decision = _instant(as_of)
    by_evidence = {item.evidence_id: item for item in citations}
    required = (
        "candidate_id",
        "issuer_id",
        "statement",
        "verbatim_quote",
        "value",
        "unit",
        "period",
        "evidence_id",
        "citation_locator",
    )
    admitted: list[AdmittedHermesCandidate] = []
    rejected: list[RejectedHermesCandidate] = []
    for candidate in candidates:
        if any(
            not isinstance(candidate.get(field), str)
            or (field != "citation_locator" and not str(candidate[field]).strip())
            for field in required
        ):
            rejected.append(_reject(candidate, "malformed_candidate"))
            continue
        evidence = by_evidence.get(str(candidate["evidence_id"]))
        if evidence is None:
            rejected.append(_reject(candidate, "unknown_evidence"))
        elif candidate["issuer_id"] != issuer_id:
            rejected.append(_reject(candidate, "issuer_identity_mismatch"))
        elif _instant(evidence.available_at) > decision:
            rejected.append(_reject(candidate, "pit_violation"))
        elif str(candidate["verbatim_quote"]) not in evidence.verbatim_excerpt:
            rejected.append(_reject(candidate, "original_text_missing"))
        elif str(candidate["value"]) not in _NUMBER.findall(
            str(candidate["verbatim_quote"])
        ):
            rejected.append(_reject(candidate, "numeric_value_mismatch"))
        elif str(candidate["unit"]) not in str(candidate["verbatim_quote"]):
            rejected.append(_reject(candidate, "unit_mismatch"))
        elif candidate["period"] != evidence.period:
            rejected.append(_reject(candidate, "period_mismatch"))
        elif not str(candidate["citation_locator"]).strip():
            rejected.append(_reject(candidate, "citation_locator_missing"))
        elif candidate["citation_locator"] != _locator(evidence):
            rejected.append(_reject(candidate, "citation_locator_mismatch"))
        else:
            admitted.append(
                AdmittedHermesCandidate(
                    candidate_id=str(candidate["candidate_id"]).strip(),
                    statement=str(candidate["statement"]).strip(),
                    evidence_id=evidence.evidence_id,
                )
            )
    return HermesAdmissionResult(tuple(admitted), tuple(rejected))


__all__ = [
    "AdmittedKamJudgement",
    "AdmittedHermesCandidate",
    "HermesAdmissionResult",
    "HermesApiCandidateAdapter",
    "HermesCandidateAdapter",
    "RejectedHermesCandidate",
    "admit_kam_judgement",
    "admit_hermes_candidates",
]
