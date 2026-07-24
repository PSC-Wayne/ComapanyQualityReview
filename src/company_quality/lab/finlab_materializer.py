"""FinLab-first materializer for Taiwan equity universe and adjusted wealth."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Callable, Mapping
from urllib.request import Request, urlopen

import pandas as pd


PRICE_DATASET = "price:收盤價"
ADJUSTED_PRICE_DATASET = "etl:adj_close"
VOLUME_DATASET = "price:成交股數"
SECURITY_CATEGORIES_DATASET = "security_categories"
TWSE_CURRENT_IDENTITY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_CURRENT_IDENTITY_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TWSE_DELISTED_URL = (
    "https://www.twse.com.tw/rwd/zh/company/suspendListing?response=json"
)

DataGetter = Callable[[str], pd.DataFrame]


def _fetch_json(url: str) -> object:
    request = Request(url, headers={"User-Agent": "CompanyQualityResearch/0.1"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def _official_identity(
    universe: pd.DataFrame,
    payloads: Mapping[str, object],
) -> pd.DataFrame:
    twse = payloads.get("twse_current")
    tpex = payloads.get("tpex_current")
    twse_delisted = payloads.get("twse_delisted")
    if not isinstance(twse, list) or not isinstance(tpex, list):
        raise ValueError("official current identity payload drifted")
    if not isinstance(twse_delisted, dict) or not isinstance(
        twse_delisted.get("data"), list
    ):
        raise ValueError("official TWSE delisted payload drifted")

    current: dict[tuple[str, str], dict[str, object]] = {}
    for row in twse:
        if not isinstance(row, dict):
            raise ValueError("official TWSE identity row drifted")
        code = str(row.get("公司代號", "")).strip()
        current[("sii", code)] = {
            "official_name": str(row.get("公司名稱", "")).strip(),
            "unified_business_number": str(row.get("營利事業統一編號", "")).strip(),
            "listed_on": str(row.get("上市日期", "")).strip(),
        }
    for row in tpex:
        if not isinstance(row, dict):
            raise ValueError("official TPEx identity row drifted")
        code = str(row.get("SecuritiesCompanyCode", "")).strip()
        current[("otc", code)] = {
            "official_name": str(row.get("CompanyName", "")).strip(),
            "unified_business_number": str(row.get("UnifiedBusinessNo.", "")).strip(),
            "listed_on": str(row.get("DateOfListing", "")).strip(),
        }

    fields = twse_delisted.get("fields")
    if fields != ["終止上市日期", "公司名稱", "上市編號"]:
        raise ValueError("official TWSE delisted fields drifted")
    delisted: dict[str, dict[str, str]] = {}
    for row in twse_delisted["data"]:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError("official TWSE delisted row drifted")
        delisted[str(row[2]).strip()] = {
            "delisted_on": str(row[0]).strip(),
            "official_name": str(row[1]).strip(),
        }

    records: list[dict[str, object]] = []
    for row in universe.itertuples(index=False):
        code = str(row.stock_id)
        market = str(row.market)
        authority = current.get((market, code))
        if authority is not None:
            status = "CURRENT_OFFICIAL_IDENTITY"
            lifecycle_id = f"{market}:{code}:{authority['listed_on']}"
            record = {
                **authority,
                "delisted_on": None,
                "legal_identity_resolved": bool(
                    authority["unified_business_number"]
                ),
            }
        elif market == "sii" and code in delisted:
            authority = delisted[code]
            status = "OFFICIAL_DELISTED_SECURITY_LIFECYCLE"
            lifecycle_id = f"{market}:{code}:delisted:{authority['delisted_on']}"
            record = {
                **authority,
                "listed_on": None,
                "unified_business_number": None,
                "legal_identity_resolved": False,
            }
        else:
            status = "UNRESOLVED_OFFICIAL_IDENTITY"
            lifecycle_id = None
            record = {
                "official_name": None,
                "unified_business_number": None,
                "listed_on": None,
                "delisted_on": None,
                "legal_identity_resolved": False,
            }
        records.append({
            "security_code": code,
            "market": market,
            "finlab_name": str(row.name),
            "security_lifecycle_id": lifecycle_id,
            "identity_status": status,
            **record,
        })
    return pd.DataFrame(records)


def _stock_universe(categories: pd.DataFrame) -> pd.DataFrame:
    required = {"stock_id", "name", "market", "category"}
    if not required.issubset(categories.columns):
        raise ValueError("FinLab security_categories schema drifted")
    result = categories.copy()
    result["stock_id"] = result["stock_id"].astype(str)
    result = result[
        result["market"].isin(["sii", "otc"])
        & result["stock_id"].str.fullmatch(r"[0-9]{4}")
    ]
    return result.drop_duplicates(subset=["stock_id", "market"], keep="last")


def _slice(frame: pd.DataFrame, start: date, end: date, codes: list[str]) -> pd.DataFrame:
    sliced = frame.loc[str(start):str(end)].copy()
    return sliced.reindex(columns=codes)


def _adjusted_wealth(adjusted_close: pd.DataFrame) -> pd.DataFrame:
    first = adjusted_close.apply(lambda series: series.dropna().iloc[0] if series.notna().any() else pd.NA)
    return adjusted_close.divide(first, axis="columns") * 100


def materialize_finlab(
    *,
    data_get: DataGetter,
    start: date,
    end: date,
    output_dir: Path,
    official_identity_payloads: Mapping[str, object],
) -> dict[str, object]:
    if end < start:
        raise ValueError("end precedes start")
    categories = data_get(SECURITY_CATEGORIES_DATASET)
    universe = _stock_universe(categories)
    candidate_codes = sorted(universe["stock_id"].unique())

    raw_close = _slice(data_get(PRICE_DATASET), start, end, candidate_codes)
    adjusted_close = _slice(
        data_get(ADJUSTED_PRICE_DATASET), start, end, candidate_codes
    )
    volume = _slice(data_get(VOLUME_DATASET), start, end, candidate_codes)
    observed = [
        code for code in candidate_codes
        if raw_close[code].notna().any() or adjusted_close[code].notna().any()
    ]
    raw_close = raw_close[observed]
    adjusted_close = adjusted_close[observed]
    volume = volume[observed]
    wealth = _adjusted_wealth(adjusted_close)
    universe = universe[universe["stock_id"].isin(observed)].copy()
    identity = _official_identity(universe, official_identity_payloads)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_close.to_parquet(output_dir / "raw_close.parquet")
    adjusted_close.to_parquet(output_dir / "adjusted_close.parquet")
    volume.to_parquet(output_dir / "volume.parquet")
    wealth.to_parquet(output_dir / "adjusted_wealth.parquet")
    universe.to_parquet(output_dir / "security_universe.parquet", index=False)
    identity.to_parquet(output_dir / "official_identity.parquet", index=False)

    coverage: list[dict[str, object]] = []
    market_by_code = universe.groupby("stock_id")["market"].first().to_dict()
    for code in observed:
        raw = raw_close[code].dropna()
        adjusted = adjusted_close[code].dropna()
        coverage.append({
            "security_code": code,
            "market": market_by_code.get(code),
            "raw_close_count": int(len(raw)),
            "adjusted_close_count": int(len(adjusted)),
            "first_raw_close": raw.index.min().date().isoformat() if len(raw) else None,
            "last_raw_close": raw.index.max().date().isoformat() if len(raw) else None,
            "first_adjusted_close": (
                adjusted.index.min().date().isoformat() if len(adjusted) else None
            ),
            "last_adjusted_close": (
                adjusted.index.max().date().isoformat() if len(adjusted) else None
            ),
            "status": "READY" if len(raw) and len(adjusted) else "BLOCKED_INPUT_DATA",
        })

    ready = sum(row["status"] == "READY" for row in coverage)
    market_counts = (
        universe.groupby("market")["stock_id"].nunique().astype(int).to_dict()
    )
    membership_resolved = int(identity["security_lifecycle_id"].notna().sum())
    legal_identity_resolved = int(identity["legal_identity_resolved"].sum())
    unresolved_identity = identity.loc[
        identity["identity_status"] == "UNRESOLVED_OFFICIAL_IDENTITY",
        ["security_code", "market", "finlab_name"],
    ].to_dict("records")
    report = {
        "schema_version": "FinLabT20T21Materialization.v1",
        "source_policy": "FinLab first; official-source fallback only for unavailable fields",
        "datasets": {
            "raw_close": PRICE_DATASET,
            "adjusted_close": ADJUSTED_PRICE_DATASET,
            "volume": VOLUME_DATASET,
            "security_universe": SECURITY_CATEGORIES_DATASET,
        },
        "start": start.isoformat(),
        "end": end.isoformat(),
        "security_count": len(observed),
        "market_security_counts": market_counts,
        "ready_security_count": ready,
        "blocked_security_count": len(coverage) - ready,
        "coverage": coverage,
        "official_identity": {
            "sources": {
                "TWSE_current": TWSE_CURRENT_IDENTITY_URL,
                "TPEx_current": TPEX_CURRENT_IDENTITY_URL,
                "TWSE_delisted": TWSE_DELISTED_URL,
                "TPEx_delisted": "not_materialized",
            },
            "security_membership_resolved_count": membership_resolved,
            "security_membership_unresolved_count": len(identity) - membership_resolved,
            "security_membership_coverage": membership_resolved / len(identity),
            "legal_identity_resolved_count": legal_identity_resolved,
            "legal_identity_gap_count": len(identity) - legal_identity_resolved,
            "legal_identity_coverage": legal_identity_resolved / len(identity),
            "unresolved": unresolved_identity,
            "t20_status": (
                "READY" if membership_resolved == len(identity)
                else "BLOCKED_INCOMPLETE_HISTORICAL_IDENTITY"
            ),
        },
        "materialized_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    from finlab import data

    report = materialize_finlab(
        data_get=data.get,
        start=args.start,
        end=args.end,
        output_dir=args.output_dir,
        official_identity_payloads={
            "twse_current": _fetch_json(TWSE_CURRENT_IDENTITY_URL),
            "tpex_current": _fetch_json(TPEX_CURRENT_IDENTITY_URL),
            "twse_delisted": _fetch_json(TWSE_DELISTED_URL),
        },
    )
    print(json.dumps({
        key: report[key]
        for key in (
            "security_count", "market_security_counts",
            "ready_security_count", "blocked_security_count",
        )
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
