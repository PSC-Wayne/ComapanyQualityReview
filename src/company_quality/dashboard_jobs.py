"""Persistent local analysis jobs for the company-research dashboard."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import queue
import sqlite3
import threading
from typing import Callable, Mapping, Sequence
import uuid

from company_quality.company_analysis.evidence_bundle import (
    collect_company_evidence_bundle,
)
from company_quality.identity import (
    OfficialIdentitySource,
    fetch_official_identity_sources,
    resolve_identity,
)


IdentitySourceLoader = Callable[[], Sequence[OfficialIdentitySource]]
Analyzer = Callable[..., object]
_TERMINAL = frozenset({"succeeded", "failed"})


class DashboardJobError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


class AnalysisJobService:
    """One durable queue and one local worker for official-source analysis."""

    def __init__(
        self,
        *,
        database_path: Path,
        output_root: Path,
        identity_sources: IdentitySourceLoader = fetch_official_identity_sources,
        analyzer: Analyzer = collect_company_evidence_bundle,
    ) -> None:
        self.database_path = database_path
        self.output_root = output_root
        self._identity_sources = identity_sources
        self._source_cache: tuple[OfficialIdentitySource, ...] | None = None
        self._source_lock = threading.Lock()
        self._analyzer = analyzer
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._started = False
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    job_id TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL UNIQUE,
                    identifier TEXT NOT NULL,
                    security_code TEXT NOT NULL,
                    issuer_id TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    market TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    error TEXT,
                    result_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "UPDATE analysis_jobs SET status='queued', stage='queued', "
                "error=NULL, updated_at=? WHERE status='running'",
                (_now(),),
            )

    def _sources(self) -> tuple[OfficialIdentitySource, ...]:
        with self._source_lock:
            if self._source_cache is None:
                self._source_cache = tuple(self._identity_sources())
            return self._source_cache

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._worker = threading.Thread(
            target=self._work_loop, name="company-analysis-worker", daemon=True
        )
        self._worker.start()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id FROM analysis_jobs WHERE status='queued' ORDER BY created_at"
            ).fetchall()
        for row in rows:
            self._queue.put(str(row["job_id"]))

    def stop(self) -> None:
        if not self._started:
            return
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=10)
        self._started = False
        self._worker = None

    def create_job(
        self,
        *,
        identifier: str,
        market: str | None,
        as_of: str,
    ) -> dict[str, object]:
        needle = identifier.strip() if isinstance(identifier, str) else ""
        if not needle or len(needle) > 128:
            raise DashboardJobError("identifier must contain 1..128 characters")
        requested_market = market if market in (None, "TWSE", "TPEx") else "INVALID"
        if requested_market == "INVALID":
            raise DashboardJobError("market must be TWSE, TPEx or omitted")
        sources = self._sources()
        resolution = resolve_identity(needle, requested_market, as_of, sources=sources)
        if resolution.status != "resolved" or resolution.identity is None:
            raise DashboardJobError(f"identity resolution failed: {resolution.status}")
        identity = resolution.identity

        with self._connect() as connection:
            active = connection.execute(
                """
                SELECT * FROM analysis_jobs
                WHERE security_code=? AND market=? AND as_of=?
                  AND status IN ('queued','running')
                ORDER BY created_at DESC LIMIT 1
                """,
                (identity.security_code, identity.market, resolution.decision_time),
            ).fetchone()
            if active is not None:
                return dict(active)

            job_id = str(uuid.uuid4())
            generation_id = str(uuid.uuid4())
            timestamp = _now()
            connection.execute(
                """
                INSERT INTO analysis_jobs (
                    job_id, generation_id, identifier, security_code, issuer_id,
                    company_name, market, as_of, status, stage, error,
                    result_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'queued', NULL, NULL, ?, ?)
                """,
                (
                    job_id,
                    generation_id,
                    needle,
                    identity.security_code,
                    identity.issuer_id,
                    identity.company_name,
                    identity.market,
                    resolution.decision_time,
                    timestamp,
                    timestamp,
                ),
            )
        if self._started:
            self._queue.put(job_id)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise DashboardJobError("analysis job not found")
        return dict(row)

    def get_result(self, job_id: str) -> object | None:
        job = self.get_job(job_id)
        if job["status"] != "succeeded" or not job["result_path"]:
            return None
        path = Path(str(job["result_path"]))
        if not path.is_file():
            raise DashboardJobError("analysis result file is missing")
        return json.loads(path.read_text(encoding="utf-8"))

    def search_companies(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        needle = query.strip()
        if not needle:
            return []
        matches: list[dict[str, str]] = []
        for source in self._sources():
            for row in source.rows:
                values = (
                    str(row["security_code"]),
                    str(row["company_name"]),
                    str(row["short_name"]),
                )
                if any(needle.casefold() in value.casefold() for value in values):
                    matches.append(
                        {
                            "security_code": values[0],
                            "company_name": values[1],
                            "short_name": values[2],
                            "market": source.market,
                        }
                    )
                if len(matches) >= limit:
                    return matches
        return matches

    def _update(
        self,
        job_id: str,
        *,
        status: str,
        stage: str,
        error: str | None = None,
        result_path: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE analysis_jobs
                SET status=?, stage=?, error=?, result_path=COALESCE(?, result_path),
                    updated_at=?
                WHERE job_id=?
                """,
                (status, stage, error, result_path, _now(), job_id),
            )

    def _work_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            try:
                self._run(job_id)
            finally:
                self._queue.task_done()

    def _run(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job["status"] in _TERMINAL:
            return
        self._update(job_id, status="running", stage="collecting_official_evidence")
        job = self.get_job(job_id)
        result_dir = self.output_root / str(job["generation_id"])
        result_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = self._analyzer(
                identifier=str(job["security_code"]),
                requested_market=str(job["market"]),
                as_of=str(job["as_of"]),
                retrieved_at=str(job["as_of"]),
                output_root=result_dir / "evidence",
            )
            result_path = result_dir / "result.json"
            result_path.write_text(
                json.dumps(_jsonable(result), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._update(
                job_id,
                status="succeeded",
                stage="evidence_bundle_complete",
                result_path=str(result_path.resolve()),
            )
        except Exception as exc:
            detail = " ".join(str(exc).split())[:1000]
            self._update(
                job_id,
                status="failed",
                stage="failed",
                error=f"{type(exc).__name__}: {detail or 'analysis failed'}",
            )


__all__ = ["AnalysisJobService", "DashboardJobError"]
