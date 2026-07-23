import json
from copy import deepcopy
from pathlib import Path

from tools.validate_json import main

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "docs/governance/calibration-freeze/schemas"
SHA = "a" * 64


def thresholds() -> dict[str, object]:
    return {
        "quality_bands": [20, 40, 60, 80],
        "upside_stars": [0, 1, 2, 3],
        "downside_faces": [10, 20, 30, 40],
        "bomb_materiality": 0.5,
    }


def pillar_weights() -> dict[str, float | int]:
    return {
        "audit_reliability": 0.1,
        "earnings_capital_efficiency": 0.25,
        "cash_balance_allocation": 0.25,
        "business_moat": 0.25,
        "governance": 0.05,
        "people_adaptability": 0.1,
        "sum": 1,
    }


def downside_weights() -> dict[str, float | int]:
    return {
        "maximum_drawdown_vulnerability": 0.3,
        "permanent_capital_loss_vulnerability": 0.3,
        "material_adverse_event_vulnerability": 0.4,
        "sum": 1,
    }


def package() -> dict[str, object]:
    return {
        "decision_package_id": "freeze-001",
        "active_binding_generation": 1,
        "eligibility_generation": 1,
        "validation_report_sha256": SHA,
        "candidate_policy_sha256": SHA,
        "ticket_set_digest": SHA,
        "frozen_spec_sha256": SHA,
        "decision_map_sha256": SHA,
        "delivery_plan_sha256": SHA,
        "candidate_ranges": thresholds(),
        "pillar_weights": pillar_weights(),
        "downside_component_weights": downside_weights(),
        "anti_double_count_policy_version": "1.0.0",
        "evidence_family_policy_scope": "quality_and_downside",
        "evidence_family_policy_locator": "AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership",
        "evidence_family_policy_canonicalization": "RFC8785_JCS",
        "evidence_family_policy_sha256": SHA,
        "metrics": {"auc": 0.8, "brier": None, "calibration_error": 0.1},
        "calibration_curves": [
            {"bucket": "low", "predicted": 0.2, "observed": 0.25, "count": 12}
        ],
        "leakage_checks": {
            "pit_join_pass": True,
            "purge_pass": True,
            "embargo_pass": True,
            "survivorship_pass": True,
        },
        "evidence_package_coverage": 1.0,
        "rating_disposition": "NO_RATING_NOT_APPLICABLE",
        "review_deadline_at": "2026-07-24T06:00:00+08:00",
    }


def manifest(decision: str = "hold") -> dict[str, object]:
    approved = decision == "approve"
    return {
        "decision_id": "decision-001",
        "evidence_package_sha256": SHA,
        "validation_report_sha256": SHA,
        "approved_policy_version": "1.0.0" if approved else None,
        "approved_thresholds": thresholds() if approved else None,
        "decision": decision,
        "decided_by": "Wayne",
        "decided_at": "2026-07-24T05:00:00+08:00",
        "independent_review_ack": (
            f"EVIDENCE:PASS:{SHA};SEMANTICS:PASS:{SHA};WAYNE:APPROVE:{SHA}"
            if approved
            else "reviews pending"
        ),
        "pillar_weights": pillar_weights(),
        "downside_component_weights": downside_weights(),
        "anti_double_count_policy_version": "1.0.0",
        "evidence_family_policy_scope": "quality_and_downside",
        "evidence_family_policy_locator": "AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership",
        "evidence_family_policy_canonicalization": "RFC8785_JCS",
        "evidence_family_policy_sha256": SHA,
        "expiry": None,
        "evidence_package_coverage": 1.0,
        "rating_disposition": "NO_RATING_NOT_APPLICABLE",
    }


def validate(tmp_path: Path, schema_name: str, instance: dict[str, object]) -> int:
    instance_path = tmp_path / "fixture.json"
    instance_path.write_text(json.dumps(instance), encoding="utf-8")
    return main(["--schema", str(SCHEMA_DIR / schema_name), "--input", str(instance_path)])


