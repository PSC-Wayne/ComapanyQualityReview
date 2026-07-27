from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from company_quality.lab.official_benchmarks import (
    TPEX_TOTAL_RETURN_URL,
    TWSE_TOTAL_RETURN_URL,
    materialize_official_total_returns,
)
from company_quality.lab.real_t21 import _official_benchmark


def _roc(month: date, day: int = 2) -> tuple[str, str]:
    year = month.year - 1911
    return f"{year:03d}/{month.month:02d}/{day:02d}", f"{year:03d}{month.month:02d}{day:02d}"


def _twse(month: date) -> object:
    slash, _ = _roc(month)
    return {
        "stat": "OK",
        "date": month.strftime("%Y%m01"),
        "fields": ["日　期", "發行量加權股價報酬指數"],
        "data": [[slash, "22,566.08"]],
    }


def _tpex(month: date) -> object:
    _, compact = _roc(month)
    return {
        "stat": "ok",
        "date": month.strftime("%Y%m01"),
        "tables": [{
            "fields": ["日期", "櫃買指數", "櫃買報酬指數(基期:94/12/30)"],
            "data": [[compact, "150.91", "229.98"]],
        }],
    }


def test_materializes_both_official_series_before_final_oos() -> None:
    twse, tpex, report = materialize_official_total_returns(
        start=date(2019, 12, 1),
        end=date(2020, 1, 31),
        final_oos_start=date(2020, 2, 1),
        requested_months=(date(2020, 1, 1), date(2019, 12, 1)),
        fetch_twse=_twse,
        fetch_tpex=_tpex,
    )

    assert list(twse.index) == [pd.Timestamp("2019-12-02"), pd.Timestamp("2020-01-02")]
    assert list(tpex.index) == [pd.Timestamp("2019-12-02"), pd.Timestamp("2020-01-02")]
    assert twse.tolist() == [22566.08, 22566.08]
    assert tpex.tolist() == [229.98, 229.98]
    assert report == {
        "schema_version": "OfficialPreOOSBenchmarkMaterialization.v1",
        "start": "2019-12-01",
        "end": "2020-01-31",
        "final_oos_start": "2020-02-01",
        "requested_month_count": 2,
        "twse_row_count": 2,
        "tpex_row_count": 2,
        "twse_source_ref": TWSE_TOTAL_RETURN_URL,
        "tpex_source_ref": TPEX_TOTAL_RETURN_URL,
        "final_oos_rows_read": False,
        "final_oos_record_written": False,
    }


def test_refuses_to_fetch_when_window_touches_final_oos() -> None:
    def forbidden(_: date) -> object:
        raise AssertionError("fetch must not run")

    with pytest.raises(ValueError, match="must end before final OOS"):
        materialize_official_total_returns(
            start=date(2020, 1, 1),
            end=date(2020, 2, 1),
            final_oos_start=date(2020, 2, 1),
            fetch_twse=forbidden,
            fetch_tpex=forbidden,
        )


def test_official_payload_month_and_fields_fail_closed() -> None:
    def drifted_twse(month: date) -> object:
        payload = _twse(month)
        assert isinstance(payload, dict)
        payload["fields"] = ["日期", "收盤指數"]
        return payload

    with pytest.raises(ValueError, match="TWSE official total-return fields drifted"):
        materialize_official_total_returns(
            start=date(2020, 1, 1),
            end=date(2020, 1, 31),
            final_oos_start=date(2021, 1, 1),
            fetch_twse=drifted_twse,
            fetch_tpex=_tpex,
        )

    def wrong_tpex_month(month: date) -> object:
        payload = _tpex(month)
        assert isinstance(payload, dict)
        payload["date"] = "20191201"
        return payload

    with pytest.raises(ValueError, match="TPEx official total-return month drifted"):
        materialize_official_total_returns(
            start=date(2020, 1, 1),
            end=date(2020, 1, 31),
            final_oos_start=date(2021, 1, 1),
            fetch_twse=_twse,
            fetch_tpex=wrong_tpex_month,
        )


def test_t21_lineage_uses_historical_official_endpoints() -> None:
    series = pd.Series([100.0], index=[pd.Timestamp("2020-01-02")])

    assert _official_benchmark("TWSE", series).series_ref == TWSE_TOTAL_RETURN_URL
    assert _official_benchmark("TPEx", series).series_ref == TPEX_TOTAL_RETURN_URL
