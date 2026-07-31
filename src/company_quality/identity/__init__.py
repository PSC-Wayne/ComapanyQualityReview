"""Official TWSE/TPEx company identity resolution."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

Market = Literal["TWSE", "TPEx"]
Status = Literal[
    "resolved",
    "not_found",
    "not_found_in_requested_market",
    "ambiguous_identity",
    "historical_identity_unresolved",
    "invalid_decision_time",
]
ResolutionReason = Literal[
    "official_identity_confirmed",
    "no_official_candidate",
    "preferred_market_candidate_not_found",
    "ambiguous_official_candidates",
    "historical_identity_snapshot_unavailable",
    "invalid_decision_time",
]

TWSE_IDENTITY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_IDENTITY_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class OfficialIdentitySource:
    market: Market
    url: str
    available_at: str
    rows: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class CompanyIdentity:
    security_id: str
    security_code: str
    issuer_id: str
    company_name: str
    short_name: str
    market: Market
    valid_from: str
    valid_to: None = None
    industry_code: str | None = None


@dataclass(frozen=True, slots=True)
class OfficialIdentityCandidate:
    security_code: str
    issuer_id: str
    company_name: str
    short_name: str
    market: Market
    evidence_url: str
    industry_code: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    identifier: str
    requested_market: Market | None
    decision_time: str
    status: Status
    identity: CompanyIdentity | None
    evidence_urls: tuple[str, ...]
    candidates: tuple[OfficialIdentityCandidate, ...] = ()
    reason: ResolutionReason = "no_official_candidate"
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )


@dataclass(frozen=True, slots=True)
class ArtifactIdentityAdmission:
    status: Literal["admitted", "rejected"]
    reason: Literal[
        "official_issuer_identity_match",
        "official_issuer_identity_unconfirmed",
        "wrong_issuer_candidate",
    ]
    resolved_issuer_id: str
    artifact_issuer_id: str | None
    artifact_security_code: str
    artifact_market: Market
    identity_evidence_url: str | None


def admit_artifact_identity(
    identity: CompanyIdentity,
    *,
    artifact_market: Market,
    artifact_security_code: str,
    artifact_issuer_id: str | None,
    identity_evidence_url: str | None,
) -> ArtifactIdentityAdmission:
    """Admit an artifact only through an official same-issuer identity chain."""

    confirmed = bool(
        artifact_issuer_id
        and identity_evidence_url
        and identity_evidence_url.startswith("https://")
    )
    if not confirmed:
        status: Literal["admitted", "rejected"] = "rejected"
        reason: Literal[
            "official_issuer_identity_match",
            "official_issuer_identity_unconfirmed",
            "wrong_issuer_candidate",
        ] = "official_issuer_identity_unconfirmed"
    elif artifact_issuer_id != identity.issuer_id:
        status = "rejected"
        reason = "wrong_issuer_candidate"
    else:
        status = "admitted"
        reason = "official_issuer_identity_match"
    return ArtifactIdentityAdmission(
        status=status,
        reason=reason,
        resolved_issuer_id=identity.issuer_id,
        artifact_issuer_id=artifact_issuer_id,
        artifact_security_code=artifact_security_code,
        artifact_market=artifact_market,
        identity_evidence_url=identity_evidence_url,
    )


def _candidate(
    source: OfficialIdentitySource, row: Mapping[str, str]
) -> OfficialIdentityCandidate:
    return OfficialIdentityCandidate(
        security_code=row["security_code"].strip(),
        issuer_id=row["issuer_id"].strip(),
        company_name=row["company_name"].strip(),
        short_name=row["short_name"].strip(),
        market=source.market,
        evidence_url=source.url,
        industry_code=str(row.get("industry_code", "")).strip() or None,
    )


def _parse_instant(value: str) -> datetime | None:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(_TAIPEI)


def _source_date(value: str) -> datetime:
    digits = str(value).strip()
    if len(digits) == 7:
        year = int(digits[:3]) + 1911
        month, day = int(digits[3:5]), int(digits[5:7])
    elif len(digits) == 8:
        year = int(digits[:4])
        month, day = int(digits[4:6]), int(digits[6:8])
    else:
        raise ValueError(f"unsupported official source date: {value!r}")
    return datetime(year, month, day, tzinfo=_TAIPEI)


def _listing_instant(value: str) -> str:
    return _source_date(value).isoformat(timespec="seconds")


def _available_instant(value: str) -> datetime:
    parsed = _parse_instant(value)
    if parsed is None:
        raise ValueError(f"invalid source available_at: {value!r}")
    return parsed


def _fetch_json(url: str) -> list[dict[str, str]]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "CompanyQualityResearch/0.1"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"official identity source returned no rows: {url}")
    return payload


def fetch_official_identity_sources() -> tuple[OfficialIdentitySource, ...]:
    """Fetch current official listed and OTC company identity snapshots."""
    twse_raw = _fetch_json(TWSE_IDENTITY_URL)
    tpex_raw = _fetch_json(TPEX_IDENTITY_URL)

    twse_rows = tuple(
        {
            "security_code": row["公司代號"].strip(),
            "company_name": row["公司名稱"].strip(),
            "short_name": row["公司簡稱"].strip(),
            "issuer_id": row["營利事業統一編號"].strip(),
            "listing_date": row["上市日期"].strip(),
            "industry_code": row["產業別"].strip(),
        }
        for row in twse_raw
    )
    tpex_rows = tuple(
        {
            "security_code": row["SecuritiesCompanyCode"].strip(),
            "company_name": row["CompanyName"].strip(),
            "short_name": row["CompanyAbbreviation"].strip(),
            "issuer_id": row["UnifiedBusinessNo."].strip(),
            "listing_date": row["DateOfListing"].strip(),
            "industry_code": row["SecuritiesIndustryCode"].strip(),
        }
        for row in tpex_raw
    )

    twse_available = _source_date(twse_raw[0]["出表日期"]) + timedelta(days=1)
    tpex_available = _source_date(tpex_raw[0]["Date"]) + timedelta(days=1)
    return (
        OfficialIdentitySource(
            "TWSE", TWSE_IDENTITY_URL, twse_available.isoformat(timespec="seconds"), twse_rows
        ),
        OfficialIdentitySource(
            "TPEx", TPEX_IDENTITY_URL, tpex_available.isoformat(timespec="seconds"), tpex_rows
        ),
    )


def resolve_identity(
    identifier: str,
    market: Market | None,
    decision_time: str,
    sources: Sequence[OfficialIdentitySource] | None = None,
) -> IdentityResolution:
    """Resolve one company as of an exact decision time without guessing ambiguity."""
    parsed_time = _parse_instant(decision_time)
    if parsed_time is None:
        return IdentityResolution(
            identifier,
            market,
            decision_time,
            "invalid_decision_time",
            None,
            (),
            reason="invalid_decision_time",
        )

    normalized_time = parsed_time.isoformat(
        timespec="microseconds" if parsed_time.microsecond else "seconds"
    )
    source_set = tuple(sources) if sources is not None else fetch_official_identity_sources()
    relevant = tuple(source for source in source_set if market is None or source.market == market)
    if not relevant or any(
        parsed_time < _available_instant(source.available_at) for source in relevant
    ):
        return IdentityResolution(
            identifier,
            market,
            normalized_time,
            "historical_identity_unresolved",
            None,
            tuple(source.url for source in relevant),
            reason="historical_identity_snapshot_unavailable",
        )

    needle = identifier.strip()
    all_matches: list[tuple[OfficialIdentitySource, Mapping[str, str]]] = []
    for source in source_set:
        if parsed_time < _available_instant(source.available_at):
            continue
        for row in source.rows:
            if needle in {
                row["security_code"].strip(),
                row["company_name"].strip(),
                row["short_name"].strip(),
            }:
                all_matches.append((source, row))
    matches = [
        item for item in all_matches if market is None or item[0].market == market
    ]
    candidates = tuple(_candidate(source, row) for source, row in all_matches)

    if len(matches) > 1:
        return IdentityResolution(
            identifier,
            market,
            normalized_time,
            "ambiguous_identity",
            None,
            tuple(sorted({source.url for source, _ in matches})),
            candidates=candidates,
            reason="ambiguous_official_candidates",
        )
    if not matches:
        other_market_match = market is not None and bool(all_matches)
        return IdentityResolution(
            identifier,
            market,
            normalized_time,
            "not_found_in_requested_market" if other_market_match else "not_found",
            None,
            tuple(source.url for source in relevant),
            candidates=candidates,
            reason=(
                "preferred_market_candidate_not_found"
                if other_market_match
                else "no_official_candidate"
            ),
        )

    source, row = matches[0]
    identity = CompanyIdentity(
        security_id=f"{source.market}:{row['security_code'].strip()}",
        security_code=row["security_code"].strip(),
        issuer_id=row["issuer_id"].strip(),
        company_name=row["company_name"].strip(),
        short_name=row["short_name"].strip(),
        market=source.market,
        valid_from=_listing_instant(row["listing_date"]),
        industry_code=str(row.get("industry_code", "")).strip() or None,
    )
    return IdentityResolution(
        identifier,
        market,
        normalized_time,
        "resolved",
        identity,
        (source.url,),
        candidates=candidates,
        reason="official_identity_confirmed",
    )


__all__ = [
    "ArtifactIdentityAdmission",
    "CompanyIdentity",
    "IdentityResolution",
    "OfficialIdentityCandidate",
    "OfficialIdentitySource",
    "TPEX_IDENTITY_URL",
    "TWSE_IDENTITY_URL",
    "admit_artifact_identity",
    "fetch_official_identity_sources",
    "resolve_identity",
]
