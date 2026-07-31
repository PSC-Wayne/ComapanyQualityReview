"""Bind a current evidence bundle to a conservative single-company report."""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from typing import Iterable, Literal, Mapping, Protocol, Sequence
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from company_quality.audit.inventory import AuditFilingInventory
from company_quality.company_analysis.checklist_analysis import build_checklist_assessment
from company_quality.company_analysis.contracts import (
    CaseProbability,
    DownsideCase,
    DownsideSection,
    DownsideSectionItem,
    EvidenceCitation,
    Finding,
    SingleCompanyResearchReport,
    SourceCoverage,
    UpsideCase,
    build_single_company_research_report,
)
from company_quality.company_analysis.candidate_admission import (
    HermesApiCandidateAdapter,
    HermesCandidateAdapter,
    admit_kam_judgement,
    admit_hermes_candidates,
)
from company_quality.company_analysis.evidence_bundle import (
    CompanyEvidenceBundle,
    collect_company_evidence_bundle,
)
from company_quality.company_analysis.detailed_analysis import (
    build_detailed_analysis,
    build_financial_deterioration,
)
from company_quality.company_analysis.probability_calibration import (
    EmpiricalProbabilityCalibration,
    SingleCompanyProbabilityCalibration,
)
from company_quality.company_analysis.probability_provider import (
    ProbabilitySourceError,
    calibrate_current_generation,
)
from company_quality.sources.financial import FinancialArtifact
from company_quality.identity import CompanyIdentity, OfficialIdentitySource
from company_quality.filing_store import FilingStoreStats


class ReportOrchestrationError(RuntimeError):
    """Raised when current-generation evidence cannot safely form a report."""


class NewsSourceError(RuntimeError):
    """Raised when discovery or original-source materialization is unavailable."""


NewsSourceRole = Literal[
    "regulator",
    "court",
    "authority",
    "issuer",
    "mainstream_media",
    "social",
    "forum",
    "anonymous",
]
NewsCategory = Literal[
    "litigation_penalty",
    "project_performance",
    "safety_environment",
    "financial_credit",
    "governance_audit",
    "customer_supply_chain",
    "cybersecurity",
    "operational_interruption",
]
_NEWS_CATEGORIES = frozenset(
    {
        "litigation_penalty",
        "project_performance",
        "safety_environment",
        "financial_credit",
        "governance_audit",
        "customer_supply_chain",
        "cybersecurity",
        "operational_interruption",
    }
)
_EXTENDED_NEWS_CATEGORIES = frozenset(
    {"litigation_penalty", "project_performance", "safety_environment"}
)
_UNVERIFIED_ROLES = frozenset({"social", "forum", "anonymous"})
_SOURCE_PRECEDENCE = {
    "regulator": 0,
    "court": 0,
    "authority": 0,
    "issuer": 1,
    "mainstream_media": 2,
    "social": 3,
    "forum": 3,
    "anonymous": 3,
}
_MAINSTREAM_DOMAINS = (
    "cna.com.tw",
    "udn.com",
    "ltn.com.tw",
    "chinatimes.com",
    "ctee.com.tw",
    "ettoday.net",
    "tw.stock.yahoo.com",
)


@dataclass(frozen=True, slots=True)
class NewsDiscoveryCandidate:
    """Discovery metadata only; never report evidence by itself."""

    discovery_id: str
    url: str
    publisher: str
    source_role: NewsSourceRole
    title: str
    publication_at: str
    available_at: str


@dataclass(frozen=True, slots=True)
class _MaterializedNewsSource:
    evidence_id: str
    discovery_id: str
    issuer_id: str
    security_code: str
    company_name: str
    url: str
    publisher: str
    source_role: NewsSourceRole
    title: str
    publication_at: str
    available_at: str
    retrieved_at: str
    content_sha256: str
    artifact_path: Path
    text: str
    citation_locator: str


@dataclass(frozen=True, slots=True)
class RecentNegativeNewsEvent:
    event_id: str
    evidence_id: str
    issuer_id: str
    security_code: str
    company_name: str
    category: NewsCategory
    status: Literal["resolved", "unresolved", "ongoing"]
    event_date: str
    publication_at: str
    available_at: str
    retrieved_at: str
    publisher: str
    source_url: str
    source_role: NewsSourceRole
    citation_locator: str
    content_sha256: str
    artifact_path: Path
    verbatim_excerpt: str
    affected_account: str
    cash_flow: str
    impact: Literal["realised", "hypothetical"]
    severity: Literal["low", "medium", "high"]
    confidence: Literal["low", "medium", "high"]
    counterevidence: str
    monitoring: str
    invalidation: str
    duplicate_cluster: str
    duplicate_source_ids: tuple[str, ...]
    verification_status: Literal["verified", "unverified"]
    affects_downside: bool


@dataclass(frozen=True, slots=True)
class RecentNegativeNewsFinding(Finding):
    category: NewsCategory
    status: Literal["resolved", "unresolved", "ongoing"]
    affected_account: str
    cash_flow: str
    impact: Literal["realised", "hypothetical"]
    severity: Literal["low", "medium", "high"]
    confidence: Literal["low", "medium", "high"]
    counterevidence: str
    monitoring: str
    invalidation: str
    duplicate_cluster: str
    source_role: NewsSourceRole


@dataclass(frozen=True, slots=True)
class RecentNegativeNewsCollection:
    events: tuple[RecentNegativeNewsEvent, ...]
    status: Literal["available", "partial"]
    missing_reasons: tuple[str, ...]
    cache_hits: int
    online_fetches: int


class NewsTransport(Protocol):
    def discover(
        self, *, query: str, start_at: str, end_at: str
    ) -> Sequence[NewsDiscoveryCandidate]: ...

    def fetch(self, *, url: str) -> bytes: ...


class NewsInterpreter(Protocol):
    def interpret(
        self,
        *,
        issuer_id: str,
        as_of: str,
        sources: Sequence[Mapping[str, str]],
    ) -> Sequence[Mapping[str, object]]: ...


class GdeltNewsTransport:
    """Credential-free discovery plus direct original-URL fetches."""

    def discover(
        self, *, query: str, start_at: str, end_at: str
    ) -> Sequence[NewsDiscoveryCandidate]:
        start = _news_instant(start_at).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        end = _news_instant(end_at).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        endpoint = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(
            {
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": "250",
                "startdatetime": start,
                "enddatetime": end,
            }
        )
        request = Request(endpoint, headers={"User-Agent": "CompanyQualityResearch/0.1"})
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
        except Exception as exc:
            raise NewsSourceError("GDELT discovery unavailable") from exc
        articles = payload.get("articles") if isinstance(payload, dict) else None
        if not isinstance(articles, list):
            raise NewsSourceError("GDELT discovery returned invalid JSON")
        result: list[NewsDiscoveryCandidate] = []
        for index, item in enumerate(articles):
            if not isinstance(item, dict) or not str(item.get("url", "")).startswith("https://"):
                continue
            seen = str(item.get("seendate", ""))
            try:
                published = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc
                ).isoformat()
            except ValueError:
                continue
            domain = str(item.get("domain") or urlparse(str(item["url"])).netloc)
            role: NewsSourceRole = _domain_role(domain)
            result.append(
                NewsDiscoveryCandidate(
                    discovery_id=f"gdelt:{index}:{sha256(str(item['url']).encode()).hexdigest()[:16]}",
                    url=str(item["url"]),
                    publisher=domain,
                    source_role=role,
                    title=str(item.get("title") or domain),
                    publication_at=published,
                    available_at=published,
                )
            )
        return result

    def fetch(self, *, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "CompanyQualityResearch/0.1"})
        try:
            with urlopen(request, timeout=30) as response:
                return response.read()
        except Exception as exc:
            raise NewsSourceError("original news source unavailable") from exc


