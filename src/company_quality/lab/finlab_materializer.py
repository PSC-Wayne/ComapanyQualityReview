"""FinLab-first materializer for Taiwan equity universe and adjusted wealth."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from html import unescape
import json
from pathlib import Path
import re
from typing import Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


PRICE_DATASET = "price:收盤價"
ADJUSTED_PRICE_DATASET = "etl:adj_close"
VOLUME_DATASET = "price:成交股數"
SECURITY_CATEGORIES_DATASET = "security_categories"
TWSE_CURRENT_IDENTITY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_CURRENT_IDENTITY_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TWSE_PUBLIC_IDENTITY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_P"
TWSE_DELISTED_URL = (
    "https://www.twse.com.tw/rwd/zh/company/suspendListing?response=json"
)
TPEX_DELISTED_URL = "https://www.tpex.org.tw/www/zh-tw/company/deListed"
MOPS_COMPANY_PROFILE_URL = "https://mops.twse.com.tw/mops/api/t05st03"
GCIS_COMPANY_REGISTRY_URL = (
    "https://data.gcis.nat.gov.tw/od/data/api/6BBA2268-1367-4B42-9CCA-BC17499EBE8C"
)
GCIS_STATUSES = tuple(f"{value:02d}" for value in range(1, 11))
MOPSOV_FILING_URL = "https://mopsov.twse.com.tw/server-java/t164sb01"

DataGetter = Callable[[str], pd.DataFrame]


def _fetch_json(url: str) -> object:
    request = Request(url, headers={"User-Agent": "CompanyQualityResearch/0.1"})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def _fetch_mops_profile(code: str) -> dict[str, object] | None:
    request = Request(
        MOPS_COMPANY_PROFILE_URL,
        data=json.dumps({"companyId": code}).encode(),
        headers={
            "User-Agent": "CompanyQualityResearch/0.1",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    return result if payload.get("code") == 200 and isinstance(result, dict) else None


def _fetch_gcis_exact_identity(
    code: str, name: str, identity_link_source: str | None = None
) -> dict[str, object] | None:
    exact: dict[str, dict[str, object]] = {}
    for status in GCIS_STATUSES:
        url = GCIS_COMPANY_REGISTRY_URL + "?" + urlencode({
            "$format": "json",
            "$filter": (
                f"Company_Name like {name} and Company_Status eq {status}"
            ),
        })
        request = Request(url, headers={"User-Agent": "CompanyQualityResearch/0.1"})
        with urlopen(request, timeout=60) as response:
            body = response.read()
        if not body:
            continue
        payload = json.loads(body)
        if not isinstance(payload, list):
            raise ValueError("official GCIS company registry payload drifted")
        for row in payload:
            if not isinstance(row, dict) or str(row.get("Company_Name", "")).strip() != name:
                continue
            ubn = _ubn(row.get("Business_Accounting_NO"))
            if ubn:
                exact[ubn] = row
    if len(exact) != 1:
        return None
    result = next(iter(exact.values())).copy()
    result["_security_code"] = code
    result["_identity_link_source"] = identity_link_source
    return result


def _fetch_mopsov_filing_identity(
    code: str, years: range
) -> tuple[str, str] | None:
    for year in years:
        url = MOPSOV_FILING_URL + "?" + urlencode({
            "step": "1", "CO_ID": code, "SYEAR": str(year),
            "SSEASON": "4", "REPORT_ID": "C",
        })
        request = Request(url, headers={"User-Agent": "CompanyQualityResearch/0.1"})
        with urlopen(request, timeout=60) as response:
            text = response.read().decode("big5", "replace")
        code_match = re.search(
            r'name="tifrs-notes:CompanyID"[^>]*>([^<]+)', text
        )
        name_match = re.search(
            r'name="tifrs-notes:CompanyChineseName"[^>]*>([^<]+)', text
        )
        if code_match and name_match and code_match.group(1).strip() == code:
            return unescape(name_match.group(1)).strip(), url
    return None


def _roc_year(value: object) -> int:
    return int(str(value).strip().replace("/", "-").split("-", 1)[0]) + 1911


def _is_foreign_issuer(finlab_name: str, official_name: str) -> bool:
    combined = f"{finlab_name} {official_name}"
    return any(marker in combined for marker in ("-KY", "KY", "-DR", "F-", "開曼"))


def _ubn(value: object) -> str:
    candidate = str(value or "").strip()
    return (
        candidate
        if re.fullmatch(r"[0-9]{8}", candidate) and candidate != "00000000"
        else ""
    )


def _official_identity(
    universe: pd.DataFrame,
    payloads: Mapping[str, object],
) -> pd.DataFrame:
    twse = payloads.get("twse_current")
    tpex = payloads.get("tpex_current")
    twse_delisted = payloads.get("twse_delisted")
    tpex_delisted = payloads.get("tpex_delisted")
    twse_public = payloads.get("twse_public")
    mops_profiles = payloads.get("mops_profiles")
    gcis_identities = payloads.get("gcis_identities")
    listing_date_evidence = payloads.get("listing_date_evidence", [])
    if not isinstance(twse, list) or not isinstance(tpex, list) or not isinstance(
        twse_public, list
    ):
        raise ValueError("official current identity payload drifted")
    if not isinstance(twse_delisted, dict) or not isinstance(
        twse_delisted.get("data"), list
    ):
        raise ValueError("official TWSE delisted payload drifted")
    if not isinstance(tpex_delisted, list):
        raise ValueError("official TPEx delisted payload drifted")
    if not isinstance(mops_profiles, list):
        raise ValueError("official MOPS company-profile payload drifted")
    if not isinstance(gcis_identities, list):
        raise ValueError("official GCIS company registry payload drifted")
    if not isinstance(listing_date_evidence, list):
        raise ValueError("official annual-report listing-date payload drifted")

    current: dict[tuple[str, str], dict[str, str]] = {}
    current_by_code: dict[str, dict[str, str]] = {}
    for row in twse:
        if not isinstance(row, dict):
            raise ValueError("official TWSE identity row drifted")
        code = str(row.get("公司代號", "")).strip()
        authority = {
            "official_name": str(row.get("公司名稱", "")).strip(),
            "unified_business_number": _ubn(row.get("營利事業統一編號")),
            "listed_on": str(row.get("上市日期", "")).strip(),
            "official_market": "sii",
        }
        current[("sii", code)] = authority
        current_by_code[code] = authority
    for row in tpex:
        if not isinstance(row, dict):
            raise ValueError("official TPEx identity row drifted")
        code = str(row.get("SecuritiesCompanyCode", "")).strip()
        authority = {
            "official_name": str(row.get("CompanyName", "")).strip(),
            "unified_business_number": _ubn(row.get("UnifiedBusinessNo.")),
            "listed_on": str(row.get("DateOfListing", "")).strip(),
            "official_market": "otc",
        }
        current[("otc", code)] = authority
        current_by_code[code] = authority

    public_by_code: dict[str, dict[str, str]] = {}
    for row in twse_public:
        if not isinstance(row, dict):
            raise ValueError("official public-company identity row drifted")
        code = str(row.get("公司代號", "")).strip()
        public_by_code[code] = {
            "official_name": str(row.get("公司名稱", "")).strip(),
            "unified_business_number": _ubn(row.get("營利事業統一編號")),
            "listed_on": str(row.get("上市日期", "")).strip(),
        }

    mops_by_code: dict[str, dict[str, str]] = {}
    for row in mops_profiles:
        if not isinstance(row, dict):
            raise ValueError("official MOPS company-profile row drifted")
        def mops_value(field: str) -> str:
            value = row.get(field, "")
            if isinstance(value, dict):
                value = value.get("value", "")
            return str(value).strip()

        code = mops_value("stockId")
        if not code:
            raise ValueError("official MOPS company-profile code missing")
        mops_by_code[code] = {
            "official_name": mops_value("companyName"),
            "listed_on": mops_value("listingDate"),
        }

    gcis_by_code: dict[str, dict[str, str]] = {}
    for row in gcis_identities:
        if not isinstance(row, dict):
            raise ValueError("official GCIS company registry row drifted")
        code = str(row.get("_security_code", "")).strip()
        ubn = _ubn(row.get("Business_Accounting_NO"))
        if not code or not ubn:
            raise ValueError("official GCIS company registry identity missing")
        gcis_by_code[code] = {
            "official_name": str(row.get("Company_Name", "")).strip(),
            "unified_business_number": ubn,
            "listed_on": "",
            "identity_link_source": str(
                row.get("_identity_link_source", "") or ""
            ),
        }

    annual_listing_by_code: dict[str, dict[str, str]] = {}
    for row in listing_date_evidence:
        if not isinstance(row, dict):
            raise ValueError("official annual-report listing-date row drifted")
        code = str(row.get("security_code", "")).strip()
        listed_on = str(row.get("listed_on", "")).strip()
        source_url = str(row.get("source_url", "")).strip()
        source_page = str(row.get("source_page", "")).strip()
        source_excerpt = str(row.get("source_excerpt", "")).strip()
        if (
            not re.fullmatch(r"[0-9]{4}", code)
            or not listed_on
            or not source_url.startswith("https://doc.twse.com.tw/")
            or not source_page
            or not source_excerpt
        ):
            raise ValueError("official annual-report listing-date evidence missing")
        annual_listing_by_code[code] = {
            "listed_on": listed_on,
            "listing_date_link_source": f"{source_url}#page={source_page}",
        }

    fields = twse_delisted.get("fields")
    if fields != ["終止上市日期", "公司名稱", "上市編號"]:
        raise ValueError("official TWSE delisted fields drifted")
    delisted: dict[tuple[str, str], dict[str, str]] = {}
    for row in twse_delisted["data"]:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError("official TWSE delisted row drifted")
        delisted[("sii", str(row[2]).strip())] = {
            "delisted_on": str(row[0]).strip(),
            "official_name": str(row[1]).strip(),
        }

    for payload in tpex_delisted:
        if not isinstance(payload, dict):
            raise ValueError("official TPEx delisted payload drifted")
        tables = payload.get("tables")
        if not isinstance(tables, list) or len(tables) != 1:
            raise ValueError("official TPEx delisted tables drifted")
        table = tables[0]
        if not isinstance(table, dict) or table.get("fields") != [
            "股票代號", "公司名稱", "終止上櫃日期", "終止上櫃原因", "公司資料網址"
        ]:
            raise ValueError("official TPEx delisted fields drifted")
        rows = table.get("data")
        if not isinstance(rows, list):
            raise ValueError("official TPEx delisted rows drifted")
        for row in rows:
            if not isinstance(row, list) or len(row) != 5:
                raise ValueError("official TPEx delisted row drifted")
            delisted[("otc", str(row[0]).strip())] = {
                "official_name": str(row[1]).strip(),
                "delisted_on": str(row[2]).strip(),
            }

    records: list[dict[str, object]] = []
    for row in universe.itertuples(index=False):
        code = str(row.stock_id)
        market = str(row.market)
        authority = current.get((market, code))
        if authority is not None:
            status = (
                "CURRENT_OFFICIAL_IDENTITY"
                if authority["unified_business_number"]
                else "CURRENT_OFFICIAL_LIFECYCLE_UNRESOLVED_FOREIGN_LEGAL_IDENTITY"
            )
            lifecycle_id = f"{market}:{code}:{authority['listed_on']}"
            record = {
                **authority,
                "delisted_on": None,
                "public_on": None,
                "legal_identity_resolved": bool(
                    authority["unified_business_number"]
                ),
            }
        elif code in current_by_code:
            authority = current_by_code[code]
            status = (
                "CURRENT_OFFICIAL_IDENTITY_MARKET_MIGRATED"
                if authority["unified_business_number"]
                else "CURRENT_MIGRATED_LIFECYCLE_UNRESOLVED_FOREIGN_LEGAL_IDENTITY"
            )
            lifecycle_id = f"{market}:{code}:migrated:{authority['official_market']}"
            record = {
                **authority,
                "delisted_on": None,
                "public_on": None,
                "legal_identity_resolved": bool(
                    authority["unified_business_number"]
                ),
            }
        elif (market, code) in delisted:
            authority = delisted[(market, code)]
            public = public_by_code.get(code)
            legal = public or gcis_by_code.get(code)
            status = (
                "OFFICIAL_DELISTED_LEGAL_IDENTITY"
                if legal and legal["unified_business_number"]
                else (
                    "UNRESOLVED_FOREIGN_LEGAL_IDENTITY"
                    if _is_foreign_issuer(str(row.name), authority["official_name"])
                    else "UNRESOLVED_DOMESTIC_LEGAL_IDENTITY"
                )
            )
            lifecycle_id = f"{market}:{code}:delisted:{authority['delisted_on']}"
            record = {
                **authority,
                "listed_on": (
                    mops_by_code.get(code, {}).get("listed_on")
                    or annual_listing_by_code.get(code, {}).get("listed_on")
                    or None
                ),
                "listing_date_link_source": annual_listing_by_code.get(code, {}).get(
                    "listing_date_link_source"
                ),
                "public_on": public["listed_on"] if public else None,
                "official_market": market,
                "unified_business_number": (
                    legal["unified_business_number"] if legal else None
                ),
                "legal_identity_resolved": bool(
                    legal and legal["unified_business_number"]
                ),
                "legal_identity_link_source": (
                    legal.get("identity_link_source")
                    if legal and "identity_link_source" in legal
                    else (TWSE_PUBLIC_IDENTITY_URL if public else None)
                ),
            }
        else:
            status = "UNRESOLVED_OFFICIAL_IDENTITY"
            lifecycle_id = None
            record = {
                "official_name": None,
                "unified_business_number": None,
                "listed_on": None,
                "delisted_on": None,
                "public_on": None,
                "official_market": None,
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
                "TWSE_public_companies": TWSE_PUBLIC_IDENTITY_URL,
                "TWSE_delisted": TWSE_DELISTED_URL,
                "TPEx_delisted": TPEX_DELISTED_URL,
                "MOPS_company_profile": MOPS_COMPANY_PROFILE_URL,
                "GCIS_company_registry": GCIS_COMPANY_REGISTRY_URL,
                "MOPSOV_financial_filing": MOPSOV_FILING_URL,
            },
            "security_membership_resolved_count": membership_resolved,
            "security_membership_unresolved_count": len(identity) - membership_resolved,
            "security_membership_coverage": membership_resolved / len(identity),
            "legal_identity_resolved_count": legal_identity_resolved,
            "legal_identity_gap_count": len(identity) - legal_identity_resolved,
            "legal_identity_coverage": legal_identity_resolved / len(identity),
            "unresolved": unresolved_identity,
            "t20_status": (
                "BLOCKED_INCOMPLETE_HISTORICAL_IDENTITY"
                if membership_resolved != len(identity)
                else (
                    "BLOCKED_INCOMPLETE_LEGAL_IDENTITY"
                    if legal_identity_resolved != len(identity)
                    else "READY"
                )
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

    categories = data.get(SECURITY_CATEGORIES_DATASET)
    candidate_codes = set(_stock_universe(categories)["stock_id"])

    twse_delisted = _fetch_json(TWSE_DELISTED_URL)
    twse_public = _fetch_json(TWSE_PUBLIC_IDENTITY_URL)
    if not isinstance(twse_delisted, dict) or not isinstance(twse_public, list):
        raise ValueError("official identity payload drifted")
    tpex_delisted = [
        _fetch_json(
            TPEX_DELISTED_URL + "?" + urlencode({
                "date": str(year), "reason": "-1", "code": ""
            })
        )
        for year in range(args.start.year, args.end.year + 1)
    ]
    delisted_info = {
        str(row[2]).strip(): (str(row[1]).strip(), _roc_year(row[0]))
        for row in twse_delisted.get("data", [])
        if isinstance(row, list)
        and len(row) == 3
        and str(row[2]).strip() in candidate_codes
    }
    for payload in tpex_delisted:
        if not isinstance(payload, dict):
            continue
        for table in payload.get("tables", []):
            if isinstance(table, dict):
                delisted_info.update({
                    str(row[0]).strip(): (str(row[1]).strip(), _roc_year(row[2]))
                    for row in table.get("data", [])
                    if isinstance(row, list)
                    and len(row) == 5
                    and str(row[0]).strip() in candidate_codes
                })
    public_codes = {
        str(row.get("公司代號", "")).strip()
        for row in twse_public
        if isinstance(row, dict)
    }
    mops_profiles = [
        profile
        for code in sorted(set(delisted_info) & public_codes)
        if (profile := _fetch_mops_profile(code)) is not None
    ]
    filing_identities: dict[str, tuple[str, str]] = {}
    for code, (name, delisted_year) in sorted(delisted_info.items()):
        if code in public_codes or "股份有限公司" in name:
            continue
        result = _fetch_mopsov_filing_identity(
            code, range(delisted_year - 1, max(args.start.year - 2, delisted_year - 4), -1)
        )
        if result is not None:
            filing_identities[code] = result
    gcis_identities = []
    for code, (name, _) in sorted(delisted_info.items()):
        if code in public_codes:
            continue
        link_source = None
        if code in filing_identities:
            name, link_source = filing_identities[code]
        if "股份有限公司" not in name:
            continue
        identity = _fetch_gcis_exact_identity(code, name, link_source)
        if identity is not None:
            gcis_identities.append(identity)

    report = materialize_finlab(
        data_get=lambda dataset: (
            categories if dataset == SECURITY_CATEGORIES_DATASET else data.get(dataset)
        ),
        start=args.start,
        end=args.end,
        output_dir=args.output_dir,
        official_identity_payloads={
            "twse_current": _fetch_json(TWSE_CURRENT_IDENTITY_URL),
            "tpex_current": _fetch_json(TPEX_CURRENT_IDENTITY_URL),
            "twse_public": twse_public,
            "twse_delisted": twse_delisted,
            "tpex_delisted": tpex_delisted,
            "mops_profiles": mops_profiles,
            "gcis_identities": gcis_identities,
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
