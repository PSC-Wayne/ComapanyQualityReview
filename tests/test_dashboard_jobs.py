from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import json
import threading
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from company_quality.dashboard_jobs import AnalysisJobService
from company_quality.dashboard_server import make_server
from company_quality.identity import (
    OfficialIdentitySource,
    admit_artifact_identity,
    resolve_identity,
)


AS_OF = "2026-07-29T15:00:00+08:00"
SOURCES = (
    OfficialIdentitySource(
        market="TWSE",
        url="https://official.test/twse",
        available_at="2026-07-29T00:00:00+08:00",
        rows=(
            {
                "security_code": "2330",
                "company_name": "台灣積體電路製造股份有限公司",
                "short_name": "台積電",
                "issuer_id": "22099131",
                "listing_date": "19940905",
            },
            {
                "security_code": "8888",
                "company_name": "上市測試股份有限公司",
                "short_name": "共同簡稱",
                "issuer_id": "87654321",
                "listing_date": "20200102",
            },
        ),
    ),
    OfficialIdentitySource(
        market="TPEx",
        url="https://official.test/tpex",
        available_at="2026-07-29T00:00:00+08:00",
        rows=(
            {
                "security_code": "6488",
                "company_name": "環球晶圓股份有限公司",
                "short_name": "環球晶",
                "issuer_id": "28113286",
                "listing_date": "20150925",
            },
            {
                "security_code": "9999",
                "company_name": "測試科技股份有限公司",
                "short_name": "共同簡稱",
                "issuer_id": "12345678",
                "listing_date": "20200102",
            },
        ),
    ),
)


@dataclass(frozen=True)
class FakeResult:
    status: str
    coverage: int
    ratio: Decimal = Decimal("1")


def wait_terminal(service: AnalysisJobService, job_id: str) -> dict[str, object]:
    for _ in range(100):
        job = service.get_job(job_id)
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_name_input_runs_persistent_job_and_returns_result(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def analyze(**kwargs: object) -> FakeResult:
        calls.append(kwargs)
        return FakeResult("available", 60)

    service = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=lambda: SOURCES,
        analyzer=analyze,
    )
    service.start()
    created = service.create_job(identifier="台積電", market=None, as_of=AS_OF)
    finished = wait_terminal(service, str(created["job_id"]))
    service.stop()

    assert finished["status"] == "succeeded"
    assert finished["security_code"] == "2330"
    assert finished["company_name"] == "台灣積體電路製造股份有限公司"
    assert calls[0]["identifier"] == "2330"
    assert calls[0]["generation_id"] == created["generation_id"]
    assert calls[0]["identity_sources"] == SOURCES
    assert calls[0]["retrieved_at"] == calls[0]["as_of"] == AS_OF
    assert service.get_result(str(created["job_id"])) == {
        "status": "available",
        "coverage": 60,
        "ratio": "1",
    }

    reopened = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=lambda: SOURCES,
        analyzer=analyze,
    )
    assert reopened.get_job(str(created["job_id"]))["status"] == "succeeded"
    assert reopened.get_result(str(created["job_id"]))["coverage"] == 60


def test_same_company_and_as_of_reuses_active_job(tmp_path: Path) -> None:
    service = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=lambda: SOURCES,
        analyzer=lambda **_: FakeResult("available", 60),
    )
    first = service.create_job(identifier="2330", market="TWSE", as_of=AS_OF)
    second = service.create_job(identifier="台積電", market=None, as_of=AS_OF)
    assert first["job_id"] == second["job_id"]


def test_analyzer_failure_is_visible_and_has_no_result(tmp_path: Path) -> None:
    def fail(**_: object) -> FakeResult:
        raise RuntimeError("official source unavailable")

    service = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=lambda: SOURCES,
        analyzer=fail,
    )
    service.start()
    created = service.create_job(identifier="2330", market=None, as_of=AS_OF)
    finished = wait_terminal(service, str(created["job_id"]))
    service.stop()

    assert finished["status"] == "failed"
    assert finished["stage"] == "failed"
    assert "official source unavailable" in str(finished["error"])
    assert service.get_result(str(created["job_id"])) is None


