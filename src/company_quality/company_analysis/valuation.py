"""Local-first official TWSE valuation snapshot and bounded scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from typing import Protocol
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from company_quality.company_analysis.contracts import EvidenceCitation


_TAIPEI = ZoneInfo("Asia/Taipei")
_VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
_QUOTE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
_CTCI_PEER_CODES = ("6139", "6196", "6691")
_Q_PRICE = Decimal("0.01")
_Q_RATIO = Decimal("0.1")


class ValuationEvidenceError(RuntimeError):
    """Raised when official market evidence cannot be admitted."""


class ValuationTransport(Protocol):
    def get(self, *, url: str) -> bytes: ...


class OfficialValuationTransport:
    def get(self, *, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "CompanyQualityResearch/1.0"})
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except OSError as exc:
            raise ValuationEvidenceError("official TWSE valuation source unavailable") from exc


@dataclass(frozen=True, slots=True)
class MarketValuationSnapshot:
    market_date: date
    closing_price: Decimal
    pe_ratio: Decimal
    pb_ratio: Decimal
    dividend_yield: Decimal
    peer_pe_median: Decimal | None
    quote_citation: EvidenceCitation
    valuation_citation: EvidenceCitation
    cache_hits: int
    online_fetches: int


@dataclass(frozen=True, slots=True)
class ValuationScenario:
    name: str
    backlog_conversion: Decimal
    revenue_twd_100m: Decimal
    earnings_margin_factor: Decimal
    pe_ratio: Decimal
    eps: Decimal
    implied_price: Decimal
    implied_return: Decimal
    fcf_margin: Decimal
    fcf_twd_100m: Decimal


@dataclass(frozen=True, slots=True)
class ValuationScenarios:
    market: MarketValuationSnapshot
    ttm_revenue_twd_100m: Decimal
    ttm_eps: Decimal
    backlog_twd_100m: Decimal
    scenarios: tuple[ValuationScenario, ...]
    limitations: tuple[str, ...]


def _instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValuationEvidenceError("valuation as_of must include timezone")
    return result


def _roc_date(raw: str) -> date:
    if len(raw) != 7 or not raw.isdigit():
        raise ValuationEvidenceError("invalid TWSE market date")
    return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))


def _decimal(raw: object, field: str) -> Decimal:
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except Exception as exc:
        raise ValuationEvidenceError(f"invalid TWSE {field}") from exc
    if value <= 0:
        raise ValuationEvidenceError(f"non-positive TWSE {field}")
    return value


def _artifact_paths(root: Path, key: str, digest: str) -> tuple[Path, Path]:
    stem = f"{key}-{digest}"
    return root / f"{stem}.json", root / f"{stem}.meta.json"


def _load_artifact(root: Path, key: str) -> tuple[bytes, str, str] | None:
    for metadata_path in sorted(root.glob(f"{key}-*.meta.json"), reverse=True):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        body_path = root / metadata["body_filename"]
        if not body_path.exists():
            continue
        body = body_path.read_bytes()
        digest = sha256(body).hexdigest()
        if digest != metadata.get("content_sha256"):
            raise ValuationEvidenceError("cached TWSE valuation hash mismatch")
        return body, digest, str(metadata["retrieved_at"])
    return None


def _store_artifact(
    root: Path,
    *,
    key: str,
    body: bytes,
    source_url: str,
    retrieved_at: str,
) -> tuple[bytes, str, str]:
    if not body.strip().startswith(b"["):
        raise ValuationEvidenceError("TWSE valuation response is not JSON array")
    digest = sha256(body).hexdigest()
    body_path, metadata_path = _artifact_paths(root, key, digest)
    root.mkdir(parents=True, exist_ok=True)
    if not body_path.exists():
        body_path.write_bytes(body)
    if not metadata_path.exists():
        metadata_path.write_text(
            json.dumps(
                {
                    "key": key,
                    "body_filename": body_path.name,
                    "source_url": source_url,
                    "retrieved_at": retrieved_at,
                    "content_sha256": digest,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
    return body, digest, retrieved_at


def _rows(body: bytes) -> list[dict[str, str]]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValuationEvidenceError("invalid TWSE valuation JSON") from exc
    if not isinstance(parsed, list):
        raise ValuationEvidenceError("TWSE valuation payload is not a list")
    return [row for row in parsed if isinstance(row, dict)]


def _issuer_row(rows: list[dict[str, str]], security_code: str) -> dict[str, str]:
    matches = [row for row in rows if str(row.get("Code", "")) == security_code]
    if len(matches) != 1:
        raise ValuationEvidenceError("TWSE valuation issuer identity mismatch")
    return matches[0]


def _citation(
    *,
    security_code: str,
    kind: str,
    digest: str,
    row: dict[str, str],
    market_date: date,
    source_url: str,
) -> EvidenceCitation:
    available_at = datetime.combine(market_date, time(18, 0), _TAIPEI).isoformat()
    return EvidenceCitation(
        evidence_id=f"valuation:TWSE:{security_code}:{market_date}:{kind}:{digest[:16]}",
        source_id=f"TWSE:{kind}:{market_date}",
        source_tier="official",
        url=source_url,
        content_sha256=digest,
        period=market_date.isoformat(),
        available_at=available_at,
        page=None,
        coordinate=None,
        verbatim_excerpt=json.dumps(row, ensure_ascii=False, sort_keys=True),
        source_format="json",
        locator=f"json:Code:{security_code}",
    )


class MarketValuationCollector:
    def __init__(self, transport: ValuationTransport | None = None) -> None:
        self._transport = transport

    def collect(
        self,
        *,
        market: str,
        security_code: str,
        company_name: str,
        as_of: str,
        store_root: Path,
    ) -> MarketValuationSnapshot:
        if market != "TWSE":
            raise ValuationEvidenceError("official valuation snapshot currently supports TWSE only")
        cutoff = _instant(as_of)
        root = store_root / "valuation" / market / security_code
        request_date = cutoff.astimezone(_TAIPEI).date().isoformat()
        retrieved_at = datetime.now(_TAIPEI).isoformat()
        transport = self._transport
        hits = 0
        fetches = 0
        artifacts: dict[str, tuple[bytes, str, str]] = {}
        for kind, url in (("valuation", _VALUATION_URL), ("quote", _QUOTE_URL)):
            key = f"{kind}-{request_date}"
            artifact = _load_artifact(root, key)
            if artifact is not None:
                hits += 1
            else:
                if transport is None:
                    transport = OfficialValuationTransport()
                artifact = _store_artifact(
                    root,
                    key=key,
                    body=transport.get(url=url),
                    source_url=url,
                    retrieved_at=retrieved_at,
                )
                fetches += 1
            artifacts[kind] = artifact

        valuation_body, valuation_digest, _ = artifacts["valuation"]
        quote_body, quote_digest, _ = artifacts["quote"]
        valuation_rows = _rows(valuation_body)
        quote_rows = _rows(quote_body)
        valuation_row = _issuer_row(valuation_rows, security_code)
        quote_row = _issuer_row(quote_rows, security_code)
        if str(valuation_row.get("Name", "")) not in company_name or str(quote_row.get("Name", "")) not in company_name:
            raise ValuationEvidenceError("TWSE valuation company-name mismatch")
        valuation_date = _roc_date(str(valuation_row.get("Date", "")))
        quote_date = _roc_date(str(quote_row.get("Date", "")))
        if valuation_date != quote_date:
            raise ValuationEvidenceError("TWSE quote and valuation dates differ")
        available_at = datetime.combine(valuation_date, time(18, 0), _TAIPEI)
        if available_at > cutoff:
            raise ValuationEvidenceError("TWSE valuation snapshot is future-dated")

        peer_values = []
        for code in _CTCI_PEER_CODES:
            matches = [row for row in valuation_rows if str(row.get("Code", "")) == code]
            if len(matches) == 1 and str(matches[0].get("Date", "")) == str(valuation_row.get("Date", "")):
                try:
                    peer_values.append(_decimal(matches[0].get("PEratio"), "peer PE"))
                except ValuationEvidenceError:
                    pass
        peer_median = Decimal(str(median(peer_values))) if len(peer_values) >= 2 else None
        return MarketValuationSnapshot(
            market_date=valuation_date,
            closing_price=_decimal(quote_row.get("ClosingPrice"), "closing price"),
            pe_ratio=_decimal(valuation_row.get("PEratio"), "PE ratio"),
            pb_ratio=_decimal(valuation_row.get("PBratio"), "PB ratio"),
            dividend_yield=_decimal(valuation_row.get("DividendYield"), "dividend yield"),
            peer_pe_median=peer_median,
            quote_citation=_citation(
                security_code=security_code,
                kind="quote",
                digest=quote_digest,
                row=quote_row,
                market_date=quote_date,
                source_url=_QUOTE_URL,
            ),
            valuation_citation=_citation(
                security_code=security_code,
                kind="valuation",
                digest=valuation_digest,
                row=valuation_row,
                market_date=valuation_date,
                source_url=_VALUATION_URL,
            ),
            cache_hits=hits,
            online_fetches=fetches,
        )


def build_valuation_scenarios(
    *,
    market: MarketValuationSnapshot,
    ttm_revenue_twd_100m: Decimal,
    ttm_eps: Decimal,
    backlog_twd_100m: Decimal,
) -> ValuationScenarios:
    if min(ttm_revenue_twd_100m, ttm_eps, backlog_twd_100m) <= 0:
        raise ValuationEvidenceError("valuation scenario input must be positive")
    assumptions = (
        ("downside", Decimal("0.18"), Decimal("0.75"), Decimal("0.85"), Decimal("0.02")),
        ("base", Decimal("0.22"), Decimal("1.00"), Decimal("1.05"), Decimal("0.05")),
        ("upside", Decimal("0.26"), Decimal("1.25"), Decimal("1.30"), Decimal("0.08")),
    )
    scenarios: list[ValuationScenario] = []
    for name, conversion, margin_factor, pe_factor, fcf_margin in assumptions:
        revenue = backlog_twd_100m * conversion
        eps = ttm_eps * (revenue / ttm_revenue_twd_100m) * margin_factor
        pe = market.pe_ratio * pe_factor
        price = eps * pe
        scenarios.append(
            ValuationScenario(
                name=name,
                backlog_conversion=conversion,
                revenue_twd_100m=revenue.quantize(_Q_RATIO, rounding=ROUND_HALF_UP),
                earnings_margin_factor=margin_factor,
                pe_ratio=pe.quantize(_Q_RATIO, rounding=ROUND_HALF_UP),
                eps=eps.quantize(_Q_PRICE, rounding=ROUND_HALF_UP),
                implied_price=price.quantize(_Q_PRICE, rounding=ROUND_HALF_UP),
                implied_return=((price / market.closing_price - 1) * 100).quantize(_Q_RATIO, rounding=ROUND_HALF_UP),
                fcf_margin=fcf_margin,
                fcf_twd_100m=(revenue * fcf_margin).quantize(_Q_RATIO, rounding=ROUND_HALF_UP),
            )
        )
    return ValuationScenarios(
        market=market,
        ttm_revenue_twd_100m=ttm_revenue_twd_100m,
        ttm_eps=ttm_eps,
        backlog_twd_100m=backlog_twd_100m,
        scenarios=tuple(scenarios),
        limitations=(
            "情境估值為upside-only research；backlog轉換率、獲利率倍率、PE倍率與FCF margin是透明壓力測試假設，不是公司指引或正式目標價。",
            "同業PE僅為當日current context；缺乏PIT產業分類與可比性校準，未用於正式同業排名或倍數決定。",
        ),
    )
