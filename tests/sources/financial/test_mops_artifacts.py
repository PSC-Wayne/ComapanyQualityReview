import hashlib
from email.message import Message
from urllib.error import HTTPError

import pytest

from company_quality.sources.financial import (
    ArtifactConflictError,
    MopsFinancialCollector,
    MopsTransport,
    Period,
    SourceArtifactError,
    trailing_quarters,
)


class FakeTransport:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.landing_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, str]]] = []

    def preload(self, endpoint: str) -> None:
        self.landing_calls.append(endpoint)

    def post(self, endpoint: str, payload: dict[str, str]) -> bytes:
        self.post_calls.append((endpoint, payload))
        return self.bodies[endpoint]


def html(title: str, value: str = "100") -> bytes:
    return (
        f"<html><body>本資料由台灣積體電路製造股份有限公司提供"
        f"<h2>民國115年第1季 {title}</h2><table><tr><td>{value}</td></tr></table>"
        "</body></html>"
    ).encode()


def test_trailing_five_years_is_exactly_twenty_quarters() -> None:
    periods = trailing_quarters(Period(115, 1))

    assert len(periods) == 20
    assert periods[0] == Period(110, 2)
    assert periods[-1] == Period(115, 1)


def test_mops_transport_retries_one_temporary_redirect(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b"official"

    transport = MopsTransport()
    calls: list[int] = []

    def open_once_after_redirect(_request, timeout: int):
        assert timeout == 30
        calls.append(timeout)
        if len(calls) == 1:
            raise HTTPError(
                "https://mopsov.twse.com.tw", 307, "redirect", Message(), None
            )
        return Response()

    monkeypatch.setattr(transport.opener, "open", open_once_after_redirect)
    sleeps: list[int] = []
    monkeypatch.setattr("company_quality.sources.financial.time.sleep", sleeps.append)

    assert transport.post("ajax_t164sb03", {"co_id": "5274"}) == b"official"
    assert len(calls) == 2
    assert sleeps == [1]


def test_collects_selected_company_three_statement_raw_artifacts(tmp_path) -> None:
    bodies = {
        "ajax_t164sb03": html("資產負債表"),
        "ajax_t164sb04": html("綜合損益表"),
        "ajax_t164sb05": html("現金流量表"),
        "ajax_t164sb06": html("權益變動表"),
    }
    transport = FakeTransport(bodies)
    collector = MopsFinancialCollector(transport=transport)

    result = collector.collect_period(
        security_code="2330",
        company_name="台灣積體電路製造股份有限公司",
        company_short_name="台積電",
        issuer_id="22099131",
        market="TWSE",
        period=Period(115, 1),
        output_root=tmp_path,
        retrieved_at="2026-07-24T10:00:00+08:00",
    )

    assert result.status == "available"
    assert len(result.artifacts) == 4
    assert {artifact.report for artifact in result.artifacts} == {
        "balance",
        "income",
        "cash_flow",
        "equity_changes",
    }
    for artifact in result.artifacts:
        raw = artifact.path.read_bytes()
        assert artifact.content_sha256 == hashlib.sha256(raw).hexdigest()
        assert artifact.endpoint_scope == "selected_company"
        assert artifact.available_at == "2026-07-24T10:00:00+08:00"
        assert artifact.availability_basis == "first_successful_retrieval"
    assert all(call[1]["TYPEK"] == "sii" for call in transport.post_calls)
    assert all(call[1]["co_id"] == "2330" for call in transport.post_calls)


def test_annual_equity_statement_accepts_official_annual_period_marker(tmp_path) -> None:
    def annual(title: str, marker: str) -> bytes:
        return (
            "<html><body>本資料由台灣積體電路製造股份有限公司提供"
            f"<h2>{marker} {title}</h2><table><tr><td>100</td></tr></table>"
            "</body></html>"
        ).encode()

    bodies = {
        "ajax_t164sb03": annual("資產負債表", "民國114年第4季"),
        "ajax_t164sb04": annual("綜合損益表", "民國114年第4季"),
        "ajax_t164sb05": annual("現金流量表", "民國114年第4季"),
        "ajax_t164sb06": annual("權益變動表", "民國114年度"),
    }

    result = MopsFinancialCollector(transport=FakeTransport(bodies)).collect_period(
        "2330",
        "台灣積體電路製造股份有限公司",
        "台積電",
        "22099131",
        "TWSE",
        Period(114, 4),
        tmp_path,
        "2026-07-31T12:00:00+08:00",
    )

    assert len(result.artifacts) == 4


@pytest.mark.parametrize(
    ("quarter", "equity_marker"),
    ((2, "民國114年上半年度"), (3, "民國114年前3季")),
)
def test_interim_equity_statement_accepts_official_period_marker(
    tmp_path, quarter: int, equity_marker: str
) -> None:
    def statement(title: str, marker: str) -> bytes:
        return (
            "<html><body>本資料由台灣積體電路製造股份有限公司提供"
            f"<h2>{marker} {title}</h2><table><tr><td>100</td></tr></table>"
            "</body></html>"
        ).encode()

    quarter_marker = f"民國114年第{quarter}季"
    bodies = {
        "ajax_t164sb03": statement("資產負債表", quarter_marker),
        "ajax_t164sb04": statement("綜合損益表", quarter_marker),
        "ajax_t164sb05": statement("現金流量表", quarter_marker),
        "ajax_t164sb06": statement("權益變動表", equity_marker),
    }

    result = MopsFinancialCollector(transport=FakeTransport(bodies)).collect_period(
        "2330",
        "台灣積體電路製造股份有限公司",
        "台積電",
        "22099131",
        "TWSE",
        Period(114, quarter),
        tmp_path,
        "2026-07-31T12:00:00+08:00",
    )

    assert len(result.artifacts) == 4


def test_wrong_company_or_no_data_is_not_saved_as_success(tmp_path) -> None:
    bad = "<html><body>查無公司資料！</body></html>".encode()
    transport = FakeTransport(
        {
            name: bad
            for name in (
                "ajax_t164sb03",
                "ajax_t164sb04",
                "ajax_t164sb05",
                "ajax_t164sb06",
            )
        }
    )

    with pytest.raises(SourceArtifactError, match="no official company data"):
        MopsFinancialCollector(transport=transport).collect_period(
            "2330",
            "台灣積體電路製造股份有限公司",
            "台積電",
            "22099131",
            "TWSE",
            Period(115, 1),
            tmp_path,
            "2026-07-24T10:00:00+08:00",
        )

    assert not list(tmp_path.rglob("*.html"))


def test_existing_raw_artifact_is_not_overwritten_by_changed_bytes(tmp_path) -> None:
    bodies = {
        "ajax_t164sb03": html("資產負債表"),
        "ajax_t164sb04": html("綜合損益表"),
        "ajax_t164sb05": html("現金流量表"),
        "ajax_t164sb06": html("權益變動表"),
    }
    transport = FakeTransport(bodies)
    collector = MopsFinancialCollector(transport=transport)
    args = (
        "2330",
        "台灣積體電路製造股份有限公司",
        "台積電",
        "22099131",
        "TWSE",
        Period(115, 1),
        tmp_path,
        "2026-07-24T10:00:00+08:00",
    )
    collector.collect_period(*args)
    original = next(tmp_path.rglob("balance.html")).read_bytes()
    bodies["ajax_t164sb03"] = html("資產負債表", "999")

    with pytest.raises(ArtifactConflictError):
        collector.collect_period(*args)

    assert next(tmp_path.rglob("balance.html")).read_bytes() == original
