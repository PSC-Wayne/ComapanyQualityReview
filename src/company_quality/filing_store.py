"""Local-first content-addressed repository for official filing PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Mapping
import uuid


class FilingStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FilingStoreStats:
    hits: int
    misses: int
    saved: int
    corruptions: int


@dataclass(frozen=True, slots=True)
class StoredFiling:
    document_id: str
    market: str
    security_code: str
    issuer_id: str
    period: str
    filing_type: str
    report_scope: str
    official_filed_at: str
    source_url: str
    retrieved_at: str
    content_sha256: str
    path: Path
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class StoredStatement:
    document_id: str
    market: str
    security_code: str
    issuer_id: str
    period: str
    report: str
    official_url: str
    retrieved_at: str
    available_at: str
    content_sha256: str
    path: Path


def _instant(value: str, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise FilingStoreError(f"invalid {field}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise FilingStoreError(f"{field} must be timezone-aware")
    return result


class FilingStore:
    """SQLite metadata plus immutable content-addressed PDF blobs."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.database_path = root / "filings.sqlite3"
        self.blob_root = root / "blobs"
        self.quarantine_root = root / "quarantine"
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._saved = 0
        self._corruptions = 0
        self.root.mkdir(parents=True, exist_ok=True)
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS filing_documents (
                    document_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    security_code TEXT NOT NULL,
                    issuer_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    filing_type TEXT NOT NULL,
                    report_scope TEXT NOT NULL,
                    official_filed_at TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    mime_type TEXT NOT NULL,
                    corrected INTEGER NOT NULL,
                    parser_status TEXT NOT NULL,
                    ocr_status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    valid INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(market, security_code, period, filing_type, report_scope, content_sha256)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS filing_lookup
                ON filing_documents(
                    market, security_code, period, filing_type,
                    official_filed_at DESC, corrected DESC, created_at DESC
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS statement_artifacts (
                    document_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    security_code TEXT NOT NULL,
                    issuer_id TEXT NOT NULL,
                    period TEXT NOT NULL,
                    report TEXT NOT NULL,
                    official_url TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    valid INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(market, security_code, period, report, content_sha256)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS statement_lookup
                ON statement_artifacts(
                    market, security_code, period, report, available_at DESC
                )
                """
            )

    def stats(self) -> FilingStoreStats:
        with self._lock:
            return FilingStoreStats(
                hits=self._hits,
                misses=self._misses,
                saved=self._saved,
                corruptions=self._corruptions,
            )

    def _count(self, field: str) -> None:
        with self._lock:
            if field == "hits":
                self._hits += 1
            elif field == "misses":
                self._misses += 1
            elif field == "saved":
                self._saved += 1
            elif field == "corruptions":
                self._corruptions += 1

    def _blob_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise FilingStoreError("invalid PDF SHA-256")
        return self.blob_root / digest[:2] / f"{digest}.pdf"

    @staticmethod
    def _valid_pdf(path: Path, expected_hash: str) -> bool:
        if path.is_symlink() or not path.is_file():
            return False
        body = path.read_bytes()
        return body.startswith(b"%PDF") and sha256(body).hexdigest() == expected_hash

    def _publish_blob(self, body: bytes, digest: str) -> Path:
        destination = self._blob_path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if self._valid_pdf(destination, digest):
                return destination
            quarantine = self.quarantine_root / f"{digest}-{uuid.uuid4().hex}.pdf"
            os.replace(destination, quarantine)
            self._count("corruptions")

        temporary = destination.parent / f".{digest}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if not self._valid_pdf(destination, digest):
                    raise FilingStoreError("concurrent PDF publication conflict")
            directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        if not self._valid_pdf(destination, digest):
            raise FilingStoreError("published PDF failed validation")
        return destination

    def _statement_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise FilingStoreError("invalid statement SHA-256")
        return self.root / "html" / digest[:2] / f"{digest}.html"

    @staticmethod
    def _valid_statement(path: Path, expected_hash: str) -> bool:
        if path.is_symlink() or not path.is_file():
            return False
        body = path.read_bytes()
        return b"<table" in body.lower() and sha256(body).hexdigest() == expected_hash

    def _publish_statement(self, body: bytes, digest: str) -> Path:
        destination = self._statement_path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if self._valid_statement(destination, digest):
                return destination
            quarantine = self.quarantine_root / f"{digest}-{uuid.uuid4().hex}.html"
            os.replace(destination, quarantine)
            self._count("corruptions")
        temporary = destination.parent / f".{digest}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if not self._valid_statement(destination, digest):
                    raise FilingStoreError("concurrent statement publication conflict")
        finally:
            temporary.unlink(missing_ok=True)
        if not self._valid_statement(destination, digest):
            raise FilingStoreError("published statement failed validation")
        return destination

    def put_statement(
        self,
        *,
        body: bytes,
        market: str,
        security_code: str,
        issuer_id: str,
        period: str,
        report: str,
        official_url: str,
        retrieved_at: str,
        available_at: str,
    ) -> StoredStatement:
        if b"<table" not in body.lower():
            raise FilingStoreError("statement body has no table")
        _instant(retrieved_at, "retrieved_at")
        _instant(available_at, "available_at")
        if report not in ("balance", "income", "cash_flow", "equity_changes"):
            raise FilingStoreError("invalid statement report")
        if not official_url.startswith("https://"):
            raise FilingStoreError("official statement URL must use HTTPS")
        digest = sha256(body).hexdigest()
        path = self._publish_statement(body, digest)
        identity_key = "|".join(
            (market, security_code, issuer_id, period, report, digest)
        )
        document_id = f"statement:{sha256(identity_key.encode()).hexdigest()}"
        relative = path.relative_to(self.root).as_posix()
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connect() as connection:
            before = connection.total_changes
            connection.execute(
                """
                INSERT OR IGNORE INTO statement_artifacts (
                    document_id, market, security_code, issuer_id, period,
                    report, official_url, retrieved_at, available_at,
                    content_sha256, relative_path, byte_count, valid, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    document_id, market, security_code, issuer_id, period,
                    report, official_url, retrieved_at, available_at, digest,
                    relative, len(body), created_at,
                ),
            )
            inserted = connection.total_changes > before
        if inserted:
            self._count("saved")
        return StoredStatement(
            document_id=document_id,
            market=market,
            security_code=security_code,
            issuer_id=issuer_id,
            period=period,
            report=report,
            official_url=official_url,
            retrieved_at=retrieved_at,
            available_at=available_at,
            content_sha256=digest,
            path=path,
        )

    def lookup_statement(
        self,
        *,
        market: str,
        security_code: str,
        issuer_id: str,
        period: str,
        report: str,
        as_of: str,
    ) -> StoredStatement | None:
        decision_time = _instant(as_of, "as_of")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM statement_artifacts
                WHERE market=? AND security_code=? AND issuer_id=?
                  AND period=? AND report=? AND valid=1
                ORDER BY available_at DESC, created_at DESC
                """,
                (market, security_code, issuer_id, period, report),
            ).fetchall()
        for row in rows:
            if _instant(str(row["available_at"]), "available_at") > decision_time:
                continue
            path = self.root / str(row["relative_path"])
            digest = str(row["content_sha256"])
            if not self._valid_statement(path, digest):
                with self._connect() as connection:
                    connection.execute(
                        "UPDATE statement_artifacts SET valid=0 WHERE document_id=?",
                        (row["document_id"],),
                    )
                self._count("corruptions")
                continue
            self._count("hits")
            return StoredStatement(
                document_id=str(row["document_id"]),
                market=str(row["market"]),
                security_code=str(row["security_code"]),
                issuer_id=str(row["issuer_id"]),
                period=str(row["period"]),
                report=str(row["report"]),
                official_url=str(row["official_url"]),
                retrieved_at=str(row["retrieved_at"]),
                available_at=str(row["available_at"]),
                content_sha256=digest,
                path=path,
            )
        self._count("misses")
        return None

    def put_pdf(
        self,
        *,
        body: bytes,
        market: str,
        security_code: str,
        issuer_id: str,
        period: str,
        filing_type: str,
        report_scope: str,
        official_filed_at: str,
        source_url: str,
        retrieved_at: str,
        corrected: bool,
        metadata: Mapping[str, object],
        parser_status: str = "not_parsed",
        ocr_status: str = "not_attempted",
    ) -> StoredFiling:
        if not body.startswith(b"%PDF"):
            raise FilingStoreError("filing body is not a PDF")
        _instant(official_filed_at, "official_filed_at")
        _instant(retrieved_at, "retrieved_at")
        if market not in ("TWSE", "TPEx") or not security_code or not period:
            raise FilingStoreError("invalid filing identity")
        if not source_url.startswith("https://"):
            raise FilingStoreError("official filing URL must use HTTPS")
        digest = sha256(body).hexdigest()
        path = self._publish_blob(body, digest)
        identity_key = "|".join(
            (market, security_code, issuer_id, period, filing_type, report_scope, digest)
        )
        document_id = f"filing:{sha256(identity_key.encode()).hexdigest()}"
        relative = path.relative_to(self.root).as_posix()
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            before = connection.total_changes
            connection.execute(
                """
                INSERT OR IGNORE INTO filing_documents (
                    document_id, market, security_code, issuer_id, period,
                    filing_type, report_scope, official_filed_at, source_url,
                    retrieved_at, content_sha256, relative_path, byte_count,
                    mime_type, corrected, parser_status, ocr_status,
                    metadata_json, valid, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'application/pdf', ?, ?, ?, ?, 1, ?)
                """,
                (
                    document_id, market, security_code, issuer_id, period,
                    filing_type, report_scope, official_filed_at, source_url,
                    retrieved_at, digest, relative, len(body), int(corrected),
                    parser_status, ocr_status, metadata_json, created_at,
                ),
            )
            inserted = connection.total_changes > before
        if inserted:
            self._count("saved")
        return StoredFiling(
            document_id=document_id,
            market=market,
            security_code=security_code,
            issuer_id=issuer_id,
            period=period,
            filing_type=filing_type,
            report_scope=report_scope,
            official_filed_at=official_filed_at,
            source_url=source_url,
            retrieved_at=retrieved_at,
            content_sha256=digest,
            path=path,
            metadata=dict(metadata),
        )

    def lookup(
        self,
        *,
        market: str,
        security_code: str,
        issuer_id: str,
        period: str,
        filing_type: str,
        as_of: str,
    ) -> StoredFiling | None:
        decision_time = _instant(as_of, "as_of")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM filing_documents
                WHERE market=? AND security_code=? AND issuer_id=?
                  AND period=? AND filing_type=? AND valid=1
                ORDER BY official_filed_at DESC, corrected DESC, created_at DESC
                """,
                (market, security_code, issuer_id, period, filing_type),
            ).fetchall()
        for row in rows:
            if _instant(str(row["official_filed_at"]), "official_filed_at") > decision_time:
                continue
            path = self.root / str(row["relative_path"])
            digest = str(row["content_sha256"])
            if not self._valid_pdf(path, digest):
                with self._connect() as connection:
                    connection.execute(
                        "UPDATE filing_documents SET valid=0 WHERE document_id=?",
                        (row["document_id"],),
                    )
                self._count("corruptions")
                continue
            metadata = json.loads(str(row["metadata_json"]))
            if not isinstance(metadata, dict):
                raise FilingStoreError("stored filing metadata must be an object")
            self._count("hits")
            return StoredFiling(
                document_id=str(row["document_id"]),
                market=str(row["market"]),
                security_code=str(row["security_code"]),
                issuer_id=str(row["issuer_id"]),
                period=str(row["period"]),
                filing_type=str(row["filing_type"]),
                report_scope=str(row["report_scope"]),
                official_filed_at=str(row["official_filed_at"]),
                source_url=str(row["source_url"]),
                retrieved_at=str(row["retrieved_at"]),
                content_sha256=digest,
                path=path,
                metadata=metadata,
            )
        self._count("misses")
        return None


__all__ = [
    "FilingStore",
    "FilingStoreError",
    "FilingStoreStats",
    "StoredFiling",
    "StoredStatement",
]
