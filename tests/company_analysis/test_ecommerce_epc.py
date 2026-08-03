from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.checklist_analysis import (
    _apply_ecommerce_epc_assessment,
    _industry_route,
    _placeholder_checks,
)
from company_quality.company_analysis.ecommerce_epc import (
    BusinessModelRouteClaim,
    EcommerceEpcEvidenceFact,
    build_ecommerce_epc_assessment,
)

AS_OF = "2026-03-31T23:59:59+08:00"

ROUTE_PARTS = {
    "ecommerce_platform": ("platform_operations", "third_party_transactions", "transaction_linked_revenue"),
    "project_engineering_epc": ("engineering_procurement_construction", "customer_project_contracts", "project_performance_revenue"),
}
ROW_FACTS = {
    "I-ECOM-01": ("gmv", "revenue", "take_rate"),
    "I-ECOM-02": ("traffic", "conversion_rate", "customer_acquisition_cost", "retention"),
    "I-ECOM-03": ("merchant_concentration", "customer_concentration"),
    "I-ECOM-04": ("logistics_model", "inventory_ownership", "fulfilment_cost", "customer_collection_timing", "merchant_settlement_timing"),
    "I-EPC-01": ("signed_backlog", "binding_terms", "cancellation_terms", "price_adjustment", "execution_period"),
    "I-EPC-02": ("progress_measure", "total_cost_estimate", "project_margin", "cost_overrun"),
    "I-EPC-03": ("contract_assets", "contract_liabilities", "billing_milestone", "receivable_conversion"),
    "I-EPC-04": ("retention_receivable", "warranty_provision", "change_orders", "claims", "acceptance_disputes"),
    "I-EPC-05": ("customer_collection", "supplier_payment", "advance_receipts", "project_cash_conversion"),
}


def _citation(evidence_id: str, excerpt: str, *, available_at: str = "2026-03-31T18:00:00+08:00") -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=evidence_id.split(":", 1)[0],
        source_tier="issuer_primary",
        url=f"https://issuer.example/{evidence_id.replace(':', '-')}.pdf",
        content_sha256=sha256(excerpt.encode()).hexdigest(),
        period="2025Q4",
        available_at=available_at,
        page=20,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="pdf",
        locator=f"page:20:{evidence_id}",
    )


def _route(model: str, part: str, index: int, *, available_at: str = "2026-03-31T18:00:00+08:00") -> BusinessModelRouteClaim:
    text = f"官方商業模式揭露：{part}。"
    return BusinessModelRouteClaim(
        business_model=model,  # type: ignore[arg-type]
        claim_part=part,  # type: ignore[arg-type]
        value=text,
        period="2025Q4",
        citation=_citation(f"annual:route:{index}", text, available_at=available_at),
    )


def _routes(model: str) -> tuple[BusinessModelRouteClaim, ...]:
    return tuple(_route(model, part, index) for index, part in enumerate(ROUTE_PARTS[model]))


def _fact(fact_type: str, index: int, *, signal: str = "counterevidence", role: str = "substantive", available_at: str = "2026-03-31T18:00:00+08:00") -> EcommerceEpcEvidenceFact:
    value = f"原文數值或條款:{fact_type}:{index}"
    definition = f"公司原始揭露定義:{fact_type}"
    return EcommerceEpcEvidenceFact(
        fact_type=fact_type,  # type: ignore[arg-type]
        value=value,
        definition=definition,
        period="2025Q4",
        scope="consolidated:business-model",
        signal=signal,  # type: ignore[arg-type]
        evidence_role=role,  # type: ignore[arg-type]
        citation=_citation(f"annual:fact:{fact_type}:{index}", f"{definition}；{value}", available_at=available_at),
    )


@pytest.mark.parametrize("check_id", tuple(ROW_FACTS))
def test_complete_claim_parts_evaluate_each_routed_row(check_id: str) -> None:
    model = "ecommerce_platform" if check_id.startswith("I-ECOM") else "project_engineering_epc"
    facts = tuple(_fact(fact_type, index) for index, fact_type in enumerate(ROW_FACTS[check_id]))

    assessment = build_ecommerce_epc_assessment(_routes(model), facts, as_of=AS_OF)

    assert assessment.route == model
    assert assessment.route_status == "routed"
    row = assessment.check(check_id)
    assert (row.status, row.applicability) == ("evaluated", "not_triggered")
    assert row.observations == tuple(item.value for item in facts)
    assert all(item.definition in row.inference_chain for item in facts)


