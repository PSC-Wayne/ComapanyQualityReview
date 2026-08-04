from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from company_quality.sources.tpex_f000 import (
    CURRENT_F000_URL,
    F000SourceError,
    SnapshotCapture,
    build_historical_pit,
    materialize_f000,
    parse_f000_snapshot,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "tpex_f000_snapshot.html"
BODY = FIXTURE.read_bytes()
ISSUERS = {"2388": "issuer-2388", "8096": "issuer-8096"}


def _capture(timestamp: str, marker: bytes = b"") -> SnapshotCapture:
    compact = timestamp.replace("-", "").replace(":", "").replace("T", "")[:14]
    return SnapshotCapture(
        snapshot_at=datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc),
        source_url=CURRENT_F000_URL,
        replay_url=(
            f"https://web.archive.org/web/{compact}id_/"
            "https://ic.tpex.org.tw/introduce.php?ic=F000"
        ),
        body=BODY.replace(b"</body>", marker + b"</body>"),
    )


def test_parser_extracts_stable_nodes_domestic_memberships_and_identity() -> None:
    parsed = parse_f000_snapshot(
        BODY,
        snapshot_at="2026-08-04T03:12:18+00:00",
        source_url=CURRENT_F000_URL,
        replay_url=None,
        issuer_by_security_code=ISSUERS,
    )

    assert [(row.stage, row.node_code, row.node_name) for row in parsed.nodes] == [
        ("上游", "F100", "中央處理器"),
        ("上游", "F200", "晶片組"),
        ("下游", "FI00", "筆記型電腦"),
    ]
    assert len(parsed.memberships) == 6  # exact duplicate removed; unlisted foreign row excluded
    listed = next(row for row in parsed.memberships if row.security_code == "2388")
    assert listed.security_market == "TWSE"
    assert listed.issuer_origin == "domestic"
    assert listed.issuer_id == "issuer-2388"
    assert listed.identity_status == "resolved"
    emerging = next(row for row in parsed.memberships if row.security_code == "6999")
    assert emerging.security_market == "Emerging"
    assert emerging.issuer_id is None
    assert emerging.identity_status == "unresolved"
    foreign_listed = next(row for row in parsed.memberships if row.security_code == "6526")
    assert foreign_listed.security_market == "TWSE"
    assert foreign_listed.issuer_origin == "foreign"
    assert parsed.report["deduplicated_membership_count"] == 6
    assert parsed.report["unique_security_count"] == 4
    assert parsed.report["resolved_unique_security_count"] == 2
    assert parsed.report["issuer_coverage"] == pytest.approx(2 / 4)
    assert parsed.report["exclusion_counts"] == {"unlisted_foreign_company": 1}
    assert parsed.report["market_is_not_route_key"] is True


def test_historical_pit_uses_latest_pre_decision_snapshot_and_never_current_fill() -> None:
    captures = [
        _capture("2020-06-01T00:00:00"),
        _capture("2021-06-19T00:23:56"),
        _capture("2023-01-01T00:00:00"),
    ]
    result = build_historical_pit(
        decision_dates=["2019-06-30", "2021-06-30", "2022-06-30"],
        captures=captures,
        issuer_by_security_code=ISSUERS,
    )

    mappings = {row.decision_date: row for row in result.decisions}
    assert mappings["2019-06-30"].status == "NO_PRE_DECISION_SNAPSHOT"
    assert mappings["2021-06-30"].snapshot_at == "2021-06-19T00:23:56+00:00"
    assert mappings["2021-06-30"].status == "AVAILABLE"
    assert mappings["2022-06-30"].snapshot_at == "2021-06-19T00:23:56+00:00"
    assert mappings["2022-06-30"].snapshot_age_days == 376
    assert mappings["2022-06-30"].status == "STALE_AUDIT_ONLY"
    assert all(row.decision_date != "2019-06-30" for row in result.memberships)
    assert result.report["missing_decision_dates"] == ["2019-06-30"]
    assert result.report["stale_audit_only_decision_dates"] == ["2022-06-30"]
    assert result.report["current_fill_used"] is False
    assert result.report["fresh_membership_count"] == 6
    assert result.report["audit_only_membership_count"] == 6


def test_rejects_post_decision_replay_and_non_official_authority() -> None:
    with pytest.raises(F000SourceError, match="official TPEx F000"):
        parse_f000_snapshot(
            BODY,
            snapshot_at="2021-01-01T00:00:00+00:00",
            source_url="https://example.com/introduce.php?ic=F000",
            replay_url=None,
        )
    bad = _capture("2021-07-01T00:00:00")
    result = build_historical_pit(decision_dates=["2021-06-30"], captures=[bad])
    assert result.decisions[0].status == "NO_PRE_DECISION_SNAPSHOT"


def test_materialization_is_deterministic_atomic_and_reports_coverage(tmp_path) -> None:
    current = parse_f000_snapshot(
        BODY,
        snapshot_at="2026-08-04T03:12:18+00:00",
        source_url=CURRENT_F000_URL,
        replay_url=None,
        issuer_by_security_code=ISSUERS,
    )
    historical = build_historical_pit(
        decision_dates=["2021-06-30", "2022-06-30"],
        captures=[_capture("2021-06-19T00:23:56")],
        issuer_by_security_code=ISSUERS,
    )
    output = tmp_path / "f000.json"

    first = materialize_f000(output, current=current, historical=historical)
    first_bytes = output.read_bytes()
    second = materialize_f000(output, current=current, historical=historical)

    assert first == second
    assert output.read_bytes() == first_bytes
    payload = json.loads(first_bytes)
    assert payload["schema_version"] == "TPExF000Materialization.v1"
    assert payload["current"]["report"]["source_kind"] == "current_official_page"
    assert payload["historical"]["report"]["historical_source"] == (
        "Wayback replay of official TPEx pages"
    )
    assert not list(tmp_path.glob("*.tmp"))
