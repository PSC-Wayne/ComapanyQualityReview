from company_quality.pit import FactCandidate, admit_facts


def fact(
    *,
    version_id: str = "v1",
    value: str = "100",
    available_at: str = "2026-07-23",
    valid_from: str = "2026-07-24T00:00:00+08:00",
    valid_to: str | None = None,
    authority_rank: int = 1,
    append_sequence: int = 1,
) -> FactCandidate:
    return FactCandidate(
        fact_id="TWSE:2330:official_close:2026-07-23",
        fact_type="official_close_price",
        value=value,
        unit="TWD",
        effective_at="2026-07-23T13:30:00+08:00",
        announced_at=None,
        available_at=available_at,
        retrieved_at="2026-07-24T00:05:00+08:00",
        valid_from=valid_from,
        valid_to=valid_to,
        authority_rank=authority_rank,
        append_sequence=append_sequence,
        version_id=version_id,
        source_id=f"official:{version_id}",
    )


def test_date_only_source_admits_at_next_taipei_midnight() -> None:
    before = admit_facts((fact(),), "2026-07-23T23:59:59+08:00")
    boundary = admit_facts((fact(),), "2026-07-24T00:00:00+08:00")
    after = admit_facts((fact(),), "2026-07-24T00:00:01+08:00")

    assert before.facts[0].disposition == "blocked_unavailable"
    assert boundary.facts[0].disposition == "admitted"
    assert after.facts[0].disposition == "admitted"
    assert boundary.facts[0].available_at == "2026-07-24T00:00:00+08:00"


def test_final_bar_is_blocked_before_exact_official_availability() -> None:
    candidate = fact(
        available_at="2026-07-23T14:15:00+08:00",
        valid_from="2026-07-23T14:15:00+08:00",
    )

    result = admit_facts((candidate,), "2026-07-23T14:14:59+08:00")

    assert result.facts[0].disposition == "blocked_unavailable"
    assert result.facts[0].failure_reason == "not_yet_available"


def test_same_rank_authority_conflict_does_not_choose_a_convenient_version() -> None:
    first = fact(version_id="official-a", value="100")
    second = fact(version_id="official-b", value="101", append_sequence=2)

    result = admit_facts((first, second), "2026-07-24T12:00:00+08:00")

    assert result.facts[0].disposition == "blocked_conflict"
    assert result.facts[0].value is None
    assert result.facts[0].failure_reason == "unresolved_same_rank_conflict"


def test_revision_intervals_are_half_open_and_append_only() -> None:
    first = fact(
        version_id="v1",
        value="100",
        valid_to="2026-07-25T00:00:00+08:00",
        append_sequence=1,
    )
    corrected = fact(
        version_id="v2",
        value="102",
        available_at="2026-07-25T00:00:00+08:00",
        valid_from="2026-07-25T00:00:00+08:00",
        append_sequence=2,
    )

    before = admit_facts((first, corrected), "2026-07-24T23:59:59+08:00")
    boundary = admit_facts((first, corrected), "2026-07-25T00:00:00+08:00")

    assert before.facts[0].version_id == "v1"
    assert before.facts[0].value == "100"
    assert boundary.facts[0].version_id == "v2"
    assert boundary.facts[0].value == "102"


def test_lower_authority_is_not_used_when_top_authority_is_unavailable() -> None:
    top = fact(
        version_id="official",
        available_at="2026-07-25T00:00:00+08:00",
        valid_from="2026-07-25T00:00:00+08:00",
        authority_rank=1,
    )
    lower = fact(version_id="vendor", authority_rank=2)

    result = admit_facts((top, lower), "2026-07-24T12:00:00+08:00")

    assert result.facts[0].disposition == "blocked_unavailable"
    assert result.facts[0].version_id == "official"


def test_same_decision_time_is_deterministic() -> None:
    candidates = (fact(),)
    first = admit_facts(candidates, "2026-07-24T12:00:00+08:00")
    second = admit_facts(candidates, "2026-07-24T12:00:00+08:00")

    assert first == second
    assert first.schema_version == "AdmittedFactSet.v1"
    assert first.rating_disposition == "NO_RATING_NOT_APPLICABLE"
