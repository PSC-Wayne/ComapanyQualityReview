import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
from jsonschema import Draft202012Validator

from company_quality.lab.cohort import OfficialUniverseMember, build_adverse_control_cohort
from company_quality.lab.outcome_labels import (
    CorporateAction,
    DailyClose,
    GovernedOutcomeEvent,
    OfficialMarketTotalReturnInput,
    OfficialTotalReturnPoint,
    OutcomeLabelError,
    PITWealthInput,
    SuspensionInterval,
    add_calendar_months_clamped,
    build_outcome_label_set,
)


def sha(char: str) -> str:
    return char * 64


def cohort():
    return build_adverse_control_cohort(
        [OfficialUniverseMember(
            issuer_id="issuer-1",
            security_code="1101",
            company_name="Issuer One",
            market="TWSE",
            listed_on="2020-01-01",
            delisted_on=None,
            evidence_ids=("cohort-source",),
            available_at="2024-01-10T09:00:00+08:00",
        )],
        (),
        market="TWSE",
        cohort_asof="2024-01-10T12:00:00+08:00",
        min_followup_days=0,
        eligibility_version="1.0.0",
        producer_shas={"T03": sha("a"), "T04": sha("b"), "T06": sha("c")},
        generation_id="r9",
        producer_candidate_sha=sha("d"),
    )


def close(day: str, value: str) -> DailyClose:
    return DailyClose(
        effective_on=day,
        unadjusted_close=Decimal(value),
        available_at=f"{day}T18:00:00+08:00",
        evidence_ids=(f"close:{day}",),
    )


def wealth_input(
    closes,
    *,
    actions=(),
    suspensions=(),
    missing=(),
    events=(),
    complete="2024-01-01",
    price_basis: Literal[
        "unadjusted_close_with_actions", "pre_adjusted_total_return"
    ] = "unadjusted_close_with_actions",
):
    return PITWealthInput(
        issuer_id="issuer-1",
        wealth_series_ref="pit://wealth/TWSE/1101/v1",
        daily_closes=tuple(closes),
        corporate_actions=tuple(actions),
        suspension_intervals=tuple(suspensions),
        unresolved_missing_dates=tuple(missing),
        governed_events=tuple(events),
        complete_through=complete,
        evidence_ids=("wealth-input",),
        price_basis=price_basis,
    )


def official_benchmark(market: Literal["TWSE", "TPEx"] = "TWSE"):
    source = (
        "https://openapi.twse.com.tw/v1/indicesReport/MFI94U"
        if market == "TWSE"
        else "https://www.tpex.org.tw/openapi/v1/tpex_reward_index"
    )
    return OfficialMarketTotalReturnInput(
        market=market,
        series_ref=source,
        points=(
            OfficialTotalReturnPoint(
                effective_on="2020-12-31",
                value=Decimal("200"),
                available_at="2020-12-31T18:00:00+08:00",
                evidence_ids=(f"{market}:total-return:baseline",),
            ),
            OfficialTotalReturnPoint(
                effective_on="2022-01-01",
                value=Decimal("220"),
                available_at="2022-01-01T18:00:00+08:00",
                evidence_ids=(f"{market}:total-return:end",),
            ),
        ),
        complete_through="2024-01-01",
        evidence_ids=(f"{market}:official-total-return-index",),
    )


def build(source, *, benchmark=None):
    return build_outcome_label_set(
        cohort(),
        source,
        issuer_id="issuer-1",
        decision_time="2021-01-01T12:00:00+08:00",
        base_label_version="1.0.0",
        producer_shas={"T20": sha("e"), "PITWealthInput": sha("f")},
        generation_id="r9",
        producer_candidate_sha=sha("1"),
        market="TWSE",
        official_market_total_return=benchmark or official_benchmark(),
        same_market_median_return=Decimal("0.05"),
        same_market_median_source_ref="generation://r9/TWSE/2021-01-01/median",
    )


def test_calendar_month_horizons_clamp_month_end() -> None:
    from datetime import date

    assert add_calendar_months_clamped(date(2020, 2, 29), 12).isoformat() == "2021-02-28"
    assert add_calendar_months_clamped(date(2021, 1, 31), 1).isoformat() == "2021-02-28"


