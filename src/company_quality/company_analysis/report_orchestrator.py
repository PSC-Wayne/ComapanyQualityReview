1|"""Bind a current evidence bundle to a conservative single-company report."""
2|
3|from __future__ import annotations
4|
5|import calendar
6|from dataclasses import asdict, dataclass, replace
7|from datetime import datetime, timedelta, timezone
8|from decimal import Decimal
9|from hashlib import sha256
10|from html.parser import HTMLParser
11|import json
12|import os
13|from pathlib import Path
14|import re
15|from typing import Iterable, Literal, Mapping, Protocol, Sequence
16|from urllib.parse import urlencode, urlparse
17|from urllib.request import Request, urlopen
18|
19|from company_quality.audit.inventory import AuditFilingInventory
20|from company_quality.company_analysis.contracts import (
21|    CaseProbability,
22|    DownsideCase,
23|    EvidenceCitation,
24|    Finding,
25|    SingleCompanyResearchReport,
26|    SourceCoverage,
27|    UpsideCase,
28|    build_single_company_research_report,
29|)
30|from company_quality.company_analysis.candidate_admission import (
31|    HermesApiCandidateAdapter,
32|    HermesCandidateAdapter,
33|    admit_kam_judgement,
34|    admit_hermes_candidates,
35|)
36|from company_quality.company_analysis.evidence_bundle import (
37|    CompanyEvidenceBundle,
38|    collect_company_evidence_bundle,
39|)
40|from company_quality.company_analysis.detailed_analysis import (
41|    build_detailed_analysis,
42|    build_financial_deterioration,
43|)
44|from company_quality.company_analysis.probability_calibration import (
45|    EmpiricalProbabilityCalibration,
46|    SingleCompanyProbabilityCalibration,
47|)
48|from company_quality.company_analysis.probability_provider import (
49|    ProbabilitySourceError,
50|    calibrate_current_generation,
51|)
52|from company_quality.sources.financial import FinancialArtifact
53|from company_quality.identity import CompanyIdentity, OfficialIdentitySource
54|from company_quality.filing_store import FilingStoreStats
55|
56|
57|class ReportOrchestrationError(RuntimeError):
58|    """Raised when current-generation evidence cannot safely form a report."""
59|
60|
61|class NewsSourceError(RuntimeError):
62|    """Raised when discovery or original-source materialization is unavailable."""
63|
64|
65|NewsSourceRole = Literal[
66|    "regulator",
67|    "court",
68|    "authority",
69|    "issuer",
70|    "mainstream_media",
71|    "social",
72|    "forum",
73|    "anonymous",
74|]
75|NewsCategory = Literal[
76|    "litigation_penalty",
77|    "project_performance",
78|    "safety_environment",
79|    "financial_credit",
80|    "governance_audit",
81|    "customer_supply_chain",
82|    "cybersecurity",
83|    "operational_interruption",
84|]
85|_NEWS_CATEGORIES = frozenset(
86|    {
87|        "litigation_penalty",
88|        "project_performance",
89|        "safety_environment",
90|        "financial_credit",
91|        "governance_audit",
92|        "customer_supply_chain",
93|        "cybersecurity",
94|        "operational_interruption",
95|    }
96|)
97|_EXTENDED_NEWS_CATEGORIES = frozenset(
98|    {"litigation_penalty", "project_performance", "safety_environment"}
99|)
100|_UNVERIFIED_ROLES = frozenset({"social", "forum", "anonymous"})
101|_SOURCE_PRECEDENCE = {
102|    "regulator": 0,
103|    "court": 0,
104|    "authority": 0,
105|    "issuer": 1,
106|    "mainstream_media": 2,
107|    "social": 3,
108|    "forum": 3,
109|    "anonymous": 3,
110|}
111|_MAINSTREAM_DOMAINS = (
112|    "cna.com.tw",
113|    "udn.com",
114|    "ltn.com.tw",
115|    "chinatimes.com",
116|    "ctee.com.tw",
117|    "ettoday.net",
118|    "tw.stock.yahoo.com",
119|)
120|
121|
122|@dataclass(frozen=True, slots=True)
123|class NewsDiscoveryCandidate:
124|    """Discovery metadata only; never report evidence by itself."""
125|
126|    discovery_id: str
127|    url: str
128|    publisher: str
129|    source_role: NewsSourceRole
130|    title: str
131|    publication_at: str
132|    available_at: str
133|
134|
135|@dataclass(frozen=True, slots=True)
136|class _MaterializedNewsSource:
137|    evidence_id: str
138|    discovery_id: str
139|    issuer_id: str
140|    security_code: str
141|    company_name: str
142|    url: str
143|    publisher: str
144|    source_role: NewsSourceRole
145|    title: str
146|    publication_at: str
147|    available_at: str
148|    retrieved_at: str
149|    content_sha256: str
150|    artifact_path: Path
151|    text: str
152|    citation_locator: str
153|
154|
155|@dataclass(frozen=True, slots=True)
156|class RecentNegativeNewsEvent:
157|    event_id: str
158|    evidence_id: str
159|    issuer_id: str
160|    security_code: str
161|    company_name: str
162|    category: NewsCategory
163|    status: Literal["resolved", "unresolved", "ongoing"]
164|    event_date: str
165|    publication_at: str
166|    available_at: str
167|    retrieved_at: str
168|    publisher: str
169|    source_url: str
170|    source_role: NewsSourceRole
171|    citation_locator: str
172|    content_sha256: str
173|    artifact_path: Path
174|    verbatim_excerpt: str
175|    affected_account: str
176|    cash_flow: str
177|    impact: Literal["realised", "hypothetical"]
178|    severity: Literal["low", "medium", "high"]
179|    confidence: Literal["low", "medium", "high"]
180|    counterevidence: str
181|    monitoring: str
182|    invalidation: str
183|    duplicate_cluster: str
184|    duplicate_source_ids: tuple[str, ...]
185|    verification_status: Literal["verified", "unverified"]
186|    affects_downside: bool
187|
188|
189|@dataclass(frozen=True, slots=True)
190|class RecentNegativeNewsFinding(Finding):
191|    category: NewsCategory
192|    status: Literal["resolved", "unresolved", "ongoing"]
193|    affected_account: str
194|    cash_flow: str
195|    impact: Literal["realised", "hypothetical"]
196|    severity: Literal["low", "medium", "high"]
197|    confidence: Literal["low", "medium", "high"]
198|    counterevidence: str
199|    monitoring: str
200|    invalidation: str
201|    duplicate_cluster: str
202|    source_role: NewsSourceRole
203|
204|
205|@dataclass(frozen=True, slots=True)
206|class RecentNegativeNewsCollection:
207|    events: tuple[RecentNegativeNewsEvent, ...]
208|    status: Literal["available", "partial"]
209|    missing_reasons: tuple[str, ...]
210|    cache_hits: int
211|    online_fetches: int
212|
213|
214|class NewsTransport(Protocol):
215|    def discover(
216|        self, *, query: str, start_at: str, end_at: str
217|    ) -> Sequence[NewsDiscoveryCandidate]: ...
218|
219|    def fetch(self, *, url: str) -> bytes: ...
220|
221|
222|class NewsInterpreter(Protocol):
223|    def interpret(
224|        self,
225|        *,
226|        issuer_id: str,
227|        as_of: str,
228|        sources: Sequence[Mapping[str, str]],
229|    ) -> Sequence[Mapping[str, object]]: ...
230|
231|
232|class GdeltNewsTransport:
233|    """Credential-free discovery plus direct original-URL fetches."""
234|
235|    def discover(
236|        self, *, query: str, start_at: str, end_at: str
237|    ) -> Sequence[NewsDiscoveryCandidate]:
238|        start = _news_instant(start_at).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
239|        end = _news_instant(end_at).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
240|        endpoint = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(
241|            {
242|                "query": query,
243|                "mode": "ArtList",
244|                "format": "json",
245|                "maxrecords": "250",
246|                "startdatetime": start,
247|                "enddatetime": end,
248|            }
249|        )
250|        request = Request(endpoint, headers={"User-Agent": "CompanyQualityResearch/0.1"})
251|        try:
252|            with urlopen(request, timeout=30) as response:
253|                payload = json.loads(response.read())
254|        except Exception as exc:
255|            raise NewsSourceError("GDELT discovery unavailable") from exc
256|        articles = payload.get("articles") if isinstance(payload, dict) else None
257|        if not isinstance(articles, list):
258|            raise NewsSourceError("GDELT discovery returned invalid JSON")
259|        result: list[NewsDiscoveryCandidate] = []
260|        for index, item in enumerate(articles):
261|            if not isinstance(item, dict) or not str(item.get("url", "")).startswith("https://"):
262|                continue
263|            seen = str(item.get("seendate", ""))
264|            try:
265|                published = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(
266|                    tzinfo=timezone.utc
267|                ).isoformat()
268|            except ValueError:
269|                continue
270|            domain = str(item.get("domain") or urlparse(str(item["url"])).netloc)
271|            role: NewsSourceRole = _domain_role(domain)
272|            result.append(
273|                NewsDiscoveryCandidate(
274|                    discovery_id=f"gdelt:{index}:{sha256(str(item['url']).encode()).hexdigest()[:16]}",
275|                    url=str(item["url"]),
276|                    publisher=domain,
277|                    source_role=role,
278|                    title=str(item.get("title") or domain),
279|                    publication_at=published,
280|                    available_at=published,
281|                )
282|            )
283|        return result
284|
285|    def fetch(self, *, url: str) -> bytes:
286|        request = Request(url, headers={"User-Agent": "CompanyQualityResearch/0.1"})
287|        try:
288|            with urlopen(request, timeout=30) as response:
289|                return response.read()
290|        except Exception as exc:
291|            raise NewsSourceError("original news source unavailable") from exc
292|
293|
294|class HermesNewsInterpreter:
295|    """Hermes may interpret only supplied, already materialized original text."""
296|
297|    def __init__(self, *, base_url: str, api_key: str, session_id: str) -> None:
298|        self.base_url = base_url.rstrip("/")
299|        self.api_key = api_key
300|        self.session_id = session_id
301|
302|    @classmethod
303|    def from_environment(cls, generation_id: str) -> HermesNewsInterpreter | None:
304|        api_key = (
305|            os.environ.get("HERMES_API_KEY")
306|            or os.environ.get("API_SERVER_KEY")
307|            or ""
308|        ).strip()
309|        if not api_key:
310|            return None
311|        return cls(
312|            base_url=os.environ.get(
313|                "HERMES_API_BASE_URL", "http://127.0.0.1:8642/v1"
314|            ),
315|            api_key=api_key,
316|            session_id=f"company-quality-news-{generation_id}",
317|        )
318|
319|    def interpret(
320|        self,
321|        *,
322|        issuer_id: str,
323|        as_of: str,
324|        sources: Sequence[Mapping[str, str]],
325|    ) -> Sequence[Mapping[str, object]]:
326|        fields = (
327|            "candidate_id, issuer_id, evidence_id, verbatim_quote, event_date, category, "
328|            "status, affected_account, cash_flow, impact, severity, confidence, "
329|            "counterevidence, monitoring, invalidation, duplicate_cluster"
330|        )
331|        prompt = (
332|            "Interpret negative-event candidates only from supplied original source text. "
333|            "Return one JSON object with candidates array and no markdown. Each candidate "
334|            f"must contain string fields: {fields}. Copy verbatim_quote exactly. Categories "
335|            f"must be one of {sorted(_NEWS_CATEGORIES)}. Do not invent missing facts."
336|        )
337|        endpoint = (
338|            f"{self.base_url}/chat/completions"
339|            if self.base_url.endswith("/v1")
340|            else f"{self.base_url}/v1/chat/completions"
341|        )
342|        payload = {
343|            "model": "hermes-agent",
344|            "messages": [
345|                {"role": "system", "content": prompt},
346|                {
347|                    "role": "user",
348|                    "content": json.dumps(
349|                        {"issuer_id": issuer_id, "as_of": as_of, "sources": sources},
350|                        ensure_ascii=False,
351|                    ),
352|                },
353|            ],
354|            "stream": False,
355|            "tools": [],
356|        }
357|        request = Request(
358|            endpoint,
359|            data=json.dumps(payload, ensure_ascii=False).encode(),
360|            headers={
361|                "Authorization": f"Bearer {self.api_key}",
362|                "Content-Type": "application/json",
363|                "X-Hermes-Session-Id": self.session_id,
364|            },
365|            method="POST",
366|        )
367|        with urlopen(request, timeout=30) as response:
368|            decoded = json.loads(response.read())
369|        content = json.loads(decoded["choices"][0]["message"]["content"])
370|        candidates = content.get("candidates")
371|        if not isinstance(candidates, list) or not all(
372|            isinstance(item, dict) for item in candidates
373|        ):
374|            raise ValueError("Hermes news response must contain candidates array")
375|        return candidates
376|
377|
378|def _news_instant(value: str) -> datetime:
379|    try:
380|        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
381|    except (AttributeError, ValueError) as exc:
382|        raise NewsSourceError("invalid news timestamp") from exc
383|    if result.tzinfo is None or result.utcoffset() is None:
384|        raise NewsSourceError("news timestamp must be timezone-aware")
385|    return result
386|
387|
388|def _months_before(value: datetime, months: int) -> datetime:
389|    year = value.year
390|    month = value.month - months
391|    while month <= 0:
392|        year -= 1
393|        month += 12
394|    day = min(value.day, calendar.monthrange(year, month)[1])
395|    return value.replace(year=year, month=month, day=day)
396|
397|
398|def _domain_role(domain: str) -> NewsSourceRole:
399|    host = domain.casefold()
400|    if "judicial.gov.tw" in host:
401|        return "court"
402|    if any(
403|        marker in host
404|        for marker in ("gov.tw", "twse.com.tw", "tpex.org.tw", "mops.twse.com.tw")
405|    ):
406|        return "authority"
407|    if any(host == domain or host.endswith(f".{domain}") for domain in _MAINSTREAM_DOMAINS):
408|        return "mainstream_media"
409|    return "anonymous"
410|
411|
412|def _atomic_json(path: Path, payload: object) -> None:
413|    path.parent.mkdir(parents=True, exist_ok=True)
414|    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
415|    temporary.write_text(
416|        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
417|        encoding="utf-8",
418|    )
419|    os.replace(temporary, path)
420|
421|
422|def _atomic_bytes(path: Path, body: bytes) -> None:
423|    path.parent.mkdir(parents=True, exist_ok=True)
424|    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
425|    temporary.write_bytes(body)
426|    os.replace(temporary, path)
427|
428|
429|def _discovery_cache_path(root: Path, issuer_id: str, as_of: str) -> Path:
430|    key = sha256(f"{issuer_id}|{as_of}".encode()).hexdigest()
431|    return root / "discovery" / f"{key}.json"
432|
433|
434|def _load_discovery(path: Path) -> tuple[NewsDiscoveryCandidate, ...]:
435|    payload = json.loads(path.read_text(encoding="utf-8"))
436|    if not isinstance(payload, list):
437|        raise NewsSourceError("invalid cached news discovery")
438|    try:
439|        return tuple(NewsDiscoveryCandidate(**item) for item in payload)
440|    except (TypeError, ValueError) as exc:
441|        raise NewsSourceError("invalid cached news discovery") from exc
442|
443|
444|def _visible_news_text(body: bytes) -> str:
445|    parser = _VisibleText()
446|    parser.feed(body.decode("utf-8", "replace"))
447|    return " ".join(parser.parts)
448|
449|
450|def _materialize_news_source(
451|    *,
452|    candidate: NewsDiscoveryCandidate,
453|    issuer_id: str,
454|    security_code: str,
455|    company_name: str,
456|    retrieved_at: str,
457|    root: Path,
458|    transport: NewsTransport,
459|) -> tuple[_MaterializedNewsSource, bool]:
460|    key = sha256(candidate.url.encode()).hexdigest()
461|    body_path = root / "artifacts" / f"{key}.html"
462|    metadata_path = root / "artifacts" / f"{key}.json"
463|    cached = False
464|    if body_path.is_file() and metadata_path.is_file():
465|        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
466|        body = body_path.read_bytes()
467|        if metadata.get("content_sha256") != sha256(body).hexdigest():
468|            raise NewsSourceError("cached news artifact hash mismatch")
469|        cached = True
470|    else:
471|        body = transport.fetch(url=candidate.url)
472|        if not body:
473|            raise NewsSourceError("original news source returned empty body")
474|        digest = sha256(body).hexdigest()
475|        _atomic_bytes(body_path, body)
476|        metadata = {
477|            **asdict(candidate),
478|            "issuer_id": issuer_id,
479|            "security_code": security_code,
480|            "company_name": company_name,
481|            "retrieved_at": retrieved_at,
482|            "content_sha256": digest,
483|            "citation_locator": "document-text:verbatim-quote",
484|        }
485|        _atomic_json(metadata_path, metadata)
486|    text = _visible_news_text(body)
487|    if not text:
488|        raise NewsSourceError("original news source has no readable text")
489|    if not any(value and value in text for value in (company_name, security_code, issuer_id)):
490|        raise NewsSourceError("news source issuer identity mismatch")
491|    digest = sha256(body).hexdigest()
492|    evidence_id = f"news-source:{candidate.discovery_id}"
493|    return (
494|        _MaterializedNewsSource(
495|            evidence_id=evidence_id,
496|            discovery_id=candidate.discovery_id,
497|            issuer_id=issuer_id,
498|            security_code=security_code,
499|            company_name=company_name,
500|            url=candidate.url,
501|            publisher=candidate.publisher,
502|            source_role=candidate.source_role,
503|            title=candidate.title,
504|            publication_at=candidate.publication_at,
505|            available_at=candidate.available_at,
506|            retrieved_at=str(metadata["retrieved_at"]),
507|            content_sha256=digest,
508|            artifact_path=body_path,
509|            text=text,
510|            citation_locator=str(metadata["citation_locator"]),
511|        ),
512|        cached,
513|    )
514|
515|
516|def _admit_news_candidate(
517|    candidate: Mapping[str, object],
518|    *,
519|    source: _MaterializedNewsSource,
520|    issuer_id: str,
521|) -> RecentNegativeNewsEvent | None:
522|    required = (
523|        "candidate_id",
524|        "issuer_id",
525|        "evidence_id",
526|        "verbatim_quote",
527|        "event_date",
528|        "category",
529|        "status",
530|        "affected_account",
531|        "cash_flow",
532|        "impact",
533|        "severity",
534|        "confidence",
535|        "counterevidence",
536|        "monitoring",
537|        "invalidation",
538|        "duplicate_cluster",
539|    )
540|    if any(
541|        not isinstance(candidate.get(field), str) or not str(candidate[field]).strip()
542|        for field in required
543|    ):
544|        return None
545|    quote = str(candidate["verbatim_quote"]).strip()
546|    event_date = str(candidate["event_date"]).strip()
547|    category = str(candidate["category"])
548|    status = str(candidate["status"])
549|    impact = str(candidate["impact"])
550|    severity = str(candidate["severity"])
551|    confidence = str(candidate["confidence"])
552|    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date) is None:
553|        return None
554|    try:
555|        datetime.fromisoformat(event_date)
556|    except ValueError:
557|        return None
558|    if (
559|        candidate["issuer_id"] != issuer_id
560|        or candidate["evidence_id"] != source.evidence_id
561|        or quote not in source.text
562|        or event_date not in quote
563|        or category not in _NEWS_CATEGORIES
564|        or status not in {"resolved", "unresolved", "ongoing"}
565|        or impact not in {"realised", "hypothetical"}
566|        or severity not in {"low", "medium", "high"}
567|        or confidence not in {"low", "medium", "high"}
568|    ):
569|        return None
570|    unverified = source.source_role in _UNVERIFIED_ROLES
571|    return RecentNegativeNewsEvent(
572|        event_id=str(candidate["candidate_id"]).strip(),
573|        evidence_id=source.evidence_id,
574|        issuer_id=issuer_id,
575|        security_code=source.security_code,
576|        company_name=source.company_name,
577|        category=category,  # type: ignore[arg-type]
578|        status=status,  # type: ignore[arg-type]
579|        event_date=event_date,
580|        publication_at=source.publication_at,
581|        available_at=source.available_at,
582|        retrieved_at=source.retrieved_at,
583|        publisher=source.publisher,
584|        source_url=source.url,
585|        source_role=source.source_role,
586|        citation_locator=source.citation_locator,
587|        content_sha256=source.content_sha256,
588|        artifact_path=source.artifact_path,
589|        verbatim_excerpt=quote,
590|        affected_account=str(candidate["affected_account"]).strip(),
591|        cash_flow=str(candidate["cash_flow"]).strip(),
592|        impact=impact,  # type: ignore[arg-type]
593|        severity=severity,  # type: ignore[arg-type]
594|        confidence=confidence,  # type: ignore[arg-type]
595|        counterevidence=str(candidate["counterevidence"]).strip(),
596|        monitoring=str(candidate["monitoring"]).strip(),
597|        invalidation=str(candidate["invalidation"]).strip(),
598|        duplicate_cluster=str(candidate["duplicate_cluster"]).strip(),
599|        duplicate_source_ids=(source.evidence_id,),
600|        verification_status="unverified" if unverified else "verified",
601|        affects_downside=not unverified,
602|    )
603|
604|
605|class RecentNegativeNewsCollector:
606|    def __init__(
607|        self,
608|        transport: NewsTransport | None = None,
609|        interpreter: NewsInterpreter | None = None,
610|    ) -> None:
611|        self.transport = transport or GdeltNewsTransport()
612|        self.interpreter = interpreter
613|
614|    def collect(
615|        self,
616|        *,
617|        issuer_id: str,
618|        security_code: str,
619|        company_name: str,
620|        as_of: str,
621|        retrieved_at: str,
622|        store_root: Path,
623|    ) -> RecentNegativeNewsCollection:
624|        decision = _news_instant(as_of)
625|        _news_instant(retrieved_at)
626|        twelve_month_start = _months_before(decision, 12)
627|        general_start = decision - timedelta(days=180)
628|        root = store_root / "news" / issuer_id
629|        discovery_path = _discovery_cache_path(root, issuer_id, as_of)
630|        cache_hits = 0
631|        online_fetches = 0
632|        missing: list[str] = []
633|        if discovery_path.is_file():
634|            discoveries = _load_discovery(discovery_path)
635|            cache_hits += 1
636|        else:
637|            try:
638|                discoveries = tuple(
639|                    self.transport.discover(
640|                        query=f'"{company_name}" OR "{security_code}"',
641|                        start_at=twelve_month_start.isoformat(),
642|                        end_at=decision.isoformat(),
643|                    )
644|                )
645|            except Exception:
646|                return RecentNegativeNewsCollection(
647|                    events=(),
648|                    status="partial",
649|                    missing_reasons=("news_discovery_unavailable",),
650|                    cache_hits=0,
651|                    online_fetches=0,
652|                )
653|            _atomic_json(discovery_path, [asdict(item) for item in discoveries])
654|            online_fetches += 1
655|
656|        sources: list[_MaterializedNewsSource] = []
657|        for item in discoveries:
658|            try:
659|                if item.source_role not in _SOURCE_PRECEDENCE:
660|                    raise NewsSourceError("invalid news source role")
661|                published = _news_instant(item.publication_at)
662|                available = _news_instant(item.available_at)
663|                if published > decision or available > decision:
664|                    continue
665|                source, cached = _materialize_news_source(
666|                    candidate=item,
667|                    issuer_id=issuer_id,
668|                    security_code=security_code,
669|                    company_name=company_name,
670|                    retrieved_at=retrieved_at,
671|                    root=root,
672|                    transport=self.transport,
673|                )
674|                sources.append(source)
675|                if cached:
676|                    cache_hits += 1
677|                else:
678|                    online_fetches += 1
679|            except Exception:
680|                missing.append(f"news_original_unavailable:{item.discovery_id}")
681|
682|        if self.interpreter is None:
683|            return RecentNegativeNewsCollection(
684|                events=(),
685|                status="partial",
686|                missing_reasons=tuple((*missing, "hermes_news_not_configured")),
687|                cache_hits=cache_hits,
688|                online_fetches=online_fetches,
689|            )
690|        supplied = tuple(
691|            {
692|                "evidence_id": item.evidence_id,
693|                "publisher": item.publisher,
694|                "source_role": item.source_role,
695|                "publication_at": item.publication_at,
696|                "available_at": item.available_at,
697|                "source_url": item.url,
698|                "original_text": item.text[:12000],
699|            }
700|            for item in sources
701|        )
702|        try:
703|            candidates = self.interpreter.interpret(
704|                issuer_id=issuer_id, as_of=as_of, sources=supplied
705|            )
706|        except Exception:
707|            return RecentNegativeNewsCollection(
708|                events=(),
709|                status="partial",
710|                missing_reasons=tuple((*missing, "hermes_news_unavailable")),
711|                cache_hits=cache_hits,
712|                online_fetches=online_fetches,
713|            )
714|        by_evidence = {item.evidence_id: item for item in sources}
715|        admitted: list[RecentNegativeNewsEvent] = []
716|        for candidate in candidates:
717|            source = by_evidence.get(str(candidate.get("evidence_id", "")))
718|            event = (
719|                _admit_news_candidate(candidate, source=source, issuer_id=issuer_id)
720|                if source is not None
721|                else None
722|            )
723|            if event is None:
724|                missing.append("news_candidate_rejected")
725|                continue
726|            publication = _news_instant(event.publication_at)
727|            in_general_window = publication >= general_start
728|            in_extended_window = (
729|                publication >= twelve_month_start
730|                and event.category in _EXTENDED_NEWS_CATEGORIES
731|                and event.status in {"unresolved", "ongoing"}
732|            )
733|            if in_general_window or in_extended_window:
734|                admitted.append(event)
735|
736|        clusters: dict[str, list[RecentNegativeNewsEvent]] = {}
737|        for event in admitted:
738|            clusters.setdefault(event.duplicate_cluster, []).append(event)
739|        promoted: list[RecentNegativeNewsEvent] = []
740|        for cluster in clusters.values():
741|            primary = min(cluster, key=lambda item: _SOURCE_PRECEDENCE[item.source_role])
742|            promoted.append(
743|                replace(
744|                    primary,
745|                    duplicate_source_ids=tuple(item.evidence_id for item in cluster),
746|                )
747|            )
748|        promoted.sort(key=lambda item: item.publication_at, reverse=True)
749|        return RecentNegativeNewsCollection(
750|            events=tuple(promoted),
751|            status="partial" if missing else "available",
752|            missing_reasons=tuple(dict.fromkeys(missing)),
753|            cache_hits=cache_hits,
754|            online_fetches=online_fetches,
755|        )
756|
757|
758|@dataclass(frozen=True, slots=True)
759|class KamAnnualTimeline:
760|    period: str
761|    citation: EvidenceCitation
762|    kam_present: bool
763|    opinion_type: str | None
764|    modified_opinion: bool | None
765|    going_concern: bool
766|    emphasis_matter: bool
767|    auditor_change: bool | None
768|
769|
770|@dataclass(frozen=True, slots=True)
771|class KamJudgement:
772|    generation_id: str
773|    status: Literal["available", "partial"]
774|    coverage: SourceCoverage
775|    years: tuple[KamAnnualTimeline, ...]
776|    missing_year_reasons: tuple[str, ...]
777|    change_summary: str | None
778|    risk_mechanism: str | None
779|    counterevidence: str | None
780|    severity: Literal["none", "low", "medium", "high", "critical"] | None
781|    confidence: Decimal | None
782|    monitoring: str | None
783|    invalidation: str | None
784|    rejection_reasons: tuple[str, ...]
785|    schema_version: Literal["KamJudgement.v1"] = "KamJudgement.v1"
786|
787|
788|@dataclass(frozen=True, slots=True)
789|class CompanyAnalysisResult:
790|    generation_id: str
791|    identity: CompanyIdentity
792|    evidence_status: Literal["available", "partial", "blocked"]
793|    source_coverage: tuple[SourceCoverage, ...]
794|    kam_judgement: KamJudgement
795|    research_report: SingleCompanyResearchReport
796|    recent_negative_news: RecentNegativeNewsCollection
797|    probability_calibration: SingleCompanyProbabilityCalibration | None
798|    calibration_error: str | None
799|    filing_store_stats: FilingStoreStats | None = None
800|    status: Literal["research_only"] = "research_only"
801|    schema_version: Literal["DashboardCompanyAnalysisResult.v1"] = (
802|        "DashboardCompanyAnalysisResult.v1"
803|    )
804|
805|
806|class _VisibleText(HTMLParser):
807|    def __init__(self) -> None:
808|        super().__init__()
809|        self.parts: list[str] = []
810|
811|    def handle_data(self, data: str) -> None:
812|        text = " ".join(data.replace("\xa0", " ").split())
813|        if text:
814|            self.parts.append(text)
815|
816|
817|def _income_artifacts(bundle: CompanyEvidenceBundle) -> Iterable[FinancialArtifact]:
818|    for period in reversed(bundle.periods):
819|        if period.financial is None:
820|            continue
821|        for artifact in period.financial.artifacts:
822|            if artifact.report == "income":
823|                yield artifact
824|
825|
826|def _citation(bundle: CompanyEvidenceBundle) -> EvidenceCitation:
827|    artifact = next(iter(_income_artifacts(bundle)), None)
828|    if artifact is None:
829|        raise ReportOrchestrationError("no citable official income statement")
830|    body = artifact.path.read_bytes()
831|    if sha256(body).hexdigest() != artifact.content_sha256:
832|        raise ReportOrchestrationError("financial artifact content hash mismatch")
833|    parser = _VisibleText()
834|    parser.feed(body.decode("utf-8", "replace"))
835|    text = " ".join(parser.parts)
836|    marker = "綜合損益表"
837|    index = text.find(marker)
838|    if index < 0:
839|        raise ReportOrchestrationError("income statement title not found in official artifact")
840|    start = max(0, index - 120)
841|    excerpt = text[start : index + len(marker) + 180].strip()
842|    if not excerpt:
843|        raise ReportOrchestrationError("official income statement has no citable text")
844|    return EvidenceCitation(
845|        evidence_id=artifact.artifact_id,
846|        source_id=artifact.artifact_id,
847|        source_tier="official",
848|        url=artifact.official_url,
849|        content_sha256=artifact.content_sha256,
850|        period=artifact.period,
851|        available_at=artifact.available_at,
852|        page=None,
853|        coordinate=None,
854|        verbatim_excerpt=excerpt,
855|        source_format="html",
856|        locator="document-text:contains(綜合損益表)",
857|    )
858|
859|
860|def _unavailable(reason: str) -> CaseProbability:
861|    return CaseProbability(
862|        status="unavailable",
863|        lower=None,
864|        point=None,
865|        upper=None,
866|        confidence=None,
867|        calibration_id=None,
868|        reason=reason,
869|    )
870|
871|
872|def _formal(metric: EmpiricalProbabilityCalibration) -> CaseProbability:
873|    if any(
874|        value is None
875|        for value in (
876|            metric.lower,
877|            metric.point,
878|            metric.upper,
879|            metric.confidence_level,
880|            metric.calibration_id,
881|        )
882|    ):
883|        raise ReportOrchestrationError("formal calibration has incomplete values")
884|    return CaseProbability(
885|        status="formal",
886|        lower=metric.lower,
887|        point=metric.point,
888|        upper=metric.upper,
889|        confidence=metric.confidence_level,
890|        calibration_id=metric.calibration_id,
891|        reason="歷史季節匹配、互不重疊12個月標籤的Wilson 90%區間；不是當前證據條件機率。",
892|    )
893|
894|
895|def _probabilities(
896|    bundle: CompanyEvidenceBundle,
897|    generation_id: str,
898|    calibration: SingleCompanyProbabilityCalibration | None,
899|    unavailable_reason: str | None,
900|) -> tuple[CaseProbability, CaseProbability]:
901|    if calibration is None:
902|        reason = unavailable_reason or "本generation尚未取得可重現的公司總報酬與官方benchmark校準輸入。"
903|        return _unavailable(reason), _unavailable(reason)
904|    if calibration.generation_id != generation_id:
905|        raise ReportOrchestrationError("calibration generation mismatch")
906|    if (
907|        calibration.issuer_id != bundle.identity.issuer_id
908|        or calibration.security_code != bundle.identity.security_code
909|        or calibration.market != bundle.identity.market
910|    ):
911|        raise ReportOrchestrationError("calibration identity mismatch")
912|    if calibration.status != "formal":
913|        reason = calibration.failure_reasons.get(
914|            "minimum_observations", "formal probability calibration unavailable"
915|        )
916|        return _unavailable(reason), _unavailable(reason)
917|    return _formal(calibration.positive_return), _formal(calibration.official_outperformance)
918|
919|
920|def _coverage(bundle: CompanyEvidenceBundle, family: str) -> tuple[int, int]:
921|    item = next((row for row in bundle.source_coverage if row.family == family), None)
922|    return (item.available, item.required) if item is not None else (0, 0)
923|
924|
925|def _pdf_pages(path: Path) -> tuple[str, ...]:
926|    from pypdf import PdfReader
927|
928|    return tuple((page.extract_text() or "") for page in PdfReader(path).pages)
929|
930|
931|def _kam_excerpt(pages: Sequence[str]) -> tuple[int, str] | None:
932|    marker = "關鍵查核事項"
933|    for page_number, raw in enumerate(pages, start=1):
934|        text = " ".join(raw.replace("\xa0", " ").split())
935|        index = text.find(marker)
936|        if index < 0:
937|            continue
938|        excerpt = text[index : index + 3900].strip()
939|        if len(excerpt) > len(marker) + 8:
940|            return page_number, excerpt
941|    return None
942|
943|
944|def build_kam_judgement(
945|    *,
946|    bundle: CompanyEvidenceBundle,
947|    generation_id: str,
948|    candidate_adapter: HermesCandidateAdapter | None,
949|) -> KamJudgement:
950|    """Build the latest-three available annual KAM timeline and admit Hermes judgement."""
951|
952|    decision = datetime.fromisoformat(bundle.request.as_of.replace("Z", "+00:00"))
953|    rows: list[tuple[AuditFilingInventory, EvidenceCitation, tuple[str, ...]]] = []
954|    missing: list[str] = []
955|    annuals = sorted(
956|        (item for item in bundle.periods if item.is_annual),
957|        key=lambda item: item.period,
958|        reverse=True,
959|    )
960|    for period in annuals:
961|        audit = period.audit
962|        if audit is None:
963|            missing.append(f"{period.period}:annual_audit_pdf:missing")
964|            continue
965|        if audit.issuer_id != bundle.request.issuer_id:
966|            missing.append(f"{period.period}:kam:wrong_issuer")
967|            continue
968|        available = datetime.fromisoformat(audit.available_at.replace("Z", "+00:00"))
969|        if available > decision:
970|            missing.append(f"{period.period}:kam:after_as_of")
971|            continue
972|        if (
973|            audit.pdf_path is None
974|            or audit.pdf_sha256 is None
975|            or audit.pdf_source_url is None
976|            or not audit.pdf_path.is_file()
977|        ):
978|            missing.append(f"{period.period}:kam:pdf_missing")
979|            continue
980|        body = audit.pdf_path.read_bytes()
981|        if sha256(body).hexdigest() != audit.pdf_sha256:
982|            missing.append(f"{period.period}:kam:content_hash_mismatch")
983|            continue
984|        try:
985|            pages = _pdf_pages(audit.pdf_path)
986|        except Exception:
987|            missing.append(f"{period.period}:kam:pdf_parse_failed")
988|            continue
989|        located = _kam_excerpt(pages)
990|        if located is None:
991|            missing.append(f"{period.period}:kam:original_text_missing")
992|            continue
993|        page, excerpt = located
994|        citation = EvidenceCitation(
995|            evidence_id=f"kam:{audit.period}:{audit.pdf_sha256}",
996|            source_id=f"annual-audit:{audit.period}",
997|            source_tier="official",
998|            url=audit.pdf_source_url,
999|            content_sha256=audit.pdf_sha256,
1000|            period=audit.period,
1001|            available_at=audit.available_at,
1002|            page=page,
1003|            coordinate=(Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1")),
1004|            verbatim_excerpt=excerpt,
1005|        )
1006|        rows.append((audit, citation, pages))
1007|        if len(rows) == 3:
1008|            break
1009|
1010|    if len(rows) < 3:
1011|        annual_coverage = next(
1012|            (item for item in bundle.source_coverage if item.family == "annual_audit_pdf"),
1013|            None,
1014|        )
1015|        if annual_coverage is not None:
1016|            missing.extend(annual_coverage.missing_reasons)
1017|        if not missing:
1018|            missing.append(f"kam_annual_comparison:only_{len(rows)}_available")
1019|    missing_reasons = tuple(dict.fromkeys(missing))
1020|    years: list[KamAnnualTimeline] = []
1021|    for index, (audit, citation, pages) in enumerate(rows):
1022|        older = rows[index + 1][0] if index + 1 < len(rows) else None
1023|        current_auditor = (audit.auditor_firm, audit.auditors)
1024|        older_auditor = (
1025|            (older.auditor_firm, older.auditors)
1026|            if older is not None
1027|            else None
1028|        )
1029|        full_text = " ".join(pages)
1030|        opinion = audit.opinion_type
1031|        years.append(
1032|            KamAnnualTimeline(
1033|                period=citation.period,
1034|                citation=citation,
1035|                kam_present=True,
1036|                opinion_type=opinion,
1037|                modified_opinion=None if opinion is None else opinion != "unmodified",
1038|                going_concern="繼續經營有關之重大不確定性" in full_text,
1039|                emphasis_matter="強調事項" in full_text,
1040|                auditor_change=(
1041|                    current_auditor != older_auditor if older_auditor is not None else None
1042|                ),
1043|            )
1044|        )
1045|
1046|    admitted = None
1047|    rejection_reasons: tuple[str, ...]
1048|    citations = tuple(item.citation for item in years)
1049|    if not citations:
1050|        rejection_reasons = ("kam_timeline_unavailable",)
1051|    elif candidate_adapter is None:
1052|        rejection_reasons = ("hermes_not_configured",)
1053|    else:
1054|        try:
1055|            candidate = candidate_adapter.judge_kam(
1056|                issuer_id=bundle.request.issuer_id,
1057|                as_of=bundle.request.as_of,
1058|                generation_id=generation_id,
1059|                citations=citations,
1060|            )
1061|            admitted, rejection_reasons = admit_kam_judgement(
1062|                candidate=candidate,
1063|                issuer_id=bundle.request.issuer_id,
1064|                citations=citations,
1065|            )
1066|        except Exception:
1067|            rejection_reasons = ("hermes_unavailable",)
1068|    complete = len(years) == 3 and admitted is not None
1069|    return KamJudgement(
1070|        generation_id=generation_id,
1071|        status="available" if complete else "partial",
1072|        coverage=SourceCoverage(
1073|            family="kam_annual_comparison",
1074|            required=3,
1075|            available=len(years),
1076|            missing_reasons=missing_reasons,
1077|        ),
1078|        years=tuple(years),
1079|        missing_year_reasons=missing_reasons,
1080|        change_summary=admitted.change_summary if admitted else None,
1081|        risk_mechanism=admitted.risk_mechanism if admitted else None,
1082|        counterevidence=admitted.counterevidence if admitted else None,
1083|        severity=admitted.severity if admitted else None,
1084|        confidence=admitted.confidence if admitted else None,
1085|        monitoring=admitted.monitoring if admitted else None,
1086|        invalidation=admitted.invalidation if admitted else None,
1087|        rejection_reasons=rejection_reasons,
1088|    )
1089|
1090|
1091|def _unique_citations(
1092|    citations: Iterable[EvidenceCitation],
1093|) -> tuple[EvidenceCitation, ...]:
1094|    return tuple({item.evidence_id: item for item in citations}.values())
1095|
1096|
1097|def _with_hermes_candidates(
1098|    *,
1099|    report: SingleCompanyResearchReport,
1100|    candidate_adapter: HermesCandidateAdapter | None,
1101|) -> SingleCompanyResearchReport:
1102|    if candidate_adapter is None:
1103|        return replace(
1104|            report,
1105|            limitations=(
1106|                *report.limitations,
1107|                "Hermes候選抽取：partial (hermes_not_configured)。",
1108|            ),
1109|        )
1110|    try:
1111|        locked_values = (
1112|            tuple(
1113|                {
1114|                    "period": period.period,
1115|                    "basis": period.basis,
1116|                    "metrics": tuple(
1117|                        {
1118|                            "metric_id": metric.metric_id,
1119|                            "absolute_value": str(metric.absolute_value),
1120|                            "ratio": str(metric.ratio) if metric.ratio is not None else None,
1121|                            "yoy_change": (
1122|                                str(metric.yoy_change)
1123|                                if metric.yoy_change is not None
1124|                                else None
1125|                            ),
1126|                            "ratio_yoy_change": (
1127|                                str(metric.ratio_yoy_change)
1128|                                if metric.ratio_yoy_change is not None
1129|                                else None
1130|                            ),
1131|                            "sequential_change": (
1132|                                str(metric.sequential_change)
1133|                                if metric.sequential_change is not None
1134|                                else None
1135|                            ),
1136|                            "ratio_sequential_change": (
1137|                                str(metric.ratio_sequential_change)
1138|                                if metric.ratio_sequential_change is not None
1139|                                else None
1140|                            ),
1141|                            "direction": metric.direction,
1142|                            "evidence_ids": metric.evidence_ids,
1143|                        }
1144|                        for metric in period.metrics
1145|                    ),
1146|                }
1147|                for period in report.financial_deterioration.periods
1148|            )
1149|            if report.financial_deterioration is not None
1150|            else ()
1151|        )
1152|        candidates = candidate_adapter.extract_candidates(
1153|            issuer_id=report.request.issuer_id,
1154|            as_of=report.request.as_of,
1155|            generation_id=report.generation_id,
1156|            citations=report.citations,
1157|            locked_values=locked_values,
1158|        )
1159|        admission = admit_hermes_candidates(
1160|            candidates=candidates,
1161|            issuer_id=report.request.issuer_id,
1162|            as_of=report.request.as_of,
1163|            citations=report.citations,
1164|        )
1165|    except Exception:
1166|        financial_deterioration = (
1167|            replace(
1168|                report.financial_deterioration,
1169|                status="partial",
1170|                partial_reason="hermes_unavailable",
1171|            )
1172|            if report.financial_deterioration is not None
1173|            else None
1174|        )
1175|        return replace(
1176|            report,
1177|            limitations=(
1178|                *report.limitations,
1179|                "Hermes候選抽取：partial (hermes_unavailable)。",
1180|            ),
1181|            financial_deterioration=financial_deterioration,
1182|        )
1183|    findings = tuple(
1184|        Finding(
1185|            finding_id=item.candidate_id,
1186|            kind="fact",
1187|            direction="context",
1188|            statement=item.statement,
1189|            materiality=Decimal("0"),
1190|            evidence_ids=(item.evidence_id,),
1191|            supporting_finding_ids=(),
1192|            counter_finding_ids=(),
1193|            counter_evidence_reason=None,
1194|        )
1195|        for item in admission.admitted
1196|        if item.candidate_id != "hermes:financial-deterioration:synthesis"
1197|    )
1198|    rejected = ",".join(item.reason for item in admission.rejected)
1199|    status = "available" if not admission.rejected else "partial"
1200|    detail = f"；typed_rejections={rejected}" if rejected else ""
1201|    financial_deterioration = report.financial_deterioration
1202|    financial_evidence_ids = (
1203|        {
1204|            evidence_id
1205|            for period in financial_deterioration.periods
1206|            for metric in period.metrics
1207|            for evidence_id in metric.evidence_ids
1208|        }
1209|        if financial_deterioration is not None
1210|        else set()
1211|    )
1212|    syntheses = tuple(
1213|        item
1214|        for item in admission.admitted
1215|        if item.candidate_id == "hermes:financial-deterioration:synthesis"
1216|        and item.evidence_id in financial_evidence_ids
1217|        and not any(character.isdigit() for character in item.statement)
1218|    )
1219|    if financial_deterioration is not None:
1220|        if syntheses:
1221|            first_item = replace(
1222|                financial_deterioration.items[0], summary=syntheses[0].statement
1223|            )
1224|            financial_deterioration = replace(
1225|                financial_deterioration,
1226|                status="available",
1227|                items=(first_item, *financial_deterioration.items[1:]),
1228|                partial_reason=None,
1229|            )
1230|        else:
1231|            financial_deterioration = replace(
1232|                financial_deterioration,
1233|                status="partial",
1234|                partial_reason="hermes_synthesis_not_admitted",
1235|            )
1236|    return build_single_company_research_report(
1237|        request=report.request,
1238|        generation_id=report.generation_id,
1239|        generated_at=report.generated_at,
1240|        citations=report.citations,
1241|        source_coverage=report.source_coverage,
1242|        downside=replace(report.downside, findings=(*report.downside.findings, *findings)),
1243|        upside=report.upside,
1244|        limitations=(
1245|            *report.limitations,
1246|            f"Hermes候選抽取：{status}{detail}。",
1247|        ),
1248|        financial_deterioration=financial_deterioration,
1249|    )
1250|
1251|
1252|def build_report_from_evidence(
1253|    *,
1254|    bundle: CompanyEvidenceBundle,
1255|    generation_id: str,
1256|    generated_at: str,
1257|    calibration: SingleCompanyProbabilityCalibration | None = None,
1258|    calibration_unavailable_reason: str | None = None,
1259|    candidate_adapter: HermesCandidateAdapter | None = None,
1260|) -> SingleCompanyResearchReport:
1261|    """Produce a valid conservative report without inventing unimplemented analysis."""
1262|
1263|    try:
1264|        generated = datetime.fromisoformat(generated_at)
1265|    except ValueError as exc:
1266|        raise ReportOrchestrationError("invalid generated_at") from exc
1267|    if generated.tzinfo is None or generated.utcoffset() is None:
1268|        raise ReportOrchestrationError("generated_at must be timezone-aware")
1269|    audit_available, audit_required = _coverage(bundle, "audit_or_review_pdf")
1270|    annual_available, annual_required = _coverage(bundle, "annual_audit_pdf")
1271|    positive, outperform = _probabilities(
1272|        bundle, generation_id, calibration, calibration_unavailable_reason
1273|    )
1274|    financial_deterioration, financial_citations = build_financial_deterioration(
1275|        bundle, generation_id
1276|    )
1277|    detailed = build_detailed_analysis(bundle)
1278|    if detailed.available:
1279|        limitations = [
1280|            *detailed.limitations,
1281|            f"查核／核閱PDF coverage為{audit_available}/{audit_required}；年度查核PDF為{annual_available}/{annual_required}。",
1282|        ]
1283|        if positive.status != "formal":
1284|            limitations.append("本generation沒有正式12個月報酬機率，Dashboard必須顯示unavailable。")
1285|        report = build_single_company_research_report(
1286|            request=bundle.request,
1287|            generation_id=generation_id,
1288|            generated_at=generated_at,
1289|            citations=_unique_citations((*detailed.citations, *financial_citations)),
1290|            source_coverage=bundle.source_coverage,
1291|            downside=DownsideCase(
1292|                generation_id=generation_id,
1293|                status="research_only",
1294|                headline=detailed.downside_headline,
1295|                findings=detailed.downside_findings,
1296|                twelve_month_drawdown_probability=_unavailable(
1297|                    "未來12個月最大跌幅事件尚未正式校準。"
1298|                ),
1299|                confidence=detailed.downside_confidence,
1300|            ),
1301|            upside=UpsideCase(
1302|                generation_id=generation_id,
1303|                status="research_only",
1304|                headline=detailed.upside_headline,
1305|                findings=detailed.upside_findings,
1306|                positive_return_probability=positive,
1307|                benchmark_outperform_probability=outperform,
1308|                confidence=detailed.upside_confidence,
1309|            ),
1310|            limitations=tuple(limitations),
1311|            financial_deterioration=financial_deterioration,
1312|        )
1313|        return _with_hermes_candidates(
1314|            report=report, candidate_adapter=candidate_adapter
1315|        )
1316|
1317|    citation = _citation(bundle)
1318|    downside_fact = Finding(
1319|        finding_id=f"downside:{citation.evidence_id}",
1320|        kind="fact",
1321|        direction="context",
1322|        statement=f"MOPS官方來源已取得{citation.period}綜合損益表。",
1323|        materiality=Decimal("0.30"),
1324|        evidence_ids=(citation.evidence_id,),
1325|        supporting_finding_ids=(),
1326|        counter_finding_ids=(),
1327|        counter_evidence_reason=None,
1328|    )
1329|    upside_fact = Finding(
1330|        finding_id=f"upside:{citation.evidence_id}",
1331|        kind="fact",
1332|        direction="context",
1333|        statement=f"MOPS官方來源已取得{citation.period}綜合損益表。",
1334|        materiality=Decimal("0.30"),
1335|        evidence_ids=(citation.evidence_id,),
1336|        supporting_finding_ids=(),
1337|        counter_finding_ids=(),
1338|        counter_evidence_reason=None,
1339|    )
1340|    limitations = [
1341|        "通用KAM、高風險附註、重大事件、產業前景與估值extractor尚未接入；不得由財報存在推導投資結論。",
1342|        f"查核／核閱PDF coverage為{audit_available}/{audit_required}；年度查核PDF為{annual_available}/{annual_required}。",
1343|    ]
1344|    if positive.status != "formal":
1345|        limitations.append("本generation沒有正式12個月報酬機率，Dashboard必須顯示unavailable。")
1346|    report = build_single_company_research_report(
1347|        request=bundle.request,
1348|        generation_id=generation_id,
1349|        generated_at=generated_at,
1350|        citations=_unique_citations((citation, *financial_citations)),
1351|        source_coverage=bundle.source_coverage,
1352|        downside=DownsideCase(
1353|            generation_id=generation_id,
1354|            status="blocked",
1355|            headline=(
1356|                "下跌風險結論被阻擋：尚未完成通用KAM、高風險附註與重大事件抽取；"
1357|                f"目前查核／核閱PDF coverage為{audit_available}/{audit_required}。"
1358|            ),
1359|            findings=(downside_fact,),
1360|            twelve_month_drawdown_probability=_unavailable(
1361|                "未來12個月最大跌幅事件尚未正式校準。"
1362|            ),
1363|            confidence=Decimal("0.10"),
1364|        ),
1365|        upside=UpsideCase(
1366|            generation_id=generation_id,
1367|            status="blocked",
1368|            headline="上漲潛力結論被阻擋：尚未完成通用產業前景、成長驅動與估值抽取。",
1369|            findings=(upside_fact,),
1370|            positive_return_probability=positive,
1371|            benchmark_outperform_probability=outperform,
1372|            confidence=Decimal("0.10"),
1373|        ),
1374|        limitations=tuple(limitations),
1375|        financial_deterioration=financial_deterioration,
1376|    )
1377|    return _with_hermes_candidates(report=report, candidate_adapter=candidate_adapter)
1378|
1379|
1380|def _news_citation(event: RecentNegativeNewsEvent) -> EvidenceCitation:
1381|    tier = (
1382|        "official"
1383|        if event.source_role in {"regulator", "court", "authority"}
1384|        else "issuer_primary"
1385|        if event.source_role == "issuer"
1386|        else "trusted_secondary"
1387|    )
1388|    return EvidenceCitation(
1389|        evidence_id=event.evidence_id,
1390|        source_id=event.evidence_id,
1391|        source_tier=tier,  # type: ignore[arg-type]
1392|        url=event.source_url,
1393|        content_sha256=event.content_sha256,
1394|        period=event.event_date,
1395|        available_at=event.available_at,
1396|        page=None,
1397|        coordinate=None,
1398|        verbatim_excerpt=event.verbatim_excerpt,
1399|        source_format="html",
1400|        locator=event.citation_locator,
1401|    )
1402|
1403|
1404|def attach_recent_negative_news(
1405|    report: SingleCompanyResearchReport,
1406|    collection: RecentNegativeNewsCollection,
1407|) -> SingleCompanyResearchReport:
1408|    """Attach only verified events to downside; retain unverified items in collection JSON."""
1409|
1410|    if any(item.family == "recent_negative_news" for item in report.source_coverage):
1411|        raise ReportOrchestrationError("recent negative news already attached")
1412|    verified = tuple(item for item in collection.events if item.affects_downside)
1413|    citations = tuple(_news_citation(item) for item in verified)
1414|    findings: list[Finding] = []
1415|    for item in verified:
1416|        source_finding_id = f"source-fact:{item.event_id}"
1417|        findings.append(
1418|            Finding(
1419|                finding_id=source_finding_id,
1420|                kind="fact",
1421|                direction="context",
1422|                statement=item.verbatim_excerpt,
1423|                materiality=Decimal("0"),
1424|                evidence_ids=(item.evidence_id,),
1425|                supporting_finding_ids=(),
1426|                counter_finding_ids=(),
1427|                counter_evidence_reason=None,
1428|            )
1429|        )
1430|        findings.append(
1431|            RecentNegativeNewsFinding(
1432|                finding_id=item.event_id,
1433|                kind="judgement",
1434|                direction="support",
1435|                statement=(
1436|                    f"{item.event_date} {item.category}；status={item.status}；"
1437|                    f"affected_account={item.affected_account}；cash_flow={item.cash_flow}；"
1438|                    f"impact={item.impact}。"
1439|                ),
1440|                materiality=Decimal("0"),
1441|                evidence_ids=(item.evidence_id,),
1442|                supporting_finding_ids=(source_finding_id,),
1443|                counter_finding_ids=(),
1444|                counter_evidence_reason=item.counterevidence,
1445|                category=item.category,
1446|                status=item.status,
1447|                affected_account=item.affected_account,
1448|                cash_flow=item.cash_flow,
1449|                impact=item.impact,
1450|                severity=item.severity,
1451|                confidence=item.confidence,
1452|                counterevidence=item.counterevidence,
1453|                monitoring=item.monitoring,
1454|                invalidation=item.invalidation,
1455|                duplicate_cluster=item.duplicate_cluster,
1456|                source_role=item.source_role,
1457|            )
1458|        )
1459|    unverified_count = sum(not item.affects_downside for item in collection.events)
1460|    limitation = (
1461|        "近期負面新聞：available；社群／論壇／匿名來源"
1462|        f"{unverified_count}件僅unverified展示且不影響downside。"
1463|        if collection.status == "available"
1464|        else "近期負面新聞：partial ("
1465|        + ",".join(collection.missing_reasons)
1466|        + ")；缺失不得視為零風險。"
1467|    )
1468|    coverage = SourceCoverage(
1469|        family="recent_negative_news",
1470|        required=1,
1471|        available=1 if collection.status == "available" else 0,
1472|        missing_reasons=collection.missing_reasons,
1473|    )
1474|    return build_single_company_research_report(
1475|        request=report.request,
1476|        generation_id=report.generation_id,
1477|        generated_at=report.generated_at,
1478|        citations=(*report.citations, *citations),
1479|        source_coverage=(*report.source_coverage, coverage),
1480|        downside=replace(
1481|            report.downside,
1482|            findings=(*report.downside.findings, *findings),
1483|        ),
1484|        upside=report.upside,
1485|        limitations=(*report.limitations, limitation),
1486|    )
1487|
1488|
1489|def run_single_company_analysis(
1490|    *,
1491|    identifier: str,
1492|    requested_market: Literal["TWSE", "TPEx"] | None,
1493|    as_of: str,
1494|    retrieved_at: str,
1495|    output_root: Path,
1496|    generation_id: str,
1497|    identity_sources: Sequence[OfficialIdentitySource] | None = None,
1498|    calibration: SingleCompanyProbabilityCalibration | None = None,
1499|    filing_store_root: Path | None = None,
1500|) -> CompanyAnalysisResult:
1501|    """Collect current evidence and bind the same generation to a report."""
1502|
1503|    bundle = collect_company_evidence_bundle(
1504|        identifier=identifier,
1505|        requested_market=requested_market,
1506|        as_of=as_of,
1507|        retrieved_at=retrieved_at,
1508|        output_root=output_root / "evidence",
1509|        identity_sources=identity_sources,
1510|        filing_store_root=filing_store_root,
1511|    )
1512|    decision = datetime.fromisoformat(as_of)
1513|    generated_at = datetime.now(decision.tzinfo).isoformat(timespec="seconds")
1514|    calibration_error: str | None = None
1515|    if calibration is None:
1516|        try:
1517|            calibration = calibrate_current_generation(
1518|                issuer_id=bundle.identity.issuer_id,
1519|                security_code=bundle.identity.security_code,
1520|                market=bundle.identity.market,
1521|                as_of=as_of,
1522|                generated_at=generated_at,
1523|                generation_id=generation_id,
1524|                output_root=output_root / "calibration",
1525|            )
1526|            if calibration is None:
1527|                calibration_error = "目前只支援TWSE官方benchmark校準。"
1528|        except ProbabilitySourceError as exc:
1529|            calibration_error = str(exc)
1530|    candidate_adapter = HermesApiCandidateAdapter.from_environment(generation_id)
1531|    report = build_report_from_evidence(
1532|        bundle=bundle,
1533|        generation_id=generation_id,
1534|        generated_at=generated_at,
1535|        calibration=calibration,
1536|        calibration_unavailable_reason=calibration_error,
1537|        candidate_adapter=candidate_adapter,
1538|    )
1539|    kam_judgement = build_kam_judgement(
1540|        bundle=bundle,
1541|        generation_id=generation_id,
1542|        candidate_adapter=candidate_adapter,
1543|    )
1544|    news = RecentNegativeNewsCollector(
1545|        interpreter=HermesNewsInterpreter.from_environment(generation_id)
1546|    ).collect(
1547|        issuer_id=bundle.identity.issuer_id,
1548|        security_code=bundle.identity.security_code,
1549|        company_name=bundle.identity.company_name,
1550|        as_of=as_of,
1551|        retrieved_at=retrieved_at,
1552|        store_root=output_root / "evidence",
1553|    )
1554|    report = attach_recent_negative_news(report, news)
1555|    evidence_status = (
1556|        "partial" if news.status == "partial" and bundle.status != "blocked" else bundle.status
1557|    )
1558|    return CompanyAnalysisResult(
1559|        generation_id=generation_id,
1560|        identity=bundle.identity,
1561|        evidence_status=evidence_status,
        source_coverage=report.source_coverage,
        kam_judgement=kam_judgement,
1569|        research_report=report,
1570|        recent_negative_news=news,
1571|        probability_calibration=calibration,
1572|        calibration_error=calibration_error,
1573|        filing_store_stats=bundle.filing_store_stats,
1574|    )
1575|
1576|
1577|__all__ = [
1578|    "CompanyAnalysisResult",
1579|    "GdeltNewsTransport",
1580|    "HermesApiCandidateAdapter",
1581|    "KamAnnualTimeline",
    "KamJudgement",
    "HermesNewsInterpreter",
    "NewsDiscoveryCandidate",
    "NewsSourceError",
    "RecentNegativeNewsCollection",
    "RecentNegativeNewsCollector",
    "RecentNegativeNewsEvent",
1592|    "ReportOrchestrationError",
1593|    "attach_recent_negative_news",
1594|    "admit_hermes_candidates",
1595|    "build_report_from_evidence",
1596|    "build_kam_judgement",
1597|    "run_single_company_analysis",
1598|]
1599|