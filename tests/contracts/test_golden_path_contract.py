import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from company_quality.runtime import GoldenPathQuery, run_golden_path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "src/company_quality/runtime/contracts/GoldenPathResult.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
CANDIDATE_SHA = "1" * 40


def test_success_and_failure_envelopes_validate() -> None:
    cases = [
        (GoldenPathQuery("2330", "TWSE", "2026-07-23T06:30:00Z"), CANDIDATE_SHA),
        (GoldenPathQuery("ACME", None, "2026-07-23T14:30:00+08:00"), CANDIDATE_SHA),
        (GoldenPathQuery("2330", "NYSE", "2026-07-23T14:30:00+08:00"), CANDIDATE_SHA),
        (GoldenPathQuery("2330", "TWSE", "not-a-time"), CANDIDATE_SHA),
        (GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00"), None),
    ]
    for query, candidate_sha in cases:
        result = run_golden_path(query, producer_candidate_sha=candidate_sha)
        VALIDATOR.validate(result.contract_dict())
        assert set(result.contract_dict()["foundation_artifacts"]) == {
            "admission_scan_path",
            "validate_json_path",
            "freeze_package_schema_path",
            "freeze_manifest_schema_path",
        }


def test_contract_rejects_undeclared_fields() -> None:
    envelope = run_golden_path(
        GoldenPathQuery("2330", "TWSE", "2026-07-23T14:30:00+08:00"),
        producer_candidate_sha=CANDIDATE_SHA,
    ).contract_dict()
    envelope["rating"] = 5
    assert any("Additional properties" in error.message for error in VALIDATOR.iter_errors(envelope))


def test_contract_requires_null_artifact_fields_on_failure() -> None:
    envelope = run_golden_path(
        GoldenPathQuery("ACME", None, "2026-07-23T14:30:00+08:00"),
        producer_candidate_sha=CANDIDATE_SHA,
    ).contract_dict()
    envelope["snapshot_hash"] = "0" * 64
    assert list(VALIDATOR.iter_errors(envelope))
