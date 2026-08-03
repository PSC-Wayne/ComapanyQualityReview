from decimal import Decimal
from hashlib import sha256

import pytest

from company_quality.company_analysis.forecast_capital import (
    ActualResult,
    CapitalEvent,
    DividendResolution,
    FinancialCapacity,
    FormalForecast,
    assess_forecast_dividend_capital,
)
from company_quality.sources.forecast_dividend import (
    ForecastDividendSourceError,
    parse_openapi_window,
)


AS_OF = "2026-08-03T12:00:00+08:00"


def _window(dataset: str, market: str, rows: list[dict[str, str]]):
    body = repr(rows).encode()
    return parse_openapi_window(
        dataset_id=dataset,
        market=market,
        security_code="2330" if market == "TWSE" else "5274",
        rows=rows,
        source_url=f"https://official.example/{dataset}",
        content_sha256=sha256(body).hexdigest(),
        retrieved_at=AS_OF,
        as_of=AS_OF,
    )


def test_source_windows_keep_formal_forecast_and_dividend_claim_boundaries() -> None:
    forecast = _window(
        "t187ap15_L",
        "TWSE",
        [{
            "出表日期": "1150802", "年度": "115", "季別": "2",
            "公司代號": "2330", "公司名稱": "台積電", "財測序號": "1",
            "涵蓋期間": "一、二", "截至該季經會計師查核或核閱數": "100",
            "截至該季綜合損益預測數": "90~110",
        }],
    )
    dividend = _window(
        "t187ap45_L",
        "TWSE",
        [{
            "出表日期": "1150802", "公司代號": "2330", "公司名稱": "台積電",
            "決議（擬議）進度": "股東會確認", "股利年度": "114",
            "董事會（擬議）股利分派日": "1150211", "股東會日期": "1150522",
            "股東配發-盈餘分配之現金股利(元/股)": "10",
            "股東配發-資本公積發放之現金(元/股)": "2",
            "股東配發-股東配發之現金(股利)總金額(元)": "1200",
        }],
    )

    assert forecast.status == "available"
    assert forecast.records[0].claim_type == "formal_forecast_window"
    assert dividend.records[0].claim_type == "dividend_resolution_window"
    assert dividend.records[0].payload["capital_reserve_cash_per_share"] == "2"
    assert all(item.citation.source_tier == "official" for item in (*forecast.records, *dividend.records))


def test_blank_tpex_placeholder_is_unresolved_not_zero_or_absence() -> None:
    result = _window(
        "mopsfin_t187ap15_O",
        "TPEx",
        [{
            "Date": "1150802", "Year": "", "季別": "",
            "SecuritiesCompanyCode": "", "CompanyName": "", "財測序號": "",
            "涵蓋期間": "", "截至第1季經會計師查核或核閱數": "",
            "截至第1季稅前損益預測數": "",
        }],
    )

    assert result.status == "unresolved"
    assert result.records == ()
    assert result.bounded_absence is False
    assert "blank_placeholder" in result.unresolved_reasons


def test_tpex_dividend_window_and_market_dataset_authority_are_explicit() -> None:
    dividend = _window(
        "mopsfin_t187ap39_O",
        "TPEx",
        [{
            "Date": "1150802",
            "SecuritiesCompanyCode": "5274",
            "DecisionProgress": "股東會確認",
            "DividendYear": "114",
            "BoardMeetingDate": "1150211",
            "ShareholdersMeetingDate": "1150522",
            "CashDividendFromEarningsPerShare": "8",
            "CashDividendFromCapitalReservePerShare": "1",
            "TotalCashDividend": "900",
        }],
    )

    assert dividend.status == "available"
    assert dividend.records[0].claim_type == "dividend_resolution_window"
    assert dividend.records[0].payload["capital_reserve_cash_per_share"] == "1"
    with pytest.raises(ForecastDividendSourceError, match="not authoritative"):
        _window("t187ap45_L", "TPEx", [])


def test_formal_forecast_matches_period_basis_and_does_not_accept_ir_guidance() -> None:
    formal = FormalForecast(
        forecast_id="forecast-1", fiscal_period="115Q2", period_basis="year_to_date",
        metric="pretax_income", lower=Decimal("90"), upper=Decimal("110"),
        revision_sequence=1, announced_at="2026-05-01T18:00:00+08:00",
        source_window_evidence_id="window-1", original_filing_evidence_id="filing-1",
    )
    actual = ActualResult(
        fiscal_period="115Q2", period_basis="year_to_date", metric="pretax_income",
        value=Decimal("105"), evidence_id="actual-1",
    )
    result = assess_forecast_dividend_capital(
        forecast_window_status="available", formal_forecasts=(formal,), actuals=(actual,),
        ordinary_guidance_evidence_ids=("ir-guidance-1",),
    )
    g25 = result.by_check_id["G25"]

    assert g25.status == "evaluated"
    assert g25.applicability == "triggered"
    assert "命中" in " ".join(g25.observations)
    assert "ir-guidance-1" not in g25.evidence_ids


