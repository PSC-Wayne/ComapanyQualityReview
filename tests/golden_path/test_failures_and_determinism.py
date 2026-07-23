from dataclasses import FrozenInstanceError

import pytest

from company_quality.runtime import GoldenPathQuery, run_golden_path

CANDIDATE_SHA = "1" * 40


@pytest.mark.parametrize(
    ("identifier", "market", "decision_time", "error_code"),
    [
        ("ACME", None, "2026-07-23T14:30:00+08:00", "identity_ambiguous"),
        ("2330", "TWSE", "2026-07-23T14:30:00", "invalid_decision_time"),
        ("2330", "NYSE", "2026-07-23T14:30:00+08:00", "unsupported_scope"),
        ("BLOCKED", "TWSE", "2026-07-23T14:30:00+08:00", "blocked_contract"),
        ("MISMATCH", "TWSE", "2026-07-23T14:30:00+08:00", "generation_mismatch"),
    ],
)
def test_controlled_failures_are_explicit(
    identifier: str, market: str | None, decision_time: str, error_code: str
) -> None:
    result = run_golden_path(
        GoldenPathQuery(identifier, market, decision_time),
        producer_candidate_sha=CANDIDATE_SHA,
    )

    assert result.error_code == error_code
    assert result.failure_reason
    assert result.report.complete is True
    assert result.report.generation_id == result.snapshot.generation_id


def test_rerun_is_semantically_deterministic_and_same_generation() -> None:
    query = GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00")
    first = run_golden_path(query, producer_candidate_sha=CANDIDATE_SHA)
    second = run_golden_path(query, producer_candidate_sha=CANDIDATE_SHA)

    assert first.contract_dict() == second.contract_dict()
    assert first.snapshot == second.snapshot
    assert first.report == second.report
    assert first.snapshot_hash == second.snapshot_hash
    assert first.report_hash == second.report_hash
    assert first.snapshot.manifest_version == first.report.manifest_version
    assert first.snapshot.model_version == first.report.model_version
    assert first.snapshot.decision_time == first.report.decision_time


def test_producer_candidate_changes_generation() -> None:
    query = GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00")

    first = run_golden_path(query, producer_candidate_sha="1" * 40)
    second = run_golden_path(query, producer_candidate_sha="2" * 40)

    assert first.generation_id != second.generation_id
    assert first.snapshot_hash != second.snapshot_hash
    assert first.report_hash != second.report_hash


def test_missing_producer_candidate_blocks_contract() -> None:
    result = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00"),
        producer_candidate_sha=None,
    )

    assert result.error_code == "blocked_contract"
    assert result.failure_reason == (
        "producer_candidate_sha must be a full 40-character lowercase Git SHA"
    )
    assert result.producer_candidate_sha == "0" * 40
    assert result.snapshot.producer_candidate_sha == result.report.producer_candidate_sha


def test_snapshot_and_nested_sections_are_immutable() -> None:
    result = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00"),
        producer_candidate_sha=CANDIDATE_SHA,
    )

    with pytest.raises(FrozenInstanceError):
        result.snapshot.generation_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.snapshot.sections["changed"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        result.report.content["changed"] = True  # type: ignore[index]
