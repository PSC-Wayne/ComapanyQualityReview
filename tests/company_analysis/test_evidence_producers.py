from dataclasses import replace

import pytest

from company_quality.company_analysis.evidence_producers import (
    EvidenceProducerRegistry,
    MultiSourceEvidence,
    ProducerRegistryError,
)


AS_OF = "2026-08-03T12:00:00+08:00"


def _evidence(
    evidence_id: str,
    source_family: str,
    *,
    market: str = "TWSE",
    observed_period: str = "115Q1",
    available_at: str = "2026-05-15T18:00:00+08:00",
    evidence_handle: str | None = None,
    is_summary_only: bool = False,
) -> MultiSourceEvidence:
    return MultiSourceEvidence(
        evidence_id=evidence_id,
        evidence_handle=evidence_handle or f"sha256:{evidence_id}",
        source_url=f"https://official.example/{source_family}/{evidence_id}",
        source_family=source_family,
        market=market,
        observed_period=observed_period,
        retrieved_at="2026-08-03T11:00:00+08:00",
        available_at=available_at,
        as_of=AS_OF,
        is_summary_only=is_summary_only,
    )


class Producer:
    def __init__(self, source_family: str, *evidence: MultiSourceEvidence) -> None:
        self.source_family = source_family
        self.evidence = evidence
        self.calls = []

    def produce(self, *, market: str, as_of: str):
        self.calls.append((market, as_of))
        return self.evidence


def test_registry_collects_all_supported_source_windows_with_lineage() -> None:
    families = (
        "twse_openapi",
        "tpex_openapi",
        "mops",
        "issuer_ir",
        "annual_report",
        "sustainability_report",
    )
    registry = EvidenceProducerRegistry()
    producers = []
    for family in families:
        producer = Producer(family, _evidence(f"evidence:{family}", family))
        producers.append(producer)
        registry.register(producer)

    result = registry.collect(market="TWSE", as_of=AS_OF, required_families=families)

    assert result.status == "available"
    assert {item.source_family for item in result.evidence} == set(families)
    assert all(item.source_url and item.observed_period for item in result.evidence)
    assert all(item.retrieved_at and item.available_at and item.as_of for item in result.evidence)
    assert all(item.evidence_handle for item in result.evidence)
    assert all(producer.calls == [("TWSE", AS_OF)] for producer in producers)


def test_openapi_windows_are_supplementary_and_never_sole_completion_evidence() -> None:
    registry = EvidenceProducerRegistry()
    registry.register(Producer("twse_openapi", _evidence("twse:summary", "twse_openapi")))
    registry.register(Producer("mops", _evidence("mops:filing", "mops")))

    result = registry.collect(
        market="TWSE",
        as_of=AS_OF,
        required_families=("twse_openapi", "mops"),
    )

    assert result.discovery_evidence_ids == ("twse:summary", "mops:filing")
    assert result.substantive_evidence_ids == ("mops:filing",)
    assert result.can_support_completion(("twse:summary",)) is False
    assert result.can_support_completion(("mops:filing",)) is True


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (_evidence("late", "mops", available_at="2026-08-04T00:00:00+08:00"), "post_as_of"),
        (_evidence("summary", "annual_report", is_summary_only=True), "summary_only"),
    ],
)
def test_post_as_of_and_summary_only_evidence_remain_unresolved(evidence, reason) -> None:
    registry = EvidenceProducerRegistry()
    registry.register(Producer(evidence.source_family, evidence))

    result = registry.collect(
        market="TWSE", as_of=AS_OF, required_families=(evidence.source_family,)
    )

    assert result.status == "unresolved"
    assert result.substantive_evidence_ids == ()
    assert result.can_support_completion((evidence.evidence_id,)) is False
    assert any(reason in item for item in result.unresolved_reasons)


def test_missing_and_conflicting_evidence_remain_unresolved() -> None:
    first = _evidence("mops:115Q1", "mops")
    conflicting = replace(first, evidence_handle="sha256:different")
    registry = EvidenceProducerRegistry()
    registry.register(Producer("mops", first, conflicting))

    result = registry.collect(
        market="TWSE",
        as_of=AS_OF,
        required_families=("mops", "issuer_ir"),
    )

    assert result.status == "unresolved"
    assert result.substantive_evidence_ids == ()
    assert result.can_support_completion(("mops:115Q1",)) is False
    assert any("conflict" in item for item in result.unresolved_reasons)
    assert any("missing:issuer_ir" in item for item in result.unresolved_reasons)


def test_registry_rejects_cross_market_or_cross_as_of_output() -> None:
    registry = EvidenceProducerRegistry()
    registry.register(Producer("mops", _evidence("wrong-market", "mops", market="TPEx")))

    result = registry.collect(market="TWSE", as_of=AS_OF, required_families=("mops",))

    assert result.status == "unresolved"
    assert result.evidence == ()
    assert any("market_mismatch" in item for item in result.unresolved_reasons)


def test_duplicate_family_registration_fails_closed() -> None:
    registry = EvidenceProducerRegistry()
    registry.register(Producer("mops"))

    with pytest.raises(ProducerRegistryError, match="already registered"):
        registry.register(Producer("mops"))
