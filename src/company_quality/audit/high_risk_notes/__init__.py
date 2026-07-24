"""Build a closed nine-category register from PIT-admitted note evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Sequence

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.facts.financial import CanonicalFinancialFacts

Category = Literal[
    "related_parties",
    "guarantees",
    "litigation",
    "impairments",
    "receivables",
    "inventory",
    "contract_assets",
    "goodwill",
    "debt_maturities",
]
State = Literal["present", "missing", "not_applicable"]

CATEGORIES: tuple[Category, ...] = (
    "related_parties",
    "guarantees",
    "litigation",
    "impairments",
    "receivables",
    "inventory",
    "contract_assets",
    "goodwill",
    "debt_maturities",
)


class HighRiskNoteError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Coordinate:
    x0: Decimal
    y0: Decimal
    x1: Decimal
    y1: Decimal


@dataclass(frozen=True, slots=True)
class NoteObservation:
    category: Category
    state: State
    reason: str | None
    amount: Decimal | None
    unit: str | None
    period: str
    evidence_id: str | None
    page: int | None
    coordinate: Coordinate | None
    materiality: Decimal | None


@dataclass(frozen=True, slots=True)
class HighRiskNoteItem:
    category: Category
    state: State
    reason: str | None
    amount: Decimal | None
    unit: str | None
    period: str
    evidence_id: str | None
    page: int | None
    coordinate: Coordinate | None
    materiality: Decimal | None


@dataclass(frozen=True, slots=True)
class HighRiskNoteRegister:
    items: tuple[HighRiskNoteItem, ...]
    categories_covered: tuple[Category, ...]
    missing_categories: tuple[Category, ...]
    coverage: Decimal
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["HighRiskNoteRegister.v1"] = "HighRiskNoteRegister.v1"
    source_version: Literal[
        "CanonicalFinancialFacts.v1+AuditFilingInventory.v1"
    ] = "CanonicalFinancialFacts.v1+AuditFilingInventory.v1"
    formula_version: Literal["covered-categories-over-nine.v1"] = (
        "covered-categories-over-nine.v1"
    )
    model_version: Literal["no-rating-model.v1"] = "no-rating-model.v1"


def _validate_coordinate(value: Coordinate) -> None:
    values = (value.x0, value.y0, value.x1, value.y1)
    if any(item < 0 or item > 1 for item in values):
        raise HighRiskNoteError("coordinate values must be normalized to 0..1")
    if value.x0 >= value.x1 or value.y0 >= value.y1:
        raise HighRiskNoteError("coordinate bounds must have positive area")


def _validate_observation(
    observation: NoteObservation,
    inventory: AuditFilingInventory,
) -> None:
    if observation.category not in CATEGORIES:
        raise HighRiskNoteError("unsupported high-risk note category")
    if observation.period != inventory.period:
        raise HighRiskNoteError("note observation period does not match audit inventory")
    if not observation.reason or not observation.reason.strip():
        raise HighRiskNoteError("every note observation requires an explicit reason")
    if len(observation.reason) > 512:
        raise HighRiskNoteError("note observation reason exceeds 512 characters")
    if (observation.amount is None) != (observation.unit is None):
        raise HighRiskNoteError("amount and unit must be supplied together")
    if observation.amount is not None and abs(observation.amount) > Decimal("1e18"):
        raise HighRiskNoteError("note amount is outside the contract range")
    if observation.unit is not None and len(observation.unit) > 32:
        raise HighRiskNoteError("note unit exceeds 32 characters")
    if observation.materiality is not None and not (
        Decimal("0") <= observation.materiality <= Decimal("1")
    ):
        raise HighRiskNoteError("materiality must be within 0..1")

    evidence_parts = (
        observation.evidence_id,
        observation.page,
        observation.coordinate,
    )
    supplied = tuple(value is not None for value in evidence_parts)
    if any(supplied) and not all(supplied):
        raise HighRiskNoteError("evidence ID, page and coordinate must be supplied together")
    if observation.state in ("present", "not_applicable") and not all(supplied):
        raise HighRiskNoteError(f"{observation.state} requires explicit page evidence")
    if observation.state == "not_applicable" and any(
        value is not None
        for value in (observation.amount, observation.unit, observation.materiality)
    ):
        raise HighRiskNoteError("not_applicable cannot carry amount or materiality")
    if observation.evidence_id is not None:
        if observation.evidence_id not in inventory.evidence_ids:
            raise HighRiskNoteError("note evidence ID is not admitted by audit inventory")
        if len(observation.evidence_id) > 128:
            raise HighRiskNoteError("note evidence ID exceeds 128 characters")
        assert observation.page is not None
        assert observation.coordinate is not None
        if not 1 <= observation.page <= 4_294_967_295:
            raise HighRiskNoteError("page must be a positive uint32")
        _validate_coordinate(observation.coordinate)


def _validate_producers(
    financial_facts: CanonicalFinancialFacts,
    inventory: AuditFilingInventory,
) -> None:
    if financial_facts.schema_version != "CanonicalFinancialFacts.v1":
        raise HighRiskNoteError("expected CanonicalFinancialFacts.v1")
    if inventory.schema_version != "AuditFilingInventory.v1":
        raise HighRiskNoteError("expected AuditFilingInventory.v1")
    if not financial_facts.facts:
        raise HighRiskNoteError("canonical financial facts are required")
    if any(
        fact.period_end != inventory.fiscal_period_end
        for fact in financial_facts.facts
    ):
        raise HighRiskNoteError("financial fact period conflicts with audit inventory")


def _validate_pdf(inventory: AuditFilingInventory) -> None:
    if inventory.pdf_path is None or inventory.pdf_sha256 is None:
        raise HighRiskNoteError("verified PDF evidence is required for observations")
    if not inventory.pdf_path.is_file():
        raise HighRiskNoteError("verified PDF evidence file is missing")
    digest = hashlib.sha256(inventory.pdf_path.read_bytes()).hexdigest()
    if digest != inventory.pdf_sha256:
        raise HighRiskNoteError("audit PDF hash mismatch")
    if f"pdf:{digest}" not in inventory.evidence_ids:
        raise HighRiskNoteError("audit PDF evidence ID is not admitted")


def build_high_risk_note_register(
    financial_facts: CanonicalFinancialFacts,
    inventory: AuditFilingInventory,
    observations: Sequence[NoteObservation],
) -> HighRiskNoteRegister:
    _validate_producers(financial_facts, inventory)
    if observations:
        _validate_pdf(inventory)

    by_category: dict[Category, NoteObservation] = {}
    for observation in observations:
        _validate_observation(observation, inventory)
        if observation.category in by_category:
            raise HighRiskNoteError(
                f"duplicate note observation category: {observation.category}"
            )
        by_category[observation.category] = observation

    items: list[HighRiskNoteItem] = []
    covered: list[Category] = []
    missing: list[Category] = []
    for category in CATEGORIES:
        observation = by_category.get(category)
        if observation is None:
            item = HighRiskNoteItem(
                category=category,
                state="missing",
                reason="category_not_extracted_or_evidence_missing",
                amount=None,
                unit=None,
                period=inventory.period,
                evidence_id=None,
                page=None,
                coordinate=None,
                materiality=None,
            )
            missing.append(category)
        else:
            item = HighRiskNoteItem(
                category=observation.category,
                state=observation.state,
                reason=observation.reason,
                amount=observation.amount,
                unit=observation.unit,
                period=observation.period,
                evidence_id=observation.evidence_id,
                page=observation.page,
                coordinate=observation.coordinate,
                materiality=observation.materiality,
            )
            if observation.state == "missing":
                missing.append(category)
            else:
                covered.append(category)
        items.append(item)

    return HighRiskNoteRegister(
        items=tuple(items),
        categories_covered=tuple(covered),
        missing_categories=tuple(missing),
        coverage=Decimal(len(covered)) / Decimal(len(CATEGORIES)),
    )
