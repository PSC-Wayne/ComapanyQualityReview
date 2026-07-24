"""Downside, causal-risk and stress diagnostic sourced from governed assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from company_quality.audit.gates import AuditGateDecision
from company_quality.audit.high_risk_notes import HighRiskNoteRegister
from company_quality.business.moat import BusinessMoatCandidate
from company_quality.downside.assumptions import DownsideAssumptionBundle
from company_quality.facts.financial import CanonicalFinancialFacts
from company_quality.governance.people_adaptability import GovernancePeopleCandidate
from company_quality.industry.peer_outlook import PeerOutlookEvidence
from company_quality.scoring.cash_balance import CashBalanceAllocationCandidate


class DownsideDiagnosticError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VulnerabilityConstruct:
    raw_value: Decimal | None
    normalised_score: None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Constructs:
    maximum_drawdown_vulnerability: VulnerabilityConstruct
    permanent_capital_loss_vulnerability: VulnerabilityConstruct
    material_adverse_event_vulnerability: VulnerabilityConstruct


@dataclass(frozen=True, slots=True)
class RiskItem:
    cause: str
    exposure: str
    transmission_path: str
    buffer: str | None
    indicator: str
    severity: Literal["low", "medium", "high", "critical"]
    trigger: str
    threshold: Decimal | None
    evidence_id: str


@dataclass(frozen=True, slots=True)
class StressScenario:
    assumption_ids: tuple[str, ...]
    equity_value_change_pct: Decimal
    liquidity_state: Literal["adequate", "tight", "insolvent"]


@dataclass(frozen=True, slots=True)
class StressPack:
    bear: StressScenario
    base: StressScenario
    bull: StressScenario


@dataclass(frozen=True, slots=True)
class BombCandidate:
    event_id: str
    event_type: Literal[
        "formal_adverse_opinion", "formal_disclaimer", "confirmed_fraud",
        "default", "insolvency", "major_regulatory_action", "other_governed",
    ]
    authoritative: bool
    material: bool
    current_relevance: bool
    authority_source_id: str
    effective_at: str
    expires_at: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DownsideStressDiagnostic:
    horizon_months: Literal[12]
    constructs: Constructs
    risk_items: tuple[RiskItem, ...]
    stress_pack: StressPack
    bomb_candidate: BombCandidate | None
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
    schema_version: Literal["DownsideStressDiagnostic.v1"] = (
        "DownsideStressDiagnostic.v1"
    )
    source_version: Literal[
        "DownsideAssumptionBundle.v1+CanonicalFinancialFacts.v1+AuditGateDecision.v1+HighRiskNoteRegister.v1+CashBalanceAllocationCandidate.v1+PeerOutlookEvidence.v1+BusinessMoatCandidate.v1+GovernancePeopleCandidate.v1"
    ] = "DownsideAssumptionBundle.v1+CanonicalFinancialFacts.v1+AuditGateDecision.v1+HighRiskNoteRegister.v1+CashBalanceAllocationCandidate.v1+PeerOutlookEvidence.v1+BusinessMoatCandidate.v1+GovernancePeopleCandidate.v1"
    formula_version: Literal["governed-downside-diagnostic.v1"] = (
        "governed-downside-diagnostic.v1"
    )
    model_version: Literal["normalisation-pending-t23"] = (
        "normalisation-pending-t23"
    )


def _instant(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DownsideDiagnosticError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise DownsideDiagnosticError(f"{field} must be timezone-aware")
    return result


def _validate_inputs(
    assumptions: DownsideAssumptionBundle,
    financials: CanonicalFinancialFacts,
    gate: AuditGateDecision,
    notes: HighRiskNoteRegister,
    cash: CashBalanceAllocationCandidate,
    peers: PeerOutlookEvidence,
    business: BusinessMoatCandidate,
    governance: GovernancePeopleCandidate,
) -> None:
    expected = (
        (assumptions.schema_version, "DownsideAssumptionBundle.v1"),
        (financials.schema_version, "CanonicalFinancialFacts.v1"),
        (gate.schema_version, "AuditGateDecision.v1"),
        (notes.schema_version, "HighRiskNoteRegister.v1"),
        (cash.schema_version, "CashBalanceAllocationCandidate.v1"),
        (peers.schema_version, "PeerOutlookEvidence.v1"),
        (business.schema_version, "BusinessMoatCandidate.v1"),
        (governance.schema_version, "GovernancePeopleCandidate.v1"),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise DownsideDiagnosticError("BLOCKED_CONTRACT: producer schema mismatch")
    if assumptions.status != "ready":
        raise DownsideDiagnosticError("BLOCKED_CONTRACT: T18A assumptions are not ready")
    if not financials.facts:
        raise DownsideDiagnosticError("BLOCKED_CONTRACT: financial facts required")
    if peers.status != "available" or peers.issuer_id != business.issuer_id:
        raise DownsideDiagnosticError("BLOCKED_CONTRACT: issuer/peer evidence mismatch")
    if tuple(peers.peer_ids) != tuple(business.peer_ids):
        raise DownsideDiagnosticError("BLOCKED_CONTRACT: peer set mismatch")
    if (
        len(assumptions.constructs) != 3
        or {item.name for item in assumptions.constructs} != {
            "maximum_drawdown_vulnerability",
            "permanent_capital_loss_vulnerability",
            "material_adverse_event_vulnerability",
        }
        or any(
            item.state != "present"
            or item.raw_value is None
            or not item.evidence_ids
            for item in assumptions.constructs
        )
    ):
        raise DownsideDiagnosticError("BLOCKED_CONTRACT: all explicit constructs required")
    if not 1 <= len(assumptions.risk_items) <= 100:
        raise DownsideDiagnosticError(
            "BLOCKED_CONTRACT: 1..100 causal risk items required"
        )
    if (
        len(assumptions.stress_assumptions) != 3
        or {item.scenario for item in assumptions.stress_assumptions}
        != {"bear", "base", "bull"}
    ):
        raise DownsideDiagnosticError("BLOCKED_CONTRACT: complete stress pack required")


def build_downside_stress_diagnostic(
    assumptions: DownsideAssumptionBundle,
    financials: CanonicalFinancialFacts,
    gate: AuditGateDecision,
    notes: HighRiskNoteRegister,
    cash: CashBalanceAllocationCandidate,
    peers: PeerOutlookEvidence,
    business: BusinessMoatCandidate,
    governance: GovernancePeopleCandidate,
) -> DownsideStressDiagnostic:
    _validate_inputs(
        assumptions, financials, gate, notes, cash, peers, business, governance
    )

    construct_by_name = {item.name: item for item in assumptions.constructs}
    constructs = Constructs(**{
        name: VulnerabilityConstruct(
            construct_by_name[name].raw_value,
            None,
            construct_by_name[name].evidence_ids,
        )
        for name in (
            "maximum_drawdown_vulnerability",
            "permanent_capital_loss_vulnerability",
            "material_adverse_event_vulnerability",
        )
    })
    risk_items = tuple(
        RiskItem(
            item.cause, item.exposure, item.transmission_path, item.buffer,
            item.indicator, item.severity, item.trigger, item.threshold,
            item.evidence_id,
        )
        for item in assumptions.risk_items
    )
    stress_by_name = {item.scenario: item for item in assumptions.stress_assumptions}
    stress_pack = StressPack(**{
        name: StressScenario(
            stress_by_name[name].assumption_ids,
            stress_by_name[name].equity_value_change_pct,
            stress_by_name[name].liquidity_state,
        )
        for name in ("bear", "base", "bull")
    })

    event = assumptions.bomb_event
    expected_formal = (
        {
            "adverse": "formal_adverse_opinion",
            "disclaimer": "formal_disclaimer",
        }.get(gate.opinion_type)
        if gate.opinion_type is not None
        else None
    )
    if expected_formal and (event is None or event.event_type != expected_formal):
        raise DownsideDiagnosticError(
            "BLOCKED_CONTRACT: T07 formal opinion lacks matching Bomb event"
        )
    if expected_formal and event is not None and not (
        event.authoritative and event.material and event.current_relevance
    ):
        raise DownsideDiagnosticError(
            "BLOCKED_CONTRACT: formal Bomb event must be authoritative, material and current"
        )
    if event and event.event_type in {
        "formal_adverse_opinion", "formal_disclaimer"
    } and event.event_type != expected_formal:
        raise DownsideDiagnosticError(
            "BLOCKED_CONTRACT: Bomb event conflicts with T07 opinion"
        )
    bomb = None
    if event and event.authoritative and event.material and event.current_relevance:
        bomb = BombCandidate(
            event.event_id, event.event_type, event.authoritative, event.material,
            event.current_relevance, event.authority_source_id, event.effective_at,
            event.expires_at, event.evidence_ids,
        )

    direct_evidence = [
        *(evidence for item in assumptions.constructs for evidence in item.evidence_ids),
        *(item.evidence_id for item in assumptions.risk_items),
        *(evidence for item in assumptions.stress_assumptions for evidence in item.assumption_ids),
    ]
    if bomb is not None:
        direct_evidence.extend(bomb.evidence_ids)
    evidence_ids = tuple(dict.fromkeys(direct_evidence))
    if not evidence_ids or len(evidence_ids) > 128:
        raise DownsideDiagnosticError("BLOCKED_CONTRACT: evidence count must be 1..128")

    metric_lineage = {
        **{
            f"construct.{item.name}": item.evidence_ids
            for item in assumptions.constructs
        },
        **{
            f"risk.{item.fact_id}": (item.evidence_id,)
            for item in assumptions.risk_items
        },
        **{
            f"stress.{item.scenario}": item.assumption_ids
            for item in assumptions.stress_assumptions
        },
        "bomb_candidate": () if bomb is None else bomb.evidence_ids,
    }
    coverages = (
        assumptions.coverage,
        financials.fact_coverage,
        gate.coverage,
        notes.coverage,
        cash.coverage,
        peers.coverage,
        business.coverage,
        governance.coverage,
    )
    if any(not Decimal("0") <= value <= Decimal("1") for value in coverages):
        raise DownsideDiagnosticError("upstream coverage outside 0..1")
    available_values = [
        *(_instant(fact.available_at, "financial fact available_at") for fact in financials.facts),
        _instant(gate.available_at, "gate available_at"),
        _instant(notes.available_at, "notes available_at"),
        _instant(cash.available_at, "cash available_at"),
        _instant(peers.available_at, "peers available_at"),
        _instant(business.available_at, "business available_at"),
        _instant(governance.available_at, "governance available_at"),
        _instant(assumptions.available_at, "assumptions available_at"),
    ]
    available = max(item for item in available_values if item is not None)
    return DownsideStressDiagnostic(
        horizon_months=12,
        constructs=constructs,
        risk_items=risk_items,
        stress_pack=stress_pack,
        bomb_candidate=bomb,
        evidence_ids=evidence_ids,
        metric_lineage=metric_lineage,
        coverage=min(coverages),
        available_at=available.isoformat(),
    )


__all__ = [
    "DownsideDiagnosticError",
    "DownsideStressDiagnostic",
    "build_downside_stress_diagnostic",
]
