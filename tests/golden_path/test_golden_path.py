from company_quality.runtime import GoldenPathQuery, run_golden_path


def test_controlled_fixture_resolves_identity_into_snapshot_and_report() -> None:
    result = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T06:30:00Z")
    )

    assert result.error_code is None
    assert result.failure_reason is None
    assert result.snapshot is not None
    assert result.report is not None
    assert result.snapshot.identity.canonical_identifier == "TWSE:2330"
    assert result.snapshot.generation_id == result.report.generation_id == result.generation_id
    assert result.query.decision_time == "2026-07-23T14:30:00+08:00"
    assert result.snapshot.decision_time == result.report.decision_time == result.query.decision_time
    assert result.report.complete is True
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"
    assert result.snapshot.sections["golden_path"]["status"] == "complete"
