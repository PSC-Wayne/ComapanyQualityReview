"""Official industry authority and medium-V1 model routing."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Mapping
from zoneinfo import ZoneInfo

from company_quality.identity import IdentityResolution, Market

Status = Literal["routed", "unsupported_scope", "blocked"]
Cyclicality = Literal["defensive", "moderate", "cyclical", "deep_cyclical"]
_TAIPEI = ZoneInfo("Asia/Taipei")
_URLS = {
    "TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "TPEx": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
}
_EXCLUDED = {"14", "15", "17"}
_SPECIAL_INDUSTRIES = {"22": "biotech", "23": "energy", "35": "energy"}
_SECTORS = {
    "materials": {"01", "03", "08", "09", "10", "11", "21"},
    "consumer": {"02", "04", "12", "16", "18", "32", "34", "37"},
    "industrial": {"05", "06"},
    "energy_utilities": {"23", "35"},
    "electronics": {"24", "25", "26", "27", "28", "29", "30", "31", "36"},
    "other_operating": {"20", "33"},
    "real_estate_construction": {"14"},
    "transportation": {"15"},
    "financial": {"17"},
    "biotechnology": {"22"},
}
_KNOWN_CODES = set().union(*_SECTORS.values())
_DEEP_CYCLICAL = {"01", "03", "08", "09", "10", "11", "21", "23"}
_CYCLICAL = {"04", "05", "06", "12", "15", "16", "35", "37"}
_DEFENSIVE = {"02"}


class IndustryRouteError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IndustryAuthority:
    market: Market
    url: str
    content_sha256: str
    available_at: str
    retrieved_at: str
    rows: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class CompanyLevelRouteEvidence:
    """Company evidence used to refine a specialised official route.

    Names are deliberately absent: a legal or short company name is identity
    provenance, not evidence of the issuer's business model.
    """

    issuer_id: str
    business_model: str
    products: tuple[str, ...]
    end_markets: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    available_at: str


@dataclass(frozen=True, slots=True)
class IndustryRoute:
    status: Status
    reason: str | None
    issuer_id: str
    sector_code: str
    industry_code: str
    business_model_tags: tuple[str, ...]
    cyclicality: Cyclicality
    peer_rule_id: str
    route_version: str
    evidence_ids: tuple[str, ...]
    route_coverage: Decimal
    decision_time: str
    authority_url: str
    authority_sha256: str
    available_at: str
    retrieved_at: str
    rating_disposition: Literal["NO_RATING_NOT_APPLICABLE"] = (
        "NO_RATING_NOT_APPLICABLE"
    )
    schema_version: Literal["IndustryRoute.v1"] = "IndustryRoute.v1"
    source_version: Literal["official-company-list-industry.v1"] = (
        "official-company-list-industry.v1"
    )
    formula_version: Literal["medium-v1-route-policy.v1"] = (
        "medium-v1-route-policy.v1"
    )
    model_version: Literal["industry-route-1.0.0"] = "industry-route-1.0.0"


def _source_date(raw: str) -> datetime:
    value = str(raw).strip()
    if len(value) == 7:
        year, month, day = int(value[:3]) + 1911, int(value[3:5]), int(value[5:])
    elif len(value) == 8:
        year, month, day = int(value[:4]), int(value[4:6]), int(value[6:])
    else:
        raise IndustryRouteError("unsupported official company-list date")
    return datetime(year, month, day, tzinfo=_TAIPEI) + timedelta(days=1)


def fetch_industry_authority(market: Market) -> IndustryAuthority:
    url = _URLS[market]
    request = urllib.request.Request(
        url, headers={"User-Agent": "CompanyQualityResearch/0.1"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    retrieved = datetime.now(_TAIPEI)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IndustryRouteError("official industry source returned invalid JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise IndustryRouteError("official industry source returned no rows")

    if market == "TWSE":
        date_key = "出表日期"
        rows = tuple({
            "security_code": row["公司代號"].strip(),
            "issuer_id": row["營利事業統一編號"].strip(),
            "company_name": row["公司名稱"].strip(),
            "short_name": row["公司簡稱"].strip(),
            "industry_code": row["產業別"].strip(),
        } for row in payload)
    else:
        date_key = "Date"
        rows = tuple({
            "security_code": row["SecuritiesCompanyCode"].strip(),
            "issuer_id": row["UnifiedBusinessNo."].strip(),
            "company_name": row["CompanyName"].strip(),
            "short_name": row["CompanyAbbreviation"].strip(),
            "industry_code": row["SecuritiesIndustryCode"].strip(),
        } for row in payload)
    available = _source_date(payload[0][date_key])
    return IndustryAuthority(
        market=market,
        url=url,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        available_at=available.isoformat(timespec="seconds"),
        retrieved_at=retrieved.isoformat(timespec="seconds"),
        rows=rows,
    )


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise IndustryRouteError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise IndustryRouteError(f"{field} must be timezone-aware")
    return result


def _sector(industry_code: str) -> str:
    for sector, codes in _SECTORS.items():
        if industry_code in codes:
            return sector
    return "unknown"


def _cyclicality(industry_code: str) -> Cyclicality:
    if industry_code in _DEEP_CYCLICAL:
        return "deep_cyclical"
    if industry_code in _CYCLICAL:
        return "cyclical"
    if industry_code in _DEFENSIVE:
        return "defensive"
    return "moderate"


def _blocked(
    identity: IdentityResolution,
    authority: IndustryAuthority,
    reason: str,
    industry_code: str = "unknown",
    evidence_ids: tuple[str, ...] = (),
    route_coverage: Decimal = Decimal("0"),
) -> IndustryRoute:
    assert identity.identity is not None
    return IndustryRoute(
        status="blocked",
        reason=reason,
        issuer_id=identity.identity.issuer_id,
        sector_code=_sector(industry_code),
        industry_code=industry_code,
        business_model_tags=("route_unresolved",),
        cyclicality=_cyclicality(industry_code),
        peer_rule_id="blocked-route.v1",
        route_version="1.0.0",
        evidence_ids=(
            f"identity:{identity.identity.security_id}",
            f"authority:{authority.content_sha256}",
            *evidence_ids,
        ),
        route_coverage=route_coverage,
        decision_time=identity.decision_time,
        authority_url=authority.url,
        authority_sha256=authority.content_sha256,
        available_at=authority.available_at,
        retrieved_at=authority.retrieved_at,
    )


def route_industry(
    identity: IdentityResolution,
    authority: IndustryAuthority,
    *,
    company_business_evidence: CompanyLevelRouteEvidence | None = None,
) -> IndustryRoute:
    if identity.status != "resolved" or identity.identity is None:
        raise IndustryRouteError("industry routing requires a resolved identity")
    company = identity.identity
    if company.market != authority.market:
        raise IndustryRouteError("identity and industry authority market mismatch")
    decision_time = _instant(identity.decision_time, "decision_time")
    available_at = _instant(authority.available_at, "authority available_at")
    _instant(authority.retrieved_at, "authority retrieved_at")
    if available_at > decision_time:
        return _blocked(
            identity, authority, "industry_authority_not_available_at_decision_time"
        )

    code_rows = tuple(
        row for row in authority.rows
        if row.get("security_code", "").strip() == company.security_code
    )
    if not code_rows:
        return _blocked(identity, authority, "official_industry_route_not_found")
    # Security code + issuer ID are the official identity join.  Legal-name and
    # short-name aliases are source provenance and never classify a route.
    matching = tuple(
        row for row in code_rows
        if row.get("issuer_id", "").strip() == company.issuer_id
    )
    if not matching:
        return _blocked(identity, authority, "industry_identity_mismatch")
    industries = {row.get("industry_code", "").strip() for row in matching}
    if len(industries) != 1:
        return _blocked(identity, authority, "conflicting_official_industry_routes")
    industry_code = next(iter(industries))
    if industry_code not in _KNOWN_CODES:
        return _blocked(
            identity, authority, "unsupported_official_industry_code", industry_code
        )

    sector = _sector(industry_code)
    cyclicality = _cyclicality(industry_code)
    unsupported = industry_code in _EXCLUDED
    specialised = _SPECIAL_INDUSTRIES.get(industry_code)
    business_evidence_ids: tuple[str, ...] = ()
    business_tags: tuple[str, ...] = ()
    route_available_at = authority.available_at
    if specialised is not None:
        if company_business_evidence is None:
            return _blocked(
                identity,
                authority,
                "company_level_business_evidence_required",
                industry_code,
            )
        business_evidence_ids = tuple(
            dict.fromkeys(company_business_evidence.evidence_ids)
        )
        populated = sum(
            (
                bool(company_business_evidence.business_model.strip()),
                bool(company_business_evidence.products),
                bool(company_business_evidence.end_markets),
            )
        )
        coverage = Decimal(populated) / Decimal("3")
        if company_business_evidence.issuer_id != company.issuer_id:
            return _blocked(
                identity,
                authority,
                "company_business_evidence_issuer_mismatch",
                industry_code,
                business_evidence_ids,
                coverage,
            )
        business_available = _instant(
            company_business_evidence.available_at,
            "company business evidence available_at",
        )
        if business_available > decision_time:
            return _blocked(
                identity,
                authority,
                "company_business_evidence_not_available_at_decision_time",
                industry_code,
                business_evidence_ids,
                coverage,
            )
        if (
            populated != 3
            or not business_evidence_ids
            or any(
                not item.strip()
                for item in (
                    *company_business_evidence.products,
                    *company_business_evidence.end_markets,
                )
            )
        ):
            return _blocked(
                identity,
                authority,
                "company_level_business_evidence_incomplete",
                industry_code,
                business_evidence_ids,
                coverage,
            )
        route_available_at = max(available_at, business_available).isoformat(
            timespec="seconds"
        )
        business_tags = (
            f"specialised_route:{specialised}",
            "company_business_model_evidenced",
            "company_products_evidenced",
            "company_end_markets_evidenced",
        )
    return IndustryRoute(
        status="unsupported_scope" if unsupported else "routed",
        reason="owner_excluded_v1_industry" if unsupported else None,
        issuer_id=company.issuer_id,
        sector_code=sector,
        industry_code=industry_code,
        business_model_tags=(
            ("unsupported_specialised_route" if unsupported else "general_operating_company"),
            f"sector:{sector}",
            *business_tags,
        ),
        cyclicality=cyclicality,
        peer_rule_id=(
            "unsupported-scope.v1"
            if unsupported else "same-market-exact-official-industry.v1"
        ),
        route_version="1.0.0",
        evidence_ids=(
            f"identity:{company.security_id}",
            f"authority:{authority.content_sha256}",
            *business_evidence_ids,
        ),
        route_coverage=Decimal("1"),
        decision_time=identity.decision_time,
        authority_url=authority.url,
        authority_sha256=authority.content_sha256,
        available_at=route_available_at,
        retrieved_at=authority.retrieved_at,
    )
