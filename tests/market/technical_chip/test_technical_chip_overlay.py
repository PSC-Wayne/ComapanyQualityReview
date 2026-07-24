"""Black-box contract tests for the T15 technical/chip overlay public seam."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
from jsonschema import Draft202012Validator

from company_quality.market.technical_chip import (
    MarketAuthority,
    TechnicalChipError,
    build_technical_chip_overlay,
    probe_twse_daily_authority,
)
from company_quality.pit import AdmittedFactSet, FactAdmission


DECISION_TIME = "2026-03-03T23:00:00+08:00"
SOURCE_ID = "twse-daily-official"
OFFICIAL_SHA = "a" * 64
GENERATION_ID = "generation-20260303-technical-chip"
PRODUCER_SHA = "c" * 40


def authority(
    *,
    source_id: str = SOURCE_ID,
    authority_type: Literal["official"] = "official",
    content_sha256: str = OFFICIAL_SHA,
    url: str = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY",
) -> MarketAuthority:
    return MarketAuthority(
        source_id=source_id,
        authority_type=authority_type,
        url=url,
        content_sha256=content_sha256,
        available_at="2026-03-03T14:30:00+08:00",
        retrieved_at="2026-03-03T18:00:00+08:00",
    )


def admitted_fact(
    fact_id: str,
    fact_type: str,
    value,
    *,
    source_id: str = SOURCE_ID,
    effective_at: str = "2026-03-03T00:00:00+08:00",
    available_at: str = "2026-03-03T14:30:00+08:00",
    disposition: str = "admitted",
    failure_reason: str | None = None,
) -> FactAdmission:
    is_admitted = disposition == "admitted"
    return FactAdmission(
        fact_id=fact_id,
        fact_type=fact_type,
        value=value if is_admitted else None,
        unit=None,
        effective_at=effective_at,
        announced_at=None,
        available_at=available_at,
        retrieved_at="2026-03-03T18:00:00+08:00",
        valid_from=available_at,
        valid_to=None,
        authority_rank=1,
        append_sequence=1,
        version_id="v1",
        source_id=source_id,
        disposition=disposition,
        failure_reason=failure_reason,
        admission_coverage=1.0 if is_admitted else 0.0,
    )


def fact_set(facts, *, schema_version: str = "AdmittedFactSet.v1") -> AdmittedFactSet:
    return AdmittedFactSet(
        decision_time=DECISION_TIME,
        facts=tuple(facts),
        schema_version=schema_version,
    )


def session_date(index: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=index)).isoformat()


def daily_bars(count: int = 62, *, include_unavailable_final: bool = False):
    facts = []
    for index in range(count):
        date = session_date(index)
        close = Decimal(100 + index)
        facts.append(
            admitted_fact(
                f"bar:{date}",
                "market.daily_bar",
                {
                    "date": date,
                    "open": str(close - 1),
                    "high": str(close + 2),
                    "low": str(close - 2),
                    "close": str(close),
                    "volume": str(1_000_000 + index),
                },
                effective_at=f"{date}T13:30:00+08:00",
            )
        )
    if include_unavailable_final:
        facts.append(
            admitted_fact(
                "bar:2026-03-04",
                "market.daily_bar",
                {},
                effective_at="2026-03-04T13:30:00+08:00",
                available_at="2026-03-04T14:30:00+08:00",
                disposition="blocked_unavailable",
                failure_reason="not_yet_available",
            )
        )
    return facts


def chip_facts():
    facts = []
    for index in range(62):
        date = session_date(index)
        for fact_type, value in (
            ("chip.foreign_net", "1"),
            ("chip.dealer_net", "2"),
            ("chip.investment_trust_net", "3"),
            ("chip.margin_balance", str(1000 + index)),
        ):
            facts.append(
                admitted_fact(
                    f"{fact_type}:{date}",
                    fact_type,
                    {"date": date, "value": value},
                    effective_at=f"{date}T18:00:00+08:00",
                )
            )
    return facts


def build(facts, *, authorities=None):
    return build_technical_chip_overlay(
        fact_set(facts),
        tuple(authorities or (authority(),)),
        generation_id=GENERATION_ID,
        producer_candidate_sha=PRODUCER_SHA,
    )


def decimal(value) -> Decimal:
    return Decimal(str(value))


def test_uses_trading_session_windows_and_sample_stdev_for_frozen_technical_metrics() -> None:
    result = build(daily_bars())

    assert result.window_start == "2026-01-21"
    assert result.window_end == "2026-03-03"
    assert result.warmup_state == "ready"
    assert decimal(result.technical_signals.return_1m) == Decimal("0.15")
    assert decimal(result.technical_signals.return_2m) == Decimal(
        "0.352941176470588235294117647058823529412"
    )
    assert decimal(result.technical_signals.ma20_gap) == Decimal(
        "0.062706270627062706270627062706270627063"
    )
    assert decimal(result.technical_signals.ma60_gap) == Decimal(
        "0.224334600760456273764258555133079847909"
    )
    assert decimal(result.technical_signals.volatility_20d) == pytest.approx(
        Decimal("0.0002620357905388930829910871820551714557498"),
        rel=Decimal("1e-25"),
    )


def test_total_return_back_adjusts_cash_and_capital_actions_in_ohlc_and_returns() -> None:
    facts = []
    for index in range(62):
        date = session_date(index)
        price = Decimal("100") if index < 21 else Decimal("90") if index < 41 else Decimal("45")
        facts.append(
            admitted_fact(
                f"bar:{date}",
                "market.daily_bar",
                {
                    "date": date,
                    "open": str(price),
                    "high": str(price),
                    "low": str(price),
                    "close": str(price),
                    "volume": "1000000",
                },
                effective_at=f"{date}T13:30:00+08:00",
            )
        )
    facts.extend(
        (
            admitted_fact(
                "cash:cash-20260122",
                "market.cash_distribution",
                {"ex_date": "2026-01-22", "cash_per_share": "10", "event_id": "cash-20260122"},
            ),
            admitted_fact(
                "action:split-20260211",
                "market.capital_action",
                {
                    "ex_date": "2026-02-11",
                    "adjustment_factor": "0.5",
                    "pre_event_denominator": 1_000_000,
                    "post_event_denominator": 2_000_000,
                    "event_id": "split-20260211",
                },
            ),
        )
    )

    result = build(facts)

    assert len(result.price_series) == 42
    assert {decimal(bar.adjusted_open) for bar in result.price_series} == {Decimal("45")}
    assert {decimal(bar.adjusted_high) for bar in result.price_series} == {Decimal("45")}
    assert {decimal(bar.adjusted_low) for bar in result.price_series} == {Decimal("45")}
    assert {decimal(bar.adjusted_close) for bar in result.price_series} == {Decimal("45")}
    assert decimal(result.technical_signals.return_1m) == Decimal("0")
    assert decimal(result.technical_signals.return_2m) == Decimal("0")
    assert result.capital_event_adjustment.applied is True
    assert result.capital_event_adjustment.corporate_action_ids == (
        "cash-20260122",
        "split-20260211",
    )
    assert result.capital_event_adjustment.pre_event_denominator == 1_000_000
    assert result.capital_event_adjustment.post_event_denominator == 2_000_000
    assert decimal(result.capital_event_adjustment.adjustment_factor) == Decimal("0.45")


def test_unavailable_final_bar_is_excluded_and_sixty_vs_sixty_one_valid_bars_is_exact() -> None:
    insufficient = build(daily_bars(60, include_unavailable_final=True))
    ready = build(daily_bars(61, include_unavailable_final=True))

    assert insufficient.warmup_state == "insufficient_history"
    assert insufficient.technical_signals.return_2m is None
    assert insufficient.technical_signals.ma60_gap is None
    assert ready.warmup_state == "ready"
    assert ready.window_end == "2026-03-02"
    assert all(bar.date != "2026-03-04" for bar in ready.price_series)
    assert "not_yet_available" in ready.failure_reasons.values()


def test_all_three_institutions_and_margin_balance_use_twenty_session_windows() -> None:
    result = build(daily_bars() + chip_facts())

    assert decimal(result.chip_signals.foreign_net_20d) == Decimal("20")
    assert decimal(result.chip_signals.dealer_net_20d) == Decimal("40")
    assert decimal(result.chip_signals.investment_trust_net_20d) == Decimal("60")
    assert decimal(result.chip_signals.margin_balance_change) == Decimal("20")


def tdcc_facts(*, cross_capital: bool = False, with_adjustment: bool = True):
    facts = []
    previous = (("1-399", 500, 550_000, "55"), ("400-999", 50, 200_000, "20"), ("1000+", 20, 250_000, "25"))
    if cross_capital:
        previous = tuple(
            (band, holders, shares // 2, pct)
            for band, holders, shares, pct in previous
        )
    current = (("1-399", 480, 500_000, "50"), ("400-999", 55, 200_000, "20"), ("1000+", 25, 300_000, "30"))
    for as_of, rows in (("2026-02-20", previous), ("2026-02-27", current)):
        for band, holders, shares, pct in rows:
            facts.append(
                admitted_fact(
                    f"tdcc:{as_of}:{band}",
                    "chip.tdcc_band",
                    {
                        "as_of": as_of,
                        "band": band,
                        "min_lots": 1 if band == "1-399" else 400 if band == "400-999" else 1000,
                        "holder_count": holders,
                        "share_count": shares,
                        "share_pct": pct,
                        "outstanding_shares": 1_000_000 if not cross_capital or as_of.endswith("27") else 500_000,
                        "evidence_id": f"tdcc-evidence:{as_of}:{band}",
                    },
                )
            )
        facts.append(
            admitted_fact(
                f"tdcc-complete:{as_of}",
                "chip.tdcc_distribution_complete",
                {
                    "as_of": as_of,
                    "complete": True,
                    "band_count": 3,
                    "evidence_id": f"tdcc-complete-evidence:{as_of}",
                },
            )
        )
    if cross_capital and with_adjustment:
        facts.append(
            admitted_fact(
                "action:tdcc-split",
                "market.capital_action",
                {
                    "ex_date": "2026-02-24",
                    "adjustment_factor": "0.5",
                    "pre_event_denominator": 500_000,
                    "post_event_denominator": 1_000_000,
                    "event_id": "tdcc-split",
                },
            )
        )
    return facts


def test_tdcc_retains_complete_distribution_ratios_denominator_and_previous_changes() -> None:
    result = build(daily_bars() + tdcc_facts())

    assert result.tdcc_state == "present"
    assert result.tdcc_as_of == "2026-02-27"
    assert [band.band for band in result.tdcc_bands] == ["1-399", "400-999", "1000+"]
    assert [band.share_count for band in result.tdcc_bands] == [500_000, 200_000, 300_000]
    by_band = {band.band: band for band in result.tdcc_bands}
    assert by_band["1000+"].previous_as_of == "2026-02-20"
    assert decimal(by_band["1000+"].previous_share_pct) == Decimal("25")
    assert decimal(by_band["1000+"].change_pct_points) == Decimal("5")
    assert result.tdcc_headline_ratios.denominator_outstanding_shares == 1_000_000
    assert decimal(result.tdcc_headline_ratios.gte_400_lots_share_pct) == Decimal("50")
    assert decimal(result.tdcc_headline_ratios.gte_1000_lots_share_pct) == Decimal("30")


def test_tdcc_complete_marker_band_count_mismatch_fails_closed() -> None:
    facts = daily_bars() + tdcc_facts()
    marker = next(
        fact for fact in facts if fact.fact_id == "tdcc-complete:2026-02-27"
    )
    facts[facts.index(marker)] = admitted_fact(
        marker.fact_id,
        marker.fact_type,
        {**marker.value, "band_count": 4},
    )
    with pytest.raises(TechnicalChipError, match="band_count"):
        build(facts)


def test_cross_capital_tdcc_without_governed_adjustment_nulls_changes() -> None:
    result = build(daily_bars() + tdcc_facts(cross_capital=True, with_adjustment=False))

    assert all(band.previous_share_pct is None for band in result.tdcc_bands)
    assert all(band.change_pct_points is None for band in result.tdcc_bands)
    assert result.capital_event_adjustment.applied is False
    assert "cross_capital_event_missing_adjustment" in result.failure_reasons.values()


def test_missing_and_not_applicable_are_distinct_and_never_fabricate_zero() -> None:
    facts = daily_bars() + [
        admitted_fact(
            "tdcc-state",
            "chip.tdcc_distribution_complete",
            {"as_of": "2026-02-27", "state": "missing", "reason": "official_file_unavailable"},
        ),
        admitted_fact(
            "insider-na",
            "chip.insider_holding_change",
            {
                "person_type": "supervisor",
                "as_of": "2026-02-28",
                "holding_change_shares": 0,
                "holding_change_pct": None,
                "state": "not_applicable",
                "reason": "issuer_has_no_supervisor",
                "evidence_id": None,
            },
        ),
    ]
    result = build(facts)

    assert result.tdcc_state == "missing"
    assert result.tdcc_state_reason == "official_file_unavailable"
    assert result.tdcc_bands == ()
    assert result.tdcc_headline_ratios.ratio_state == "missing"
    assert result.tdcc_headline_ratios.gte_400_lots_share_pct is None
    assert result.insider_holding_changes[0].state == "not_applicable"
    assert result.insider_holding_changes[0].holding_change_pct is None


def test_insider_and_pledge_changes_preserve_person_type_as_of_state_and_evidence() -> None:
    facts = daily_bars() + [
        admitted_fact(
            "insider:director:20260228",
            "chip.insider_holding_change",
            {
                "person_type": "director",
                "as_of": "2026-02-28",
                "holding_change_shares": 1250,
                "holding_change_pct": "0.25",
                "state": "present",
                "reason": None,
                "evidence_id": "mops-insider-1",
            },
        ),
        admitted_fact(
            "pledge:major:20260228",
            "chip.pledge_change",
            {
                "person_type": "major_shareholder",
                "as_of": "2026-02-28",
                "pledged_share_change": -500,
                "pledged_ratio_change_pct": "-0.1",
                "state": "present",
                "reason": None,
                "evidence_id": "mops-pledge-1",
            },
        ),
    ]
    result = build(facts)

    insider = result.insider_holding_changes[0]
    pledge = result.pledge_changes[0]
    assert (insider.person_type, insider.as_of, insider.evidence_id) == (
        "director", "2026-02-28", "mops-insider-1"
    )
    assert decimal(insider.holding_change_pct) == Decimal("0.25")
    assert (pledge.person_type, pledge.as_of, pledge.evidence_id) == (
        "major_shareholder", "2026-02-28", "mops-pledge-1"
    )
    assert decimal(pledge.pledged_ratio_change_pct) == Decimal("-0.1")


def test_every_used_fact_is_exactly_bound_to_authority_lineage() -> None:
    facts = daily_bars(61)
    result = build(facts)

    record = next(item for item in result.authority_records if item.used)
    assert record.source_id == SOURCE_ID
    assert record.authority_type == "official"
    assert record.url == "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    assert record.content_sha256 == OFFICIAL_SHA
    assert record.available_at == "2026-03-03T14:30:00+08:00"
    assert record.retrieved_at == "2026-03-03T18:00:00+08:00"
    assert set(result.metric_lineage["price_series"]) == {fact.fact_id for fact in facts}


def test_unbound_source_and_unresolved_same_rank_authority_conflict_fail_closed() -> None:
    unbound = daily_bars(61)
    unbound[0] = admitted_fact(
        "bar:unbound", "market.daily_bar",
        {"date": "2026-01-01", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"},
        source_id="unknown-source",
    )
    with pytest.raises(TechnicalChipError, match="source|authority|bind"):
        build(unbound)

    conflicting = (
        authority(),
        authority(content_sha256="b" * 64, url="https://www.twse.com.tw/conflicting-copy"),
    )
    with pytest.raises(TechnicalChipError, match="conflict|same.rank|authority"):
        build(daily_bars(61), authorities=conflicting)


def test_overlay_is_literal_independent_and_has_no_headline_rating_surface() -> None:
    result = build(daily_bars(61))
    payload = asdict(result)

    assert result.rating_independence == "INDEPENDENT_NO_HEADLINE_EFFECT"
    assert result.independent_from_ratings is True
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"
    forbidden = {"quality", "quality_rating", "rating", "stars", "faces", "bomb"}
    assert forbidden.isdisjoint(payload)


def test_envelope_versions_publication_coverage_confidence_and_closed_schema() -> None:
    result = build(daily_bars(61) + chip_facts() + tdcc_facts())
    assert result.generation_id == GENERATION_ID
    assert result.producer_candidate_sha == PRODUCER_SHA
    assert result.schema_version == "TechnicalChipOverlay.v1"
    assert result.source_version == "AdmittedFactSet.v1+official-market-authority.v1"
    assert result.formula_version == "technical-chip-total-return.v1"
    assert result.model_version == "technical-chip-deterministic-1.0.0"
    assert result.publication_status == "NON_PUBLISHABLE_CANDIDATE"
    assert Decimal("0") <= decimal(result.overlay_coverage) <= Decimal("1")
    assert Decimal("0") <= decimal(result.confidence) <= Decimal("1")
    assert isinstance(result.failure_reasons, dict)

    schema_path = (
        Path(__file__).parents[3]
        / "src/company_quality/market/technical_chip/contracts/TechnicalChipOverlay.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(result), default=float))
    validator.validate(payload)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "TechnicalChipOverlay.v1"
    assert schema["additionalProperties"] is False
    assert next(validator.iter_errors(payload | {"quality": 5})).validator == "additionalProperties"
    nested = dict(payload)
    nested["technical_signals"] = payload["technical_signals"] | {"stars": 5}
    assert next(validator.iter_errors(nested)).validator == "additionalProperties"


def test_producer_major_version_mismatch_is_blocked() -> None:
    mismatched = fact_set(daily_bars(61), schema_version="AdmittedFactSet.v2")
    with pytest.raises(TechnicalChipError, match="AdmittedFactSet.v1|producer|schema"):
        build_technical_chip_overlay(
            mismatched,
            (authority(),),
            generation_id=GENERATION_ID,
            producer_candidate_sha=PRODUCER_SHA,
        )


@pytest.mark.authority_probe
def test_live_twse_daily_authority_probe_is_official_hash_bound_and_nonempty() -> None:
    live, row_count = probe_twse_daily_authority()
    assert live.authority_type == "official"
    assert "twse.com.tw" in live.url
    assert re.fullmatch(r"[0-9a-f]{64}", live.content_sha256)
    assert row_count > 0
    assert live.available_at
    assert live.retrieved_at
