import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from company_quality.runtime import GoldenPathQuery, run_golden_path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "src/company_quality/runtime/contracts/GoldenPathResult.schema.json").read_text()
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
CANDIDATE_SHA = "1" * 40


def test_success_envelope_validates_against_contract() -> None:
    result = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00"),
        producer_candidate_sha=CANDIDATE_SHA,
    )
    VALIDATOR.validate(result.contract_dict())


def test_contract_rejects_undeclared_fields() -> None:
    envelope = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00"),
        producer_candidate_sha=CANDIDATE_SHA,
    ).contract_dict()
    envelope["rating"] = 5

    errors = list(VALIDATOR.iter_errors(envelope))
    assert any("Additional properties" in error.message for error in errors)


def test_contract_rejects_naive_decision_time_and_implicit_nullable_fields() -> None:
    envelope = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00"),
        producer_candidate_sha=CANDIDATE_SHA,
    ).contract_dict()
    envelope["query"]["decision_time"] = "2026-07-23T14:30:00"
    envelope.pop("failure_reason")

    errors = list(VALIDATOR.iter_errors(envelope))
    assert len(errors) >= 2


def test_failure_envelopes_still_validate_against_contract() -> None:
    cases = [
        (GoldenPathQuery("2330", "NYSE", "2026-07-23T14:30:00+08:00"), CANDIDATE_SHA),
        (GoldenPathQuery("", "TWSE", "2026-07-23T14:30:00+08:00"), CANDIDATE_SHA),
        (GoldenPathQuery("2330", "TWSE", "not-a-time"), CANDIDATE_SHA),
        (GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00"), None),
    ]

    for query, candidate_sha in cases:
        result = run_golden_path(query, producer_candidate_sha=candidate_sha)
        assert result.error_code is not None
        VALIDATOR.validate(result.contract_dict())