def test_http_dashboard_creates_polls_and_reads_job_result(tmp_path: Path) -> None:
    source_loads = 0

    def load_sources():
        nonlocal source_loads
        source_loads += 1
        return SOURCES

    service = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=load_sources,
        analyzer=lambda **_: FakeResult("available", 60),
    )
    service.start()
    server = make_server(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/", timeout=5) as response:
            html = response.read().decode()
        assert "輸入上市／上櫃公司股號或名稱" in html
        assert "companyQualityJobId" in html
        assert "research_report_complete" in html
        assert "12個月絕對正報酬" in html
        assert "官方引用證據" in html
        assert "本機財報庫" in html
        assert "Local hits" in html
        assert "materiality" in html
        assert "無法解釋財報異常" in html
        assert "severity" in html
        assert "counterevidence" in html
        assert "monitoring" in html
        assert "invalidation" in html
        assert "issuer_id" in html and "job.market" in html

        with urlopen(base + "/api/companies/search?q=" + quote("台積"), timeout=5) as response:
            matches = json.load(response)
        assert matches[0]["security_code"] == "2330"

        request = Request(
            base + "/api/analyses",
            data=json.dumps({"identifier": "台積電", "market": None}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 202
            created = json.load(response)
        job_id = created["job_id"]
        job: dict[str, object] = {}
        for _ in range(100):
            with urlopen(base + f"/api/analyses/{job_id}", timeout=5) as response:
                job = json.load(response)
            if job["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert job["stage"] == "research_report_complete"
        assert "result_path" not in job
        with urlopen(base + f"/api/analyses/{job_id}/result", timeout=5) as response:
            result = json.load(response)
        assert result == {"status": "available", "coverage": 60, "ratio": "1"}
        assert source_loads == 1
    finally:
        server.shutdown()
        server.server_close()
        service.stop()


def test_twse_and_tpex_queries_complete_same_generation_api_report_contract(
    tmp_path: Path,
) -> None:
    def analyze(**kwargs: object) -> dict[str, object]:
        resolution = resolve_identity(
            str(kwargs["identifier"]),
            str(kwargs["requested_market"]),
            str(kwargs["as_of"]),
            SOURCES,
        )
        assert resolution.identity is not None
        return {
            "generation_id": kwargs["generation_id"],
            "identity": resolution.identity,
            "status": "partial",
        }

    service = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=lambda: SOURCES,
        analyzer=analyze,
    )
    service.start()
    server = make_server(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for identifier, market, issuer_id, company_name in (
            ("2330", "TWSE", "22099131", "台灣積體電路製造股份有限公司"),
            ("環球晶", "TPEx", "28113286", "環球晶圓股份有限公司"),
        ):
            request = Request(
                base + "/api/analyses",
                data=json.dumps({"identifier": identifier, "market": None}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                created = json.load(response)
            finished = wait_terminal(service, created["job_id"])
            with urlopen(
                base + f"/api/analyses/{created['job_id']}/result", timeout=5
            ) as response:
                result = json.load(response)

            assert finished["market"] == market
            assert finished["issuer_id"] == issuer_id
            assert finished["company_name"] == company_name
            assert result["generation_id"] == created["generation_id"]
            assert result["identity"]["market"] == market
            assert result["identity"]["issuer_id"] == issuer_id
            assert result["identity"]["company_name"] == company_name
    finally:
        server.shutdown()
        server.server_close()
        service.stop()


def test_cross_market_artifact_requires_official_same_issuer_chain() -> None:
    resolution = resolve_identity("2330", "TWSE", AS_OF, SOURCES)
    assert resolution.identity is not None

    confirmed = admit_artifact_identity(
        resolution.identity,
        artifact_market="TPEx",
        artifact_security_code="9998",
        artifact_issuer_id="22099131",
        identity_evidence_url="https://official.test/issuer-chain/22099131",
    )
    unconfirmed = admit_artifact_identity(
        resolution.identity,
        artifact_market="TPEx",
        artifact_security_code="2330",
        artifact_issuer_id=None,
        identity_evidence_url=None,
    )
    wrong_issuer = admit_artifact_identity(
        resolution.identity,
        artifact_market="TPEx",
        artifact_security_code="2330",
        artifact_issuer_id="12345678",
        identity_evidence_url="https://official.test/tpex",
    )

    assert confirmed.status == "admitted"
    assert confirmed.reason == "official_issuer_identity_match"
    assert unconfirmed.status == wrong_issuer.status == "rejected"
    assert unconfirmed.reason == "official_issuer_identity_unconfirmed"
    assert wrong_issuer.reason == "wrong_issuer_candidate"


def test_ambiguous_cross_market_identity_returns_typed_candidates() -> None:
    resolution = resolve_identity("共同簡稱", None, AS_OF, SOURCES)

    assert resolution.status == "ambiguous_identity"
    assert resolution.reason == "ambiguous_official_candidates"
    assert resolution.identity is None
    assert {(item.market, item.issuer_id) for item in resolution.candidates} == {
        ("TWSE", "87654321"),
        ("TPEx", "12345678"),
    }


def test_ambiguous_api_query_returns_typed_gap_and_candidates(tmp_path: Path) -> None:
    service = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=lambda: SOURCES,
        analyzer=lambda **_: FakeResult("available", 60),
    )
    server = make_server(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = Request(
        f"http://127.0.0.1:{server.server_port}/api/analyses",
        data=json.dumps({"identifier": "共同簡稱", "market": None}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        try:
            urlopen(request, timeout=5)
        except HTTPError as exc:
            payload = json.load(exc)
            assert exc.code == 400
        else:
            raise AssertionError("ambiguous identity query unexpectedly created a job")

        assert payload["reason"] == "ambiguous_official_candidates"
        assert {(item["market"], item["issuer_id"]) for item in payload["candidates"]} == {
            ("TWSE", "87654321"),
            ("TPEx", "12345678"),
        }
    finally:
        server.shutdown()
        server.server_close()
