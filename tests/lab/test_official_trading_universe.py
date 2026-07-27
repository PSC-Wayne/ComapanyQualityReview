from __future__ import annotations

from datetime import date

import pytest

from company_quality.lab.official_trading_universe import (
    materialize_official_trading_universe,
)


def _twse(day: date) -> object:
    if day != date(2024, 6, 28):
        return {"stat": "很抱歉，沒有符合條件的資料!", "date": day.strftime("%Y%m%d")}
    return {
        "stat": "OK",
        "date": "20240628",
        "tables": [{
            "fields": ["證券代號", "證券名稱", "成交股數", "收盤價"],
            "data": [
                ["2330", "台積電", "10,000", "966.00"],
                ["0050", "元大台灣50", "30,000", "190.00"],
                ["006208", "富邦台50", "20,000", "112.50"],
            ],
        }],
    }


def _tpex(day: date) -> object:
    if day == date(2024, 6, 29):
        return {
            "stat": "ok",
            "date": "20240629",
            "tables": [{
                "title": "上櫃股票行情",
                "fields": ["代號", "名稱", "收盤", "成交股數"],
                "data": [],
            }],
        }
    if day != date(2024, 6, 28):
        return {"stat": "error", "date": day.strftime("%Y%m%d"), "tables": []}
    return {
        "stat": "ok",
        "date": "20240628",
        "tables": [{
            "title": "上櫃股票行情",
            "fields": ["代號", "名稱", "收盤", "成交股數"],
            "data": [
                ["6488", "環球晶", "523.00", "1,000"],
                ["006201", "元大富櫃50", "22.00", "2,000"],
            ],
        }, {
            "title": "管理股票",
            "fields": ["代號", "名稱", "收盤", "成交股數"],
            "data": [],
        }],
    }


def test_materializes_quote_observed_universe_and_uses_prior_trading_day() -> None:
    frame, report = materialize_official_trading_universe(
        decision_dates=(date(2024, 6, 30),),
        final_oos_start=date(2025, 1, 1),
        fetch_twse=_twse,
        fetch_tpex=_tpex,
    )

    assert frame[["decision_date", "effective_trading_date", "market", "security_code"]].to_dict("records") == [
        {
            "decision_date": "2024-06-30",
            "effective_trading_date": "2024-06-28",
            "market": "TPEx",
            "security_code": "6488",
        },
        {
            "decision_date": "2024-06-30",
            "effective_trading_date": "2024-06-28",
            "market": "TWSE",
            "security_code": "2330",
        },
    ]
    assert report == {
        "schema_version": "OfficialTradingUniverse.v1",
        "status": "READY_TRADING_UNIVERSE_ONLY",
        "decision_dates": ["2024-06-30"],
        "final_oos_start": "2025-01-01",
        "market_counts": {"2024-06-30": {"TPEx": 1, "TWSE": 1}},
        "effective_trading_dates": {
            "2024-06-30": {"TPEx": "2024-06-28", "TWSE": "2024-06-28"}
        },
        "membership_policy": "four_digit_company_code_1xxx_to_9xxx_present_in_official_quote_table",
        "suspended_without_quotes_policy": "excluded_by_owner_direction",
        "final_oos_rows_read": False,
        "identity_readiness": "NOT_EVALUATED",
    }


def test_refuses_decision_date_at_or_after_final_oos() -> None:
    def forbidden(_: date) -> object:
        raise AssertionError("fetch must not run")

    with pytest.raises(ValueError, match="decision dates must precede final OOS"):
        materialize_official_trading_universe(
            decision_dates=(date(2025, 1, 1),),
            final_oos_start=date(2025, 1, 1),
            fetch_twse=forbidden,
            fetch_tpex=forbidden,
        )
