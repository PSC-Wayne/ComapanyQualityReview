from dataclasses import replace

import pytest

from company_quality.company_analysis.evidence_producers import (
    EvidenceRole,
    EvidenceProducerRegistry,
    Market,
    MultiSourceEvidence,
    ProducerRegistryError,
    SourceFamily,
)


AS_OF = "2026-08-03T12:00:00+08:00"
ISSUER_ID = "22099131"
SECURITY_CODE = "2330"
REPORTED_COMPANY_NAME = "台灣積體電路製造股份有限公司"


def _evidence(
    evidence_id: str,
    source_family: SourceFamily,
    *,
    market: Market = "TWSE",
    issuer_id: str = ISSUER_ID,
    security_code: str = SECURITY_CODE,
    reported_company_name: str = REPORTED_COMPANY_NAME,
    dataset_id: str = "official-dataset-v1",
    source_locator: str = "row:17",
    observed_period: str = "115Q1",
    available_at: str = "2026-05-15T18:00:00+08:00",
    evidence_handle: str | None = None,
    evidence_role: EvidenceRole = "substantive",
    is_summary_only: bool = False,
) -> MultiSourceEvidence:
    return MultiSourceEvidence(
        evidence_id=evidence_id,
        evidence_handle=evidence_handle or f"sha256:{evidence_id}",
        issuer_id=issuer_id,
        security_code=security_code,
        reported_company_name=reported_company_name,
        dataset_id=dataset_id,
        source_locator=source_locator,
        source_url=f"https://official.example/{source_family}/{evidence_id}",
        source_family=source_family,
        market=market,
        observed_period=observed_period,
        retrieved_at="2026-08-03T11:00:00+08:00",
        available_at=available_at,
        as_of=AS_OF,
        evidence_role=evidence_role,
        is_summary_only=is_summary_only,
    )


class Producer:
    def __init__(
        self,
        producer_id: str,
        source_family: SourceFamily,
        *evidence: MultiSourceEvidence,
    ) -> None:
        self.producer_id = producer_id
        self.source_family = source_family
        self.evidence = evidence
        self.calls = []

    def produce(
        self,
        *,
        issuer_id: str,
        security_code: str,
        reported_company_name: str,
        market: Market,
        as_of: str,
    ):
        self.calls.append(
            (issuer_id, security_code, reported_company_name, market, as_of)
        )
        return self.evidence


def _collect(registry: EvidenceProducerRegistry, **kwargs):
    return registry.collect(
        issuer_id=ISSUER_ID,
        security_code=SECURITY_CODE,
        reported_company_name=REPORTED_COMPANY_NAME,
        market="TWSE",
        as_of=AS_OF,
        **kwargs,
    )


