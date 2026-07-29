from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import json
import threading
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

from company_quality.dashboard_jobs import AnalysisJobService
from company_quality.dashboard_server import make_server
from company_quality.identity import OfficialIdentitySource


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
