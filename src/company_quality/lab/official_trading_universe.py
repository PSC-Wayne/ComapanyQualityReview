"""Materialize quote-observed TWSE and TPEx universes before final OOS."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
from time import sleep
from typing import Callable

import pandas as pd
import requests


TWSE_DAILY_QUOTES_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_DAILY_QUOTES_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
LIVE_REQUEST_DELAY_SECONDS = 0.5
FetchDay = Callable[[date], object]
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "CompanyQualityResearch/0.1"})


def fetch_twse_day(day: date) -> object:
    sleep(LIVE_REQUEST_DELAY_SECONDS)
    response = _SESSION.get(
        TWSE_DAILY_QUOTES_URL,
        params={
            "response": "json",
            "date": day.strftime("%Y%m%d"),
            "type": "ALLBUT0999",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def fetch_tpex_day(day: date) -> object:
    sleep(LIVE_REQUEST_DELAY_SECONDS)
    response = _SESSION.get(
        TPEX_DAILY_QUOTES_URL,
        params={
            "date": day.strftime("%Y/%m/%d"),
            "id": "",
            "response": "json",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _rows(
    payload: object,
    day: date,
    *,
    market: str,
) -> list[tuple[str, str]] | None:
    if not isinstance(payload, dict):
        raise ValueError(f"{market} official quote payload drifted")
    expected_status = "OK" if market == "TWSE" else "ok"
    if payload.get("stat") != expected_status:
        return None
    if payload.get("date") != day.strftime("%Y%m%d"):
        raise ValueError(f"{market} official quote date drifted")
    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise ValueError(f"{market} official quote tables drifted")

    code_field = "證券代號" if market == "TWSE" else "代號"
    name_field = "證券名稱" if market == "TWSE" else "名稱"
    close_field = "收盤價" if market == "TWSE" else "收盤"
    candidates = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = table.get("fields")
        data = table.get("data")
        if market == "TPEx" and table.get("title") != "上櫃股票行情":
            continue
        if (
            isinstance(fields, list)
            and code_field in fields
            and name_field in fields
            and close_field in fields
        ) and isinstance(data, list):
            candidates.append((fields, data))
    if len(candidates) != 1:
        raise ValueError(f"{market} official quote table drifted")

    fields, data = candidates[0]
    code_index = fields.index(code_field)
    name_index = fields.index(name_field)
    result: list[tuple[str, str]] = []
    for row in data:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError(f"{market} official quote row drifted")
        code = str(row[code_index]).strip()
        if re.fullmatch(r"[1-9][0-9]{3}", code):
            result.append((code, str(row[name_index]).strip()))
    if not result:
        return None
    if len({code for code, _ in result}) != len(result):
        raise ValueError(f"{market} official quote code duplicated")
    return sorted(result)


def _resolve(
    decision_date: date,
    fetch: FetchDay,
    *,
    market: str,
) -> tuple[date, list[tuple[str, str]]]:
    for days_back in range(7):
        effective = decision_date - timedelta(days=days_back)
        rows = _rows(fetch(effective), effective, market=market)
        if rows is not None:
            return effective, rows
    raise ValueError(f"{market} official quote day unavailable within seven days")


def materialize_official_trading_universe(
    *,
    decision_dates: tuple[date, ...],
    final_oos_start: date,
    fetch_twse: FetchDay = fetch_twse_day,
    fetch_tpex: FetchDay = fetch_tpex_day,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if not decision_dates or len(set(decision_dates)) != len(decision_dates):
        raise ValueError("decision dates must be non-empty and unique")
    if any(day >= final_oos_start for day in decision_dates):
        raise ValueError("decision dates must precede final OOS")

    records: list[dict[str, str]] = []
    market_counts: dict[str, dict[str, int]] = {}
    effective_dates: dict[str, dict[str, str]] = {}
    for decision in sorted(decision_dates):
        decision_text = decision.isoformat()
        market_counts[decision_text] = {}
        effective_dates[decision_text] = {}
        for market, fetch, source in (
            ("TPEx", fetch_tpex, TPEX_DAILY_QUOTES_URL),
            ("TWSE", fetch_twse, TWSE_DAILY_QUOTES_URL),
        ):
            effective, rows = _resolve(decision, fetch, market=market)
            market_counts[decision_text][market] = len(rows)
            effective_dates[decision_text][market] = effective.isoformat()
            records.extend({
                "decision_date": decision_text,
                "effective_trading_date": effective.isoformat(),
                "market": market,
                "security_code": code,
                "company_name": name,
                "source_ref": source,
            } for code, name in rows)

    frame = pd.DataFrame(records).sort_values(
        ["decision_date", "market", "security_code"]
    ).reset_index(drop=True)
    report = {
        "schema_version": "OfficialTradingUniverse.v1",
        "status": "READY_TRADING_UNIVERSE_ONLY",
        "decision_dates": [day.isoformat() for day in sorted(decision_dates)],
        "final_oos_start": final_oos_start.isoformat(),
        "market_counts": market_counts,
        "effective_trading_dates": effective_dates,
        "membership_policy": "four_digit_company_code_1xxx_to_9xxx_present_in_official_quote_table",
        "suspended_without_quotes_policy": "excluded_by_owner_direction",
        "final_oos_rows_read": False,
        "identity_readiness": "NOT_EVALUATED",
    }
    return frame, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision-dates", required=True)
    parser.add_argument("--final-oos-start", required=True, type=date.fromisoformat)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    frame, report = materialize_official_trading_universe(
        decision_dates=tuple(
            date.fromisoformat(value) for value in args.decision_dates.split(",")
        ),
        final_oos_start=args.final_oos_start,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output_dir / "official-trading-universe.parquet", index=False)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
