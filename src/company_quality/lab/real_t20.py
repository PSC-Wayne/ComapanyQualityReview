"""Execute real single-market T20 cohorts from FinLab and official authorities."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Mapping, cast

import pandas as pd

from company_quality.lab.cohort import (
    GovernedEventLabel,
    Market,
    OfficialUniverseMember,
    build_adverse_control_cohort,
)
from company_quality.lab.finlab_materializer import (
    TPEX_CURRENT_IDENTITY_URL,
    TWSE_CURRENT_IDENTITY_URL,
)


def _date(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"[0-9]{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    match = re.fullmatch(r"([0-9]{2,3})[-/]([0-9]{1,2})[-/]([0-9]{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        return f"{year + 1911:04d}-{month:02d}-{day:02d}"
    return datetime.fromisoformat(text).date().isoformat()


def _evidence(*values: object) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _source_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def build_real_t20(
    identity: pd.DataFrame,
    materializer_report: Mapping[str, object],
    tpex_reasons: list[dict[str, object]],
    *,
    cohort_asof: str,
    source_root: Path,
) -> dict[str, object]:
    materialized_at = str(materializer_report["materialized_at"])
    reason_by_code = {
        str(row["security_code"]).strip(): row
        for row in tpex_reasons
        if str(row.get("security_code", "")).strip()
    }
    producer_shas = {
        "T03": _source_sha(source_root / "pit/__init__.py"),
        "T04": _source_sha(source_root / "sources/financial/__init__.py"),
        "T06": _source_sha(source_root / "audit/inventory/__init__.py"),
    }
    cohort_sha = _source_sha(source_root / "lab/cohort/__init__.py")
    generation_id = f"real-t20-{datetime.fromisoformat(cohort_asof).date().isoformat()}"

    cohorts: dict[str, object] = {}
    excluded_inventory: dict[str, dict[str, str]] = {}
    market_pairs: tuple[tuple[str, Market], ...] = (("sii", "TWSE"), ("otc", "TPEx"))
    for source_market, contract_market in market_pairs:
        rows = identity.loc[identity["market"] == source_market]
        members: list[OfficialUniverseMember] = []
        labels: list[GovernedEventLabel] = []
        failures: dict[str, str] = {}
        for row in rows.itertuples(index=False):
            code = str(row.security_code)
            failure_key = f"security:{contract_market}:{code}"
            issuer_id = str(row.unified_business_number or "").strip()
            listed_on = _date(row.listed_on)
            if not bool(row.legal_identity_resolved) or not re.fullmatch(
                r"(?!00000000)[0-9]{8}", issuer_id
            ):
                failures[failure_key] = "unresolved_immutable_legal_identity"
                continue
            if listed_on is None:
                failures[failure_key] = "unresolved_official_exchange_listing_date"
                continue
            delisted_on = _date(row.delisted_on)
            identity_source = (
                TWSE_CURRENT_IDENTITY_URL
                if source_market == "sii"
                else TPEX_CURRENT_IDENTITY_URL
            )
            member_evidence = _evidence(
                f"official-lifecycle:{row.security_lifecycle_id}",
                getattr(row, "legal_identity_link_source", None),
                getattr(row, "listing_date_link_source", None),
                identity_source,
            )
            members.append(OfficialUniverseMember(
                issuer_id=issuer_id,
                security_code=code,
                company_name=str(row.official_name),
                market=contract_market,
                listed_on=listed_on,
                delisted_on=delisted_on,
                evidence_ids=member_evidence,
                available_at=materialized_at,
            ))
            if delisted_on is None or source_market != "otc":
                continue
            reason = reason_by_code.get(code)
            if reason is None or reason.get("adverse") is None:
                continue
            labels.append(GovernedEventLabel(
                issuer_id=issuer_id,
                event_code="official_delisting",
                event_class="delisting",
                adverse=bool(reason["adverse"]),
                effective_on=delisted_on,
                official_reason=str(reason["official_reason"]),
                authoritative_source_type="exchange_delisting_registry",
                delisting_kind="other_delisting",
                evidence_ids=_evidence(str(reason["source_url"])),
                available_at=materialized_at,
            ))

        cohort = build_adverse_control_cohort(
            members,
            labels,
            market=contract_market,
            cohort_asof=cohort_asof,
            min_followup_days=365,
            eligibility_version="1.0.0",
            producer_shas=producer_shas,
            generation_id=generation_id,
            producer_candidate_sha=cohort_sha,
            eligibility_failures=failures,
        )
        cohorts[contract_market] = asdict(cohort)
        excluded_inventory[contract_market] = dict(sorted(failures.items()))

    return {
        "schema_version": "RealT20Execution.v1",
        "status": "EXECUTED_NON_PUBLISHABLE",
        "publishable": False,
        "cohort_asof": cohort_asof,
        "generation_id": generation_id,
        "producer_shas": producer_shas,
        "cohorts": cohorts,
        "pre_admission_failures": excluded_inventory,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--materializer-report", required=True, type=Path)
    parser.add_argument("--tpex-reasons", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cohort-asof")
    args = parser.parse_args()

    materializer_report = json.loads(args.materializer_report.read_text())
    asof = args.cohort_asof
    if asof is None:
        asof = (
            datetime.fromisoformat(materializer_report["materialized_at"])
            + timedelta(seconds=1)
        ).isoformat()
    payload = build_real_t20(
        pd.read_parquet(args.identity),
        materializer_report,
        json.loads(args.tpex_reasons.read_text()),
        cohort_asof=asof,
        source_root=Path(__file__).parents[1],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=lambda value: float(value) if isinstance(value, Decimal) else value,
        )
        + "\n"
    )
    cohorts = cast(dict[str, dict[str, object]], payload["cohorts"])
    print(json.dumps({
        "status": payload["status"],
        "TWSE_members": len(cast(list[str], cohorts["TWSE"]["issuer_ids"])),
        "TPEx_members": len(cast(list[str], cohorts["TPEx"]["issuer_ids"])),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