def test_cash_and_share_actions_restore_wealth_without_false_drawdown() -> None:
    action = CorporateAction(
        effective_on="2021-03-01",
        share_multiplier=Decimal("2"),
        cash_per_pre_action_share=Decimal("10"),
        terminal_cash=False,
        available_at="2021-03-01T18:00:00+08:00",
        evidence_ids=("action:split-and-cash",),
    )
    result = build(wealth_input([
        close("2020-12-31", "100"), close("2021-03-01", "45"),
        close("2022-01-01", "45"), close("2023-01-01", "45"),
        close("2024-01-01", "45"),
    ], actions=[action]))

    assert result.drawdown_episodes == ()
    assert result.adverse_labels == ()
    assert result.wealth_series_ref == "OutcomeLabelSet.adjusted_wealth_series"
    assert tuple(
        point.adjusted_wealth_index for point in result.adjusted_wealth_series
    ) == (
        Decimal("100.000000"), Decimal("100.000000"),
        Decimal("100.000000"), Decimal("100.000000"), Decimal("100.000000"),
    )
    assert "action:split-and-cash" in result.adjustment_evidence_ids
    assert result.censoring_state == "fully_observed"


def test_drawdown_over_50_and_governed_event_return_to_authority() -> None:
    event = GovernedOutcomeEvent(
        effective_on="2021-06-15",
        adverse_label="default",
        official_reason="Court-confirmed default",
        available_at="2021-06-15T18:00:00+08:00",
        evidence_ids=("authority:default",),
    )
    result = build(wealth_input([
        close("2020-12-31", "100"),
        close("2021-06-01", "40"),
        close("2022-01-01", "40"),
        close("2023-01-01", "40"),
        close("2024-01-01", "40"),
    ], events=[event]))

    assert result.adverse_labels == ("drawdown_over_50", "default")
    episode = result.drawdown_episodes[0]
    assert episode.peak_date == "2020-12-31"
    assert episode.trough_date == "2021-06-01"
    assert episode.maximum_drawdown_pct == Decimal("-60.000000")
    assert episode.recovery_date is None
    assert "authority:default" in result.adjustment_evidence_ids


def test_twelve_month_total_return_uses_market_specific_official_benchmark() -> None:
    result = build(wealth_input([
        close("2020-12-31", "100"), close("2022-01-01", "120"),
        close("2023-01-01", "120"), close("2024-01-01", "120"),
    ], price_basis="pre_adjusted_total_return"))

    label = result.twelve_month_return
    assert label.status == "complete"
    assert label.decision_date == "2021-01-01"
    assert label.result_end_date == "2022-01-01"
    assert label.actual_total_return == Decimal("0.200000")
    assert label.official_benchmark_return == Decimal("0.100000")
    assert label.official_excess_return == Decimal("0.100000")
    assert label.same_market_median_return == Decimal("0.050000")
    assert label.positive_return is True
    assert label.outperformed_official_market is True
    assert label.official_benchmark_source_ref.endswith("MFI94U")
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"

    with pytest.raises(OutcomeLabelError, match="market mismatch"):
        build(wealth_input([
            close("2020-12-31", "100"), close("2022-01-01", "120"),
            close("2023-01-01", "120"), close("2024-01-01", "120"),
        ]), benchmark=official_benchmark("TPEx"))


def test_pre_adjusted_total_return_is_not_adjusted_twice() -> None:
    result = build(wealth_input([
        close("2020-12-31", "100"),
        close("2021-06-01", "40"),
        close("2022-01-01", "40"),
        close("2023-01-01", "40"),
        close("2024-01-01", "40"),
    ], price_basis="pre_adjusted_total_return"))
    assert result.adverse_labels == ("drawdown_over_50",)
    assert result.formula_version == "pre-adjusted-total-return-series.v1"

    action = CorporateAction(
        effective_on="2021-03-01", share_multiplier=Decimal("2"),
        cash_per_pre_action_share=Decimal("0"), terminal_cash=False,
        available_at="2021-03-01T18:00:00+08:00", evidence_ids=("split",),
    )
    with pytest.raises(OutcomeLabelError, match="forbids additional corporate actions"):
        build(wealth_input(
            [close("2020-12-31", "100")], actions=[action],
            price_basis="pre_adjusted_total_return",
        ))


