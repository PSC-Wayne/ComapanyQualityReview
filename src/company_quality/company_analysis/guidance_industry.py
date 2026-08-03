"""Local-first issuer guidance and bounded external industry evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from typing import Literal, Protocol
from urllib.request import Request, build_opener, HTTPCookieProcessor
from http.cookiejar import CookieJar
import uuid
from zoneinfo import ZoneInfo

import fitz

from .contracts import EvidenceCitation


_TAIPEI = ZoneInfo("Asia/Taipei")
_IR_PAGE = "https://mopsov.twse.com.tw/mops/web/t100sb02_1"
_IR_QUERY = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
_IR_DOWNLOAD = "https://mopsov.twse.com.tw/server-java/FileDownLoad"
_CTCI_PARSED_PRESENTATION = "993320260514M001.pdf"
_TSMC_PARSED_PRESENTATION = "233020260716M001.pdf"
_ASPEED_PARSED_PRESENTATION = "527420260529M001.pdf"
_SEC_CTCI_PROFILE = (
    (
        "industry:tsmc:q2-2026-demand",
        "2026-07-16T00:00:00-04:00",
        "https://www.sec.gov/Archives/edgar/data/1046179/000104617926000451/a2q26e_withguidancexfinal.htm",
        "strong demand for our leading-edge process technologies",
    ),
    (
        "industry:tsmc:q2-2026-capex",
        "2026-07-16T00:00:00-04:00",
        "https://www.sec.gov/Archives/edgar/data/1046179/000104617926000451/a2q26presentatione.htm",
        "Capital expenditures (496.00) (350.76) (297.22)",
    ),
)


class GuidanceEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GuidanceFact:
    fact_id: str
    statement: str
    direction: Literal["support", "counter", "context"]
    confidence: Decimal
    citation: EvidenceCitation


@dataclass(frozen=True, slots=True)
class GuidanceCollection:
    facts: tuple[GuidanceFact, ...]
    limitations: tuple[str, ...]
    cache_hits: int
    online_fetches: int
    issuer_presentation: str | None


@dataclass(frozen=True, slots=True)
class _IRRecord:
    security_code: str
    company_name: str
    event_date: date
    event_time: str
    subject: str
    chinese_filename: str


@dataclass(frozen=True, slots=True)
class _StoredArtifact:
    body: bytes
    digest: str
    source_url: str
    available_at: str
    retrieved_at: str


class GuidanceTransport(Protocol):
    def ir_list(self, *, market: str, security_code: str, roc_year: int) -> bytes: ...

    def ir_pdf(self, *, filename: str) -> bytes: ...

    def get(self, *, url: str) -> bytes: ...


class OfficialGuidanceTransport:
    def __init__(self) -> None:
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._headers = {
            "User-Agent": "CompanyQualityResearch/0.1",
            "Referer": _IR_PAGE,
        }
        try:
            self._opener.open(Request(_IR_PAGE, headers=self._headers), timeout=30).read()
        except OSError as exc:
            raise GuidanceEvidenceError("official guidance source unavailable") from exc

    def _post(self, url: str, payload: dict[str, str]) -> bytes:
        from urllib.parse import urlencode

        request = Request(
            url,
            data=urlencode(payload).encode(),
            headers={**self._headers, "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._opener.open(request, timeout=60) as response:
                return response.read()
        except OSError as exc:
            raise GuidanceEvidenceError("official guidance source unavailable") from exc

    def ir_list(self, *, market: str, security_code: str, roc_year: int) -> bytes:
        market_type = {"TWSE": "sii", "TPEx": "otc"}.get(market)
        if market_type is None:
            raise GuidanceEvidenceError("unsupported market for MOPS IR query")
        return self._post(
            _IR_QUERY,
            {
                "step": "1",
                "firstin": "ture",
                "off": "1",
                "TYPEK": market_type,
                "year": str(roc_year),
                "month": "all",
                "co_id": security_code,
            },
        )

    def ir_pdf(self, *, filename: str) -> bytes:
        return self._post(
            _IR_DOWNLOAD,
            {
                "step": "9",
                "filePath": "/home/html/nas/STR/",
                "fileName": filename,
                "functionName": "t100sb02_1",
            },
        )

    def get(self, *, url: str) -> bytes:
        request = Request(
            url,
            headers={"User-Agent": "CompanyQualityResearch wayne@example.invalid"},
        )
        try:
            with self._opener.open(request, timeout=60) as response:
                return response.read()
        except OSError as exc:
            raise GuidanceEvidenceError("official industry source unavailable") from exc


class _IRParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.nodes.append(value)


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GuidanceEvidenceError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise GuidanceEvidenceError(f"{field} must be timezone-aware")
    return result


def _artifact_root(store_root: Path, market: str, security_code: str) -> Path:
    path = store_root / "guidance" / market / security_code
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def _load_artifact(root: Path, key: str) -> _StoredArtifact | None:
    candidates: list[tuple[datetime, _StoredArtifact]] = []
    for metadata_path in root.glob(f"{_safe_key(key)}-*.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            body_path = root / str(metadata["body_file"])
            body = body_path.read_bytes()
            digest = sha256(body).hexdigest()
            if digest != metadata["sha256"]:
                continue
            artifact = _StoredArtifact(
                body=body,
                digest=digest,
                source_url=str(metadata["source_url"]),
                available_at=str(metadata["available_at"]),
                retrieved_at=str(metadata["retrieved_at"]),
            )
            candidates.append((_instant(artifact.retrieved_at, "retrieved_at"), artifact))
        except (OSError, ValueError, KeyError, TypeError, GuidanceEvidenceError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _store_artifact(
    root: Path,
    *,
    key: str,
    suffix: str,
    body: bytes,
    source_url: str,
    available_at: str,
    retrieved_at: str,
) -> _StoredArtifact:
    digest = sha256(body).hexdigest()
    stem = f"{_safe_key(key)}-{digest}"
    body_path = root / f"{stem}.{suffix}"
    metadata_path = root / f"{stem}.json"
    if not body_path.exists():
        temporary = root / f".{stem}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, body_path)
        finally:
            if temporary.exists():
                temporary.unlink()
    metadata = {
        "key": key,
        "body_file": body_path.name,
        "source_url": source_url,
        "available_at": available_at,
        "retrieved_at": retrieved_at,
        "sha256": digest,
    }
    if not metadata_path.exists():
        temporary_metadata = root / f".{stem}.{uuid.uuid4().hex}.json.tmp"
        temporary_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary_metadata, metadata_path)
    return _StoredArtifact(body, digest, source_url, available_at, retrieved_at)


def _roc_date(raw: str) -> date:
    match = re.fullmatch(r"(\d{3})/(\d{2})/(\d{2})", raw)
    if not match:
        raise GuidanceEvidenceError("invalid MOPS IR date")
    return date(int(match.group(1)) + 1911, int(match.group(2)), int(match.group(3)))


def _parse_ir_list(body: bytes, security_code: str) -> tuple[_IRRecord, ...]:
    text = body.decode("utf-8", "replace")
    if security_code not in text and "查無" not in text:
        raise GuidanceEvidenceError("MOPS IR identity mismatch")
    parser = _IRParser()
    parser.feed(text)
    records: list[_IRRecord] = []
    for row in parser.rows:
        if len(row) < 8 or row[0] != security_code:
            continue
        if not re.fullmatch(r"\d{3}/\d{2}/\d{2}", row[2]):
            continue
        filename = row[6]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.pdf", filename):
            continue
        records.append(
            _IRRecord(
                security_code=row[0],
                company_name=row[1],
                event_date=_roc_date(row[2]),
                event_time=row[3],
                subject=row[5],
                chinese_filename=filename,
            )
        )
    return tuple(records)


def _ir_available_at(record: _IRRecord) -> datetime:
    match = re.fullmatch(r"(\d{2}):(\d{2})(?::(\d{2}))?", record.event_time)
    if match is None:
        raise GuidanceEvidenceError("invalid MOPS IR time")
    return datetime(
        record.event_date.year,
        record.event_date.month,
        record.event_date.day,
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or "0"),
        tzinfo=_TAIPEI,
    )


def _pdf_pages(body: bytes) -> tuple[str, ...]:
    if not body.startswith(b"%PDF"):
        raise GuidanceEvidenceError("MOPS IR artifact is not PDF")
    try:
        document = fitz.open(stream=body, filetype="pdf")
    except Exception as exc:
        raise GuidanceEvidenceError("unreadable MOPS IR PDF") from exc
    pages = tuple(" ".join(page.get_text().split()) for page in document)
    if not any(pages):
        raise GuidanceEvidenceError("MOPS IR PDF has no readable text")
    return pages


def _pdf_fact(
    *,
    fact_id: str,
    statement: str,
    direction: Literal["support", "counter", "context"],
    confidence: str,
    period: str,
    page_number: int,
    page_text: str,
    artifact: _StoredArtifact,
) -> GuidanceFact:
    excerpt = page_text[:1800]
    citation = EvidenceCitation(
        evidence_id=f"guidance:{fact_id}:{artifact.digest[:16]}",
        source_id=f"mops-ir:{fact_id}",
        source_tier="issuer_primary",
        url=artifact.source_url,
        content_sha256=artifact.digest,
        period=period,
        available_at=artifact.available_at,
        page=page_number,
        coordinate=(Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1")),
        verbatim_excerpt=excerpt,
        source_format="pdf",
        locator=f"pdf:page:{page_number}",
    )
    return GuidanceFact(fact_id, statement, direction, Decimal(confidence), citation)


def _find_page(pages: tuple[str, ...], marker: str) -> tuple[int, str] | None:
    for index, page in enumerate(pages, start=1):
        if marker in page:
            return index, page
    return None


def _ctci_guidance_facts(
    pages: tuple[str, ...], artifact: _StoredArtifact, record: _IRRecord
) -> tuple[GuidanceFact, ...]:
    facts: list[GuidanceFact] = []
    period = record.event_date.isoformat()
    specs: tuple[
        tuple[
            str,
            str,
            str,
            Literal["support", "counter", "context"],
            str,
            tuple[str, ...],
        ],
        ...,
    ] = (
        (
            "issuer:new-contracts",
            "新簽約額及分布",
            "公司簡報揭露2025年新簽約額1,813億元；截至2026/05/04累計簽約734.46億元，當期組合以高科技41%、能資源循環28%、水資源及環境20%為主。",
            "support",
            "0.92",
            ("1,813", "734.46", "高科技41%", "能資源循環28%", "水資源及環境20%"),
        ),
        (
            "issuer:backlog",
            "在建工程及分布",
            "公司簡報揭露在建工程由2025年底4,504億元增至2026年3月底4,718億元；規模雖創高，但不等同當期營收或毛利。",
            "support",
            "0.92",
            ("4,504", "4,718"),
        ),
        (
            "issuer:revenue-conversion",
            "合併營收及分布",
            "公司簡報揭露2025年合併營收918億元，低於2024年的1,199億元；2026年第一季營收172億元，顯示高在建工程尚未自動轉為營收成長。",
            "counter",
            "0.92",
            ("1,199", "918", "172"),
        ),
        (
            "issuer:opportunity-pipeline",
            "未來12個月全球潛在商機",
            "公司自行估計未來12個月全球潛在商機9,760億元；此數字是未得標pipeline，不是合約、營收或外部需求統計。",
            "context",
            "0.82",
            ("9,760",),
        ),
        (
            "issuer:high-tech-opportunity",
            "高科技及AI商機 (1/2)",
            "公司將半導體、數據中心、電子零組件與車用電子列為高科技及AI商機；屬issuer guidance，須由實際新簽約與外部資本支出驗證。",
            "context",
            "0.82",
            ("半導體", "數據中心"),
        ),
        (
            "issuer:power-opportunity",
            "ESG商機 – 燃氣電廠",
            "公司估計燃氣電廠潛在商機約4,000億元，並稱國內天然氣電廠市占率70%；目前未取得外部官方能源規劃artifact交叉驗證，維持issuer-only。",
            "context",
            "0.75",
            ("4,000", "70%"),
        ),
    )
    for fact_id, marker, statement, direction, confidence, required_text in specs:
        found = _find_page(pages, marker)
        if found is None:
            continue
        page_number, page_text = found
        if not all(value in page_text for value in required_text):
            continue
        facts.append(
            _pdf_fact(
                fact_id=fact_id,
                statement=statement,
                direction=direction,
                confidence=confidence,
                period=period,
                page_number=page_number,
                page_text=page_text,
                artifact=artifact,
            )
        )
    return tuple(facts)


def _verified_issuer_guidance_facts(
    security_code: str,
    pages: tuple[str, ...],
    artifact: _StoredArtifact,
    record: _IRRecord,
) -> tuple[GuidanceFact, ...]:
    profiles: dict[
        str,
        tuple[
            tuple[
                str, str, str, Literal["support", "counter", "context"],
                str, tuple[str, ...],
            ], ...
        ],
    ] = {
        "2330": (
            (
                "issuer:quarter-guidance", "2026年第三季業績展望",
                "台積公司2026年第三季官方展望：美元營收446億至458億元、毛利率65%至67%、營業利益率56%至58%；屬公司指引而非已實現結果。",
                "support", "0.95", ("446", "458", "65", "67", "56", "58"),
            ),
            (
                "issuer:annual-growth-guidance", "未來展望",
                "台積公司官方簡報預期2026年美元合併營收成長略高於40%；實際結果仍受前瞻性風險影響。",
                "support", "0.95", ("2026", "40%"),
            ),
        ),
        "5274": (
            (
                "issuer:quarter-guidance", "2026年第三季營運展望",
                "信驊官方展望在美元兌新台幣31.6假設下，2026年第三季合併營收41億至43億元、毛利率67%至68%；屬公司指引而非已實現結果。",
                "support", "0.95", ("31.6", "41", "43", "67%", "68%"),
            ),
            (
                "issuer:product-roadmap", "產品路線圖",
                "信驊官方產品路線圖逐產品列示Design-in、Production-ready與Ramp-up時程，包含AST2700、AST1700、AST1040、AST1080及AST1840。",
                "support", "0.92", ("Design-in", "Production-ready", "Ramp-up", "AST2700", "AST1840"),
            ),
            (
                "issuer:business-model", "公司簡介",
                "信驊官方簡報載明其為無晶圓廠IC設計公司，產品組合涵蓋企業及雲端BMC/BIC/PFR與智慧AV。",
                "context", "0.95", ("無晶圓廠", "BMC", "智慧AV"),
            ),
            (
                "issuer:fx-one-time", "本期淨利",
                "信驊官方簡報註明2025年第二季淨利受一次性匯兌損失影響、第三季則有匯兌利益，須與本業營運分開解讀。",
                "counter", "0.92", ("one-time FX loss", "FX gain"),
            ),
        ),
    }
    facts: list[GuidanceFact] = []
    for fact_id, marker, statement, direction, confidence, required in profiles.get(
        security_code, ()
    ):
        found = next(
            (
                (page_number, page_text)
                for page_number, page_text in enumerate(pages, start=1)
                if marker in page_text
                and all(value in page_text for value in required)
            ),
            None,
        )
        if found is None:
            continue
        page_number, page_text = found
        facts.append(
            _pdf_fact(
                fact_id=fact_id,
                statement=statement,
                direction=direction,
                confidence=confidence,
                period=record.event_date.isoformat(),
                page_number=page_number,
                page_text=page_text,
                artifact=artifact,
            )
        )
    return tuple(facts)


def _sec_fact(
    *,
    fact_id: str,
    available_at: str,
    source_url: str,
    needle: str,
    artifact: _StoredArtifact,
) -> GuidanceFact:
    parser = _TextParser()
    parser.feed(artifact.body.decode("utf-8", "replace"))
    matches = [node for node in parser.nodes if needle.lower() in node.lower()]
    if not matches:
        raise GuidanceEvidenceError(f"SEC evidence text missing: {fact_id}")
    excerpt = matches[0]
    direction = "support"
    statement = (
        "TSMC於2026Q2官方SEC簡報揭露資本支出4,960億元，2025Q2為2,972.2億元；高科技建廠資本支出需求明顯增加，但不代表中鼎必然取得訂單。"
        if fact_id.endswith("capex")
        else "TSMC於2026Q2官方SEC新聞稿表示先進製程需求強勁，並預期2026Q3持續受到先進製程需求支持；此為高科技產業需求證據，不是中鼎營收指引。"
    )
    citation = EvidenceCitation(
        evidence_id=f"guidance:{fact_id}:{artifact.digest[:16]}",
        source_id=f"sec:{fact_id}",
        source_tier="official",
        url=source_url,
        content_sha256=artifact.digest,
        period="2026Q2",
        available_at=available_at,
        page=None,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="html",
        locator=f"html:data-node:{parser.nodes.index(matches[0]) + 1}",
    )
    return GuidanceFact(fact_id, statement, direction, Decimal("0.95"), citation)


class GuidanceIndustryCollector:
    def __init__(self, transport: GuidanceTransport | None = None) -> None:
        self.transport = transport

    def collect(
        self,
        *,
        market: str,
        security_code: str,
        company_name: str,
        as_of: str,
        store_root: Path,
    ) -> GuidanceCollection:
        cutoff = _instant(as_of, "as_of")
        retrieved_at = datetime.now(_TAIPEI).isoformat()
        root = _artifact_root(store_root, market, security_code)
        transport = self.transport
        hits = 0
        fetches = 0
        limitations: list[str] = []
        facts: list[GuidanceFact] = []
        current_roc_year = cutoff.astimezone(_TAIPEI).year - 1911
        records: list[_IRRecord] = []

        for roc_year in (current_roc_year, current_roc_year - 1):
            key = f"ir-list-{roc_year}"
            artifact = _load_artifact(root, key)
            is_current_snapshot = (
                artifact is not None
                and _instant(artifact.retrieved_at, "retrieved_at")
                .astimezone(_TAIPEI)
                .date()
                == cutoff.astimezone(_TAIPEI).date()
            )
            if artifact is not None and (roc_year < current_roc_year or is_current_snapshot):
                hits += 1
            else:
                if transport is None:
                    transport = OfficialGuidanceTransport()
                body = transport.ir_list(
                    market=market, security_code=security_code, roc_year=roc_year
                )
                artifact = _store_artifact(
                    root,
                    key=key,
                    suffix="html",
                    body=body,
                    source_url=_IR_QUERY,
                    available_at=retrieved_at,
                    retrieved_at=retrieved_at,
                )
                fetches += 1
            records.extend(_parse_ir_list(artifact.body, security_code))

        eligible_records = [
            record
            for record in records
            if _ir_available_at(record) <= cutoff
        ]
        if not eligible_records:
            limitations.append("as_of以前未取得可解析的MOPS法說中文簡報。")
            presentation = None
        else:
            latest = max(eligible_records, key=lambda record: (record.event_date, record.event_time))
            presentation = latest.chinese_filename
            key = f"ir-pdf-{latest.chinese_filename}"
            artifact = _load_artifact(root, key)
            if artifact is not None:
                hits += 1
            else:
                if transport is None:
                    transport = OfficialGuidanceTransport()
                body = transport.ir_pdf(filename=latest.chinese_filename)
                available_at = _ir_available_at(latest).isoformat()
                artifact = _store_artifact(
                    root,
                    key=key,
                    suffix="pdf",
                    body=body,
                    source_url=f"{_IR_DOWNLOAD}?functionName=t100sb02_1&fileName={latest.chinese_filename}",
                    available_at=available_at,
                    retrieved_at=retrieved_at,
                )
                fetches += 1
            pages = _pdf_pages(artifact.body)
            if security_code == "9933" and latest.chinese_filename == _CTCI_PARSED_PRESENTATION:
                facts.extend(_ctci_guidance_facts(pages, artifact, latest))
            elif (
                security_code == "2330"
                and latest.chinese_filename == _TSMC_PARSED_PRESENTATION
            ) or (
                security_code == "5274"
                and latest.chinese_filename == _ASPEED_PARSED_PRESENTATION
            ):
                facts.extend(
                    _verified_issuer_guidance_facts(
                        security_code, pages, artifact, latest
                    )
                )
            elif security_code == "9933":
                limitations.append(
                    "最新中鼎法說PDF已保存，但版型／數值尚未加入已驗證parser profile，未自動推論。"
                )
            else:
                limitations.append("最新法說PDF尚未加入已驗證issuer profile；原始檔已保存但未自動推論。")

        if security_code == "9933":
            for fact_id, available_at, source_url, needle in _SEC_CTCI_PROFILE:
                if _instant(available_at, "SEC available_at") > cutoff:
                    continue
                key = fact_id
                artifact = _load_artifact(root, key)
                if artifact is not None:
                    hits += 1
                else:
                    if transport is None:
                        transport = OfficialGuidanceTransport()
                    body = transport.get(url=source_url)
                    artifact = _store_artifact(
                        root,
                        key=key,
                        suffix="html",
                        body=body,
                        source_url=source_url,
                        available_at=available_at,
                        retrieved_at=retrieved_at,
                    )
                    fetches += 1
                facts.append(
                    _sec_fact(
                        fact_id=fact_id,
                        available_at=available_at,
                        source_url=source_url,
                        needle=needle,
                        artifact=artifact,
                    )
                )
            limitations.append(
                "外部產業需求目前只完成TSMC SEC高科技資本支出／需求切片；政府能源、水資源與公共工程資料源本run取得失敗，維持coverage gap。"
            )
        else:
            limitations.append("尚未設定該issuer的外部產業需求source profile。")

        unique_facts = {fact.fact_id: fact for fact in facts}
        return GuidanceCollection(
            facts=tuple(unique_facts.values()),
            limitations=tuple(limitations),
            cache_hits=hits,
            online_fetches=fetches,
            issuer_presentation=presentation,
        )
