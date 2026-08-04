from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from company_quality.industry.primary_business import (
    PrimaryBusinessEvidenceError,
    validate_primary_business_pilot,
)


ARTIFACT = (
    Path(__file__).parents[2]
    / "artifacts"
    / "real_data"
    / "tpex-f000-primary-business-pilot.json"
)


def _payload() -> dict[str, object]:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_official_pit_primary_business_pilot_is_bounded_and_evidence_backed() -> None:
    payload = _payload()
    summary = validate_primary_business_pilot(payload)

    assert summary == {
        "observation_count": 8,
        "attributed_count": 7,
        "ambiguous_count": 1,
        "missing_evidence_count": 0,
        "attributed_coverage": 0.875,
        "market_count": 2,
        "primary_node_count": 7,
        "scale_recommendation": "CONDITIONAL_SCALE_WITH_EXCLUSION",
    }
    rows = payload["observations"]
    assert isinstance(rows, list)
    attributed_nodes = {
        row["primary_child"]["node_code"]
        for row in rows
        if row["status"] == "attributed"
    }
    assert {"FM00", "FK00", "F600", "F800", "FB00", "FG00", "F500"} <= attributed_nodes
    assert {row["market"] for row in rows} == {"TWSE", "TPEx"}
    assert next(row for row in rows if row["security_code"] == "2376")["status"] == "ambiguous"
    assert payload["current_backfill_used"] is False


def test_ambiguous_observation_cannot_claim_a_primary_child() -> None:
    payload = deepcopy(_payload())
    rows = payload["observations"]
    assert isinstance(rows, list)
    ambiguous = next(row for row in rows if row["security_code"] == "2376")
    ambiguous["primary_child"] = {"node_code": "FM00", "node_name": "伺服器"}
    ambiguous["reported_revenue_share_pct"] = 64.27

    with pytest.raises(PrimaryBusinessEvidenceError, match="ambiguous/missing"):
        validate_primary_business_pilot(payload)