def test_registry_collects_all_supported_source_windows_with_lineage() -> None:
    families: tuple[SourceFamily, ...] = (
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
        producer = Producer(
            f"producer:{family}", family, _evidence(f"evidence:{family}", family)
        )
        producers.append(producer)
        registry.register(producer)

    result = _collect(registry, required_families=families)

    assert result.status == "available"
    assert {item.source_family for item in result.evidence} == set(families)
    assert all(item.source_url and item.observed_period for item in result.evidence)
    assert all(item.retrieved_at and item.available_at and item.as_of for item in result.evidence)
    assert all(item.evidence_handle for item in result.evidence)
    assert all(
        item.issuer_id == ISSUER_ID
        and item.security_code == SECURITY_CODE
        and item.reported_company_name == REPORTED_COMPANY_NAME
        and item.dataset_id
        and item.source_locator
        for item in result.evidence
    )
    assert all(
        producer.calls
        == [(ISSUER_ID, SECURITY_CODE, REPORTED_COMPANY_NAME, "TWSE", AS_OF)]
        for producer in producers
    )


def test_two_independent_producers_can_share_one_source_family() -> None:
    registry = EvidenceProducerRegistry()
    registry.register(
        Producer("mops.financial", "mops", _evidence("mops:financial", "mops"))
    )
    registry.register(Producer("mops.audit", "mops", _evidence("mops:audit", "mops")))

    result = _collect(registry, required_families=("mops",))

    assert result.status == "available"
    assert tuple(item.evidence_id for item in result.evidence) == (
        "mops:financial",
        "mops:audit",
    )


def test_duplicate_producer_identity_fails_closed_even_across_families() -> None:
    registry = EvidenceProducerRegistry()
    registry.register(Producer("official.filing", "mops"))

    with pytest.raises(ProducerRegistryError, match="producer identity already registered"):
        registry.register(Producer("official.filing", "annual_report"))


def test_openapi_discovery_item_cannot_support_completion() -> None:
    registry = EvidenceProducerRegistry()
    registry.register(
        Producer(
            "twse.discovery",
            "twse_openapi",
            _evidence(
                "twse:summary", "twse_openapi", evidence_role="discovery"
            ),
        )
    )
    registry.register(
        Producer("mops.filing", "mops", _evidence("mops:filing", "mops"))
    )

    result = _collect(
        registry, required_families=("twse_openapi", "mops")
    )

    assert result.discovery_evidence_ids == ("twse:summary", "mops:filing")
    assert result.substantive_evidence_ids == ("mops:filing",)
    assert result.can_support_completion(("twse:summary",)) is False
    assert result.can_support_completion(("mops:filing",)) is True


def test_claim_specific_openapi_item_can_be_substantive() -> None:
    registry = EvidenceProducerRegistry()
    registry.register(
        Producer(
            "twse.claim-specific",
            "twse_openapi",
            _evidence(
                "twse:official-field",
                "twse_openapi",
                evidence_role="substantive",
            ),
        )
    )

    result = _collect(registry, required_families=("twse_openapi",))

    assert result.status == "available"
    assert result.can_support_completion(("twse:official-field",)) is True


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (_evidence("late", "mops", available_at="2026-08-04T00:00:00+08:00"), "post_as_of"),
        (_evidence("summary", "annual_report", is_summary_only=True), "summary_only"),
    ],
)
def test_post_as_of_and_summary_only_evidence_remain_unresolved(evidence, reason) -> None:
    registry = EvidenceProducerRegistry()
    registry.register(Producer("only.producer", evidence.source_family, evidence))

    result = _collect(registry, required_families=(evidence.source_family,))

    assert result.status == "unresolved"
    assert result.substantive_evidence_ids == ()
    assert result.can_support_completion((evidence.evidence_id,)) is False
    assert any(reason in item for item in result.unresolved_reasons)
    if reason == "post_as_of":
        assert result.evidence == ()
    else:
        assert result.evidence == (evidence,)


def test_conflicting_evidence_is_absent_from_admitted_result() -> None:
    first = _evidence("mops:115Q1", "mops")
    conflicting = replace(first, evidence_handle="sha256:different")
    registry = EvidenceProducerRegistry()
    registry.register(Producer("mops.first", "mops", first))
    registry.register(Producer("mops.second", "mops", conflicting))

    result = _collect(
        registry, required_families=("mops", "issuer_ir")
    )

    assert result.status == "unresolved"
    assert result.evidence == ()
    assert result.substantive_evidence_ids == ()
    assert result.can_support_completion(("mops:115Q1",)) is False
    assert any("conflict" in item for item in result.unresolved_reasons)
    assert any("missing:issuer_ir" in item for item in result.unresolved_reasons)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issuer_id", "wrong-issuer"),
        ("security_code", "2317"),
    ],
)
def test_registry_rejects_cross_issuer_output(field, value) -> None:
    evidence = replace(_evidence("wrong-issuer", "mops"), **{field: value})
    registry = EvidenceProducerRegistry()
    registry.register(Producer("mops.wrong-issuer", "mops", evidence))

    result = _collect(registry, required_families=("mops",))

    assert result.status == "unresolved"
    assert result.evidence == ()
    assert any(f"{field}_mismatch" in item for item in result.unresolved_reasons)


def test_registry_preserves_source_reported_name_variation() -> None:
    registry = EvidenceProducerRegistry()
    evidence = _evidence(
        "short-name", "twse_openapi", reported_company_name="台積電"
    )
    registry.register(Producer("twse.short-name", "twse_openapi", evidence))

    result = _collect(registry)

    assert result.status == "available"
    assert result.evidence == (evidence,)


def test_registry_rejects_cross_market_or_cross_as_of_output() -> None:
    registry = EvidenceProducerRegistry()
    registry.register(
        Producer(
            "mops.wrong-market",
            "mops",
            _evidence("wrong-market", "mops", market="TPEx"),
        )
    )

    result = _collect(registry, required_families=("mops",))

    assert result.status == "unresolved"
    assert result.evidence == ()
    assert any("market_mismatch" in item for item in result.unresolved_reasons)


@pytest.mark.parametrize(
    "field",
    (
        "issuer_id",
        "security_code",
        "reported_company_name",
        "dataset_id",
        "source_locator",
    ),
)
def test_evidence_rejects_missing_issuer_or_source_location_binding(field) -> None:
    with pytest.raises(ProducerRegistryError, match=field):
        replace(_evidence("missing-binding", "mops"), **{field: " "})