def test_terminal_cash_makes_outcome_observed_without_synthetic_close() -> None:
    terminal = CorporateAction(
        effective_on="2021-04-01",
        share_multiplier=Decimal("1"),
        cash_per_pre_action_share=Decimal("60"),
        terminal_cash=True,
        available_at="2021-04-01T18:00:00+08:00",
        evidence_ids=("authority:terminal-cash",),
    )
    result = build(wealth_input(
        [close("2020-12-31", "100")],
        actions=[terminal],
        complete="2021-04-01",
    ))

    assert result.censoring_state == "fully_observed"
    assert result.drawdown_episodes[0].maximum_drawdown_pct == Decimal("-40.000000")
    assert result.adverse_labels == ()


def test_suspension_is_explicit_and_unresolved_missing_blocks_clean_negative() -> None:
    suspension = SuspensionInterval(
        start_on="2021-02-01",
        end_on="2021-03-01",
        available_at="2021-02-01T18:00:00+08:00",
        evidence_ids=("authority:suspension",),
    )
    clean = build(wealth_input([
        close("2020-12-31", "100"), close("2021-03-02", "100"),
        close("2022-01-01", "100"), close("2023-01-01", "100"),
        close("2024-01-01", "100"),
    ], suspensions=[suspension]))
    assert clean.drawdown_episodes == ()
    assert "authority:suspension" in clean.adjustment_evidence_ids

    blocked = build(wealth_input([
        close("2020-12-31", "100"), close("2024-01-01", "100"),
    ], missing=["2021-05-01"]))
    assert blocked.censoring_state == "blocked_missing_authority"
    assert blocked.label_coverage == Decimal("0")
    assert blocked.adverse_labels == ()
    assert blocked.failure_reasons == {
        "wealth": "unresolved_event_price_or_action_authority"
    }


def test_right_censored_case_is_not_promoted_to_clean_negative() -> None:
    result = build(wealth_input([
        close("2020-12-31", "100"), close("2021-06-01", "100"),
    ], complete="2021-06-01"))

    assert result.censoring_state == "right_censored"
    assert result.label_coverage > 0
    assert result.label_coverage < 1
    assert result.adverse_labels == ()


def test_headline_and_sensitivities_have_independent_versions() -> None:
    result = build(wealth_input([
        close("2020-12-31", "100"), close("2022-01-01", "100"),
        close("2023-01-01", "100"), close("2024-01-01", "100"),
    ]))

    assert result.horizon_months == 12
    assert result.label_version == "1.0.0-h12"
    assert tuple(item.horizon_months for item in result.sensitivity_outcomes) == (24, 36)
    assert tuple(item.label_version for item in result.sensitivity_outcomes) == (
        "1.0.0-h24", "1.0.0-h36"
    )


def test_pit_schema_and_duplicate_prices_fail_closed() -> None:
    future = wealth_input([
        DailyClose(
            effective_on="2021-01-02", unadjusted_close=Decimal("100"),
            available_at="2024-01-11T00:00:00+08:00", evidence_ids=("future",),
        ),
        close("2020-12-31", "100"),
    ])
    with pytest.raises(OutcomeLabelError, match="PIT boundary"):
        build(future)

    duplicated = close("2020-12-31", "100")
    with pytest.raises(OutcomeLabelError, match="duplicate daily close"):
        build(wealth_input([duplicated, duplicated]))

    with pytest.raises(OutcomeLabelError, match="exact input producer SHAs"):
        build_outcome_label_set(
            cohort(), wealth_input([close("2020-12-31", "100")]),
            issuer_id="issuer-1", decision_time="2021-01-01T12:00:00+08:00",
            base_label_version="1.0.0", producer_shas={"T20": sha("e")},
            generation_id="r9", producer_candidate_sha=sha("1"),
        )


def test_closed_schema_accepts_output_and_rejects_undeclared_fields() -> None:
    result = build(wealth_input([
        close("2020-12-31", "100"), close("2022-01-01", "100"),
        close("2023-01-01", "100"), close("2024-01-01", "100"),
    ]))
    path = (
        Path(__file__).parents[3]
        / "src/company_quality/lab/outcome_labels/contracts/OutcomeLabelSet.schema.json"
    )
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(result), default=float))
    validator.validate(payload)
    payload["calibrated_probability"] = 0.5
    assert next(validator.iter_errors(payload)).validator == "additionalProperties"