def test_forecast_without_original_filing_or_aligned_actual_stays_unresolved() -> None:
    formal = FormalForecast(
        forecast_id="forecast-1", fiscal_period="115Q2", period_basis="year_to_date",
        metric="pretax_income", lower=Decimal("90"), upper=Decimal("110"),
        revision_sequence=1, announced_at="2026-05-01T18:00:00+08:00",
        source_window_evidence_id="window-1", original_filing_evidence_id=None,
    )
    result = assess_forecast_dividend_capital(
        forecast_window_status="available", formal_forecasts=(formal,), actuals=(),
    )

    assert result.by_check_id["G25"].status == "unresolved"
    assert "原始正式財測申報" in " ".join(result.by_check_id["G25"].unresolved_reasons)


def test_dividend_requires_resolution_and_complete_cash_capacity_facts() -> None:
    dividends = (
        DividendResolution(
            dividend_id="div-113", fiscal_period="113", lifecycle="approved",
            proposal_date="2025-02-10", approval_date="2025-05-20", payment_date=None,
            cash_dividend=Decimal("80"), capital_reserve_dividend=Decimal("0"),
            evidence_ids=("window-113", "resolution-113"),
        ),
        DividendResolution(
            dividend_id="div-114", fiscal_period="114", lifecycle="approved",
            proposal_date="2026-02-10", approval_date="2026-05-20", payment_date=None,
            cash_dividend=Decimal("120"), capital_reserve_dividend=Decimal("20"),
            evidence_ids=("window-114", "resolution-114"),
        ),
    )
    capacity = FinancialCapacity(
        fiscal_period="114", operating_cash_flow=Decimal("100"), capex=Decimal("30"),
        net_income=Decimal("90"), debt=Decimal("50"), cash=Decimal("40"),
        investment_need=Decimal("20"), evidence_ids=("ocf", "capex", "net", "debt", "cash", "need"),
    )
    result = assess_forecast_dividend_capital(
        forecast_window_status="available", bounded_no_formal_forecast=True,
        dividends=dividends, financial_capacity=(capacity,),
    )

    assert result.by_check_id["G24"].applicability == "triggered"
    assert result.by_check_id["R46"].applicability == "triggered"
    assert "資本公積" in " ".join(result.by_check_id["R46"].observations)
    assert "淨利=90" in " ".join(result.by_check_id["R46"].observations)
    assert "淨負債=10" in " ".join(result.by_check_id["R46"].observations)

    missing_capex = assess_forecast_dividend_capital(
        forecast_window_status="available", bounded_no_formal_forecast=True,
        dividends=dividends,
        financial_capacity=(FinancialCapacity(
            fiscal_period="114", operating_cash_flow=Decimal("100"), capex=None,
            net_income=Decimal("90"), debt=Decimal("50"), cash=Decimal("40"),
            investment_need=Decimal("20"), evidence_ids=("ocf", "net", "debt", "cash", "need"),
        ),),
    )
    assert missing_capex.by_check_id["R46"].status == "unresolved"


def test_proposals_and_authorizations_never_become_completed_capital_events() -> None:
    events = (
        CapitalEvent(
            event_id="raise-1", event_type="cash_raise", lifecycle="proposed",
            announced_at="2026-01-01T18:00:00+08:00", effective_at=None,
            amount=Decimal("100"), mops_event_evidence_id="event-raise",
            prospectus_evidence_id="prospectus-raise", note_evidence_id=None,
        ),
        CapitalEvent(
            event_id="buyback-1", event_type="buyback", lifecycle="authorized",
            announced_at="2026-02-01T18:00:00+08:00", effective_at=None,
            amount=Decimal("50"), mops_event_evidence_id="event-buyback",
            prospectus_evidence_id=None, note_evidence_id=None,
            transaction_history_evidence_id=None,
        ),
        CapitalEvent(
            event_id="acq-1", event_type="acquisition", lifecycle="completed",
            announced_at="2026-03-01T18:00:00+08:00", effective_at="2026-04-01",
            amount=Decimal("500"), mops_event_evidence_id="event-acq",
            prospectus_evidence_id=None, note_evidence_id="note-acq",
        ),
    )
    result = assess_forecast_dividend_capital(
        forecast_window_status="available", bounded_no_formal_forecast=True,
        capital_events=events,
    )

    assert result.by_check_id["R43"].status == "unresolved"
    assert result.by_check_id["R48"].status == "unresolved"
    assert result.by_check_id["R47"].status == "evaluated"
    assert result.by_check_id["R47"].applicability == "triggered"
    assert result.by_check_id["G21"].applicability == "triggered"


def test_conversion_terms_and_history_are_mandatory_for_convertible_dilution() -> None:
    event = CapitalEvent(
        event_id="cb-1", event_type="convertible_bond", lifecycle="completed",
        announced_at="2026-01-01T18:00:00+08:00", effective_at="2026-02-01",
        amount=Decimal("100"), mops_event_evidence_id="event-cb",
        prospectus_evidence_id="prospectus-cb", note_evidence_id="note-cb",
        conversion_terms_evidence_id=None, transaction_history_evidence_id=None,
    )
    result = assess_forecast_dividend_capital(
        forecast_window_status="available", bounded_no_formal_forecast=True,
        capital_events=(event,),
    )

    assert result.by_check_id["R44"].status == "unresolved"
    assert "轉換條件" in " ".join(result.by_check_id["R44"].unresolved_reasons)
