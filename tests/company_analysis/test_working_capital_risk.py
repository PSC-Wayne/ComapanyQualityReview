from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.working_capital_risk import (
    WorkingCapitalPeriod,
    WorkingCapitalQualitativeEvidence,
    build_working_capital_risk,
)


def _citation(evidence_id: str, period: str = "114Q4") -> EvidenceCitation:
    excerpt = f"{evidence_id} 官方附註原文"
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=f"official:{evidence_id}",
        source_tier="official",
        url=f"https://mops.twse.com.tw/{evidence_id}",
        content_sha256=sha256(excerpt.encode()).hexdigest(),
        period=period,
        available_at="2026-03-31T18:00:00+08:00",
        page=1,
        coordinate=(Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1")),
        verbatim_excerpt=excerpt,
        source_format="pdf",
        locator="page:1",
    )


def _period(period: str, *, annual: bool, **overrides: object) -> WorkingCapitalPeriod:
    values: dict[str, object] = {
        "period": period,
        "annual": annual,
        "period_days": 365 if annual else 90,
        "revenue": Decimal("1000"),
        "cost_of_revenue": Decimal("600"),
        "purchases": Decimal("620"),
        "receivables": Decimal("100"),
        "contract_assets": Decimal("30"),
        "inventory": Decimal("120"),
        "prepayments": Decimal("20"),
        "accounts_payable": Decimal("80"),
        "operating_cash_flow": Decimal("150"),
        "net_income": Decimal("120"),
        "capex": Decimal("-50"),
        "evidence_ids": (f"facts:{period}",),
    }
    values.update(overrides)
    return WorkingCapitalPeriod(**values)  # type: ignore[arg-type]


def _five_years() -> tuple[WorkingCapitalPeriod, ...]:
    return tuple(
        _period(
            f"{year}Q4",
            annual=True,
            operating_cash_flow=Decimal(str(130 + index * 5)),
            net_income=Decimal(str(100 + index * 5)),
            capex=Decimal("-40"),
        )
        for index, year in enumerate(range(110, 115))
    )


def _qualitative() -> tuple[WorkingCapitalQualitativeEvidence, ...]:
    return tuple(
        WorkingCapitalQualitativeEvidence(kind=kind, signal="counterevidence", citation=_citation(kind))
        for kind in (
            "receivables_aging",
            "ecl_assessment",
            "receivables_roll_forward",
            "contract_asset_roll_forward",
            "inventory_aging",
            "inventory_allowance_roll_forward",
            "prepayment_roll_forward",
            "payables_roll_forward",
            "subsequent_collection",
            "subsequent_sale",
        )
    ) + tuple(
        WorkingCapitalQualitativeEvidence(
            kind="revenue_recognition_kam",
            signal="counterevidence",
            citation=_citation(f"revenue-kam-{year}", f"{year}Q4"),
        )
        for year in (112, 113, 114)
    )


def test_quantitative_anomalies_trigger_but_do_not_become_evaluated_safety() -> None:
    prior = _period("114Q1", annual=False)
    current = _period(
        "115Q1",
        annual=False,
        revenue=Decimal("1050"),
        receivables=Decimal("180"),
        contract_assets=Decimal("60"),
        inventory=Decimal("190"),
        prepayments=Decimal("50"),
        accounts_payable=Decimal("140"),
        operating_cash_flow=Decimal("260"),
    )

    result = build_working_capital_risk(
        comparison_periods=(prior, current), annual_periods=_five_years(), qualitative_evidence=()
    )
    checks = {item.check_id: item for item in result.checks}

    for check_id in ("R01", "R02", "R03", "R05", "R06", "R19"):
        assert checks[check_id].applicability == "triggered"
        assert checks[check_id].status == "unresolved"
    assert (checks["R07"].applicability, checks["R07"].status) == ("triggered", "evaluated")
    assert checks["R07"].observations == ("payables_release",)
    assert "average" in " ".join(checks["R01"].observations).lower()
    assert "purchases" in " ".join(checks["R05"].observations).lower()
    assert "fraud" not in str(asdict(result)).lower()


def test_complete_counterevidence_can_evaluate_not_triggered_rows_and_labels_cogs_proxy() -> None:
    prior = _period("114Q1", annual=False, purchases=None)
    current = _period("115Q1", annual=False, purchases=None)

    result = build_working_capital_risk(
        comparison_periods=(prior, current),
        annual_periods=_five_years(),
        qualitative_evidence=_qualitative(),
    )
    checks = {item.check_id: item for item in result.checks}

    assert all(
        (checks[check_id].status, checks[check_id].applicability)
        == ("evaluated", "not_triggered")
        for check_id in ("R01", "R02", "R03", "R04", "R05", "R06", "R19", "R20")
    )
    assert "COGS approximation" in " ".join(checks["R05"].observations)
    assert len(checks["R20"].evidence_ids) == 3
    assert result.peer_inventory_context_ids == ()


def test_supported_working_capital_release_is_identified_for_r07() -> None:
    prior = _period("114Q1", annual=False, operating_cash_flow=Decimal("90"))
    current = _period(
        "115Q1",
        annual=False,
        receivables=Decimal("70"),
        inventory=Decimal("90"),
        accounts_payable=Decimal("100"),
        operating_cash_flow=Decimal("220"),
    )

    result = build_working_capital_risk(
        comparison_periods=(prior, current),
        annual_periods=_five_years(),
        qualitative_evidence=(),
    )
    r07 = next(item for item in result.checks if item.check_id == "R07")

    assert (r07.applicability, r07.status) == ("triggered", "evaluated")
    assert "receivables_release" in r07.observations
    assert "inventory_release" in r07.observations
    assert "payables_release" in r07.observations


def test_missing_values_nonpositive_denominators_partial_horizons_and_current_feed_absence_stay_unresolved() -> None:
    result = build_working_capital_risk(
        comparison_periods=(
            _period("114Q1", annual=False),
            _period("115Q1", annual=False, revenue=Decimal("0"), inventory=None),
        ),
        annual_periods=_five_years()[:3],
        qualitative_evidence=_qualitative(),
        current_feed_available=False,
        peer_inventory_context_ids=("peer:inventory:context",),
    )
    checks = {item.check_id: item for item in result.checks}

    assert all(item.status == "unresolved" for item in checks.values())
    assert checks["R08"].unresolved_reasons
    assert checks["R09"].unresolved_reasons
    assert checks["R20"].unresolved_reasons
    assert result.peer_inventory_context_ids == ("peer:inventory:context",)
    assert all("=0" not in observation for item in checks.values() for observation in item.observations)
