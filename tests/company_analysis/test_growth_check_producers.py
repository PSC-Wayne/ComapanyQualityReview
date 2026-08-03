from datetime import date
from decimal import Decimal

import pytest

from company_quality.company_analysis.growth_check_producers import (
    GROWTH_PRODUCER_SPECS,
    GrowthCheckInput,
    build_growth_check_assessment,
)
from company_quality.company_analysis.checklist_analysis import (
    _apply_growth_check_assessment,
    _placeholder_checks,
)


D = Decimal


def _input(check_id: str, **facts: object) -> GrowthCheckInput:
    return GrowthCheckInput(
        check_id=check_id,
        financial_period="115Q2",
        available_at="2026-08-01T18:00:00+08:00",
        facts=facts,
        evidence_by_fact={key: f"evidence:{check_id}:{key}" for key in facts},
    )


def _facts() -> dict[str, dict[str, object]]:
    return {
        "G08": {
            "prior_basic_eps": D("5"), "current_basic_eps": D("6.5"),
            "prior_attributable_profit": D("100"), "current_attributable_profit": D("110"),
            "prior_weighted_average_shares": D("20"), "current_weighted_average_shares": D("17"),
            "prior_diluted_shares": D("21"), "current_diluted_shares": D("18"),
            "treasury_share_change": D("2"), "capital_reduction_change": D("1"),
            "prior_net_debt": D("10"), "current_net_debt": D("15"),
        },
        "G14": {
            "prior_ppe": D("100"), "current_ppe": D("150"), "prior_cip": D("40"),
            "current_cip": D("10"), "prior_revenue": D("100"), "current_revenue": D("95"),
            "promise_type": "official_ramp", "promise_date": date(2026, 3, 31),
            "measurement_date": date(2026, 6, 30),
        },
        "G15": {
            "annual_periods": ("110", "111", "112", "113", "114"),
            "annual_ocf": (D("10"), D("9"), D("8"), D("7"), D("6")),
            "annual_capex": (D("20"), D("20"), D("20"), D("20"), D("20")),
            "unrestricted_cash": D("35"), "growth_claim": "高速成長",
            "growth_claim_horizon": "115-117",
        },
        "G16": {
            "prior_rd_expense": D("10"), "current_rd_expense": D("14"),
            "prior_capitalized_development": D("2"), "current_capitalized_development": D("4"),
            "prior_product_revenue": D("5"), "current_product_revenue": D("8"),
            "product_identity": "new-product-A",
        },
        "G17": {
            "opening_contract_liabilities": D("80"), "contract_liability_additions": D("70"),
            "revenue_recognized_from_contract_liabilities": D("40"), "refunds": D("10"),
            "closing_contract_liabilities": D("100"), "next_period_conversion": D("30"),
            "cancellation_or_refund_terms": "customer may cancel subject to 10% fee",
        },
        "G18": {
            "prior_backlog": D("100"), "current_backlog": D("140"), "pipeline": D("500"),
            "binding_backlog": D("120"), "cancellable_backlog": D("20"),
            "performance_period": "115Q3-116Q2", "pricing_adjustment_terms": "index linked",
            "expected_backlog_margin": D("0.20"), "backlog_cash_collected": D("30"),
        },
        "G20": {
            "geography": "Japan", "currency": "JPY", "prior_local_revenue": D("100"),
            "current_local_revenue": D("120"), "prior_translated_revenue": D("22"),
            "current_translated_revenue": D("23"), "local_profit": D("4"),
            "translation_fx_effect": D("-3"), "local_tax": D("1"),
            "remittance_restriction": "none disclosed in cited tax note",
        },
        "G21": {
            "acquisition_effective_date": date(2026, 1, 1), "organic_revenue": D("110"),
            "acquired_revenue": D("30"), "consideration": D("200"),
            "contingent_consideration": D("20"), "goodwill": D("90"),
            "acquisition_debt": D("50"), "shares_issued": D("10"),
            "post_deal_revenue": D("30"), "post_deal_profit": D("3"),
            "post_deal_cash_flow": D("2"),
        },
    }


