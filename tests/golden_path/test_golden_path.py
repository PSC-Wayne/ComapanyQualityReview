from company_quality.runtime import GoldenPathQuery, run_golden_path

CANDIDATE_SHA = "1" * 40


def test_controlled_fixture_resolves_identity_into_snapshot_and_report() -> None:
    result = run_golden_path(
        GoldenPathQuery(
            identifier="2330",
            market="TWSE",
            decision_time="2026-07-23T14:30:00+08:00",
        ),
        producer_candidate_sha=CANDIDATE_SHA,
    )

    assert result.error_code is None
    assert result.failure_reason is None
    assert result.snapshot.identity.canonical_identifier == "TWSE:2330"
    assert result.snapshot.generation_id == result.generation_id
    assert result.report.generation_id == result.generation_id
    assert result.snapshot.decision_time == result.report.decision_time
    assert result.producer_candidate_sha == CANDIDATE_SHA
    assert result.snapshot.producer_candidate_sha == CANDIDATE_SHA
    assert result.report.producer_candidate_sha == CANDIDATE_SHA
    assert result.report.complete is True
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"
