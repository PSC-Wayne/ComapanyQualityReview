"""Build quote-observed historical T20 cohorts from official pre-OOS inputs."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from typing import cast

import pandas as pd


_UBN = re.compile(r"(?!00000000)[0-9]{8}")
_FOREIGN_STATUS = "FOREIGN_ISSUER_NO_TAIWAN_UBN"
_REQUIRED_UNIVERSE = {
    "decision_date",
    "market",
    "security_code",
    "company_name",
    "source_ref",
}
_REQUIRED_IDENTITY = {
    "security_code",
    "official_name",
    "unified_business_number",
    "identity_status",
    "identity_source_ref",
}


def build_historical_t20(
    trading_universe: pd.DataFrame,
    legal_identity: pd.DataFrame,
    *,
    cohort_asof: str | None = None,
) -> dict[str, object]:
    """Join exact official quote observations to immutable domestic identities."""
    missing_universe = sorted(_REQUIRED_UNIVERSE - set(trading_universe.columns))
    missing_identity = sorted(_REQUIRED_IDENTITY - set(legal_identity.columns))
    if missing_universe:
        raise ValueError("trading universe columns missing: " + ",".join(missing_universe))
    if missing_identity:
        raise ValueError("legal identity columns missing: " + ",".join(missing_identity))
    if trading_universe.empty:
        raise ValueError("trading universe required")
    if legal_identity["security_code"].astype(str).duplicated().any():
        raise ValueError("legal identity requires one row per security code")

    universe = trading_universe.copy()
    universe["security_code"] = universe["security_code"].astype(str)
    universe["decision_date"] = pd.to_datetime(
        universe["decision_date"], errors="raise"
    ).dt.date.astype(str)
    if set(universe["market"].astype(str)) - {"TWSE", "TPEx"}:
        raise ValueError("trading universe market drifted")
    final_decision = max(date.fromisoformat(value) for value in universe["decision_date"])
    if cohort_asof is None:
        cohort_asof = (
            f"{(final_decision + timedelta(days=1)).isoformat()}T00:00:00+08:00"
        )
    else:
        instant = datetime.fromisoformat(cohort_asof)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("cohort_asof must include a timezone")
    identity_by_code = {
        str(row["security_code"]): row
        for row in legal_identity.to_dict("records")
    }

    cohorts: dict[str, object] = {}
    failures: dict[str, dict[str, str]] = {"TWSE": {}, "TPEx": {}}
    for market in ("TWSE", "TPEx"):
        market_rows = universe.loc[universe["market"].astype(str).eq(market)]
        members: list[dict[str, object]] = []
        issuer_ids: set[str] = set()
        for code, rows in market_rows.groupby("security_code", sort=True):
            failure_key = f"security:{market}:{code}"
            identity = identity_by_code.get(str(code))
            if identity is None:
                failures[market][failure_key] = "missing_historical_legal_identity_row"
                continue
            status = str(identity["identity_status"])
            ubn = str(identity["unified_business_number"] or "").strip()
            if status == _FOREIGN_STATUS:
                failures[market][failure_key] = "owner_excluded_foreign_issuer"
                continue
            if _UBN.fullmatch(ubn) is None:
                failures[market][failure_key] = "unresolved_immutable_legal_identity"
                continue
            observed = sorted(set(rows["decision_date"].astype(str)))
            source_refs = sorted(set(rows["source_ref"].astype(str)))
            identity_source = str(identity["identity_source_ref"] or "").strip()
            members.append({
                "issuer_id": ubn,
                "security_code": str(code),
                "company_name": str(identity["official_name"] or "").strip(),
                "market": market,
                "observed_decision_dates": observed,
                "evidence_ids": [
                    *source_refs,
                    *([identity_source] if identity_source else []),
                ],
            })
            issuer_ids.add(ubn)
        cohorts[market] = {
            "schema_version": "AdverseControlCohort.v1",
            "issuer_ids": sorted(issuer_ids),
            "cohort_asof": cohort_asof,
            "members": members,
        }

    return {
        "schema_version": "HistoricalQuoteObservedT20Execution.v1",
        "status": "EXECUTED_NON_PUBLISHABLE",
        "publishable": False,
        "membership_policy": "official_quote_observed_by_decision_date",
        "identity_policy": (
            "owner_excludes_foreign_issuers_and_unresolved_domestic_identities"
        ),
        "decision_dates": sorted(set(universe["decision_date"])),
        "generation_id": f"real-historical-t20-{final_decision.isoformat()}",
        "cohorts": cohorts,
        "pre_admission_failures": failures,
        "final_oos_rows_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-universe", required=True, type=Path)
    parser.add_argument("--legal-identity", required=True, type=Path)
    parser.add_argument("--cohort-asof")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = build_historical_t20(
        pd.read_parquet(args.trading_universe),
        pd.read_parquet(args.legal_identity),
        cohort_asof=args.cohort_asof,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": payload["status"],
        "decision_dates": payload["decision_dates"],
        "pre_admission_failure_count": sum(len(rows) for rows in cast(
            dict[str, dict[str, str]], payload["pre_admission_failures"]
        ).values()),
        "final_oos_rows_read": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_historical_t20"]
