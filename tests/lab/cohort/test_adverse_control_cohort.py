import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
from jsonschema import Draft202012Validator

from company_quality.lab.cohort import (
    CohortError,
    GovernedEventLabel,
    OfficialUniverseMember,
    build_adverse_control_cohort,
    five_year_window,
    probe_market_identity,
    probe_tpex_delisted_year,
    probe_twse_delisted,
)


def sha(char: str) -> str:
    return char * 64


def member(
    issuer: str,
    *,
    listed="2020-01-01",
    delisted=None,
    market: Literal["TWSE", "TPEx"] = "TWSE",
    available="2026-07-24T09:00:00+08:00",
):
    return OfficialUniverseMember(
        issuer_id=issuer,
        security_code=issuer[-4:],
        company_name=f"Company {issuer}",
        market=market,
        listed_on=listed,
        delisted_on=delisted,
        evidence_ids=(f"universe:{issuer}",),
        available_at=available,
    )


def label(
    issuer: str,
    *,
    adverse=True,
    kind: Literal[
        "forced_redemption", "maturity", "bankruptcy", "other_delisting"
    ] = "bankruptcy",
):
    return GovernedEventLabel(
        issuer_id=issuer,
        event_code="official_delisting",
        event_class="delisting",
        adverse=adverse,
        effective_on="2024-06-30",
        official_reason="Official rule citation 50-1",
        authoritative_source_type="exchange_delisting_registry",
        delisting_kind=kind,
        evidence_ids=(f"event:{issuer}",),
        available_at="2024-06-01T12:00:00+08:00",
    )


def build(
    members,
    labels=(),
    *,
    market: Literal["TWSE", "TPEx"] = "TWSE",
    min_days=365,
):
    return build_adverse_control_cohort(
        members,
        labels,
        market=market,
        cohort_asof="2026-07-24T14:00:00+08:00",
        min_followup_days=min_days,
        eligibility_version="1.0.0",
        producer_shas={"T03": sha("a"), "T04": sha("b"), "T06": sha("c")},
        generation_id="r9-generation",
        producer_candidate_sha=sha("d"),
    )


def test_five_calendar_year_half_open_boundaries_include_leap_clamp() -> None:
    assert tuple(value.isoformat() for value in five_year_window(
        "2024-02-28T23:00:00+08:00"
    )) == ("2019-02-28", "2024-02-29")
    assert tuple(value.isoformat() for value in five_year_window(
        "2025-02-28T23:00:00+08:00"
    )) == ("2020-03-01", "2025-03-01")


def test_delisted_newly_listed_controls_and_reasons_are_explicit() -> None:
    result = build(
        [
            member("issuer-active"),
            member("issuer-new", listed="2026-06-30"),
            member("issuer-adverse", delisted="2024-06-30"),
            member("issuer-nonadverse", delisted="2024-06-30"),
        ],
        [label("issuer-adverse"), label("issuer-nonadverse", adverse=False, kind="other_delisting")],
    )

    dispositions = {item.issuer_id: item.disposition for item in result.members}
    assert dispositions == {
        "issuer-active": "control",
        "issuer-adverse": "adverse",
        "issuer-new": "right_censored",
        "issuer-nonadverse": "control",
    }
    assert result.control_ids == ("issuer-active", "issuer-nonadverse")
    assert "issuer-adverse" in result.issuer_ids
    adverse = next(item for item in result.members if item.issuer_id == "issuer-adverse")
    assert adverse.official_reasons == ("Official rule citation 50-1",)
    assert adverse.event_codes == ("official_delisting",)
    assert result.delisting_states.bankruptcy == "confirmed"
    assert result.delisting_states.other_delisting == "confirmed"
    assert result.window_start_inclusive == "2021-07-25"
    assert result.window_end_exclusive == "2026-07-25"
    assert result.delisted_included is True
    assert result.cohort_coverage == Decimal("1")
    assert result.rating_disposition == "NO_RATING_NOT_APPLICABLE"


def test_unresolved_delisting_blocks_only_affected_membership() -> None:
    result = build([
        member("issuer-active"),
        member("issuer-unresolved", delisted="2025-01-01"),
    ])

    assert result.issuer_ids == ("issuer-active",)
    assert result.failure_reasons == {
        "issuer-unresolved": "unresolved_delisting_event_label"
    }
    assert result.cohort_coverage == Decimal("0.5")
    assert result.delisting_states.maturity == "unknown"
    assert result.censoring_rules.missing_price_policy == "block_unconfirmed"
    assert result.censoring_rules.suspension_policy == (
        "right_censor_until_official_resume_or_delisting"
    )