class HermesNewsInterpreter:
    """Hermes may interpret only supplied, already materialized original text."""

    def __init__(self, *, base_url: str, api_key: str, session_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id

    @classmethod
    def from_environment(cls, generation_id: str) -> HermesNewsInterpreter | None:
        api_key = (
            os.environ.get("HERMES_API_KEY")
            or os.environ.get("API_SERVER_KEY")
            or ""
        ).strip()
        if not api_key:
            return None
        return cls(
            base_url=os.environ.get(
                "HERMES_API_BASE_URL", "http://127.0.0.1:8642/v1"
            ),
            api_key=api_key,
            session_id=f"company-quality-news-{generation_id}",
        )

    def interpret(
        self,
        *,
        issuer_id: str,
        as_of: str,
        sources: Sequence[Mapping[str, str]],
    ) -> Sequence[Mapping[str, object]]:
        fields = (
            "candidate_id, issuer_id, evidence_id, verbatim_quote, event_date, category, "
            "status, affected_account, cash_flow, impact, severity, confidence, "
            "counterevidence, monitoring, invalidation, duplicate_cluster"
        )
        prompt = (
            "Interpret negative-event candidates only from supplied original source text. "
            "Return one JSON object with candidates array and no markdown. Each candidate "
            f"must contain string fields: {fields}. Copy verbatim_quote exactly. Categories "
            f"must be one of {sorted(_NEWS_CATEGORIES)}. Do not invent missing facts."
        )
        endpoint = (
            f"{self.base_url}/chat/completions"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/chat/completions"
        )
        payload = {
            "model": "hermes-agent",
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"issuer_id": issuer_id, "as_of": as_of, "sources": sources},
                        ensure_ascii=False,
                    ),
                },
            ],
            "stream": False,
            "tools": [],
        }
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Hermes-Session-Id": self.session_id,
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            decoded = json.loads(response.read())
        content = json.loads(decoded["choices"][0]["message"]["content"])
        candidates = content.get("candidates")
        if not isinstance(candidates, list) or not all(
            isinstance(item, dict) for item in candidates
        ):
            raise ValueError("Hermes news response must contain candidates array")
        return candidates