@pytest.mark.parametrize("check_id", tuple(GROWTH_PRODUCER_SPECS))
def test_each_growth_producer_has_triggered_not_triggered_and_unresolved_states(check_id: str) -> None:
    facts = _facts()[check_id]
    triggered = build_growth_check_assessment((_input(check_id, **facts),)).by_check_id[check_id]
    assert triggered.status == "evaluated"
    assert triggered.applicability == "triggered"
    assert triggered.evidence_ids

    not_triggered_facts = dict(facts)
    if check_id == "G08":
        not_triggered_facts["current_basic_eps"] = D("5.2")
    elif check_id == "G14":
        not_triggered_facts["current_revenue"] = D("160")
    elif check_id == "G15":
        not_triggered_facts["annual_ocf"] = (D("30"),) * 5
    elif check_id == "G16":
        not_triggered_facts["current_rd_expense"] = D("7")
        not_triggered_facts["current_capitalized_development"] = D("2")
    elif check_id == "G17":
        not_triggered_facts["closing_contract_liabilities"] = D("80")
        not_triggered_facts["contract_liability_additions"] = D("50")
    elif check_id == "G18":
        not_triggered_facts["current_backlog"] = D("90")
    elif check_id == "G20":
        not_triggered_facts["current_local_revenue"] = D("90")
    else:
        not_triggered_facts["acquired_revenue"] = D("0")
        not_triggered_facts["post_deal_revenue"] = D("0")
    not_triggered = build_growth_check_assessment(
        (_input(check_id, **not_triggered_facts),)
    ).by_check_id[check_id]
    assert not_triggered.status == "evaluated"
    assert not_triggered.applicability == "not_triggered"

    missing = dict(facts)
    missing.pop(next(iter(GROWTH_PRODUCER_SPECS[check_id].required_facts)))
    unresolved = build_growth_check_assessment((_input(check_id, **missing),)).by_check_id[check_id]
    assert unresolved.status == "unresolved"
    assert unresolved.applicability == "unresolved"
    assert "缺少" in " ".join(unresolved.unresolved_reasons)


def test_nonpositive_growth_denominators_stay_unresolved() -> None:
    g08 = _facts()["G08"] | {"prior_basic_eps": D("0")}
    g20 = _facts()["G20"] | {"prior_local_revenue": D("-1")}

    result = build_growth_check_assessment((_input("G08", **g08), _input("G20", **g20)))

    assert result.by_check_id["G08"].status == "unresolved"
    assert result.by_check_id["G20"].status == "unresolved"
    assert all("正數分母" in " ".join(result.by_check_id[item].unresolved_reasons) for item in ("G08", "G20"))


def test_missing_fact_lineage_stays_unresolved_even_when_value_exists() -> None:
    item = _input("G18", **_facts()["G18"])
    evidence = dict(item.evidence_by_fact)
    evidence.pop("pricing_adjustment_terms")
    item = GrowthCheckInput(item.check_id, item.financial_period, item.available_at, item.facts, evidence)

    result = build_growth_check_assessment((item,)).by_check_id["G18"]

    assert result.status == "unresolved"
    assert "來源" in " ".join(result.unresolved_reasons)


def test_g17_roll_forward_must_reconcile_and_g18_never_counts_pipeline_as_backlog() -> None:
    broken = _facts()["G17"] | {"closing_contract_liabilities": D("101")}
    g17 = build_growth_check_assessment((_input("G17", **broken),)).by_check_id["G17"]
    assert g17.status == "unresolved"
    assert "roll-forward" in " ".join(g17.unresolved_reasons)

    g18 = build_growth_check_assessment((_input("G18", **_facts()["G18"]),)).by_check_id["G18"]
    assert "pipeline=500" in " ".join(g18.observations)
    assert "backlog=140" in " ".join(g18.observations)
    assert "不得視為backlog" in " ".join(g18.observations)


def test_g14_waits_for_official_promise_date_and_g15_reports_both_horizons_and_runway() -> None:
    early = _facts()["G14"] | {"measurement_date": date(2026, 3, 1)}
    g14 = build_growth_check_assessment((_input("G14", **early),)).by_check_id["G14"]
    assert g14.applicability == "not_triggered"
    assert "尚未到期" in " ".join(g14.observations)

    g15 = build_growth_check_assessment((_input("G15", **_facts()["G15"]),)).by_check_id["G15"]
    text = " ".join(g15.observations)
    assert "3A累計FCF" in text and "5A累計FCF" in text and "runway" in text


def test_g21_requires_post_deal_actuals_not_later_outcome_backfill() -> None:
    facts = _facts()["G21"]
    missing_actual = dict(facts)
    missing_actual.pop("post_deal_cash_flow")

    row = build_growth_check_assessment((_input("G21", **missing_actual),)).by_check_id["G21"]

    assert row.status == "unresolved"
    assert "post_deal_cash_flow" in " ".join(row.unresolved_reasons)


def test_checklist_hook_replaces_only_dedicated_growth_rows() -> None:
    base = _placeholder_checks("pending")
    assessment = build_growth_check_assessment((_input("G08", **_facts()["G08"]),))

    rows = {item.check_id: item for item in _apply_growth_check_assessment(base, assessment)}

    assert rows["G08"].status == "evaluated"
    assert rows["G08"].applicability == "triggered"
    assert rows["G21"].status == "unresolved"
    assert "需要" in " ".join(rows["G21"].unresolved_reasons)
    assert rows["R01"] == next(item for item in base if item.check_id == "R01")
