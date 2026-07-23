from dataclasses import FrozenInstanceError, replace

import pytest

from company_quality.runtime import (
    GoldenPathQuery,
    run_golden_path,
    validate_same_generation,
)


@pytest.mark.parametrize(
    ("identifier", "market", "decision_time", "error_code"),
    [
        ("ACME", None, "2026-07-23T14:30:00+08:00", "identity_ambiguous"),
        ("2330", "TWSE", "2026-07-23T14:30:00", "invalid_decision_time"),
        ("2330", "NYSE", "2026-07-23T14:30:00+08:00", "unsupported_scope"),
        ("UNKNOWN", "TWSE", "2026-07-23T14:30:00+08:00", "unsupported_scope"),
    ],
)
def test_controlled_failures_do_not_create_snapshot_or_report(
    identifier: str, market: str | None, decision_time: str, error_code: str
) -> None:
    result = run_golden_path(GoldenPathQuery(identifier, market, decision_time))

    assert result.error_code == error_code
    assert result.failure_reason
    assert result.generation_id is None
    assert result.snapshot_hash is None
    assert result.report_hash is None
    assert result.snapshot is None
    assert result.report is None


@pytest.mark.parametrize(
    "decision_time",
    ["20260723T143000+08:00", "2026-W30-4T14:30:00+08:00", "2026-07-23"],
)
def test_non_rfc3339_times_fail_closed(decision_time: str) -> None:
    result = run_golden_path(GoldenPathQuery("2330", "TWSE", decision_time))
    assert result.error_code == "invalid_decision_time"
    assert result.snapshot is None and result.report is None


def test_rerun_is_semantically_deterministic_and_same_generation() -> None:
    query = GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00")
    first = run_golden_path(query)
    second = run_golden_path(query)

    assert first.contract_dict() == second.contract_dict()
    assert first.snapshot == second.snapshot
    assert first.report == second.report
    assert first.snapshot_hash == second.snapshot_hash
    assert first.report_hash == second.report_hash


def test_same_generation_validator_detects_actual_seam_mismatches() -> None:
    result = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00")
    )
    assert result.snapshot is not None and result.report is not None
    assert validate_same_generation(result.snapshot, result.report, result.report_hash) is None
    assert validate_same_generation(
        result.snapshot,
        replace(result.report, generation_id="00000000-0000-0000-0000-000000000000"),
        result.report_hash,
    ) == "generation_mismatch"
    assert validate_same_generation(result.snapshot, result.report, "0" * 64) == "blocked_contract"


def test_snapshot_and_nested_sections_are_immutable() -> None:
    result = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00")
    )
    assert result.snapshot is not None and result.report is not None
    with pytest.raises(FrozenInstanceError):
        result.snapshot.generation_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.snapshot.sections["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        result.report.content["changed"] = True  # type: ignore[index]