def _news_instant(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise NewsSourceError("invalid news timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise NewsSourceError("news timestamp must be timezone-aware")
    return result


def _months_before(value: datetime, months: int) -> datetime:
    year = value.year
    month = value.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _domain_role(domain: str) -> NewsSourceRole:
    host = domain.casefold()
    if "judicial.gov.tw" in host:
        return "court"
    if any(
        marker in host
        for marker in ("gov.tw", "twse.com.tw", "tpex.org.tw", "mops.twse.com.tw")
    ):
        return "authority"
    if any(host == domain or host.endswith(f".{domain}") for domain in _MAINSTREAM_DOMAINS):
        return "mainstream_media"
    return "anonymous"


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, path)


def _discovery_cache_path(root: Path, issuer_id: str, as_of: str) -> Path:
    key = sha256(f"{issuer_id}|{as_of}".encode()).hexdigest()
    return root / "discovery" / f"{key}.json"


def _load_discovery(path: Path) -> tuple[NewsDiscoveryCandidate, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise NewsSourceError("invalid cached news discovery")
    try:
        return tuple(NewsDiscoveryCandidate(**item) for item in payload)
    except (TypeError, ValueError) as exc:
        raise NewsSourceError("invalid cached news discovery") from exc


def _visible_news_text(body: bytes) -> str:
    parser = _VisibleText()
    parser.feed(body.decode("utf-8", "replace"))
    return " ".join(parser.parts)


def _materialize_news_source(
    *,
    candidate: NewsDiscoveryCandidate,
    issuer_id: str,
    security_code: str,
    company_name: str,
    retrieved_at: str,
    root: Path,
    transport: NewsTransport,
) -> tuple[_MaterializedNewsSource, bool]:
    key = sha256(candidate.url.encode()).hexdigest()
    body_path = root / "artifacts" / f"{key}.html"
    metadata_path = root / "artifacts" / f"{key}.json"
    cached = False
    if body_path.is_file() and metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        body = body_path.read_bytes()
        if metadata.get("content_sha256") != sha256(body).hexdigest():
            raise NewsSourceError("cached news artifact hash mismatch")
        cached = True
    else:
        body = transport.fetch(url=candidate.url)
        if not body:
            raise NewsSourceError("original news source returned empty body")
        digest = sha256(body).hexdigest()
        _atomic_bytes(body_path, body)
        metadata = {
            **asdict(candidate),
            "issuer_id": issuer_id,
            "security_code": security_code,
            "company_name": company_name,
            "retrieved_at": retrieved_at,
            "content_sha256": digest,
            "citation_locator": "document-text:verbatim-quote",
        }
        _atomic_json(metadata_path, metadata)
    text = _visible_news_text(body)
    if not text:
        raise NewsSourceError("original news source has no readable text")
    if not any(value and value in text for value in (company_name, security_code, issuer_id)):
        raise NewsSourceError("news source issuer identity mismatch")
    digest = sha256(body).hexdigest()
    evidence_id = f"news-source:{candidate.discovery_id}"
    return (
        _MaterializedNewsSource(
            evidence_id=evidence_id,
            discovery_id=candidate.discovery_id,
            issuer_id=issuer_id,
            security_code=security_code,
            company_name=company_name,
            url=candidate.url,
            publisher=candidate.publisher,
            source_role=candidate.source_role,
            title=candidate.title,
            publication_at=candidate.publication_at,
            available_at=candidate.available_at,
            retrieved_at=str(metadata["retrieved_at"]),
            content_sha256=digest,
            artifact_path=body_path,
            text=text,
            citation_locator=str(metadata["citation_locator"]),
        ),
        cached,
    )


def _admit_news_candidate(
    candidate: Mapping[str, object],
    *,
    source: _MaterializedNewsSource,
    issuer_id: str,
) -> RecentNegativeNewsEvent | None:
    required = (
        "candidate_id",
        "issuer_id",
        "evidence_id",
        "verbatim_quote",
        "event_date",
        "category",
        "status",
        "affected_account",
        "cash_flow",
        "impact",
        "severity",
        "confidence",
        "counterevidence",
        "monitoring",
        "invalidation",
        "duplicate_cluster",
    )
    if any(
        not isinstance(candidate.get(field), str) or not str(candidate[field]).strip()
        for field in required
    ):
        return None
    quote = str(candidate["verbatim_quote"]).strip()
    event_date = str(candidate["event_date"]).strip()
    category = str(candidate["category"])
    status = str(candidate["status"])
    impact = str(candidate["impact"])
    severity = str(candidate["severity"])
    confidence = str(candidate["confidence"])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date) is None:
        return None
    try:
        datetime.fromisoformat(event_date)
    except ValueError:
        return None
    if (
        candidate["issuer_id"] != issuer_id
        or candidate["evidence_id"] != source.evidence_id
        or quote not in source.text
        or event_date not in quote
        or category not in _NEWS_CATEGORIES
        or status not in {"resolved", "unresolved", "ongoing"}
        or impact not in {"realised", "hypothetical"}
        or severity not in {"low", "medium", "high"}
        or confidence not in {"low", "medium", "high"}
    ):
        return None
    unverified = source.source_role in _UNVERIFIED_ROLES
    return RecentNegativeNewsEvent(
        event_id=str(candidate["candidate_id"]).strip(),
        evidence_id=source.evidence_id,
        issuer_id=issuer_id,
        security_code=source.security_code,
        company_name=source.company_name,
        category=category,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        event_date=event_date,
        publication_at=source.publication_at,
        available_at=source.available_at,
        retrieved_at=source.retrieved_at,
        publisher=source.publisher,
        source_url=source.url,
        source_role=source.source_role,
        citation_locator=source.citation_locator,
        content_sha256=source.content_sha256,
        artifact_path=source.artifact_path,
        verbatim_excerpt=quote,
        affected_account=str(candidate["affected_account"]).strip(),
        cash_flow=str(candidate["cash_flow"]).strip(),
        impact=impact,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        counterevidence=str(candidate["counterevidence"]).strip(),
        monitoring=str(candidate["monitoring"]).strip(),
        invalidation=str(candidate["invalidation"]).strip(),
        duplicate_cluster=str(candidate["duplicate_cluster"]).strip(),
        duplicate_source_ids=(source.evidence_id,),
        verification_status="unverified" if unverified else "verified",
        affects_downside=not unverified,
    )


class RecentNegativeNewsCollector:
    def __init__(
        self,
        transport: NewsTransport | None = None,
        interpreter: NewsInterpreter | None = None,
    ) -> None:
        self.transport = transport or GdeltNewsTransport()
        self.interpreter = interpreter

    def collect(
        self,
        *,
        issuer_id: str,
        security_code: str,
        company_name: str,
        as_of: str,
        retrieved_at: str,
        store_root: Path,
    ) -> RecentNegativeNewsCollection:
        decision = _news_instant(as_of)
        _news_instant(retrieved_at)
        twelve_month_start = _months_before(decision, 12)
        general_start = decision - timedelta(days=180)
        root = store_root / "news" / issuer_id
        discovery_path = _discovery_cache_path(root, issuer_id, as_of)
        cache_hits = 0
        online_fetches = 0
        missing: list[str] = []
        if discovery_path.is_file():
            discoveries = _load_discovery(discovery_path)
            cache_hits += 1
        else:
            try:
                discoveries = tuple(
                    self.transport.discover(
                        query=f'"{company_name}" OR "{security_code}"',
                        start_at=twelve_month_start.isoformat(),
                        end_at=decision.isoformat(),
                    )
                )
            except Exception:
                return RecentNegativeNewsCollection(
                    events=(),
                    status="partial",
                    missing_reasons=("news_discovery_unavailable",),
                    cache_hits=0,
                    online_fetches=0,
                )
            _atomic_json(discovery_path, [asdict(item) for item in discoveries])
            online_fetches += 1

        sources: list[_MaterializedNewsSource] = []
        for item in discoveries:
            try:
                if item.source_role not in _SOURCE_PRECEDENCE:
                    raise NewsSourceError("invalid news source role")
                published = _news_instant(item.publication_at)
                available = _news_instant(item.available_at)
                if published > decision or available > decision:
                    continue
                source, cached = _materialize_news_source(
                    candidate=item,
                    issuer_id=issuer_id,
                    security_code=security_code,
                    company_name=company_name,
                    retrieved_at=retrieved_at,
                    root=root,
                    transport=self.transport,
                )
                sources.append(source)
                if cached:
                    cache_hits += 1
                else:
                    online_fetches += 1
            except Exception:
                missing.append(f"news_original_unavailable:{item.discovery_id}")

        if self.interpreter is None:
            return RecentNegativeNewsCollection(
                events=(),
                status="partial",
                missing_reasons=tuple((*missing, "hermes_news_not_configured")),
                cache_hits=cache_hits,
                online_fetches=online_fetches,
            )
        supplied = tuple(
            {
                "evidence_id": item.evidence_id,
                "publisher": item.publisher,
                "source_role": item.source_role,
                "publication_at": item.publication_at,
                "available_at": item.available_at,
                "source_url": item.url,
                "original_text": item.text[:12000],
            }
            for item in sources
        )
        try:
            candidates = self.interpreter.interpret(
                issuer_id=issuer_id, as_of=as_of, sources=supplied
            )
        except Exception:
            return RecentNegativeNewsCollection(
                events=(),
                status="partial",
                missing_reasons=tuple((*missing, "hermes_news_unavailable")),
                cache_hits=cache_hits,
                online_fetches=online_fetches,
            )
        by_evidence = {item.evidence_id: item for item in sources}
        admitted: list[RecentNegativeNewsEvent] = []
        for candidate in candidates:
            source = by_evidence.get(str(candidate.get("evidence_id", "")))
            event = (
                _admit_news_candidate(candidate, source=source, issuer_id=issuer_id)
                if source is not None
                else None
            )
            if event is None:
                missing.append("news_candidate_rejected")
                continue
            publication = _news_instant(event.publication_at)
            in_general_window = publication >= general_start
            in_extended_window = (
                publication >= twelve_month_start
                and event.category in _EXTENDED_NEWS_CATEGORIES
                and event.status in {"unresolved", "ongoing"}
            )
            if in_general_window or in_extended_window:
                admitted.append(event)

        clusters: dict[str, list[RecentNegativeNewsEvent]] = {}
        for event in admitted:
            clusters.setdefault(event.duplicate_cluster, []).append(event)
        promoted: list[RecentNegativeNewsEvent] = []
        for cluster in clusters.values():
            primary = min(cluster, key=lambda item: _SOURCE_PRECEDENCE[item.source_role])
            promoted.append(
                replace(
                    primary,
                    duplicate_source_ids=tuple(item.evidence_id for item in cluster),
                )
            )
        promoted.sort(key=lambda item: item.publication_at, reverse=True)
        return RecentNegativeNewsCollection(
            events=tuple(promoted),
            status="partial" if missing else "available",
            missing_reasons=tuple(dict.fromkeys(missing)),
            cache_hits=cache_hits,
            online_fetches=online_fetches,
        )


@dataclass(frozen=True, slots=True)
class KamAnnualTimeline:
    period: str
    citation: EvidenceCitation
    kam_present: bool
    opinion_type: str | None
    modified_opinion: bool | None
    going_concern: bool
    emphasis_matter: bool
    auditor_change: bool | None


@dataclass(frozen=True, slots=True)
class KamJudgement:
    generation_id: str
    status: Literal["available", "partial"]
    coverage: SourceCoverage
    years: tuple[KamAnnualTimeline, ...]
    missing_year_reasons: tuple[str, ...]
    change_summary: str | None
    risk_mechanism: str | None
    counterevidence: str | None
    severity: Literal["none", "low", "medium", "high", "critical"] | None
    confidence: Decimal | None
    monitoring: str | None
    invalidation: str | None
    rejection_reasons: tuple[str, ...]
    schema_version: Literal["KamJudgement.v1"] = "KamJudgement.v1"


@dataclass(frozen=True, slots=True)
class CompanyAnalysisResult:
    generation_id: str
    identity: CompanyIdentity
    evidence_status: Literal["complete", "partial", "blocked"]
    source_coverage: tuple[SourceCoverage, ...]
    kam_judgement: KamJudgement
    research_report: SingleCompanyResearchReport
    recent_negative_news: RecentNegativeNewsCollection
    probability_calibration: SingleCompanyProbabilityCalibration | None
    calibration_error: str | None
    filing_store_stats: FilingStoreStats | None = None
    status: Literal["research_only"] = "research_only"
    schema_version: Literal["DashboardCompanyAnalysisResult.v1"] = (
        "DashboardCompanyAnalysisResult.v1"
    )


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.replace("\xa0", " ").split())
        if text:
            self.parts.append(text)


