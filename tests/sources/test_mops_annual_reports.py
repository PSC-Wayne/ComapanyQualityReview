from __future__ import annotations

from pathlib import Path
from urllib.error import URLError

import pytest

from company_quality.sources.mops_annual_reports import (
    AnnualReportSourceState,
    MopsAnnualReportAcquirer,
)


FIXTURES = Path(__file__).parents[1] / "fixtures"
PDF = b"%PDF-1.7\nfixture annual report\n%%EOF\n"


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.value += seconds


class FakeTransport:
    def __init__(self, clock: FakeClock, responses: list[bytes | Exception]) -> None:
        self.clock = clock
        self.responses = list(responses)
        self.calls: list[tuple[float, str, str, bytes | None]] = []

    def request(self, method: str, url: str, data: bytes | None = None) -> bytes:
        self.calls.append((self.clock.now(), method, url, data))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def acquirer(tmp_path: Path, responses: list[bytes | Exception]):
    clock = FakeClock()
    transport = FakeTransport(clock, responses)
    client = MopsAnnualReportAcquirer(
        transport=transport,
        cache_root=tmp_path / "external-cache",
        clock=clock.now,
        sleeper=clock.sleep,
        max_attempts=3,
    )
    return client, transport, clock


def assert_throttled(transport: FakeTransport) -> None:
    times = [call[0] for call in transport.calls]
    assert all(later - earlier >= 1.0 for earlier, later in zip(times, times[1:]))


def test_available_f04_is_selected_pre_decision_resolved_through_step9_and_deduplicated(
    tmp_path: Path,
) -> None:
    client, transport, _clock = acquirer(
        tmp_path,
        [fixture("mops_f04_valid.html"), fixture("mops_step9.html"), PDF],
    )

    first = client.acquire(
        security_code="6203", report_year=2023, decision_date="2024-06-30"
    )
    second = client.acquire(
        security_code="6203", report_year=2023, decision_date="2024-06-30"
    )

    assert first is second
    assert first.state is AnnualReportSourceState.AVAILABLE
    assert first.document is not None
    assert first.document.filename == "2023_6203_20240531F04.pdf"
    assert first.document.available_at == "2024-05-31T09:30:00+08:00"
    assert first.pdf_url == (
        "https://doc.twse.com.tw/pdf/2023_6203_20240531F04_20260804_132500.pdf"
    )
    assert first.pdf_path is not None
    assert first.pdf_path.read_bytes() == PDF
    assert tmp_path in first.pdf_path.parents
    assert len(transport.calls) == 3
    assert transport.calls[0][1] == "GET"
    assert "co_id=6203" in transport.calls[0][2]
    assert "year=113" in transport.calls[0][2]
    assert transport.calls[1][1] == "POST"
    assert b"step=9" in (transport.calls[1][3] or b"")
    assert client.probes == (first,)
    assert_throttled(transport)


def test_valid_listing_without_target_f04_is_document_not_listed(tmp_path: Path) -> None:
    client, transport, _clock = acquirer(
        tmp_path, [fixture("mops_f04_not_listed.html")]
    )

    result = client.acquire("6203", 2023, "2024-06-30")

    assert result.state is AnnualReportSourceState.DOCUMENT_NOT_LISTED
    assert result.document is None
    assert result.pdf_path is None
    assert result.request_count == 1
    assert len(transport.calls) == 1


def test_security_page_is_retried_bounded_and_never_becomes_document_absence(
    tmp_path: Path,
) -> None:
    page = fixture("mops_security_page.html")
    client, transport, _clock = acquirer(tmp_path, [page, page, page])

    result = client.acquire("6203", 2023, "2024-06-30")

    assert result.state is AnnualReportSourceState.SOURCE_UNAVAILABLE
    assert result.failure_kind == "security_response"
    assert result.request_count == 3
    assert "document" not in result.detail.lower()
    assert len(transport.calls) == 3
    assert_throttled(transport)


def test_wrong_listing_identity_is_source_unavailable_not_not_listed(tmp_path: Path) -> None:
    wrong = fixture("mops_f04_wrong_identity.html")
    client, transport, _clock = acquirer(tmp_path, [wrong, wrong, wrong])

    result = client.acquire("6203", 2023, "2024-06-30")

    assert result.state is AnnualReportSourceState.SOURCE_UNAVAILABLE
    assert result.failure_kind == "malformed_response"
    assert result.request_count == 3
    assert len(transport.calls) == 3


def test_post_decision_f04_is_not_selected_or_resolved(tmp_path: Path) -> None:
    client, transport, _clock = acquirer(tmp_path, [fixture("mops_f04_valid.html")])

    result = client.acquire("6203", 2023, "2024-05-30")

    assert result.state is AnnualReportSourceState.DOCUMENT_NOT_LISTED
    assert result.document is None
    assert "pre-decision" in result.detail
    assert len(transport.calls) == 1


def test_transport_failures_retry_bounded_and_record_final_probe(tmp_path: Path) -> None:
    error = URLError("temporary reset")
    client, transport, _clock = acquirer(tmp_path, [error, error, error])

    result = client.acquire("6203", 2023, "2024-06-30")

    assert result.state is AnnualReportSourceState.SOURCE_UNAVAILABLE
    assert result.failure_kind == "transport_error"
    assert result.request_count == 3
    assert client.probes == (result,)
    assert_throttled(transport)


def test_step9_must_return_transient_pdf_link_on_official_host(tmp_path: Path) -> None:
    external = b'<html><body><a href="https://example.com/report.pdf">PDF</a></body></html>'
    client, transport, _clock = acquirer(
        tmp_path,
        [fixture("mops_f04_valid.html"), external, external, external],
    )

    result = client.acquire("6203", 2023, "2024-06-30")

    assert result.state is AnnualReportSourceState.SOURCE_UNAVAILABLE
    assert result.failure_kind == "malformed_response"
    assert result.request_count == 4
    assert not list((tmp_path / "external-cache").rglob("*.pdf"))
    assert_throttled(transport)


@pytest.mark.parametrize(
    ("security_code", "report_year", "decision_date"),
    (("", 2023, "2024-06-30"), ("6203", 1910, "2024-06-30"), ("6203", 2023, "bad")),
)
def test_invalid_probe_identity_or_dates_are_rejected_without_requests(
    tmp_path: Path, security_code: str, report_year: int, decision_date: str
) -> None:
    client, transport, _clock = acquirer(tmp_path, [])

    with pytest.raises(ValueError):
        client.acquire(security_code, report_year, decision_date)

    assert transport.calls == []


def test_cache_path_inside_repository_is_rejected() -> None:
    repository_cache = Path(__file__).parents[2] / ".local-mops-cache"

    with pytest.raises(ValueError, match="outside a Git worktree"):
        MopsAnnualReportAcquirer(cache_root=repository_cache)
