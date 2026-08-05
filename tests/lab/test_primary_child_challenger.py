from __future__ import annotations

from copy import deepcopy

import pytest

from company_quality.lab.primary_child_challenger import (
    PrimaryChildDispositionError,
    build_zero_sample_disposition,
)


def payload(code: str, status: str = "missing_evidence") -> dict[str, object]:
    return {
        "current_fill_used": False,
        "fallback_used": False,
        "pooling_used": False,
        "final_oos_read": False,
        "observations": [
            {
                "issuer_id": f"issuer-{code}",
                "security_code": code,
                "decision_date": "2019-06-30",
                "status": status,
                "model_excluded": status != "attributed",
            }
        ],
    }


def test_builds_fail_closed_zero_sample_disposition() -> None:
    result = build_zero_sample_disposition(
        [payload("3001"), payload("3002", "source_unavailable")],
        input_artifacts=["a.json", "b.json"],
    )

    assert result["status"] == "industry_sample_insufficient"
    assert result["publication_status"] == "research_only"
    assert result["attempted_count"] == 2
    assert result["admitted_training_count"] == 0
    assert result["competition_run"] is False
    assert result["champion"] is None
    assert result["stars"] is None
    assert result["frozen_candidate"] is None
    assert result["final_oos_read"] is False
    assert all(value == "not_run_sample_insufficient" for value in result["gate_results"].values())


def test_rejects_duplicate_observations_across_batches() -> None:
    item = payload("3001")
    with pytest.raises(PrimaryChildDispositionError, match="unique"):
        build_zero_sample_disposition([item, deepcopy(item)], input_artifacts=["a", "b"])


def test_rejects_attributed_samples_instead_of_skipping_real_competition() -> None:
    with pytest.raises(PrimaryChildDispositionError, match="real pre-OOS competition"):
        build_zero_sample_disposition([payload("3001", "attributed")], input_artifacts=["a"])


def test_rejects_fallback_tainted_inputs() -> None:
    item = payload("3001")
    item["fallback_used"] = True
    with pytest.raises(PrimaryChildDispositionError, match="no-fallback"):
        build_zero_sample_disposition([item], input_artifacts=["a"])