def _income_artifacts(bundle: CompanyEvidenceBundle) -> Iterable[FinancialArtifact]:
    for period in reversed(bundle.periods):
        if period.financial is None:
            continue
        for artifact in period.financial.artifacts:
            if artifact.report == "income":
                yield artifact


def _citation(bundle: CompanyEvidenceBundle) -> EvidenceCitation:
    artifact = next(iter(_income_artifacts(bundle)), None)
    if artifact is None:
        raise ReportOrchestrationError("no citable official income statement")
    body = artifact.path.read_bytes()
    if sha256(body).hexdigest() != artifact.content_sha256:
        raise ReportOrchestrationError("financial artifact content hash mismatch")
    parser = _VisibleText()
    parser.feed(body.decode("utf-8", "replace"))
    text = " ".join(parser.parts)
    marker = "綜合損益表"
    index = text.find(marker)
    if index < 0:
        raise ReportOrchestrationError("income statement title not found in official artifact")
    start = max(0, index - 120)
    excerpt = text[start : index + len(marker) + 180].strip()
    if not excerpt:
        raise ReportOrchestrationError("official income statement has no citable text")
    return EvidenceCitation(
        evidence_id=artifact.artifact_id,
        source_id=artifact.artifact_id,
        source_tier="official",
        url=artifact.official_url,
        content_sha256=artifact.content_sha256,
        period=artifact.period,
        available_at=artifact.available_at,
        page=None,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="html",
        locator="document-text:contains(綜合損益表)",
    )


def _unavailable(reason: str) -> CaseProbability:
    return CaseProbability(
        status="unavailable",
        lower=None,
        point=None,
        upper=None,
        confidence=None,
        calibration_id=None,
        reason=reason,
    )


def _formal(metric: EmpiricalProbabilityCalibration) -> CaseProbability:
    if any(
        value is None
        for value in (
            metric.lower,
            metric.point,
            metric.upper,
            metric.confidence_level,
            metric.calibration_id,
        )
    ):
        raise ReportOrchestrationError("formal calibration has incomplete values")
    return CaseProbability(
        status="formal",
        lower=metric.lower,
        point=metric.point,
        upper=metric.upper,
        confidence=metric.confidence_level,
        calibration_id=metric.calibration_id,
        reason="歷史季節匹配、互不重疊12個月標籤的Wilson 90%區間；不是當前證據條件機率。",
    )


def _probabilities(
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    calibration: SingleCompanyProbabilityCalibration | None,
    unavailable_reason: str | None,
) -> tuple[CaseProbability, CaseProbability]:
    if calibration is None:
        reason = unavailable_reason or "本generation尚未取得可重現的公司總報酬與官方benchmark校準輸入。"
        return _unavailable(reason), _unavailable(reason)
    if calibration.generation_id != generation_id:
        raise ReportOrchestrationError("calibration generation mismatch")
    if (
        calibration.issuer_id != bundle.identity.issuer_id
        or calibration.security_code != bundle.identity.security_code
        or calibration.market != bundle.identity.market
    ):
        raise ReportOrchestrationError("calibration identity mismatch")
    if calibration.status != "formal":
        reason = calibration.failure_reasons.get(
            "minimum_observations", "formal probability calibration unavailable"
        )
        return _unavailable(reason), _unavailable(reason)
    return _formal(calibration.positive_return), _formal(calibration.official_outperformance)


def _coverage(bundle: CompanyEvidenceBundle, family: str) -> tuple[int, int]:
    item = next((row for row in bundle.source_coverage if row.family == family), None)
    return (item.available, item.required) if item is not None else (0, 0)


def _pdf_pages(path: Path) -> tuple[str, ...]:
    from pypdf import PdfReader

    return tuple((page.extract_text() or "") for page in PdfReader(path).pages)


def _kam_excerpt(pages: Sequence[str]) -> tuple[int, str] | None:
    marker = "關鍵查核事項"
    for page_number, raw in enumerate(pages, start=1):
        text = " ".join(raw.replace("\xa0", " ").split())
        index = text.find(marker)
        if index < 0:
            continue
        excerpt = text[index : index + 3900].strip()
        if len(excerpt) > len(marker) + 8:
            return page_number, excerpt
    return None


