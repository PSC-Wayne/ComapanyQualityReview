"""Small producer seam for point-in-time, multi-source checklist evidence.

TWSE/TPEx OpenAPI feeds are discovery windows.  They can identify work but can
never, by themselves, satisfy a substantive checklist claim.  MOPS and issuer
published documents may carry substantive evidence after a downstream producer
has preserved the document boundary and supplied a non-summary evidence handle.
This module only admits lineage; it does not redefine source authority by topic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, Sequence, cast
from urllib.parse import urlparse

SourceFamily = Literal[
    "twse_openapi",
    "tpex_openapi",
    "mops",
    "issuer_ir",
    "annual_report",
    "sustainability_report",
]
Market = Literal["TWSE", "TPEx"]
RegistryStatus = Literal["available", "unresolved"]

SOURCE_FAMILIES: tuple[SourceFamily, ...] = (
    "twse_openapi",
    "tpex_openapi",
    "mops",
    "issuer_ir",
    "annual_report",
    "sustainability_report",
)
SUPPLEMENTARY_SOURCE_FAMILIES = frozenset({"twse_openapi", "tpex_openapi"})


class ProducerRegistryError(ValueError):
    """Raised for invalid registry configuration or evidence contracts."""


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ProducerRegistryError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ProducerRegistryError(f"{field} must be timezone-aware")
    return result


def _family(value: str) -> SourceFamily:
    if value not in SOURCE_FAMILIES:
        raise ProducerRegistryError(f"unsupported source family: {value}")
    return cast(SourceFamily, value)


@dataclass(frozen=True, slots=True)
class MultiSourceEvidence:
    """Immutable lineage handle returned by one source-specific producer."""

    evidence_id: str
    evidence_handle: str
    source_url: str
    source_family: SourceFamily
    market: Market
    observed_period: str
    retrieved_at: str
    available_at: str
    as_of: str
    is_summary_only: bool = False
    schema_version: Literal["MultiSourceEvidence.v1"] = "MultiSourceEvidence.v1"

    def __post_init__(self) -> None:
        _family(self.source_family)
        if self.market not in {"TWSE", "TPEx"}:
            raise ProducerRegistryError(f"unsupported market: {self.market}")
        required = {
            "evidence_id": self.evidence_id,
            "evidence_handle": self.evidence_handle,
            "source_url": self.source_url,
            "observed_period": self.observed_period,
        }
        missing = tuple(name for name, value in required.items() if not value.strip())
        if missing:
            raise ProducerRegistryError("missing evidence fields: " + ",".join(missing))
        parsed_url = urlparse(self.source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ProducerRegistryError("source_url must be an absolute HTTP(S) URL")
        _instant(self.retrieved_at, "retrieved_at")
        _instant(self.available_at, "available_at")
        _instant(self.as_of, "as_of")


class EvidenceProducer(Protocol):
    source_family: SourceFamily

    def produce(
        self, *, market: Market, as_of: str
    ) -> Sequence[MultiSourceEvidence]: ...


@dataclass(frozen=True, slots=True)
class ProducerEvidenceResult:
    """Fail-closed aggregate; eligibility never overrides topic authority."""

    market: Market
    as_of: str
    evidence: tuple[MultiSourceEvidence, ...]
    discovery_evidence_ids: tuple[str, ...]
    substantive_evidence_ids: tuple[str, ...]
    unresolved_reasons: tuple[str, ...]
    status: RegistryStatus
    schema_version: Literal["ProducerEvidenceResult.v1"] = "ProducerEvidenceResult.v1"

    def can_support_completion(self, evidence_ids: Sequence[str]) -> bool:
        """Return true only when every claim handle is substantive and PIT-safe."""

        requested = tuple(evidence_ids)
        return bool(requested) and set(requested).issubset(self.substantive_evidence_ids)


class EvidenceProducerRegistry:
    """Registry allowing source modules to be independently owned and tested."""

    def __init__(self) -> None:
        self._producers: dict[SourceFamily, EvidenceProducer] = {}

    def register(self, producer: EvidenceProducer) -> None:
        family = _family(producer.source_family)
        if family in self._producers:
            raise ProducerRegistryError(f"source family already registered: {family}")
        self._producers[family] = producer

    def collect(
        self,
        *,
        market: Market,
        as_of: str,
        required_families: Sequence[SourceFamily] = (),
    ) -> ProducerEvidenceResult:
        decision_time = _instant(as_of, "as_of")
        if market not in {"TWSE", "TPEx"}:
            raise ProducerRegistryError(f"unsupported market: {market}")
        required = tuple(_family(item) for item in required_families)
        if len(set(required)) != len(required):
            raise ProducerRegistryError("required source families must be unique")

        evidence: list[MultiSourceEvidence] = []
        reasons: list[str] = []
        for family, producer in self._producers.items():
            try:
                candidates = tuple(producer.produce(market=market, as_of=as_of))
            except (OSError, RuntimeError, ValueError) as exc:
                reasons.append(f"producer_error:{family}:{type(exc).__name__}")
                continue
            for item in candidates:
                if item.source_family != family:
                    reasons.append(f"source_family_mismatch:{family}:{item.evidence_id}")
                    continue
                if item.market != market:
                    reasons.append(f"market_mismatch:{family}:{item.evidence_id}")
                    continue
                if _instant(item.as_of, "evidence as_of") != decision_time:
                    reasons.append(f"as_of_mismatch:{family}:{item.evidence_id}")
                    continue
                evidence.append(item)

        conflicts: set[str] = set()
        by_id: dict[str, MultiSourceEvidence] = {}
        for item in evidence:
            prior = by_id.get(item.evidence_id)
            if prior is None:
                by_id[item.evidence_id] = item
            elif prior != item:
                conflicts.add(item.evidence_id)
        reasons.extend(f"conflict:{item}" for item in sorted(conflicts))

        temporal: list[MultiSourceEvidence] = []
        for item in evidence:
            if item.evidence_id in conflicts:
                continue
            if _instant(item.available_at, "available_at") > decision_time:
                reasons.append(f"post_as_of:{item.source_family}:{item.evidence_id}")
                continue
            temporal.append(item)

        discovery_ids = tuple(dict.fromkeys(item.evidence_id for item in temporal))
        substantive = tuple(
            item
            for item in temporal
            if item.source_family not in SUPPLEMENTARY_SOURCE_FAMILIES
            and not item.is_summary_only
        )
        substantive_ids = tuple(dict.fromkeys(item.evidence_id for item in substantive))
        reasons.extend(
            f"summary_only:{item.source_family}:{item.evidence_id}"
            for item in temporal
            if item.source_family not in SUPPLEMENTARY_SOURCE_FAMILIES
            and item.is_summary_only
        )

        temporal_families = {item.source_family for item in temporal}
        substantive_families = {item.source_family for item in substantive}
        for family in required:
            available_families = (
                temporal_families
                if family in SUPPLEMENTARY_SOURCE_FAMILIES
                else substantive_families
            )
            if family not in available_families:
                reasons.append(f"missing:{family}")

        unresolved = tuple(dict.fromkeys(reasons))
        return ProducerEvidenceResult(
            market=market,
            as_of=as_of,
            evidence=tuple(evidence),
            discovery_evidence_ids=discovery_ids,
            substantive_evidence_ids=substantive_ids,
            unresolved_reasons=unresolved,
            status="unresolved" if unresolved else "available",
        )


__all__ = [
    "SOURCE_FAMILIES",
    "SUPPLEMENTARY_SOURCE_FAMILIES",
    "EvidenceProducer",
    "EvidenceProducerRegistry",
    "MultiSourceEvidence",
    "ProducerEvidenceResult",
    "ProducerRegistryError",
    "SourceFamily",
]
