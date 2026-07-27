"""Resolve immutable legal identities for official historical trading universes."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from html import unescape
import json
from pathlib import Path
import re
from typing import Callable

import pandas as pd
import requests

from company_quality.lab.finlab_materializer import (
    GCIS_COMPANY_REGISTRY_URL,
    MOPSOV_FILING_URL,
    TPEX_CURRENT_IDENTITY_URL,
    TWSE_CURRENT_IDENTITY_URL,
    _fetch_gcis_exact_identity,
    _fetch_json,
)


FetchFiling = Callable[[str, tuple[int, ...]], tuple[str, str] | None]
FetchRegistry = Callable[[str, str], dict[str, object] | None]
_REQUIRED_UNIVERSE_COLUMNS = {
    "decision_date", "market", "security_code", "company_name",
}
_FOREIGN_MARKERS = ("-KY", "F-", "-DR", "KY", "DR")


def _ubn(value: object) -> str | None:
    text = str(value or "").strip()
    return text if re.fullmatch(r"(?!00000000)[0-9]{8}", text) else None


def _foreign(*names: object) -> bool:
    combined = " ".join(str(name or "") for name in names)
    return any(marker in combined for marker in _FOREIGN_MARKERS)


def _validate_window(
    universe: pd.DataFrame,
    final_oos_start: date,
) -> pd.DataFrame:
    missing = _REQUIRED_UNIVERSE_COLUMNS - set(universe.columns)
    if missing:
        raise ValueError("trading universe columns missing: " + ", ".join(sorted(missing)))
    if universe.empty:
        raise ValueError("trading universe required")
    result = universe.copy()
    result["decision"] = pd.to_datetime(result["decision_date"], errors="raise")
    if bool((result["decision"] >= pd.Timestamp(final_oos_start)).any()):
        raise ValueError("universe decision dates must precede final OOS")
    return result


def _current_by_code(
    twse_current: object,
    tpex_current: object,
) -> dict[str, dict[str, str | None]]:
    if not isinstance(twse_current, list) or not isinstance(tpex_current, list):
        raise ValueError("official current identity payload drifted")
    result: dict[str, dict[str, str | None]] = {}
    for row in twse_current:
        if not isinstance(row, dict):
            raise ValueError("official TWSE identity row drifted")
        code = str(row.get("公司代號", "")).strip()
        if re.fullmatch(r"[1-9][0-9]{3}", code):
            result[code] = {
                "official_name": str(row.get("公司名稱", "")).strip(),
                "unified_business_number": _ubn(row.get("營利事業統一編號")),
                "source_ref": TWSE_CURRENT_IDENTITY_URL,
            }
    for row in tpex_current:
        if not isinstance(row, dict):
            raise ValueError("official TPEx identity row drifted")
        code = str(row.get("SecuritiesCompanyCode", "")).strip()
        if re.fullmatch(r"[1-9][0-9]{3}", code):
            result[code] = {
                "official_name": str(row.get("CompanyName", "")).strip(),
                "unified_business_number": _ubn(row.get("UnifiedBusinessNo.")),
                "source_ref": TPEX_CURRENT_IDENTITY_URL,
            }
    return result


def _live_filing(code: str, years: tuple[int, ...]) -> tuple[str, str] | None:
    for year in years:
        response = requests.get(
            MOPSOV_FILING_URL,
            params={
                "step": "1", "CO_ID": code, "SYEAR": str(year),
                "SSEASON": "4", "REPORT_ID": "C",
            },
            headers={"User-Agent": "CompanyQualityResearch/0.1"},
            timeout=60,
        )
        response.raise_for_status()
        text = response.content.decode("big5", "replace")
        code_match = re.search(
            r'name="tifrs-notes:CompanyID"[^>]*>([^<]+)', text
        )
        name_match = re.search(
            r'name="tifrs-notes:CompanyChineseName"[^>]*>([^<]+)', text
        )
        if code_match and name_match and code_match.group(1).strip() == code:
            return unescape(name_match.group(1)).strip(), response.url
    return None


def _live_registry(code: str, name: str) -> dict[str, object] | None:
    return _fetch_gcis_exact_identity(code, name)


def resolve_historical_legal_identities(
    universe: pd.DataFrame,
    *,
    twse_current: object,
    tpex_current: object,
    final_oos_start: date,
    fetch_filing: FetchFiling = _live_filing,
    fetch_registry: FetchRegistry = _live_registry,
) -> tuple[pd.DataFrame, dict[str, object]]:
    data = _validate_window(universe, final_oos_start)
    current = _current_by_code(twse_current, tpex_current)
    records: list[dict[str, object]] = []

    for code, rows in data.sort_values("decision").groupby("security_code", sort=True):
        code = str(code)
        last = rows.iloc[-1]
        names = sorted(set(rows["company_name"].astype(str)))
        markets = sorted(set(rows["market"].astype(str)))
        current_identity = current.get(code)
        current_name = current_identity["official_name"] if current_identity else None
        current_ubn = current_identity["unified_business_number"] if current_identity else None
        official_name: str | None = str(current_name) if current_name else None
        ubn: str | None = str(current_ubn) if current_ubn else None
        identity_source: str | None = (
            str(current_identity["source_ref"]) if current_identity else None
        )
        filing_source: str | None = None

        if ubn:
            status = "CURRENT_OFFICIAL_UBN"
        elif _foreign(*names, current_name):
            status = "FOREIGN_ISSUER_NO_TAIWAN_UBN"
        else:
            last_year = int(pd.Timestamp(str(last["decision"])).year)
            years = tuple(range(last_year - 1, last_year - 5, -1))
            filing = fetch_filing(code, years)
            if filing is None:
                status = "MISSING_PRE_OOS_FILING_IDENTITY"
            else:
                official_name, filing_source = filing
                if _foreign(*names, official_name):
                    status = "FOREIGN_ISSUER_NO_TAIWAN_UBN"
                else:
                    registry = fetch_registry(code, official_name)
                    registry_ubn = None
                    registry_name = ""
                    if registry is not None:
                        registry_ubn = _ubn(registry.get("Business_Accounting_NO"))
                        registry_name = str(registry.get("Company_Name", "")).strip()
                    if registry_ubn and registry_name == official_name:
                        ubn = registry_ubn
                        identity_source = str(
                            registry.get("_identity_link_source", "")
                            or GCIS_COMPANY_REGISTRY_URL
                        )
                        status = "PRE_OOS_FILING_GCIS_UBN"
                    else:
                        status = "GCIS_IDENTITY_UNRESOLVED"

        records.append({
            "security_code": code,
            "markets": json.dumps(markets, ensure_ascii=False),
            "observed_names": json.dumps(names, ensure_ascii=False),
            "last_decision_date": pd.Timestamp(last["decision"]).date().isoformat(),
            "official_name": official_name,
            "unified_business_number": ubn,
            "identity_status": status,
            "filing_source_ref": filing_source,
            "identity_source_ref": identity_source,
        })

    frame = pd.DataFrame(records).sort_values("security_code").reset_index(drop=True)
    counts = Counter(frame["identity_status"].astype(str))
    foreign = int(counts.get("FOREIGN_ISSUER_NO_TAIWAN_UBN", 0))
    resolved = int(frame["unified_business_number"].notna().sum())
    domestic_gap = len(frame) - resolved - foreign
    status = (
        "BLOCKED_DOMESTIC_IDENTITY_GAPS"
        if domestic_gap
        else "BLOCKED_FOREIGN_IDENTITY_POLICY" if foreign else "READY"
    )
    report = {
        "schema_version": "HistoricalLegalIdentityResolution.v1",
        "status": status,
        "final_oos_start": final_oos_start.isoformat(),
        "security_code_count": len(frame),
        "resolved_ubn_count": resolved,
        "foreign_issuer_count": foreign,
        "domestic_identity_gap_count": domestic_gap,
        "status_counts": dict(sorted(counts.items())),
        "membership_source": "OfficialTradingUniverse.v1",
        "current_company_api_usage": "immutable_identity_metadata_only",
        "foreign_identity_policy": "separate_without_fabricated_taiwan_ubn",
        "final_oos_rows_read": False,
    }
    return frame, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-universe", required=True, type=Path)
    parser.add_argument("--final-oos-start", required=True, type=date.fromisoformat)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    universe = pd.read_parquet(args.trading_universe)
    _validate_window(universe, args.final_oos_start)
    frame, report = resolve_historical_legal_identities(
        universe,
        twse_current=_fetch_json(TWSE_CURRENT_IDENTITY_URL),
        tpex_current=_fetch_json(TPEX_CURRENT_IDENTITY_URL),
        final_oos_start=args.final_oos_start,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output_dir / "historical-legal-identity.parquet", index=False)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
