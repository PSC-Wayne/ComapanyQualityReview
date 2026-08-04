from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from company_quality.sources.tpex_value_chain import (
    INDEX_URL,
    ArchiveCaptureIndex,
    collect_current_value_chains,
    discover_archive_capture_index,
    discover_chains,
    materialize_value_chains,
    produce_archive_availability_matrix,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
INDEX = (FIXTURES / "tpex_value_chain_index.html").read_bytes()
F000 = (FIXTURES / "tpex_f000_snapshot.html").read_bytes()
D000 = (FIXTURES / "tpex_d000_snapshot.html").read_bytes()


class FixtureTransport:
    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    def get(self, url: str) -> bytes:
        self.requested.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_official_index_discovers_and_deduplicates_chain_codes_and_names() -> None:
    chains = discover_chains(INDEX, source_url=INDEX_URL)

    assert [(row.chain_code, row.chain_name) for row in chains] == [
        ("F000", "電腦週邊"),
        ("D000", "半導體"),
    ]
    assert all(row.source_url == INDEX_URL for row in chains)
    assert chains[0].page_url == "https://ic.tpex.org.tw/introduce.php?ic=F000"


def test_collects_every_parseable_chain_and_reports_parser_exceptions() -> None:
    d_url = "https://ic.tpex.org.tw/introduce.php?ic=D000"
    f_url = "https://ic.tpex.org.tw/introduce.php?ic=F000"
    transport = FixtureTransport({INDEX_URL: INDEX, f_url: F000, d_url: D000})

    result = collect_current_value_chains(
        retrieved_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        transport=transport,
        issuer_by_security_code={"2330": "issuer-2330", "2388": "issuer-2388"},
    )

    assert [row.chain_code for row in result.chains] == ["F000", "D000"]
    assert {(row.chain_code, row.node_code) for row in result.nodes} >= {
        ("F000", "F100"), ("D000", "D000"), ("D000", "D100"), ("D000", "D200")
    }
    d_stages = {row.node_code: row.stage for row in result.nodes if row.chain_code == "D000"}
    assert d_stages == {"D000": "未分層", "D100": "上游", "D200": "核心技術"}
    # The same security belongs to zero-to-many nodes; market is identity, not taxonomy.
    tsmc = [row for row in result.memberships if row.security_code == "2330"]
    assert [(row.node_code, row.security_market) for row in tsmc] == [
        ("D100", "TWSE"), ("D200", "TWSE")
    ]
    assert result.report["discovered_chain_count"] == 2
    assert result.report["parsed_chain_count"] == 2
    assert result.report["parser_exceptions"] == []
    assert result.report["market_is_not_route_key"] is True

    broken = FixtureTransport({INDEX_URL: INDEX, f_url: F000, d_url: b"not a chain"})
    partial = collect_current_value_chains(
        retrieved_at=datetime(2026, 8, 4, tzinfo=timezone.utc), transport=broken
    )
    assert partial.report["parsed_chain_count"] == 1
    assert partial.report["parser_exception_count"] == 1
    assert partial.report["parser_exceptions"] == [{
        "chain_code": "D000",
        "chain_name": "半導體",
        "error_type": "F000SourceError",
        "message": "official TPEx D000 chain heading is missing",
    }]


def test_archive_matrix_is_explicit_and_never_current_fills_history() -> None:
    chains = discover_chains(INDEX, source_url=INDEX_URL)
    matrix = produce_archive_availability_matrix(
        chains=chains,
        decision_dates=["2019-06-30", "2022-06-30", "2024-06-30", "2026-08-04"],
        captures=[
            ArchiveCaptureIndex("F000", datetime(2021, 6, 19, tzinfo=timezone.utc), "https://web.archive.org/web/20210619000000id_/https://ic.tpex.org.tw/introduce.php?ic=F000"),
            ArchiveCaptureIndex("F000", datetime(2024, 6, 1, tzinfo=timezone.utc), "https://web.archive.org/web/20240601000000id_/https://ic.tpex.org.tw/introduce.php?ic=F000"),
        ],
        current_snapshot_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    by_key = {(row.chain_code, row.decision_date): row for row in matrix.rows}

    assert by_key["F000", "2019-06-30"].state == "UNAVAILABLE"
    assert by_key["F000", "2022-06-30"].state == "STALE"
    assert by_key["F000", "2024-06-30"].state == "FRESH_PIT"
    assert by_key["F000", "2024-06-30"].historical_membership_allowed is True
    assert by_key["D000", "2024-06-30"].state == "UNAVAILABLE"
    assert by_key["D000", "2026-08-04"].state == "CURRENT_ONLY"
    assert by_key["D000", "2026-08-04"].historical_membership_allowed is False
    assert matrix.report["current_fill_used"] is False
    assert matrix.report["state_counts"] == {
        "CURRENT_ONLY": 2, "FRESH_PIT": 1, "STALE": 1, "UNAVAILABLE": 4
    }


def test_archive_discovery_is_per_chain_deduplicated_and_reports_failures() -> None:
    chains = discover_chains(INDEX, source_url=INDEX_URL)
    prefix = "https://web.archive.org/cdx/search/cdx?url="
    suffix = (
        "&output=json&filter=statuscode:200&filter=mimetype:text/html"
        "&fl=timestamp,original&collapse=digest"
    )
    f_url = chains[0].page_url
    d_url = chains[1].page_url
    archived_f_url = "http://ic.tpex.org.tw:80/introduce.php?ic=F000"
    transport = FixtureTransport({
        prefix + quote(f_url, safe="") + suffix: json.dumps([
            ["timestamp", "original"],
            ["20210619002356", archived_f_url],
            ["20210619002356", archived_f_url],
        ]).encode(),
        prefix + quote(d_url, safe="") + suffix: TimeoutError("fixture timeout"),
    })

    result = discover_archive_capture_index(chains=chains, transport=transport)

    assert [(row.chain_code, row.snapshot_at.isoformat()) for row in result.captures] == [
        ("F000", "2021-06-19T00:23:56+00:00")
    ]
    assert result.captures[0].replay_url.endswith(archived_f_url)
    assert result.report["capture_count"] == 1
    assert result.report["exception_count"] == 1
    assert result.report["exceptions"] == [{
        "chain_code": "D000", "chain_name": "半導體",
        "error_type": "TimeoutError", "message": "fixture timeout",
    }]


def test_general_materialization_is_deterministic_and_contains_archive_gate(tmp_path) -> None:
    d_url = "https://ic.tpex.org.tw/introduce.php?ic=D000"
    f_url = "https://ic.tpex.org.tw/introduce.php?ic=F000"
    current = collect_current_value_chains(
        retrieved_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        transport=FixtureTransport({INDEX_URL: INDEX, f_url: F000, d_url: D000}),
    )
    matrix = produce_archive_availability_matrix(
        chains=current.chains,
        decision_dates=["2024-06-30"],
        captures=[],
        current_snapshot_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )
    output = tmp_path / "chains.json"

    first = materialize_value_chains(output, current=current, archive_availability=matrix)
    first_bytes = output.read_bytes()
    second = materialize_value_chains(output, current=current, archive_availability=matrix)

    assert first == second
    assert output.read_bytes() == first_bytes
    payload = json.loads(first_bytes)
    assert payload["schema_version"] == "TPExValueChainMaterialization.v1"
    assert payload["archive_availability"]["report"]["current_fill_used"] is False
    assert not list(tmp_path.glob("*.tmp"))
