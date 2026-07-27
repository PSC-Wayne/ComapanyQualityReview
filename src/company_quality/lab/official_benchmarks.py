"""Materialize official TWSE and TPEx total-return indices before final OOS."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from time import sleep
from typing import Callable, cast

import pandas as pd
import requests


TWSE_TOTAL_RETURN_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U"
TPEX_TOTAL_RETURN_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/ROE"
LIVE_REQUEST_DELAY_SECONDS = 0.5
FetchMonth = Callable[[date], object]
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "CompanyQualityResearch/0.1"})


def _month_starts(start: date, end: date) -> tuple[date, ...]:
    if start > end:
        raise ValueError("start must not be after end")
    current = start.replace(day=1)
    stop = end.replace(day=1)
    result: list[date] = []
    while current <= stop:
        result.append(current)
        current = date(
            current.year + (current.month == 12),
            1 if current.month == 12 else current.month + 1,
            1,
        )
    return tuple(result)


def _official_get(url: str, params: dict[str, str]) -> object:
    response = _SESSION.get(url, params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def _official_post(url: str, form: dict[str, str]) -> object:
    response = _SESSION.post(url, data=form, timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_twse_month(month: date) -> object:
    sleep(LIVE_REQUEST_DELAY_SECONDS)
    return _official_get(
        TWSE_TOTAL_RETURN_URL,
        {"date": month.strftime("%Y%m01"), "response": "json"},
    )


def fetch_tpex_month(month: date) -> object:
    sleep(LIVE_REQUEST_DELAY_SECONDS)
    return _official_post(
        TPEX_TOTAL_RETURN_URL,
        {"date": month.strftime("%Y/%m/01"), "response": "json"},
    )


def _roc_date(value: object, *, compact: bool) -> pd.Timestamp:
    text = str(value).strip()
    if compact:
        if len(text) != 7 or not text.isdigit():
            raise ValueError("invalid compact ROC date")
        year, month, day = int(text[:3]) + 1911, int(text[3:5]), int(text[5:])
    else:
        parts = text.split("/")
        if len(parts) != 3:
            raise ValueError("invalid ROC date")
        year, month, day = int(parts[0]) + 1911, int(parts[1]), int(parts[2])
    return cast(pd.Timestamp, pd.Timestamp(date(year, month, day)))


def _twse_rows(payload: object, month: date) -> list[tuple[pd.Timestamp, float]]:
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        raise ValueError("TWSE official total-return payload failed")
    if payload.get("date") != month.strftime("%Y%m01"):
        raise ValueError("TWSE official total-return month drifted")
    if payload.get("fields") != ["日　期", "發行量加權股價報酬指數"]:
        raise ValueError("TWSE official total-return fields drifted")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("TWSE official total-return rows drifted")
    return [
        (_roc_date(row[0], compact=False), float(str(row[1]).replace(",", "")))
        for row in data
        if isinstance(row, list) and len(row) == 2
    ]


def _tpex_rows(payload: object, month: date) -> list[tuple[pd.Timestamp, float]]:
    if not isinstance(payload, dict) or payload.get("stat") != "ok":
        raise ValueError("TPEx official total-return payload failed")
    if payload.get("date") != month.strftime("%Y%m01"):
        raise ValueError("TPEx official total-return month drifted")
    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) != 1:
        raise ValueError("TPEx official total-return tables drifted")
    table = tables[0]
    expected_fields = ["日期", "櫃買指數", "櫃買報酬指數(基期:94/12/30)"]
    if not isinstance(table, dict) or table.get("fields") != expected_fields:
        raise ValueError("TPEx official total-return fields drifted")
    data = table.get("data")
    if not isinstance(data, list):
        raise ValueError("TPEx official total-return rows drifted")
    return [
        (_roc_date(row[0], compact=True), float(str(row[2]).replace(",", "")))
        for row in data
        if isinstance(row, list) and len(row) == 3
    ]


def _series(
    months: tuple[date, ...],
    fetch: FetchMonth,
    parse: Callable[[object, date], list[tuple[pd.Timestamp, float]]],
    *,
    name: str,
    start: date,
    end: date,
) -> pd.Series:
    values: dict[pd.Timestamp, float] = {}
    for month in months:
        for effective_on, value in parse(fetch(month), month):
            if value <= 0:
                raise ValueError(f"{name} official total-return value must be positive")
            if effective_on in values and values[effective_on] != value:
                raise ValueError(f"{name} official total-return duplicate conflict")
            values[effective_on] = value
    result = pd.Series(values, dtype="float64", name=name).sort_index()
    result = result.loc[str(start):str(end)]
    if result.empty:
        raise ValueError(f"{name} official total-return series is empty")
    return result


def materialize_official_total_returns(
    *,
    start: date,
    end: date,
    final_oos_start: date,
    requested_months: tuple[date, ...] | None = None,
    fetch_twse: FetchMonth = fetch_twse_month,
    fetch_tpex: FetchMonth = fetch_tpex_month,
) -> tuple[pd.Series, pd.Series, dict[str, object]]:
    if end >= final_oos_start:
        raise ValueError("official benchmark materialization must end before final OOS")
    months = requested_months or _month_starts(start, end)
    if not months or len(set(months)) != len(months):
        raise ValueError("requested months must be non-empty and unique")
    if any(
        month.day != 1 or month < start.replace(day=1) or month > end.replace(day=1)
        for month in months
    ):
        raise ValueError("requested month lies outside the pre-OOS materialization window")
    months = tuple(sorted(months))
    twse = _series(
        months, fetch_twse, _twse_rows,
        name="TWSE_official_total_return", start=start, end=end,
    )
    tpex = _series(
        months, fetch_tpex, _tpex_rows,
        name="TPEx_official_total_return", start=start, end=end,
    )
    report = {
        "schema_version": "OfficialPreOOSBenchmarkMaterialization.v1",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "final_oos_start": final_oos_start.isoformat(),
        "requested_month_count": len(months),
        "twse_row_count": len(twse),
        "tpex_row_count": len(tpex),
        "twse_source_ref": TWSE_TOTAL_RETURN_URL,
        "tpex_source_ref": TPEX_TOTAL_RETURN_URL,
        "final_oos_rows_read": False,
        "final_oos_record_written": False,
    }
    return twse, tpex, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--final-oos-start", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--months",
        help="optional comma-separated first-of-month dates required by decision windows",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    twse, tpex, report = materialize_official_total_returns(
        start=args.start,
        end=args.end,
        final_oos_start=args.final_oos_start,
        requested_months=(
            tuple(date.fromisoformat(value) for value in args.months.split(","))
            if args.months else None
        ),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    twse.to_frame().to_parquet(args.output_dir / "twse-official-total-return.parquet")
    tpex.to_frame().to_parquet(args.output_dir / "tpex-official-total-return.parquet")
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