def build_kam_judgement(
    *,
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    candidate_adapter: HermesCandidateAdapter | None,
) -> KamJudgement:
    """Build the latest-three available annual KAM timeline and admit Hermes judgement."""

    decision = datetime.fromisoformat(bundle.request.as_of.replace("Z", "+00:00"))
    rows: list[tuple[AuditFilingInventory, EvidenceCitation, tuple[str, ...]]] = []
    missing: list[str] = []
    annuals = sorted(
        (item for item in bundle.periods if item.is_annual),
        key=lambda item: item.period,
        reverse=True,
    )
    for period in annuals:
        audit = period.audit
        if audit is None:
            missing.append(f"{period.period}:annual_audit_pdf:missing")
            continue
        if audit.issuer_id != bundle.request.issuer_id:
            missing.append(f"{period.period}:kam:wrong_issuer")
            continue
        available = datetime.fromisoformat(audit.available_at.replace("Z", "+00:00"))
        if available > decision:
            missing.append(f"{period.period}:kam:after_as_of")
            continue
        if (
            audit.pdf_path is None
            or audit.pdf_sha256 is None
            or audit.pdf_source_url is None
            or not audit.pdf_path.is_file()
        ):
            missing.append(f"{period.period}:kam:pdf_missing")
            continue
        body = audit.pdf_path.read_bytes()
        if sha256(body).hexdigest() != audit.pdf_sha256:
            missing.append(f"{period.period}:kam:content_hash_mismatch")
            continue
        try:
            pages = _pdf_pages(audit.pdf_path)
        except Exception:
            missing.append(f"{period.period}:kam:pdf_parse_failed")
            continue
        located = _kam_excerpt(pages)
        if located is None:
            missing.append(f"{period.period}:kam:original_text_missing")
            continue
        page, excerpt = located
        citation = EvidenceCitation(
            evidence_id=f"kam:{audit.period}:{audit.pdf_sha256}",
            source_id=f"annual-audit:{audit.period}",
            source_tier="official",
            url=audit.pdf_source_url,
            content_sha256=audit.pdf_sha256,
            period=audit.period,
            available_at=audit.available_at,
            page=page,
            coordinate=(Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1")),
            verbatim_excerpt=excerpt,
        )
        rows.append((audit, citation, pages))
        if len(rows) == 3:
            break

    if len(rows) < 3:
        annual_coverage = next(
            (item for item in bundle.source_coverage if item.family == "annual_audit_pdf"),
            None,
        )
        if annual_coverage is not None:
            missing.extend(annual_coverage.missing_reasons)
        if not missing:
            missing.append(f"kam_annual_comparison:only_{len(rows)}_available")
    missing_reasons = tuple(dict.fromkeys(missing))
    years: list[KamAnnualTimeline] = []
    for index, (audit, citation, pages) in enumerate(rows):
        older = rows[index + 1][0] if index + 1 < len(rows) else None
        current_auditor = (audit.auditor_firm, audit.auditors)
        older_auditor = (
            (older.auditor_firm, older.auditors)
            if older is not None
            else None
        )
        full_text = " ".join(pages)
        opinion = audit.opinion_type
        years.append(
            KamAnnualTimeline(
                period=citation.period,
                citation=citation,
                kam_present=True,
                opinion_type=opinion,
                modified_opinion=None if opinion is None else opinion != "unmodified",
                going_concern="繼續經營有關之重大不確定性" in full_text,
                emphasis_matter="強調事項" in full_text,
                auditor_change=(
                    current_auditor != older_auditor if older_auditor is not None else None
                ),
            )
        )

    admitted = None
    rejection_reasons: tuple[str, ...]
    citations = tuple(item.citation for item in years)
    if not citations:
        rejection_reasons = ("kam_timeline_unavailable",)
    elif candidate_adapter is None:
        rejection_reasons = ("hermes_not_configured",)
    else:
        try:
            candidate = candidate_adapter.judge_kam(
                issuer_id=bundle.request.issuer_id,
                as_of=bundle.request.as_of,
                generation_id=generation_id,
                citations=citations,
            )
            admitted, rejection_reasons = admit_kam_judgement(
                candidate=candidate,
                issuer_id=bundle.request.issuer_id,
                citations=citations,
            )
        except Exception:
            rejection_reasons = ("hermes_unavailable",)
    complete = len(years) == 3 and admitted is not None
    return KamJudgement(
        generation_id=generation_id,
        status="available" if complete else "partial",
        coverage=SourceCoverage(
            family="kam_annual_comparison",
            required=3,
            available=len(years),
            missing_reasons=missing_reasons,
        ),
        years=tuple(years),
        missing_year_reasons=missing_reasons,
        change_summary=admitted.change_summary if admitted else None,
        risk_mechanism=admitted.risk_mechanism if admitted else None,
        counterevidence=admitted.counterevidence if admitted else None,
        severity=admitted.severity if admitted else None,
        confidence=admitted.confidence if admitted else None,
        monitoring=admitted.monitoring if admitted else None,
        invalidation=admitted.invalidation if admitted else None,
        rejection_reasons=rejection_reasons,
    )


def _unique_citations(
    citations: Iterable[EvidenceCitation],
) -> tuple[EvidenceCitation, ...]:
    return tuple({item.evidence_id: item for item in citations}.values())


def _with_hermes_candidates(
    *,
    report: SingleCompanyResearchReport,
    candidate_adapter: HermesCandidateAdapter | None,
) -> SingleCompanyResearchReport:
    if candidate_adapter is None:
        return replace(
            report,
            limitations=(
                *report.limitations,
                "Hermes候選抽取：partial (hermes_not_configured)。",
            ),
        )
    try:
        locked_values = (
            tuple(
                {
                    "period": period.period,
                    "basis": period.basis,
                    "metrics": tuple(
                        {
                            "metric_id": metric.metric_id,
                            "absolute_value": str(metric.absolute_value),
                            "ratio": str(metric.ratio) if metric.ratio is not None else None,
                            "yoy_change": (
                                str(metric.yoy_change)
                                if metric.yoy_change is not None
                                else None
                            ),
                            "ratio_yoy_change": (
                                str(metric.ratio_yoy_change)
                                if metric.ratio_yoy_change is not None
                                else None
                            ),
                            "sequential_change": (
                                str(metric.sequential_change)
                                if metric.sequential_change is not None
                                else None
                            ),
                            "ratio_sequential_change": (
                                str(metric.ratio_sequential_change)
                                if metric.ratio_sequential_change is not None
                                else None
                            ),
                            "direction": metric.direction,
                            "evidence_ids": metric.evidence_ids,
                        }
                        for metric in period.metrics
                    ),
                }
                for period in report.financial_deterioration.periods
            )
            if report.financial_deterioration is not None
            else ()
        )
        candidates = candidate_adapter.extract_candidates(
            issuer_id=report.request.issuer_id,
            as_of=report.request.as_of,
            generation_id=report.generation_id,
            citations=report.citations,
            locked_values=locked_values,
        )
        admission = admit_hermes_candidates(
            candidates=candidates,
            issuer_id=report.request.issuer_id,
            as_of=report.request.as_of,
            citations=report.citations,
        )
    except Exception:
        financial_deterioration = (
            replace(
                report.financial_deterioration,
                status="partial",
                partial_reason="hermes_unavailable",
            )
            if report.financial_deterioration is not None
            else None
        )
        return replace(
            report,
            limitations=(
                *report.limitations,
                "Hermes候選抽取：partial (hermes_unavailable)。",
            ),
            financial_deterioration=financial_deterioration,
        )
    findings = tuple(
        Finding(
            finding_id=item.candidate_id,
            kind="fact",
            direction="context",
            statement=item.statement,
            materiality=Decimal("0"),
            evidence_ids=(item.evidence_id,),
            supporting_finding_ids=(),
            counter_finding_ids=(),
            counter_evidence_reason=None,
        )
        for item in admission.admitted
        if item.candidate_id != "hermes:financial-deterioration:synthesis"
    )
    rejected = ",".join(item.reason for item in admission.rejected)
    status = "available" if not admission.rejected else "partial"
    detail = f"；typed_rejections={rejected}" if rejected else ""
    financial_deterioration = report.financial_deterioration
    financial_evidence_ids = (
        {
            evidence_id
            for period in financial_deterioration.periods
            for metric in period.metrics
            for evidence_id in metric.evidence_ids
        }
        if financial_deterioration is not None
        else set()
    )
    syntheses = tuple(
        item
        for item in admission.admitted
        if item.candidate_id == "hermes:financial-deterioration:synthesis"
        and item.evidence_id in financial_evidence_ids
        and not any(character.isdigit() for character in item.statement)
    )
    if financial_deterioration is not None:
        if syntheses:
            first_item = replace(
                financial_deterioration.items[0], summary=syntheses[0].statement
            )
            financial_deterioration = replace(
                financial_deterioration,
                status="available",
                items=(first_item, *financial_deterioration.items[1:]),
                partial_reason=None,
            )
        elif candidates:
            financial_deterioration = replace(
                financial_deterioration,
                status="partial",
                partial_reason="hermes_synthesis_not_admitted",
            )
        elif financial_deterioration.partial_reason == "hermes_not_configured":
            financial_deterioration = replace(
                financial_deterioration,
                status="available",
                partial_reason=None,
            )
    return build_single_company_research_report(
        request=report.request,
        generation_id=report.generation_id,
        generated_at=report.generated_at,
        citations=report.citations,
        source_coverage=report.source_coverage,
        downside=replace(report.downside, findings=(*report.downside.findings, *findings)),
        upside=report.upside,
        valuation=report.valuation,
        limitations=(
            *report.limitations,
            f"Hermes候選抽取：{status}{detail}。",
        ),
        financial_deterioration=financial_deterioration,
        checklist_assessment=report.checklist_assessment,
    )


def build_report_from_evidence(
    *,
    bundle: CompanyEvidenceBundle,
    generation_id: str,
    generated_at: str,
    calibration: SingleCompanyProbabilityCalibration | None = None,
    calibration_unavailable_reason: str | None = None,
    candidate_adapter: HermesCandidateAdapter | None = None,
) -> SingleCompanyResearchReport:
    """Produce a valid conservative report without inventing unimplemented analysis."""

    try:
        generated = datetime.fromisoformat(generated_at)
    except ValueError as exc:
        raise ReportOrchestrationError("invalid generated_at") from exc
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ReportOrchestrationError("generated_at must be timezone-aware")
    checklist_assessment = build_checklist_assessment(bundle, generation_id, None)
    core = next(
        (item for item in bundle.source_coverage if item.family == "three_statement_html"),
        None,
    )
    if core is None or core.available < core.required:
        unavailable = _unavailable("核心三表不足，整份分析blocked。")
        return build_single_company_research_report(
            request=bundle.request,
            generation_id=generation_id,
            generated_at=generated_at,
            citations=(),
            source_coverage=bundle.source_coverage,
            downside=DownsideCase(
                generation_id=generation_id,
                status="blocked",
                headline="核心三表不足，Downside分析blocked。",
                findings=(),
                twelve_month_drawdown_probability=unavailable,
                confidence=Decimal("0"),
            ),
            upside=UpsideCase(
                generation_id=generation_id,
                status="blocked",
                headline="核心三表不足，Upside分析blocked。",
                findings=(),
                positive_return_probability=unavailable,
                benchmark_outperform_probability=unavailable,
                confidence=Decimal("0"),
            ),
            limitations=("core_three_statements_incomplete",),
            checklist_assessment=checklist_assessment,
            status="blocked",
        )
    audit_available, audit_required = _coverage(bundle, "audit_or_review_pdf")
    annual_available, annual_required = _coverage(bundle, "annual_audit_pdf")
    positive, outperform = _probabilities(
        bundle, generation_id, calibration, calibration_unavailable_reason
    )
    financial_deterioration, financial_citations = build_financial_deterioration(
        bundle, generation_id
    )
    detailed = build_detailed_analysis(bundle)
    checklist_assessment = build_checklist_assessment(
        bundle, generation_id, financial_deterioration, detailed
    )
    if detailed.available:
        limitations = [
            *detailed.limitations,
            f"查核／核閱PDF coverage為{audit_available}/{audit_required}；年度查核PDF為{annual_available}/{annual_required}。",
        ]
        if positive.status != "formal":
            limitations.append("本generation沒有正式12個月報酬機率，Dashboard必須顯示unavailable。")
        report = build_single_company_research_report(
            request=bundle.request,
            generation_id=generation_id,
            generated_at=generated_at,
            citations=_unique_citations((*detailed.citations, *financial_citations)),
            source_coverage=bundle.source_coverage,
            downside=DownsideCase(
                generation_id=generation_id,
                status="research_only",
                headline=detailed.downside_headline,
                findings=detailed.downside_findings,
                twelve_month_drawdown_probability=_unavailable(
                    "未來12個月最大跌幅事件尚未正式校準。"
                ),
                confidence=detailed.downside_confidence,
            ),
            upside=UpsideCase(
                generation_id=generation_id,
                status="research_only",
                headline=detailed.upside_headline,
                findings=detailed.upside_findings,
                positive_return_probability=positive,
                benchmark_outperform_probability=outperform,
                confidence=detailed.upside_confidence,
            ),
            limitations=tuple(limitations),
            financial_deterioration=financial_deterioration,
            checklist_assessment=checklist_assessment,
        )
        return _with_hermes_candidates(
            report=report, candidate_adapter=candidate_adapter
        )

    citation = _citation(bundle)
    downside_fact = Finding(
        finding_id=f"downside:{citation.evidence_id}",
        kind="fact",
        direction="context",
        statement=f"MOPS官方來源已取得{citation.period}綜合損益表。",
        materiality=Decimal("0.30"),
        evidence_ids=(citation.evidence_id,),
        supporting_finding_ids=(),
        counter_finding_ids=(),
        counter_evidence_reason=None,
    )
    upside_fact = Finding(
        finding_id=f"upside:{citation.evidence_id}",
        kind="fact",
        direction="context",
        statement=f"MOPS官方來源已取得{citation.period}綜合損益表。",
        materiality=Decimal("0.30"),
        evidence_ids=(citation.evidence_id,),
        supporting_finding_ids=(),
        counter_finding_ids=(),
        counter_evidence_reason=None,
    )
    limitations = [
        "通用KAM、高風險附註、重大事件、產業前景與估值extractor尚未接入；不得由財報存在推導投資結論。",
        f"查核／核閱PDF coverage為{audit_available}/{audit_required}；年度查核PDF為{annual_available}/{annual_required}。",
    ]
    if positive.status != "formal":
        limitations.append("本generation沒有正式12個月報酬機率，Dashboard必須顯示unavailable。")
    report = build_single_company_research_report(
        request=bundle.request,
        generation_id=generation_id,
        generated_at=generated_at,
        citations=_unique_citations((citation, *financial_citations)),
        source_coverage=bundle.source_coverage,
        downside=DownsideCase(
            generation_id=generation_id,
            status="blocked",
            headline=(
                "下跌風險結論被阻擋：尚未完成通用KAM、高風險附註與重大事件抽取；"
                f"目前查核／核閱PDF coverage為{audit_available}/{audit_required}。"
            ),
            findings=(downside_fact,),
            twelve_month_drawdown_probability=_unavailable(
                "未來12個月最大跌幅事件尚未正式校準。"
            ),
            confidence=Decimal("0.10"),
        ),
        upside=UpsideCase(
            generation_id=generation_id,
            status="blocked",
            headline="上漲潛力結論被阻擋：尚未完成通用產業前景、成長驅動與估值抽取。",
            findings=(upside_fact,),
            positive_return_probability=positive,
            benchmark_outperform_probability=outperform,
            confidence=Decimal("0.10"),
        ),
        limitations=tuple(limitations),
        financial_deterioration=financial_deterioration,
        checklist_assessment=checklist_assessment,
    )
    return _with_hermes_candidates(report=report, candidate_adapter=candidate_adapter)


def _news_citation(event: RecentNegativeNewsEvent) -> EvidenceCitation:
    tier = (
        "official"
        if event.source_role in {"regulator", "court", "authority"}
        else "issuer_primary"
        if event.source_role == "issuer"
        else "trusted_secondary"
    )
    return EvidenceCitation(
        evidence_id=event.evidence_id,
        source_id=event.evidence_id,
        source_tier=tier,  # type: ignore[arg-type]
        url=event.source_url,
        content_sha256=event.content_sha256,
        period=event.event_date,
        available_at=event.available_at,
        page=None,
        coordinate=None,
        verbatim_excerpt=event.verbatim_excerpt,
        source_format="html",
        locator=event.citation_locator,
    )


def attach_recent_negative_news(
    report: SingleCompanyResearchReport,
    collection: RecentNegativeNewsCollection,
) -> SingleCompanyResearchReport:
    """Attach only verified events to downside; retain unverified items in collection JSON."""

    if any(item.family == "recent_negative_news" for item in report.source_coverage):
        raise ReportOrchestrationError("recent negative news already attached")
    verified = tuple(item for item in collection.events if item.affects_downside)
    citations = tuple(_news_citation(item) for item in verified)
    findings: list[Finding] = []
    for item in verified:
        source_finding_id = f"source-fact:{item.event_id}"
        findings.append(
            Finding(
                finding_id=source_finding_id,
                kind="fact",
                direction="context",
                statement=item.verbatim_excerpt,
                materiality=Decimal("0"),
                evidence_ids=(item.evidence_id,),
                supporting_finding_ids=(),
                counter_finding_ids=(),
                counter_evidence_reason=None,
            )
        )
        findings.append(
            RecentNegativeNewsFinding(
                finding_id=item.event_id,
                kind="judgement",
                direction="support",
                statement=(
                    f"{item.event_date} {item.category}；status={item.status}；"
                    f"affected_account={item.affected_account}；cash_flow={item.cash_flow}；"
                    f"impact={item.impact}。"
                ),
                materiality=Decimal("0"),
                evidence_ids=(item.evidence_id,),
                supporting_finding_ids=(source_finding_id,),
                counter_finding_ids=(),
                counter_evidence_reason=item.counterevidence,
                category=item.category,
                status=item.status,
                affected_account=item.affected_account,
                cash_flow=item.cash_flow,
                impact=item.impact,
                severity=item.severity,
                confidence=item.confidence,
                counterevidence=item.counterevidence,
                monitoring=item.monitoring,
                invalidation=item.invalidation,
                duplicate_cluster=item.duplicate_cluster,
                source_role=item.source_role,
            )
        )
    unverified_count = sum(not item.affects_downside for item in collection.events)
    limitation = (
        "近期負面新聞：available；社群／論壇／匿名來源"
        f"{unverified_count}件僅unverified展示且不影響downside。"
        if collection.status == "available"
        else "近期負面新聞：partial ("
        + ",".join(collection.missing_reasons)
        + ")；缺失不得視為零風險。"
    )
    coverage = SourceCoverage(
        family="recent_negative_news",
        required=1,
        available=1 if collection.status == "available" else 0,
        missing_reasons=collection.missing_reasons,
    )
    return build_single_company_research_report(
        request=report.request,
        generation_id=report.generation_id,
        generated_at=report.generated_at,
        citations=(*report.citations, *citations),
        source_coverage=(*report.source_coverage, coverage),
        downside=replace(
            report.downside,
            findings=(*report.downside.findings, *findings),
        ),
        upside=report.upside,
        valuation=report.valuation,
        limitations=(*report.limitations, limitation),
        financial_deterioration=report.financial_deterioration,
        downside_sections=report.downside_sections,
        checklist_assessment=report.checklist_assessment,
    )


def _section_placeholder(
    *, section_id: str, title: str, generation_id: str, gap: str
) -> DownsideSection:
    return DownsideSection(
        section_id=section_id,  # type: ignore[arg-type]
        title=title,
        generation_id=generation_id,
        status="partial",
        items=(
            DownsideSectionItem(
                item_id=f"{section_id}:insufficient",
                severity="unknown",
                confidence=None,
                summary="本generation資料不足，不能解讀為零風險。",
                evidence=("本區沒有足夠已准入證據。",),
                counterevidence=("資料不足，尚無法形成有效反證。",),
                monitoring=("補齊本區來源並以新generation重新分析。",),
                invalidation=("取得並准入必要來源後，由新generation取代。",),
            ),
        ),
        gaps=(gap,),
    )


def _financial_section(report: SingleCompanyResearchReport) -> DownsideSection:
    section = report.financial_deterioration
    if section is None:
        return _section_placeholder(
            section_id="financial_deterioration",
            title="財報惡化",
            generation_id=report.generation_id,
            gap="financial_trend_periods_incomplete",
        )
    return DownsideSection(
        section_id="financial_deterioration",
        title="財報惡化",
        generation_id=report.generation_id,
        status=section.status,
        items=tuple(
            DownsideSectionItem(
                item_id=item.item_id,
                severity=item.severity,
                confidence=item.confidence,
                summary=item.summary,
                evidence=item.evidence,
                counterevidence=item.counterevidence,
                monitoring=item.monitoring,
                invalidation=item.invalidation,
                evidence_ids=item.evidence_ids,
            )
            for item in section.items
        ),
        gaps=(section.partial_reason,) if section.partial_reason else (),
    )


def _anomaly_section(report: SingleCompanyResearchReport) -> DownsideSection:
    findings = tuple(
        item for item in report.downside.findings if hasattr(item, "explanation_status")
    )
    if not findings:
        return DownsideSection(
            section_id="unexplained_financial_anomalies",
            title="無法解釋財報異常",
            generation_id=report.generation_id,
            status="available",
            items=(
                DownsideSectionItem(
                    item_id="financial-anomalies:none-admitted",
                    severity="none",
                    confidence="medium",
                    summary="本generation未准入達雙重重大性門檻的財報異常；不代表未來零風險。",
                    evidence=("已套用30%相對變動與1%公司規模雙重門檻。",),
                    counterevidence=("門檻以下變動與未來新資訊仍可能改變判斷。",),
                    monitoring=("持續監控後續三表、附註、重大訊息與已准入新聞。",),
                    invalidation=("新generation出現達門檻候選時失效。",),
                ),
            ),
            gaps=(),
        )
    blocked = tuple(
        item for item in findings if getattr(item, "explanation_status") == "blocked_by_missing_evidence"
    )
    return DownsideSection(
        section_id="unexplained_financial_anomalies",
        title="無法解釋財報異常",
        generation_id=report.generation_id,
        status="partial" if blocked else "available",
        items=tuple(
            DownsideSectionItem(
                item_id=item.finding_id,
                severity=getattr(item, "severity"),
                confidence=getattr(item, "confidence"),
                summary=item.statement,
                evidence=tuple(getattr(item, "evidence")),
                counterevidence=tuple(getattr(item, "counterevidence")),
                monitoring=(str(getattr(item, "monitoring")),),
                invalidation=(str(getattr(item, "invalidation")),),
                evidence_ids=item.evidence_ids,
            )
            for item in findings
        ),
        gaps=("anomaly_explanation_sources_incomplete",) if blocked else (),
    )


def _news_section(
    report: SingleCompanyResearchReport, news: RecentNegativeNewsCollection
) -> DownsideSection:
    if news.status == "partial":
        return _section_placeholder(
            section_id="recent_negative_news",
            title="近期負面新聞",
            generation_id=report.generation_id,
            gap=news.missing_reasons[0] if news.missing_reasons else "recent_negative_news_incomplete",
        )
    items = tuple(
        DownsideSectionItem(
            item_id=item.event_id,
            severity=item.severity,
            confidence=item.confidence,
            summary=(
                f"{item.event_date} {item.category}；status={item.status}；"
                f"affected_account={item.affected_account}；cash_flow={item.cash_flow}；"
                f"impact={item.impact}。"
            ),
            evidence=(item.verbatim_excerpt,),
            counterevidence=(item.counterevidence,),
            monitoring=(item.monitoring,),
            invalidation=(item.invalidation,),
            evidence_ids=(item.evidence_id,) if item.affects_downside else (),
        )
        for item in news.events
    ) or (
        DownsideSectionItem(
            item_id="recent-negative-news:none-admitted",
            severity="none",
            confidence="medium",
            summary="本generation未准入近期負面事件；不代表未來零風險。",
            evidence=("本generation新聞探索與原文准入流程已完成。",),
            counterevidence=("搜尋窗口、來源可得性與後續事件仍有限制。",),
            monitoring=("持續監控180日一般事件與12個月未解決重大事件。",),
            invalidation=("新generation准入負面事件時失效。",),
        ),
    )
    return DownsideSection(
        section_id="recent_negative_news",
        title="近期負面新聞",
        generation_id=report.generation_id,
        status="available",
        items=items,
        gaps=(),
    )


def _kam_section(report: SingleCompanyResearchReport, kam: KamJudgement) -> DownsideSection:
    if kam.generation_id != report.generation_id:
        raise ReportOrchestrationError("KAM generation mismatch")
    if kam.status == "partial" or not all(
        (kam.change_summary, kam.risk_mechanism, kam.counterevidence, kam.monitoring, kam.invalidation)
    ):
        gap = next(
            iter((*kam.rejection_reasons, *kam.missing_year_reasons)),
            "three_year_kam_incomplete",
        )
        return _section_placeholder(
            section_id="three_year_kam",
            title="三年KAM",
            generation_id=report.generation_id,
            gap=gap,
        )
    return DownsideSection(
        section_id="three_year_kam",
        title="三年KAM",
        generation_id=report.generation_id,
        status="available",
        items=(
            DownsideSectionItem(
                item_id="three-year-kam:judgement",
                severity=kam.severity or "unknown",
                confidence=kam.confidence,
                summary=f"{kam.change_summary} 風險機制：{kam.risk_mechanism}",
                evidence=tuple(
                    year.citation.verbatim_excerpt for year in kam.years
                ) or ("已准入三年KAM判讀結果。",),
                counterevidence=(kam.counterevidence or "資料不足。",),
                monitoring=(kam.monitoring or "補齊監控條件。",),
                invalidation=(kam.invalidation or "補齊失效條件。",),
                evidence_ids=tuple(year.citation.evidence_id for year in kam.years),
            ),
        ),
        gaps=(),
    )


def publish_four_downside_sections(
    *,
    report: SingleCompanyResearchReport,
    kam: KamJudgement,
    news: RecentNegativeNewsCollection,
) -> SingleCompanyResearchReport:
    """Publish four independent, same-generation downside sections."""

    if report.status == "blocked":
        return report
    sections = (
        _financial_section(report),
        _anomaly_section(report),
        _news_section(report, news),
        _kam_section(report, kam),
    )
    citations = _unique_citations(
        (*report.citations, *(year.citation for year in kam.years))
    )
    coverage_by_family = {item.family: item for item in report.source_coverage}
    coverage_by_family["recent_negative_news"] = SourceCoverage(
        "recent_negative_news",
        1,
        1 if news.status == "available" else 0,
        news.missing_reasons,
    )
    coverage_by_family[kam.coverage.family] = kam.coverage
    coverage = tuple(coverage_by_family.values())
    status = (
        "partial"
        if any(item.status == "partial" for item in sections)
        or any(item.available < item.required for item in coverage)
        else "complete"
    )
    limitations = tuple(
        dict.fromkeys(
            (
                *report.limitations,
                *(f"{item.title}:{gap}" for item in sections for gap in item.gaps),
            )
        )
    )
    return build_single_company_research_report(
        request=report.request,
        generation_id=report.generation_id,
        generated_at=report.generated_at,
        citations=citations,
        source_coverage=coverage,
        downside=report.downside,
        upside=report.upside,
        valuation=report.valuation,
        limitations=limitations,
        financial_deterioration=report.financial_deterioration,
        downside_sections=sections,
        checklist_assessment=report.checklist_assessment,
        status=status,
    )


def run_single_company_analysis(
    *,
    identifier: str,
    requested_market: Literal["TWSE", "TPEx"] | None,
    as_of: str,
    retrieved_at: str,
    output_root: Path,
    generation_id: str,
    identity_sources: Sequence[OfficialIdentitySource] | None = None,
    calibration: SingleCompanyProbabilityCalibration | None = None,
    filing_store_root: Path | None = None,
) -> CompanyAnalysisResult:
    """Collect current evidence and bind the same generation to a report."""

    bundle = collect_company_evidence_bundle(
        identifier=identifier,
        requested_market=requested_market,
        as_of=as_of,
        retrieved_at=retrieved_at,
        output_root=output_root / "evidence",
        identity_sources=identity_sources,
        filing_store_root=filing_store_root,
    )
    decision = datetime.fromisoformat(as_of)
    generated_at = datetime.now(decision.tzinfo).isoformat(timespec="seconds")
    calibration_error: str | None = None
    if calibration is None:
        try:
            calibration = calibrate_current_generation(
                issuer_id=bundle.identity.issuer_id,
                security_code=bundle.identity.security_code,
                market=bundle.identity.market,
                as_of=as_of,
                generated_at=generated_at,
                generation_id=generation_id,
                output_root=output_root / "calibration",
            )
            if calibration is None:
                calibration_error = "目前只支援TWSE官方benchmark校準。"
        except ProbabilitySourceError as exc:
            calibration_error = str(exc)
    candidate_adapter = HermesApiCandidateAdapter.from_environment(generation_id)
    report = build_report_from_evidence(
        bundle=bundle,
        generation_id=generation_id,
        generated_at=generated_at,
        calibration=calibration,
        calibration_unavailable_reason=calibration_error,
        candidate_adapter=candidate_adapter,
    )
    kam_judgement = build_kam_judgement(
        bundle=bundle,
        generation_id=generation_id,
        candidate_adapter=candidate_adapter,
    )
    news = RecentNegativeNewsCollector(
        interpreter=HermesNewsInterpreter.from_environment(generation_id)
    ).collect(
        issuer_id=bundle.identity.issuer_id,
        security_code=bundle.identity.security_code,
        company_name=bundle.identity.company_name,
        as_of=as_of,
        retrieved_at=retrieved_at,
        store_root=output_root / "evidence",
    )
    report = attach_recent_negative_news(report, news)
    report = publish_four_downside_sections(
        report=report,
        kam=kam_judgement,
        news=news,
    )
    return CompanyAnalysisResult(
        generation_id=generation_id,
        identity=bundle.identity,
        evidence_status=report.status,
        source_coverage=report.source_coverage,
        kam_judgement=kam_judgement,
        research_report=report,
        recent_negative_news=news,
        probability_calibration=calibration,
        calibration_error=calibration_error,
        filing_store_stats=bundle.filing_store_stats,
    )


__all__ = [
    "CompanyAnalysisResult",
    "GdeltNewsTransport",
    "HermesApiCandidateAdapter",
    "KamAnnualTimeline",
    "KamJudgement",
    "HermesNewsInterpreter",
    "NewsDiscoveryCandidate",
    "NewsSourceError",
    "RecentNegativeNewsCollection",
    "RecentNegativeNewsCollector",
    "RecentNegativeNewsEvent",
    "ReportOrchestrationError",
    "attach_recent_negative_news",
    "admit_hermes_candidates",
    "build_report_from_evidence",
    "build_kam_judgement",
    "publish_four_downside_sections",
    "run_single_company_analysis",
]