@pytest.mark.parametrize("check_id", tuple(ROW_FACTS))
def test_partial_claim_is_retained_but_unresolved(check_id: str) -> None:
    model = "ecommerce_platform" if check_id.startswith("I-ECOM") else "project_engineering_epc"
    fact = _fact(ROW_FACTS[check_id][0], 0, signal="risk")

    row = build_ecommerce_epc_assessment(_routes(model), (fact,), as_of=AS_OF).check(check_id)

    assert (row.status, row.applicability) == ("unresolved", "triggered")
    assert row.observations == (fact.value,)
    assert "尚缺" in row.unresolved_reasons[0]


def test_missing_or_conflicting_business_model_claims_never_route() -> None:
    assert build_ecommerce_epc_assessment((), (), as_of=AS_OF).route_status == "unresolved"
    partial = _routes("ecommerce_platform")[:-1]
    assert build_ecommerce_epc_assessment(partial, (), as_of=AS_OF).route_status == "unresolved"
    conflict = (*_routes("ecommerce_platform"), *_routes("project_engineering_epc"))
    result = build_ecommerce_epc_assessment(conflict, (), as_of=AS_OF)
    assert result.route_status == "unresolved"
    assert "conflicting" in result.route_unresolved_reasons[0]


def test_company_name_and_broad_industry_code_are_not_route_inputs() -> None:
    # The public seam intentionally has neither company name nor industry code.
    with pytest.raises(TypeError):
        build_ecommerce_epc_assessment((), (), as_of=AS_OF, company_name="電商工程王")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        build_ecommerce_epc_assessment((), (), as_of=AS_OF, industry_code="32")  # type: ignore[call-arg]


def test_future_route_or_fact_evidence_is_excluded_at_point_in_time() -> None:
    future_route = tuple(
        replace(item, citation=replace(item.citation, available_at="2026-04-01T00:00:00+08:00"))
        for item in _routes("ecommerce_platform")
    )
    assert build_ecommerce_epc_assessment(future_route, (), as_of=AS_OF).route_status == "unresolved"

    future_fact = _fact("gmv", 1, available_at="2026-04-01T00:00:00+08:00")
    row = build_ecommerce_epc_assessment(_routes("ecommerce_platform"), (future_fact,), as_of=AS_OF).check("I-ECOM-01")
    assert future_fact.citation.evidence_id not in row.evidence_ids
    assert row.status == "unresolved"


def test_context_or_empty_definition_cannot_complete_claim() -> None:
    facts = tuple(_fact(item, index, role="context") for index, item in enumerate(ROW_FACTS["I-ECOM-01"]))
    row = build_ecommerce_epc_assessment(_routes("ecommerce_platform"), facts, as_of=AS_OF).check("I-ECOM-01")
    assert row.status == "unresolved"
    with pytest.raises(ValueError, match="definition"):
        replace(_fact("gmv", 1), definition="")


def test_checklist_hook_routes_by_assessment_and_overlays_only_selected_rows() -> None:
    from types import SimpleNamespace

    assessment = build_ecommerce_epc_assessment(
        _routes("ecommerce_platform"),
        tuple(_fact(item, index) for index, item in enumerate(ROW_FACTS["I-ECOM-01"])),
        as_of=AS_OF,
    )
    # Code 32 alone is not a route; the official business-model assessment is.
    bundle = SimpleNamespace(identity=SimpleNamespace(industry_code="32"))
    assert _industry_route(bundle, "general_non_financial") == "not_applicable"  # type: ignore[arg-type]
    assert _industry_route(bundle, "general_non_financial", assessment) == "ecommerce_platform"  # type: ignore[arg-type]

    placeholders = _placeholder_checks("尚未准入", "ecommerce_platform")
    overlaid = _apply_ecommerce_epc_assessment(placeholders, assessment)
    rows = {item.check_id: item for item in overlaid}
    assert rows["I-ECOM-01"].status == "evaluated"
    assert rows["I-ECOM-02"].status == "unresolved"
    assert not any(item.check_id.startswith("I-EPC") for item in overlaid)
