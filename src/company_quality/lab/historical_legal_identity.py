"""Resolve immutable legal identities for official historical trading universes."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from html import unescape
from io import BytesIO
import json
from pathlib import Path
import re
import time
from typing import Callable
from urllib.parse import urlencode, urljoin

import pandas as pd
from pypdf import PdfReader
import requests

from company_quality.lab.finlab_materializer import (
    GCIS_COMPANY_REGISTRY_URL,
    GCIS_STATUSES,
    MOPSOV_FILING_URL,
    TPEX_CURRENT_IDENTITY_URL,
    TWSE_CURRENT_IDENTITY_URL,
    _fetch_gcis_exact_identity,
    _fetch_json,
)


FetchFiling = Callable[[str, tuple[int, ...]], tuple[str, str] | None]
FetchRegistry = Callable[[str, str], dict[str, object] | None]
FetchTradingRegistry = Callable[[str, str], dict[str, object] | None]
FetchPreOOSEventName = Callable[
    [str, tuple[str, ...], str | None, tuple[int, ...]],
    tuple[str, str, str] | None,
]
FetchCurrentIdentityChain = Callable[[str], tuple[str, str, str] | None]
RecordCallback = Callable[[dict[str, object]], None]
_REQUIRED_UNIVERSE_COLUMNS = {
    "decision_date", "market", "security_code", "company_name",
}
_FOREIGN_MARKERS = ("-KY", "F-", "-DR", "KY", "DR")
_OUTPUT_COLUMNS = (
    "security_code", "markets", "observed_names", "last_decision_date",
    "official_name", "unified_business_number", "identity_status",
    "filing_source_ref", "identity_source_ref", "source_error",
)


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


def _live_document_filing(
    code: str, years: tuple[int, ...]
) -> tuple[str, str] | None:
    endpoint = "https://doc.twse.com.tw/server-java/t57sb01"
    session = requests.Session()
    for year in years:
        params = {
            "step": "1", "colorchg": "1", "seamon": "", "mtype": "A",
            "co_id": code, "year": str(year - 1911),
        }
        index = session.get(
            endpoint,
            params=params,
            headers={"User-Agent": "CompanyQualityResearch/0.1"},
            timeout=60,
        )
        if index.status_code != 200:
            raise RuntimeError(
                f"official TWSE document index failed: HTTP {index.status_code}"
            )
        filenames = re.findall(
            rf'readfile2\(\\?"A\\?",\\?"{re.escape(code)}\\?",'
            rf'\\?"([^"\\]+\.pdf)\\?"\)',
            index.text,
        )
        preferred = [
            name
            for suffix in ("AI1.pdf", "AI3.pdf")
            for name in filenames
            if name == f"{year}04_{code}_{suffix}"
        ]
        if not preferred:
            continue
        filename = preferred[0]
        try:
            launch = session.post(
                endpoint,
                data={
                    "step": "9", "kind": "A", "co_id": code,
                    "filename": filename, "colorchg": "1",
                },
                headers={"User-Agent": "CompanyQualityResearch/0.1"},
                timeout=60,
            )
        except requests.ConnectionError:
            time.sleep(2)
            launch = session.post(
                endpoint,
                data={
                    "step": "9", "kind": "A", "co_id": code,
                    "filename": filename, "colorchg": "1",
                },
                headers={"User-Agent": "CompanyQualityResearch/0.1"},
                timeout=60,
            )
        if launch.status_code != 200:
            raise RuntimeError(
                f"official TWSE document launch failed: HTTP {launch.status_code}"
            )
        href = re.search(r"href=['\"]([^'\"]+\.pdf)['\"]", launch.text)
        if href is None:
            return None
        pdf = session.get(
            urljoin(endpoint, href.group(1)),
            headers={"User-Agent": "CompanyQualityResearch/0.1"},
            timeout=120,
        )
        if pdf.status_code != 200 or not pdf.content.startswith(b"%PDF"):
            raise RuntimeError("official TWSE financial report PDF unavailable")
        reader = PdfReader(BytesIO(pdf.content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
        if not text.strip():
            return None
        compact = re.sub(r"\s+", "", text)
        if re.search(rf"股票代碼[：:]?{re.escape(code)}", compact) is None:
            other_codes = re.findall(r"股票代碼[：:]?([0-9]{4})", compact)
            if other_codes:
                raise ValueError(
                    f"official TWSE report security code mismatch: {code} {filename}"
                )
            return None
        for line in text.splitlines():
            candidate = re.sub(r"\s+", "", line).removesuffix("及子公司")
            if candidate.endswith("股份有限公司") and 6 <= len(candidate) <= 60:
                source = endpoint + "?" + urlencode(params) + f"#{filename}"
                return candidate, source
        return None
    return None


def _live_mopsov_filing(
    code: str, years: tuple[int, ...]
) -> tuple[str, str] | None:
    for year in years:
        for report_id in ("C", "A", "B"):
            time.sleep(0.5)
            response = requests.get(
                MOPSOV_FILING_URL,
                params={
                    "step": "1", "CO_ID": code, "SYEAR": str(year),
                    "SSEASON": "4", "REPORT_ID": report_id,
                },
                headers={"User-Agent": "CompanyQualityResearch/0.1"},
                timeout=60,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    "official MOPSOV filing request blocked: "
                    f"HTTP {response.status_code}"
                )
            text = response.content.decode("big5", errors="replace")
            code_match = re.search(
                r'name="tifrs-notes:CompanyID"[^>]*>([^<]+)', text
            )
            name_match = re.search(
                r'name="tifrs-notes:CompanyChineseName"[^>]*>([^<]+)', text
            )
            if code_match and name_match and code_match.group(1).strip() == code:
                name = (
                    unescape(name_match.group(1)).strip().removesuffix("及子公司")
                )
                return name, response.url
    return None

def _live_filing(code: str, years: tuple[int, ...]) -> tuple[str, str] | None:
    return _live_mopsov_filing(code, years) or _live_document_filing(code, years)


def _live_registry(code: str, name: str) -> dict[str, object] | None:
    return _fetch_gcis_exact_identity(code, name)


def _live_trading_registry(
    _code: str,
    trading_name: str,
) -> dict[str, object] | None:
    expected_name = trading_name + "股份有限公司"
    matches: dict[str, dict[str, object]] = {}
    for status_code in GCIS_STATUSES:
        response = requests.get(
            GCIS_COMPANY_REGISTRY_URL,
            params={
                "$format": "json",
                "$filter": (
                    f"Company_Name like {trading_name} and "
                    f"Company_Status eq {status_code}"
                ),
            },
            headers={"User-Agent": "CompanyQualityResearch/0.1"},
            timeout=60,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"official GCIS registry request failed: HTTP {response.status_code}"
            )
        if not response.content:
            continue
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("official GCIS registry payload drifted")
        for row in payload:
            if not isinstance(row, dict):
                raise ValueError("official GCIS registry row drifted")
            ubn = _ubn(row.get("Business_Accounting_NO"))
            name = str(row.get("Company_Name", "")).strip()
            if ubn and name == expected_name:
                candidate = dict(row)
                candidate["_identity_link_source"] = response.url
                matches[ubn] = candidate
    return next(iter(matches.values())) if len(matches) == 1 else None


def _live_pre_oos_event_name(
    code: str,
    observed_names: tuple[str, ...],
    official_name: str | None,
    years: tuple[int, ...],
) -> tuple[str, str, str] | None:
    endpoint = "https://mops.twse.com.tw/mops/api/t05st01"
    for year in years:
        roc_year = str(year - 1911)
        response = requests.post(
            endpoint,
            json={
                "companyId": code,
                "year": roc_year,
                "month": "all",
                "firstDay": "",
                "lastDay": "",
            },
            headers={
                "User-Agent": "CompanyQualityResearch/0.1",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"official MOPS event request failed: HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("official MOPS event payload drifted")
        result = payload.get("result")
        if result is None:
            continue
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise ValueError("official MOPS event result drifted")
        for row in result["data"]:
            if not isinstance(row, list) or len(row) < 5:
                raise ValueError("official MOPS event row drifted")
            if str(row[0]).strip() != code:
                continue
            title = re.sub(r"\s+", "", str(row[4]))
            candidate: str | None = None
            historical_name: str | None = None
            rename = re.search(
                r"名稱由「([^」]+股份有限公司)」更名為「([^」]+股份有限公司)」",
                title,
            )
            if rename and (
                rename.group(1) == official_name
                or rename.group(1).removesuffix("股份有限公司") in observed_names
            ):
                candidate = rename.group(2)
                historical_name = rename.group(1)
            if candidate is None:
                for observed_name in observed_names:
                    name = observed_name + "股份有限公司"
                    if name in title:
                        candidate = name
                        historical_name = name
                        break
            if candidate:
                source = endpoint + "#" + urlencode({
                    "companyId": code, "year": roc_year, "title": title,
                })
                assert historical_name is not None
                return candidate, historical_name, source
    return None


def _live_current_identity_chain(code: str) -> tuple[str, str, str] | None:
    endpoint = "https://mops.twse.com.tw/mops/api/t05st03"
    response = requests.post(
        endpoint,
        json={"companyId": code},
        headers={
            "User-Agent": "CompanyQualityResearch/0.1",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"official MOPS company profile request failed: HTTP {response.status_code}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("official MOPS company profile payload drifted")
    result = payload.get("result")
    if result is None:
        return None
    if not isinstance(result, dict):
        raise ValueError("official MOPS company profile result drifted")

    def value(key: str) -> str:
        field = result.get(key)
        if isinstance(field, dict):
            field = field.get("value")
        return str(field or "").strip()

    current_name = value("companyName")
    before_change_name = value("beforeChangeName")
    if not current_name or not before_change_name:
        return None
    source = endpoint + "#" + urlencode({"companyId": code})
    return current_name, before_change_name, source


def resolve_historical_legal_identities(
    universe: pd.DataFrame,
    *,
    twse_current: object,
    tpex_current: object,
    final_oos_start: date,
    fetch_filing: FetchFiling = _live_filing,
    fetch_registry: FetchRegistry = _live_registry,
    fetch_trading_registry: FetchTradingRegistry = _live_trading_registry,
    fetch_pre_oos_event_name: FetchPreOOSEventName = _live_pre_oos_event_name,
    fetch_current_identity_chain: FetchCurrentIdentityChain = (
        _live_current_identity_chain
    ),
    resume_records: pd.DataFrame | None = None,
    record_callback: RecordCallback | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    data = _validate_window(universe, final_oos_start)
    current = _current_by_code(twse_current, tpex_current)
    records: list[dict[str, object]] = []
    resume_by_code: dict[str, dict[str, object]] = {}
    if resume_records is not None and not resume_records.empty:
        missing = set(_OUTPUT_COLUMNS) - set(resume_records.columns)
        if missing:
            raise ValueError(
                "checkpoint columns missing: " + ", ".join(sorted(missing))
            )
        resume_by_code = {
            str(row["security_code"]): row
            for row in resume_records.to_dict(orient="records")
        }

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
        source_error: str | None = None
        status = ""
        last_decision_date = pd.Timestamp(last["decision"]).date().isoformat()
        resumed = resume_by_code.get(code)
        if (
            resumed is not None
            and str(resumed["identity_status"]) != "SOURCE_UNAVAILABLE"
            and str(resumed["markets"]) == json.dumps(markets, ensure_ascii=False)
            and str(resumed["observed_names"]) == json.dumps(names, ensure_ascii=False)
            and str(resumed["last_decision_date"]) == last_decision_date
        ):
            records.append({column: resumed.get(column) for column in _OUTPUT_COLUMNS})
            continue

        if ubn:
            status = "CURRENT_OFFICIAL_UBN"
        elif _foreign(*names, current_name):
            status = "FOREIGN_ISSUER_NO_TAIWAN_UBN"
        else:
            last_year = int(pd.Timestamp(str(last["decision"])).year)
            years = tuple(range(last_year - 1, last_year - 5, -1))
            try:
                filing = fetch_filing(code, years)
            except (requests.RequestException, RuntimeError) as exc:
                filing = None
                status = "SOURCE_UNAVAILABLE"
                source_error = f"{type(exc).__name__}: {exc}"
            if source_error is not None:
                pass
            elif filing is None:
                trading_source = (
                    str(last["source_ref"]).strip()
                    if "source_ref" in rows.columns
                    else ""
                )
                trading_registry = None
                if len(names) == 1 and trading_source:
                    try:
                        trading_registry = fetch_trading_registry(code, names[0])
                    except (requests.RequestException, RuntimeError) as exc:
                        status = "SOURCE_UNAVAILABLE"
                        source_error = f"{type(exc).__name__}: {exc}"
                trading_ubn = None
                trading_legal_name = ""
                if source_error is None and trading_registry is not None:
                    trading_ubn = _ubn(
                        trading_registry.get("Business_Accounting_NO")
                    )
                    trading_legal_name = str(
                        trading_registry.get("Company_Name", "")
                    ).strip()
                if source_error is not None:
                    pass
                elif (
                    trading_ubn
                    and trading_legal_name == names[0] + "股份有限公司"
                ):
                    assert trading_registry is not None
                    official_name = trading_legal_name
                    ubn = trading_ubn
                    filing_source = trading_source
                    identity_source = str(
                        trading_registry.get("_identity_link_source", "")
                        or GCIS_COMPANY_REGISTRY_URL
                    )
                    status = "OFFICIAL_TRADING_NAME_GCIS_UBN"
                else:
                    status = "MISSING_PRE_OOS_FILING_IDENTITY"
            else:
                official_name, filing_source = filing
                if _foreign(*names, official_name):
                    status = "FOREIGN_ISSUER_NO_TAIWAN_UBN"
                else:
                    try:
                        registry = fetch_registry(code, official_name)
                    except (requests.RequestException, RuntimeError) as exc:
                        registry = None
                        status = "SOURCE_UNAVAILABLE"
                        source_error = f"{type(exc).__name__}: {exc}"
                    registry_ubn = None
                    registry_name = ""
                    if source_error is None and registry is not None:
                        registry_ubn = _ubn(registry.get("Business_Accounting_NO"))
                        registry_name = str(registry.get("Company_Name", "")).strip()
                    if source_error is not None:
                        pass
                    elif registry_ubn and registry_name == official_name:
                        ubn = registry_ubn
                        identity_source = str(
                            registry.get("_identity_link_source", "")
                            or GCIS_COMPANY_REGISTRY_URL
                        )
                        status = "PRE_OOS_FILING_GCIS_UBN"
                    else:
                        status = "GCIS_IDENTITY_UNRESOLVED"

        if (
            not ubn
            and status in {
                "MISSING_PRE_OOS_FILING_IDENTITY", "GCIS_IDENTITY_UNRESOLVED",
            }
            and "source_ref" in rows.columns
        ):
            event = None
            try:
                event = fetch_pre_oos_event_name(
                    code,
                    tuple(names),
                    official_name,
                    tuple(range(
                        int(pd.Timestamp(last["decision"]).year),
                        final_oos_start.year,
                    )),
                )
            except (requests.RequestException, RuntimeError) as exc:
                status = "SOURCE_UNAVAILABLE"
                source_error = f"{type(exc).__name__}: {exc}"
            if event is not None and source_error is None:
                event_name, historical_name, event_source = event
                try:
                    event_registry = fetch_registry(code, event_name)
                except (requests.RequestException, RuntimeError) as exc:
                    event_registry = None
                    status = "SOURCE_UNAVAILABLE"
                    source_error = f"{type(exc).__name__}: {exc}"
                event_ubn = None
                registry_name = ""
                if event_registry is not None:
                    event_ubn = _ubn(event_registry.get("Business_Accounting_NO"))
                    registry_name = str(
                        event_registry.get("Company_Name", "")
                    ).strip()
                if event_ubn and registry_name == event_name:
                    assert event_registry is not None
                    official_name = historical_name
                    ubn = event_ubn
                    filing_source = event_source
                    identity_source = str(
                        event_registry.get("_identity_link_source", "")
                        or GCIS_COMPANY_REGISTRY_URL
                    )
                    status = "PRE_OOS_EVENT_GCIS_UBN"

        if (
            not ubn
            and source_error is None
            and official_name
            and status == "GCIS_IDENTITY_UNRESOLVED"
        ):
            try:
                identity_chain = fetch_current_identity_chain(code)
            except (requests.RequestException, RuntimeError) as exc:
                identity_chain = None
                status = "SOURCE_UNAVAILABLE"
                source_error = f"{type(exc).__name__}: {exc}"
            if identity_chain is not None and source_error is None:
                current_name, before_change_name, chain_source = identity_chain
                if before_change_name == official_name:
                    try:
                        current_registry = fetch_registry(code, current_name)
                    except (requests.RequestException, RuntimeError) as exc:
                        current_registry = None
                        status = "SOURCE_UNAVAILABLE"
                        source_error = f"{type(exc).__name__}: {exc}"
                    current_ubn = None
                    registry_name = ""
                    if current_registry is not None:
                        current_ubn = _ubn(
                            current_registry.get("Business_Accounting_NO")
                        )
                        registry_name = str(
                            current_registry.get("Company_Name", "")
                        ).strip()
                    if current_ubn and registry_name == current_name:
                        assert current_registry is not None
                        ubn = current_ubn
                        filing_source = chain_source
                        identity_source = str(
                            current_registry.get("_identity_link_source", "")
                            or GCIS_COMPANY_REGISTRY_URL
                        )
                        status = "CURRENT_OFFICIAL_IDENTITY_CHAIN_UBN"

        record = {
            "security_code": code,
            "markets": json.dumps(markets, ensure_ascii=False),
            "observed_names": json.dumps(names, ensure_ascii=False),
            "last_decision_date": last_decision_date,
            "official_name": official_name,
            "unified_business_number": ubn,
            "identity_status": status,
            "filing_source_ref": filing_source,
            "identity_source_ref": identity_source,
            "source_error": source_error,
        }
        records.append(record)
        if record_callback is not None:
            record_callback(record)

    frame = pd.DataFrame(records).sort_values("security_code").reset_index(drop=True)
    counts = Counter(frame["identity_status"].astype(str))
    foreign = int(counts.get("FOREIGN_ISSUER_NO_TAIWAN_UBN", 0))
    source_unavailable = int(counts.get("SOURCE_UNAVAILABLE", 0))
    resolved = int(frame["unified_business_number"].notna().sum())
    domestic_gap = len(frame) - resolved - foreign - source_unavailable
    status = (
        "BLOCKED_SOURCE_UNAVAILABLE"
        if source_unavailable
        else "BLOCKED_DOMESTIC_IDENTITY_GAPS"
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
        "source_unavailable_count": source_unavailable,
        "domestic_identity_gap_count": domestic_gap,
        "status_counts": dict(sorted(counts.items())),
        "membership_source": "OfficialTradingUniverse.v1",
        "current_company_api_usage": "immutable_identity_metadata_only",
        "foreign_identity_policy": "separate_without_fabricated_taiwan_ubn",
        "final_oos_rows_read": False,
    }
    return frame, report


def _write_checkpoint(
    path: Path,
    records_by_code: dict[str, dict[str, object]],
) -> None:
    frame = pd.DataFrame(
        records_by_code.values(), columns=_OUTPUT_COLUMNS
    ).sort_values("security_code").reset_index(drop=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-universe", required=True, type=Path)
    parser.add_argument("--final-oos-start", required=True, type=date.fromisoformat)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    universe = pd.read_parquet(args.trading_universe)
    _validate_window(universe, args.final_oos_start)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = (
        args.output_dir / "historical-legal-identity.checkpoint.parquet"
    )
    resume_records = (
        pd.read_parquet(checkpoint_path) if checkpoint_path.exists() else None
    )
    checkpoint_records = {
        str(row["security_code"]): row
        for row in (
            resume_records.to_dict(orient="records")
            if resume_records is not None
            else []
        )
    }

    def checkpoint(record: dict[str, object]) -> None:
        checkpoint_records[str(record["security_code"])] = record
        _write_checkpoint(checkpoint_path, checkpoint_records)

    frame, report = resolve_historical_legal_identities(
        universe,
        twse_current=_fetch_json(TWSE_CURRENT_IDENTITY_URL),
        tpex_current=_fetch_json(TPEX_CURRENT_IDENTITY_URL),
        final_oos_start=args.final_oos_start,
        resume_records=resume_records,
        record_callback=checkpoint,
    )
    frame.to_parquet(args.output_dir / "historical-legal-identity.parquet", index=False)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