def test_valid_and_invalid_calibration_package_fixtures(tmp_path: Path) -> None:
    assert validate(tmp_path, "CalibrationFreezePackage.v1.json", package()) == 0

    invalid = deepcopy(package())
    invalid.pop("validation_report_sha256")
    assert validate(tmp_path, "CalibrationFreezePackage.v1.json", invalid) != 0

    unsorted = deepcopy(package())
    unsorted["candidate_ranges"]["quality_bands"] = [40, 20]  # type: ignore[index]
    assert validate(tmp_path, "CalibrationFreezePackage.v1.json", unsorted) != 0

    false_total = deepcopy(package())
    false_total["downside_component_weights"] = {
        "maximum_drawdown_vulnerability": 0.25,
        "permanent_capital_loss_vulnerability": 0.25,
        "material_adverse_event_vulnerability": 0.25,
        "sum": 1,
    }
    assert validate(tmp_path, "CalibrationFreezePackage.v1.json", false_total) != 0

    tiny_difference = deepcopy(package())
    tiny_difference["downside_component_weights"] = {
        "maximum_drawdown_vulnerability": 0.3,
        "permanent_capital_loss_vulnerability": 0.3,
        "material_adverse_event_vulnerability": 0.3999999999995,
        "sum": 1,
    }
    assert validate(tmp_path, "CalibrationFreezePackage.v1.json", tiny_difference) != 0


def test_validator_rejects_non_json_numbers_and_duplicate_thresholds(tmp_path: Path) -> None:
    duplicate = deepcopy(package())
    duplicate["candidate_ranges"]["quality_bands"] = [20, 20]  # type: ignore[index]
    assert validate(tmp_path, "CalibrationFreezePackage.v1.json", duplicate) != 0

    raw = tmp_path / "nan.json"
    raw.write_text(json.dumps(package()).replace('"auc": 0.8', '"auc": NaN'), encoding="utf-8")
    assert main([
        "--schema", str(SCHEMA_DIR / "CalibrationFreezePackage.v1.json"),
        "--input", str(raw),
    ]) != 0


def test_hold_manifest_requires_explicit_null_approval_fields(tmp_path: Path) -> None:
    assert validate(tmp_path, "CalibrationFreezeManifest.v1.json", manifest("hold")) == 0

    invalid = manifest("hold")
    invalid["approved_policy_version"] = "1.0.0"
    assert validate(tmp_path, "CalibrationFreezeManifest.v1.json", invalid) != 0


def test_conditional_approve_requires_thresholds_and_both_passes(tmp_path: Path) -> None:
    assert validate(tmp_path, "CalibrationFreezeManifest.v1.json", manifest("approve")) == 0

    missing_thresholds = manifest("approve")
    missing_thresholds["approved_thresholds"] = None
    assert validate(tmp_path, "CalibrationFreezeManifest.v1.json", missing_thresholds) != 0

    missing_review = manifest("approve")
    missing_review["independent_review_ack"] = f"EVIDENCE:PASS:{SHA}"
    assert validate(tmp_path, "CalibrationFreezeManifest.v1.json", missing_review) != 0

    mismatched_package = manifest("approve")
    mismatched_package["independent_review_ack"] = (
        f"EVIDENCE:PASS:{'b' * 64};SEMANTICS:PASS:{SHA};WAYNE:APPROVE:{SHA}"
    )
    assert validate(tmp_path, "CalibrationFreezeManifest.v1.json", mismatched_package) != 0

    false_total = manifest("approve")
    false_total["downside_component_weights"] = {
        "maximum_drawdown_vulnerability": 0.25,
        "permanent_capital_loss_vulnerability": 0.25,
        "material_adverse_event_vulnerability": 0.25,
        "sum": 1,
    }
    assert validate(tmp_path, "CalibrationFreezeManifest.v1.json", false_total) != 0