def test_single_market_identity_and_exact_producer_contract_fail_closed() -> None:
    with pytest.raises(CohortError, match="cross-market"):
        build([member("issuer-otc", market="TPEx")])

    duplicate = member("issuer-a")
    with pytest.raises(CohortError, match="duplicate issuer"):
        build([duplicate, duplicate])

    with pytest.raises(CohortError, match="unknown issuer"):
        build([member("issuer-a")], [label("issuer-missing")])

    with pytest.raises(CohortError, match="PIT boundary"):
        build([member("issuer-a", available="2026-07-24T15:00:00+08:00")])

    with pytest.raises(CohortError, match="at least one control"):
        build([member("issuer-new", listed="2026-07-01")])

    with pytest.raises(CohortError, match="exact T03/T04/T06 SHAs"):
        build_adverse_control_cohort(
            [member("issuer-a")], (), market="TWSE",
            cohort_asof="2026-07-24T14:00:00+08:00",
            min_followup_days=0, eligibility_version="1.0.0",
            producer_shas={"T03": sha("a"), "T04": sha("b")},
            generation_id="g", producer_candidate_sha=sha("d"),
        )


def test_official_probe_parsers_accept_exact_shapes_and_reject_drift() -> None:
    twse_body = b'{"status":"ok","data":[["115/06/23","Name","6806"]]}'
    twse = probe_twse_delisted(lambda _: (json.loads(twse_body), twse_body))
    assert twse["row_count"] == 1
    assert isinstance(twse["source_sha256"], str)
    assert len(twse["source_sha256"]) == 64

    tpex_payload = {
        "stat": "ok",
        "tables": [{
            "fields": ["股票代號", "公司名稱", "終止上櫃日期", "終止上櫃原因", "公司資料網址"],
            "data": [["1234", "Name", "114-01-01", "Rule", "url"]],
        }],
    }
    tpex_body = json.dumps(tpex_payload, ensure_ascii=False).encode()
    tpex = probe_tpex_delisted_year(
        2025, lambda _: (tpex_payload, tpex_body)
    )
    assert tpex["row_count"] == 1
    assert isinstance(tpex["source_url"], str)
    assert "date=2025" in tpex["source_url"]

    bad = {"stat": "ok", "tables": [{"fields": ["changed"], "data": []}]}
    with pytest.raises(CohortError, match="schema invalid"):
        probe_tpex_delisted_year(2025, lambda _: (bad, b"{}"))

    identity_payload = [{
        "公司代號": "1101", "公司名稱": "台泥",
        "營利事業統一編號": "11913502", "上市日期": "19620209",
    }]
    identity_body = json.dumps(identity_payload, ensure_ascii=False).encode()
    identity = probe_market_identity(
        "TWSE", lambda _: (identity_payload, identity_body)
    )
    assert identity["row_count"] == 1

    with pytest.raises(CohortError, match="identity source schema invalid"):
        probe_market_identity("TWSE", lambda _: ([{"公司代號": "1101"}], b"[]"))


def test_closed_schema_accepts_output_and_rejects_undeclared_fields() -> None:
    result = build([member("issuer-a")])
    path = (
        Path(__file__).parents[3]
        / "src/company_quality/lab/cohort/contracts/AdverseControlCohort.schema.json"
    )
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = json.loads(json.dumps(asdict(result), default=float))
    validator.validate(payload)
    payload["calibrated_score"] = 50
    assert next(validator.iter_errors(payload)).validator == "additionalProperties"


@pytest.mark.authority_probe
def test_live_twse_and_tpex_delisting_authorities() -> None:
    twse = probe_twse_delisted()
    tpex = probe_tpex_delisted_year(2025)
    twse_identity = probe_market_identity("TWSE")
    tpex_identity = probe_market_identity("TPEx")
    assert isinstance(twse["row_count"], int)
    assert isinstance(tpex["row_count"], int)
    assert twse["row_count"] > 0
    assert tpex["row_count"] > 0
    assert isinstance(twse_identity["row_count"], int)
    assert isinstance(tpex_identity["row_count"], int)
    assert twse_identity["row_count"] > 0
    assert tpex_identity["row_count"] > 0
    assert twse["source_sha256"] != tpex["source_sha256"]
