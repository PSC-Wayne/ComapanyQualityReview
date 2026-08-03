from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.solvency_commitment_risk import (
    AmountFact,
    CovenantTerm,
    CreditFacility,
    EquityBridge,
    LeaseTerms,
    SolvencyPeriodFacts,
    UnpaidCommitment,
    assess_solvency_commitment_risk,
)

AS_OF = "2026-08-03T12:00:00+08:00"
MONITOR = "2026-11-14"


def _citation() -> EvidenceCitation:
    excerpt = "借款、流動性、契約、租賃及承諾完整附註測試資料"
    return EvidenceCitation(
        evidence_id="note", source_id="annual:114", source_tier="official",
        url="https://mops.example/annual-114.pdf",
        content_sha256=sha256(excerpt.encode()).hexdigest(), period="114",
        available_at="2026-03-31T18:00:00+08:00", page=42,
        coordinate=(Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1")),
        verbatim_excerpt=excerpt,
    )


def _f(value: str) -> AmountFact:
    return AmountFact(Decimal(value), ("note",))


def _facts(*, current: bool) -> SolvencyPeriodFacts:
    return SolvencyPeriodFacts(
        period="114" if current else "113",
        short_term_debt=_f("80" if current else "40"),
        long_term_debt=_f("300" if current else "200"),
        debt_due_within_12m=_f("180" if current else "100"),
        gross_cash=_f("100" if current else "90"),
        restricted_cash=_f("10" if current else "5"),
        pledged_cash=_f("5" if current else "5"),
        non_remittable_cash=_f("5" if current else "5"),
        customer_money=_f("10" if current else "5"),
        defensible_12m_ocf=_f("20" if current else "30"),
        capex=_f("120" if current else "80"),
        long_lived_assets=_f("700" if current else "600"),
        roic=_f("0.08" if current else "0.09"),
        expensed_interest=_f("20" if current else "10"),
        capitalized_interest=_f("8" if current else "2"),
        total_liabilities=_f("400" if current else "500"),
        total_equity=_f("600" if current else "500"),
        lease_liabilities=_f("90" if current else "60"),
    )


def _complete(**overrides: object):
    values: dict[str, object] = {
        "current": _facts(current=True),
        "prior": _facts(current=False),
        "as_of": AS_OF,
        "monitoring_date": MONITOR,
        "debt_classes_complete": True,
        "maturity_schedule_complete": True,
        "cash_restrictions_complete": True,
        "long_debt_use_linked": True,
        "long_debt_use_evidence_ids": ("note",),
        "equity_bridge": EquityBridge(
            debt_repayment=Decimal("100"), equity_issuance=Decimal("50"),
            retained_earnings=Decimal("30"), valuation_and_oci=Decimal("20"),
            other_change=Decimal("0"), evidence_ids=("note",), complete=True,
        ),
        "facility_roster_complete": True,
        "facilities": (
            CreditFacility(
                facility_id="signed", undrawn_amount=_f("30"), signed=True,
                committed=True, cancellable_by_lender=False,
                conditions_satisfied=True,
                signed_at="2026-01-01T00:00:00+08:00",
                expires_at="2027-01-01T00:00:00+08:00",
                evidence_ids=("note",),
            ),
            CreditFacility(
                facility_id="oral", undrawn_amount=_f("999"), signed=False,
                committed=False, cancellable_by_lender=None,
                conditions_satisfied=None, signed_at=None, expires_at=None,
                evidence_ids=("note",), representation="oral_renewal",
            ),
        ),
        "covenant_roster_complete": True,
        "covenants": (
            CovenantTerm(
                covenant_id="current-ratio", actual=Decimal("0.9"),
                threshold=Decimal("1.0"), comparator="minimum",
                actual_evidence_ids=("note",), threshold_evidence_ids=("note",),
                waiver_at="2026-08-04T09:00:00+08:00",
                waiver_evidence_ids=("note",),
            ),
        ),
        "lease_terms": LeaseTerms(
            benefit_metric=Decimal("0.7"), benefit_description="成熟店回收率",
            exit_or_cancellation_terms="不可提前終止", exit_cost=Decimal("20"),
            evidence_ids=("note",), complete=True,
        ),
        "commitment_roster_complete": True,
        "commitments": (
            UnpaidCommitment(
                commitment_id="fab", unpaid_amount=_f("250"),
                cancellation_terms="不可取消", funding_source="自由現金與已簽授信",
                demand_support="已簽客戶訂單", evidence_ids=("note",),
            ),
        ),
        "citations": (_citation(),),
    }
    values.update(overrides)
    return assess_solvency_commitment_risk(**values)  # type: ignore[arg-type]


def test_complete_producer_triggers_exact_debt_interest_cash_lease_and_commitment_rows() -> None:
    result = _complete()
    rows = result.by_check_id

    assert (rows["R10"].status, rows["R10"].applicability) == ("evaluated", "triggered")
    assert "短期借款由40變為80" in rows["R10"].observations[0]
    assert "未使用總負債代理" in rows["R10"].observations[0]
    assert rows["R11"].applicability == "triggered"
    assert "自由現金=70" in rows["R11"].observations[0]
    assert "已簽承諾未動用授信=30" in rows["R11"].observations[0]
    assert "oral" in rows["R11"].observations[0]
    assert "費用化＋資本化" in rows["R13"].observations[0]
    assert "自由現金=70" in rows["R14"].observations[0]
    assert "權益橋接" in rows["R15"].observations[0]
    assert rows["R16"].applicability == "not_triggered"
    assert rows["R17"].applicability == "triggered"
    assert "as-of後豁免" in rows["R17"].observations[0]
    assert "不得回填" in rows["R17"].observations[0]
    assert rows["R18"].applicability == "triggered"
    assert rows["R38"].applicability == "triggered"
    assert all(row.monitoring_date == MONITOR for row in rows.values())


def test_complete_non_triggered_case_requires_terms_and_signed_facility() -> None:
    prior = _facts(current=True)
    current = SolvencyPeriodFacts(
        **{
            name: getattr(prior, name)
            for name in SolvencyPeriodFacts.__dataclass_fields__
            if name != "period"
        },
        period="115",
    )
    current = replace(
        current,
        debt_due_within_12m=_f("100"),
        restricted_cash=_f("0"),
        pledged_cash=_f("0"),
        non_remittable_cash=_f("0"),
        customer_money=_f("0"),
    )
    no_commitments = _complete(
        current=current,
        prior=prior,
        covenants=(CovenantTerm(
            covenant_id="debt-ratio", actual=Decimal("0.30"),
            threshold=Decimal("0.60"), comparator="maximum",
            actual_evidence_ids=("note",), threshold_evidence_ids=("note",),
        ),),
        commitments=(),
    )

    for check_id in ("R10", "R11", "R12", "R13", "R14", "R15", "R17", "R18", "R38"):
        assert no_commitments.by_check_id[check_id].status == "evaluated"
        assert no_commitments.by_check_id[check_id].applicability in {"not_triggered", "not_applicable"}
    assert no_commitments.by_check_id["R16"].applicability == "not_triggered"


def test_missing_classes_maturities_facilities_covenants_and_commitment_terms_stay_unresolved() -> None:
    result = _complete(
        debt_classes_complete=False,
        maturity_schedule_complete=False,
        cash_restrictions_complete=False,
        long_debt_use_linked=None,
        long_debt_use_evidence_ids=(),
        equity_bridge=None,
        facility_roster_complete=False,
        facilities=(),
        covenant_roster_complete=False,
        covenants=(),
        lease_terms=None,
        commitment_roster_complete=False,
        commitments=(UnpaidCommitment("unknown", _f("25"), None, None, None, ("note",)),),
    )

    rows = result.by_check_id
    for check_id in ("R10", "R11", "R12", "R14", "R15", "R16", "R17", "R18", "R38"):
        assert rows[check_id].status == "unresolved"
        assert rows[check_id].unresolved_reasons
    assert "總有息負債不得替代" in rows["R10"].unresolved_reasons[0]
    assert "口頭續借不得補缺口" in rows["R11"].unresolved_reasons[0]
    assert rows["R38"].applicability == "triggered"
