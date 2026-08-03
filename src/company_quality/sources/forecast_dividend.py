"""Official OpenAPI discovery windows for formal forecasts and dividends.

These rows are endpoint/claim-specific official evidence.  Forecast windows do
not replace the original formal filing, and dividend rows do not collapse a
proposal, shareholder approval, or payment into one event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from company_quality.company_analysis.contracts import EvidenceCitation


_TAIPEI = ZoneInfo("Asia/Taipei")
_DATASETS = {
    ("TWSE", "t187ap15_L"): "formal_forecast_window",
    ("TWSE", "t187ap16_L"): "formal_forecast_window",
    ("TPEx", "mopsfin_t187ap15_O"): "formal_forecast_window",
    ("TPEx", "mopsfin_t187ap16_O"): "formal_forecast_window",
    ("TWSE", "t187ap45_L"): "dividend_resolution_window",
    ("TPEx", "mopsfin_t187ap39_O"): "dividend_resolution_window",
}


class ForecastDividendSourceError(ValueError):
    """Raised when an OpenAPI window cannot be bound to its exact claim."""


@dataclass(frozen=True, slots=True)
class OpenApiRecord:
    claim_type: Literal["formal_forecast_window", "dividend_resolution_window"]
    payload: Mapping[str, str]
    citation: EvidenceCitation


@dataclass(frozen=True, slots=True)
class OpenApiWindow:
    dataset_id: str
    market: Literal["TWSE", "TPEx"]
    security_code: str
    records: tuple[OpenApiRecord, ...]
    status: Literal["available", "unresolved"]
    bounded_absence: bool
    unresolved_reasons: tuple[str, ...]


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ForecastDividendSourceError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ForecastDividendSourceError(f"{field} must be timezone-aware")
    return result


def _row_code(market: str, row: Mapping[str, str]) -> str:
    return str(
        row.get("公司代號", "")
        if market == "TWSE"
        else row.get("SecuritiesCompanyCode", row.get("公司代號", ""))
    ).strip()


def _snapshot_date(row: Mapping[str, str], fallback: str) -> str:
    raw = str(row.get("出表日期", row.get("Date", ""))).strip()
    if len(raw) == 7 and raw.isdigit():
        value = datetime(
            int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]), tzinfo=_TAIPEI
        )
        return value.isoformat()
    return fallback


def _payload(
    claim_type: str, market: str, row: Mapping[str, str]
) -> dict[str, str]:
    if claim_type == "formal_forecast_window":
        return {
            "fiscal_year": str(row.get("年度", row.get("Year", ""))).strip(),
            "fiscal_quarter": str(row.get("季別", "")).strip(),
            "revision_sequence": str(row.get("財測序號", "")).strip(),
            "covered_periods": str(row.get("涵蓋期間", "")).strip(),
            "actual_value": str(
                row.get(
                    "截至該季經會計師查核或核閱數",
                    row.get("截至第1季經會計師查核或核閱數", ""),
                )
            ).strip(),
            "forecast_value": str(
                row.get(
                    "截至該季綜合損益預測數",
                    row.get(
                        "截至第1季稅前損益預測數",
                        row.get("稅前綜合損益預測數截至第4季", ""),
                    ),
                )
            ).strip(),
        }
    return {
        "decision_progress": str(
            row.get("決議（擬議）進度", row.get("DecisionProgress", ""))
        ).strip(),
        "dividend_year": str(row.get("股利年度", row.get("DividendYear", ""))).strip(),
        "proposal_date": str(
            row.get("董事會（擬議）股利分派日", row.get("BoardMeetingDate", ""))
        ).strip(),
        "approval_date": str(row.get("股東會日期", row.get("ShareholdersMeetingDate", ""))).strip(),
        "earnings_cash_per_share": str(
            row.get(
                "股東配發-盈餘分配之現金股利(元/股)",
                row.get("CashDividendFromEarningsPerShare", ""),
            )
        ).strip(),
        "capital_reserve_cash_per_share": str(
            row.get(
                "股東配發-資本公積發放之現金(元/股)",
                row.get("CashDividendFromCapitalReservePerShare", ""),
            )
        ).strip(),
        "total_cash_dividend": str(
            row.get(
                "股東配發-股東配發之現金(股利)總金額(元)",
                row.get("TotalCashDividend", ""),
            )
        ).strip(),
    }


def parse_openapi_window(
    *,
    dataset_id: str,
    market: Literal["TWSE", "TPEx"],
    security_code: str,
    rows: Sequence[Mapping[str, str]],
    source_url: str,
    content_sha256: str,
    retrieved_at: str,
    as_of: str,
) -> OpenApiWindow:
    """Bind one full-market snapshot without inventing endpoint parity or zeroes."""

    claim_type = _DATASETS.get((market, dataset_id))
    if claim_type is None:
        raise ForecastDividendSourceError("dataset is not authoritative for this market/claim")
    cutoff = _instant(as_of, "as_of")
    _instant(retrieved_at, "retrieved_at")
    if not security_code.strip():
        raise ForecastDividendSourceError("security_code is required")

    nonblank = [row for row in rows if _row_code(market, row)]
    placeholders = bool(rows) and not nonblank
    selected = [row for row in nonblank if _row_code(market, row) == security_code]
    records: list[OpenApiRecord] = []
    reasons: list[str] = []
    for index, row in enumerate(selected):
        available_at = _snapshot_date(row, retrieved_at)
        if _instant(available_at, "snapshot date") > cutoff:
            reasons.append("post_as_of_snapshot")
            continue
        normalized = _payload(claim_type, market, row)
        if claim_type == "formal_forecast_window" and not any(normalized.values()):
            reasons.append("blank_placeholder")
            continue
        citation = EvidenceCitation(
            evidence_id=f"{market}:{dataset_id}:{security_code}:row:{index}:{content_sha256[:16]}",
            source_id=f"{market.lower()}-openapi:{dataset_id}",
            source_tier="official",
            url=source_url,
            content_sha256=content_sha256,
            period=normalized.get("dividend_year") or (
                normalized.get("fiscal_year", "") + "Q" + normalized.get("fiscal_quarter", "")
            ),
            available_at=available_at,
            page=None,
            coordinate=None,
            verbatim_excerpt=str(dict(row))[:3900],
            source_format="json",
            locator=f"json:security_code={security_code};row={index}",
        )
        records.append(OpenApiRecord(claim_type, normalized, citation))  # type: ignore[arg-type]

    if placeholders:
        reasons.append("blank_placeholder")
    status: Literal["available", "unresolved"] = "unresolved" if reasons else "available"
    return OpenApiWindow(
        dataset_id=dataset_id,
        market=market,
        security_code=security_code,
        records=tuple(records),
        status=status,
        bounded_absence=bool(not placeholders and not selected and not reasons),
        unresolved_reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "ForecastDividendSourceError",
    "OpenApiRecord",
    "OpenApiWindow",
    "parse_openapi_window",
]
