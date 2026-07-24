"""PIT valuation/upside diagnostic with no invented forward assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal, Mapping, Sequence

from company_quality.business.moat import BusinessMoatCandidate
from company_quality.facts.financial import CanonicalFinancialFacts
from company_quality.industry.peer_outlook import PeerOutlookEvidence
from company_quality.pit import AdmittedFactSet, FactAdmission
from company_quality.scoring.cash_balance import CashBalanceAllocationCandidate
from company_quality.scoring.earnings import EarningsCapitalEfficiencyCandidate


class ValuationDiagnosticError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CurrentPrice:
    value: Decimal
    currency: Literal["TWD"]
    price_time: str
    fact_id: str
    available_at: str


@dataclass(frozen=True, slots=True)
class RelativeValue:
    peer_ids: tuple[str, ...]
    multiple: Literal["pe", "pb", "ev_ebitda"]
    issuer_multiple: Decimal
    peer_median: Decimal
    implied_value: Decimal
    upside_pct: Decimal


@dataclass(frozen=True, slots=True)
class DcfValue:
    forecast_years: int
    revenue_growth: tuple[Decimal, ...]
    operating_margin: tuple[Decimal, ...]
    wacc: Decimal
    terminal_growth: Decimal
    net_debt: Decimal
    shares: Decimal
    implied_value: Decimal
    upside_pct: Decimal


@dataclass(frozen=True, slots=True)
class ReverseDcf:
    current_price: Decimal
    implied_revenue_cagr: Decimal
    implied_terminal_margin: Decimal
    wacc: Decimal
    feasibility: Literal["plausible", "stretched", "implausible"]


@dataclass(frozen=True, slots=True)
class Scenario:
    value: Decimal
    upside_pct: Decimal
    assumption_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Scenarios:
    bear: Scenario
    base: Scenario
    bull: Scenario


@dataclass(frozen=True, slots=True)
class ModelDisagreement:
    range_pct: Decimal
    max_model: str
    min_model: str


@dataclass(frozen=True, slots=True)
class Sensitivity:
    isolated: Literal[True]
    month24_upside_pct: Decimal
    month36_upside_pct: Decimal
    headline_eligible: Literal[False]


@dataclass(frozen=True, slots=True)
class ValuationUpsideDiagnostic:
    current_price: CurrentPrice
    route: Literal["relative", "dcf", "reverse_dcf", "multi_model"]
    relative_value: RelativeValue | None
    dcf: DcfValue | None
    reverse_dcf: ReverseDcf | None
    scenarios: Scenarios
    model_disagreement: ModelDisagreement
    horizon_months: Literal[12]
    sensitivity_24_36: Sensitivity | None
    evidence_ids: tuple[str, ...]
    metric_lineage: dict[str, tuple[str, ...]]
    coverage: Decimal
    available_at: str
    publication_status: Literal["NON_PUBLISHABLE_CANDIDATE"] = (
        "NON_PUBLISHABLE_CANDIDATE"
    )
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["ValuationUpsideDiagnostic.v1"] = (
        "ValuationUpsideDiagnostic.v1"
    )
    source_version: Literal[
        "AdmittedFactSet.v1+CanonicalFinancialFacts.v1+EarningsCapitalEfficiencyCandidate.v1+CashBalanceAllocationCandidate.v1+PeerOutlookEvidence.v1+BusinessMoatCandidate.v1"
    ] = "AdmittedFactSet.v1+CanonicalFinancialFacts.v1+EarningsCapitalEfficiencyCandidate.v1+CashBalanceAllocationCandidate.v1+PeerOutlookEvidence.v1+BusinessMoatCandidate.v1"
    formula_version: Literal["admitted-valuation-upside-decimal-return.v2"] = (
        "admitted-valuation-upside-decimal-return.v2"
    )
    model_version: Literal["explicit-assumptions-only.v1"] = (
        "explicit-assumptions-only.v1"
    )


def _instant(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValuationDiagnosticError(f"invalid {field}")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValuationDiagnosticError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValuationDiagnosticError(f"{field} must be timezone-aware")
    return result


def _decimal(
    value: object,
    field: str,
    *,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    positive: bool = False,
) -> Decimal:
    if isinstance(value, bool):
        raise ValuationDiagnosticError(f"invalid {field}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValuationDiagnosticError(f"invalid {field}") from exc
    if not result.is_finite():
        raise ValuationDiagnosticError(f"invalid {field}")
    if positive and result <= 0:
        raise ValuationDiagnosticError(f"{field} must be positive")
    if minimum is not None and result < minimum:
        raise ValuationDiagnosticError(f"{field} below minimum")
    if maximum is not None and result > maximum:
        raise ValuationDiagnosticError(f"{field} above maximum")
    return result


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValuationDiagnosticError(f"invalid {field}")
    return value


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValuationDiagnosticError(f"invalid {field}")
    return value.strip()


def _upside(value: Decimal, current: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 40
        return value / current - Decimal("1")


def _selected(admitted: AdmittedFactSet, fact_type: str) -> FactAdmission | None:
    if any(
        fact.fact_type == fact_type and fact.disposition == "blocked_conflict"
        for fact in admitted.facts
    ):
        raise ValuationDiagnosticError(f"unresolved conflict for {fact_type}")
    candidates = [
        fact for fact in admitted.facts
        if fact.fact_type == fact_type and fact.disposition == "admitted"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda fact: (_instant(fact.effective_at, fact.fact_id), fact.fact_id))
    latest_time = _instant(candidates[-1].effective_at, candidates[-1].fact_id)
    latest = [fact for fact in candidates if _instant(fact.effective_at, fact.fact_id) == latest_time]
    values = {repr(sorted(_mapping(fact.value, fact.fact_id).items())) for fact in latest}
    if len(values) != 1:
        raise ValuationDiagnosticError(f"conflicting latest {fact_type} facts")
    return min(latest, key=lambda fact: fact.fact_id)


def _validate_producers(
    admitted: AdmittedFactSet,
    financials: CanonicalFinancialFacts,
    earnings: EarningsCapitalEfficiencyCandidate,
    cash: CashBalanceAllocationCandidate,
    peers: PeerOutlookEvidence,
    business: BusinessMoatCandidate,
) -> None:
    expected = (
        (admitted.schema_version, "AdmittedFactSet.v1"),
        (financials.schema_version, "CanonicalFinancialFacts.v1"),
        (earnings.schema_version, "EarningsCapitalEfficiencyCandidate.v1"),
        (cash.schema_version, "CashBalanceAllocationCandidate.v1"),
        (peers.schema_version, "PeerOutlookEvidence.v1"),
        (business.schema_version, "BusinessMoatCandidate.v1"),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise ValuationDiagnosticError("BLOCKED_CONTRACT: producer schema mismatch")
    if not financials.facts:
        raise ValuationDiagnosticError("BLOCKED_CONTRACT: financial facts required")
    if peers.status != "available":
        raise ValuationDiagnosticError("BLOCKED_CONTRACT: peer outlook unavailable")
    if peers.issuer_id != business.issuer_id:
        raise ValuationDiagnosticError("BLOCKED_CONTRACT: issuer binding mismatch")
    if tuple(peers.peer_ids) != tuple(business.peer_ids):
        raise ValuationDiagnosticError("BLOCKED_CONTRACT: peer binding mismatch")


def _scenario_fact(
    admitted: AdmittedFactSet, name: Literal["bear", "base", "bull"]
) -> FactAdmission:
    fact = _selected(admitted, f"valuation.scenario.{name}")
    if fact is None:
        raise ValuationDiagnosticError(f"BLOCKED_CONTRACT: missing {name} scenario")
    return fact


def build_valuation_upside_diagnostic(
    admitted: AdmittedFactSet,
    financials: CanonicalFinancialFacts,
    earnings: EarningsCapitalEfficiencyCandidate,
    cash: CashBalanceAllocationCandidate,
    peers: PeerOutlookEvidence,
    business: BusinessMoatCandidate,
) -> ValuationUpsideDiagnostic:
    _validate_producers(admitted, financials, earnings, cash, peers, business)
    decision = _instant(admitted.decision_time, "decision_time")
    price_fact = _selected(admitted, "official_close_price")
    if price_fact is None:
        raise ValuationDiagnosticError("BLOCKED_CONTRACT: official close price required")
    price_data = _mapping(price_fact.value, price_fact.fact_id)
    current_value = _decimal(price_data.get("value"), "current price", positive=True)
    if price_data.get("currency") != "TWD":
        raise ValuationDiagnosticError("current price currency must be TWD")
    price_time = _instant(price_data.get("price_time"), "price_time")
    if price_time > decision:
        raise ValuationDiagnosticError("official close price is later than decision time")
    current = CurrentPrice(
        current_value, "TWD", price_time.isoformat(), price_fact.fact_id,
        _instant(price_fact.available_at, "price available_at").isoformat(),
    )

    relative_fact = _selected(admitted, "valuation.relative")
    dcf_fact = _selected(admitted, "valuation.dcf")
    reverse_fact = _selected(admitted, "valuation.reverse_dcf")
    if not any((relative_fact, dcf_fact, reverse_fact)):
        raise ValuationDiagnosticError("BLOCKED_CONTRACT: explicit valuation model required")
    lineage: dict[str, tuple[str, ...]] = {"current_price": (price_fact.fact_id,)}
    model_values: dict[str, Decimal] = {}

    relative = None
    if relative_fact:
        value = _mapping(relative_fact.value, relative_fact.fact_id)
        peer_ids_raw = value.get("peer_ids")
        if not isinstance(peer_ids_raw, Sequence) or isinstance(peer_ids_raw, (str, bytes)):
            raise ValuationDiagnosticError("invalid relative peer_ids")
        peer_ids = tuple(_text(item, "relative peer_id", 4096) for item in peer_ids_raw)
        if (
            not peer_ids
            or len(peer_ids) > 50
            or len(set(peer_ids)) != len(peer_ids)
            or not set(peer_ids).issubset(peers.peer_ids)
        ):
            raise ValuationDiagnosticError("relative peer_ids are not bound to T12")
        multiple = value.get("multiple")
        if multiple not in {"pe", "pb", "ev_ebitda"}:
            raise ValuationDiagnosticError("invalid relative multiple")
        implied = _decimal(value.get("implied_value"), "relative implied value", positive=True)
        relative = RelativeValue(
            peer_ids, multiple,
            _decimal(value.get("issuer_multiple"), "issuer multiple"),
            _decimal(value.get("peer_median"), "peer median"),
            implied, _upside(implied, current_value),
        )
        model_values["relative"] = implied
        lineage["relative_value"] = (relative_fact.fact_id,)

    dcf = None
    if dcf_fact:
        value = _mapping(dcf_fact.value, dcf_fact.fact_id)
        years_raw = value.get("forecast_years")
        if isinstance(years_raw, bool) or not isinstance(years_raw, int) or not 5 <= years_raw <= 10:
            raise ValuationDiagnosticError("forecast_years must be 5..10")
        def series(name: str, low: str, high: str) -> tuple[Decimal, ...]:
            raw = value.get(name)
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                raise ValuationDiagnosticError(f"invalid {name}")
            parsed = tuple(
                _decimal(item, name, minimum=Decimal(low), maximum=Decimal(high))
                for item in raw
            )
            if len(parsed) != years_raw:
                raise ValuationDiagnosticError(f"{name} length must equal forecast_years")
            return parsed
        growth = series("revenue_growth", "-1", "5")
        margins = series("operating_margin", "-1", "1")
        wacc = _decimal(value.get("wacc"), "wacc", minimum=Decimal("0"), maximum=Decimal("1"))
        terminal = _decimal(value.get("terminal_growth"), "terminal growth", minimum=Decimal("-0.1"), maximum=Decimal("0.1"))
        if wacc <= terminal:
            raise ValuationDiagnosticError("wacc must exceed terminal growth")
        implied = _decimal(value.get("implied_value"), "DCF implied value", positive=True)
        dcf = DcfValue(
            years_raw, growth, margins, wacc, terminal,
            _decimal(value.get("net_debt"), "net debt"),
            _decimal(value.get("shares"), "shares", positive=True),
            implied, _upside(implied, current_value),
        )
        model_values["dcf"] = implied
        lineage["dcf"] = (dcf_fact.fact_id,)

    reverse = None
    if reverse_fact:
        value = _mapping(reverse_fact.value, reverse_fact.fact_id)
        feasibility = value.get("feasibility")
        if feasibility not in {"plausible", "stretched", "implausible"}:
            raise ValuationDiagnosticError("invalid reverse DCF feasibility")
        reverse_price = _decimal(value.get("current_price"), "reverse current price", positive=True)
        if reverse_price != current_value:
            raise ValuationDiagnosticError("reverse DCF current price mismatch")
        reverse = ReverseDcf(
            reverse_price,
            _decimal(value.get("implied_revenue_cagr"), "implied revenue CAGR", minimum=Decimal("-1"), maximum=Decimal("5")),
            _decimal(value.get("implied_terminal_margin"), "implied terminal margin", minimum=Decimal("-1"), maximum=Decimal("1")),
            _decimal(value.get("wacc"), "reverse WACC", minimum=Decimal("0"), maximum=Decimal("1")),
            feasibility,
        )
        model_values["reverse_dcf"] = current_value
        lineage["reverse_dcf"] = (reverse_fact.fact_id,)

    scenario_facts = {
        name: _scenario_fact(admitted, name)
        for name in ("bear", "base", "bull")
    }
    known_assumptions = {
        fact.fact_id for fact in admitted.facts if fact.disposition == "admitted"
    }
    known_assumptions.update(peers.outlook_evidence_ids)
    known_assumptions.update(business.outlook_evidence_ids)
    scenarios: dict[str, Scenario] = {}
    for name, fact in scenario_facts.items():
        value = _mapping(fact.value, fact.fact_id)
        target = _decimal(value.get("value"), f"{name} value", positive=True)
        raw_ids = value.get("assumption_ids")
        if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)):
            raise ValuationDiagnosticError(f"invalid {name} assumption_ids")
        ids = tuple(_text(item, f"{name} assumption_id", 4096) for item in raw_ids)
        if (
            not ids
            or len(ids) > 32
            or len(set(ids)) != len(ids)
            or not set(ids).issubset(known_assumptions)
        ):
            raise ValuationDiagnosticError(f"unbound {name} assumption_ids")
        scenarios[name] = Scenario(target, _upside(target, current_value), ids)
        lineage[f"scenario_{name}"] = (fact.fact_id, *ids)
    if not scenarios["bear"].value <= scenarios["base"].value <= scenarios["bull"].value:
        raise ValuationDiagnosticError("scenario values must be bear <= base <= bull")

    sensitivity = None
    sensitivity_fact = _selected(admitted, "valuation.sensitivity_24_36")
    if sensitivity_fact:
        value = _mapping(sensitivity_fact.value, sensitivity_fact.fact_id)
        if value.get("isolated") is not True or value.get("headline_eligible") is not False:
            raise ValuationDiagnosticError("24/36 sensitivity must be isolated and ineligible")
        sensitivity = Sensitivity(
            True,
            _decimal(value.get("month24_upside_pct"), "month24 upside"),
            _decimal(value.get("month36_upside_pct"), "month36 upside"),
            False,
        )
        lineage["sensitivity_24_36"] = (sensitivity_fact.fact_id,)

    names = sorted(model_values)
    max_model = max(names, key=lambda name: (model_values[name], name))
    min_model = min(names, key=lambda name: (model_values[name], name))
    with localcontext() as context:
        context.prec = 40
        range_pct = (model_values[max_model] - model_values[min_model]) / current_value * 100
    if range_pct > 1000:
        raise ValuationDiagnosticError("model disagreement exceeds contract range")
    route = names[0] if len(names) == 1 else "multi_model"
    model_fact_ids = tuple(
        fact.fact_id for fact in (relative_fact, dcf_fact, reverse_fact) if fact
    )
    evidence_list = [
        price_fact.fact_id,
        *model_fact_ids,
        *(fact.fact_id for fact in scenario_facts.values()),
        *(item for scenario in scenarios.values() for item in scenario.assumption_ids),
    ]
    if sensitivity_fact is not None:
        evidence_list.append(sensitivity_fact.fact_id)
    evidence_ids = tuple(dict.fromkeys(evidence_list))
    used_facts = [
        fact for fact in admitted.facts if fact.fact_id in set(evidence_ids)
    ]
    available = max(
        *(
            _instant(fact.available_at, f"{fact.fact_id} available_at")
            for fact in used_facts
        ),
        _instant(peers.available_at, "peer outlook available_at"),
        _instant(business.available_at, "business moat available_at"),
    )
    coverage = Decimal(2 + len(model_values)) / Decimal(5)
    return ValuationUpsideDiagnostic(
        current_price=current,
        route=route,
        relative_value=relative,
        dcf=dcf,
        reverse_dcf=reverse,
        scenarios=Scenarios(**scenarios),
        model_disagreement=ModelDisagreement(range_pct, max_model, min_model),
        horizon_months=12,
        sensitivity_24_36=sensitivity,
        evidence_ids=evidence_ids,
        metric_lineage=lineage,
        coverage=coverage,
        available_at=available.isoformat(),
    )


__all__ = [
    "ValuationDiagnosticError",
    "ValuationUpsideDiagnostic",
    "build_valuation_upside_diagnostic",
]
