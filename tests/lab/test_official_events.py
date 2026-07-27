from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

import jsonschema
import pandas as pd
import pytest

from company_quality.lab.official_events import (
    OfficialEventCoverage,
    normalize_major_announcement_rows,
    normalize_violation_rows,
    validate_downside_event_challenger,
)
from company_quality.research_snapshot import (
    CompanyResearchSnapshotError,
    DownsideCoreResult,
    OfficialMaterialEvent,
    QualityCoreResult,
    UpsideCoreResult,
    build_company_research_snapshot,
)


ROOT = Path(__file__).parents[2]
GENERATION = "g1"


def _snapshot(events: tuple[OfficialMaterialEvent, ...]):
    return build_company_research_snapshot(
        issuer_id="issuer-2330",
        security_code="2330",
        market="TWSE",
        generated_at="2026-07-27T12:00:00+08:00",
        input_source_versions={"official_events": "OfficialMaterialEventNormalization.v1"},
        quality=QualityCoreResult(
            generation_id=GENERATION,
            status="research_only",
            score=None,
            confidence=None,
            model_version="quality.v1",
            data_as_of="2026-07-27",
        ),
        upside=UpsideCoreResult(
            generation_id=GENERATION,
            status="research_only",
            positive_return_probability=None,
            official_benchmark_outperform_probability=None,
            secondary_market_median_outperform_probability=None,
            p10_return=None,
            p50_return=None,
            p90_return=None,
            p10_price=None,
            p50_price=None,
            p90_price=None,
            stars=None,
            confidence=None,
            model_version="upside.v1",
            data_as_of="2026-07-27",
        ),
        downside=DownsideCoreResult(
            generation_id=GENERATION,
            status="research_only",
            risk_score=None,
            faces=None,
            confidence=None,
            model_version="downside.v1",
            data_as_of="2026-07-27",
        ),
        official_events=events,
    )


def test_normalizes_official_dates_and_snapshot_displays_without_core_effect() -> None:
    rows = [
        {
            "發言日期": "1150726",
            "發言時間": "70003",
            "公司代號": "2330",
            "公司名稱": "台積電",
            "主旨 ": "公告正式事件",
            "符合條款": "第1款",
            "事實發生日": "1150725",
            "說明": "交易所重大訊息原文說明",
        },
        {
            "發言日期": "1150726",
            "發言時間": "70003",
            "公司代號": "9999",
            "主旨 ": "無法解析公司",
            "符合條款": "第1款",
            "事實發生日": "1150725",
            "說明": "原文",
        },
    ]

    events, report = normalize_major_announcement_rows(
        rows,
        market="TWSE",
        generation_id=GENERATION,
        issuer_by_security_code={"2330": "issuer-2330"},
    )
    snapshot = _snapshot(events)
    payload = asdict(snapshot)
    schema = json.loads(
        (
            ROOT
            / "src/company_quality/research_snapshot/contracts/CompanyResearchSnapshot.schema.json"
        ).read_text()
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(payload)

    event = events[0]
    assert event.effective_date == "2026-07-25"
    assert event.available_at == "2026-07-26T07:00:03+08:00"
    assert event.downside_candidate_status == "display_only"
    assert snapshot.official_events == list(events)
    assert snapshot.quality.score is None
    assert snapshot.downside.faces is None
    assert report["confirmed_event_count"] == 1
    assert report["rejected_counts"] == {"unresolved_issuer": 1}
    assert report["text_severity_inference"] is False

    violations, violation_report = normalize_violation_rows(
        [{
            "發函日期": "1150717",
            "股票代號": "2330",
            "公司名稱": "台積電",
            "違規事由": "交易所正式違規事由",
            "違反資訊申報作業辦法條款": "第6條",
        }],
        market="TWSE",
        generation_id=GENERATION,
        issuer_by_security_code={"2330": "issuer-2330"},
    )
    assert violations[0].event_type == "filing_violation"
    assert violations[0].available_at == "2026-07-17T23:59:59+08:00"
    assert violations[0].downside_candidate_status == "eligible_for_validation"
    assert violation_report["quality_score_effect"] is None

    with pytest.raises(CompanyResearchSnapshotError, match="unconfirmed event"):
        _snapshot((replace(
            event,
            confirmation_status="unconfirmed_research",
            downside_candidate_status="eligible_for_validation",
        ),))
    with pytest.raises(CompanyResearchSnapshotError, match="not available"):
        _snapshot((replace(event, available_at="2026-07-28T07:00:03+08:00"),))


def _candidate_event(issuer_id: str, code: str, decision: str) -> OfficialMaterialEvent:
    decision_stamp = pd.Timestamp(decision)
    available = decision_stamp - pd.Timedelta(days=30)
    effective = decision_stamp + pd.Timedelta(days=10)
    return OfficialMaterialEvent(
        generation_id=GENERATION,
        issuer_id=issuer_id,
        security_code=code,
        market="TWSE",
        event_id=f"TWSE:{code}:{available.date()}:delisting",
        event_type="delisting",
        title="交易所公告終止上市",
        effective_date=effective.date().isoformat(),
        available_at=f"{available.date().isoformat()}T12:00:00+08:00",
        official_reason="交易所正式終止上市公告原因",
        source_authority="TWSE",
        source_url="https://openapi.twse.com.tw/v1/company/suspendListingCsvAndHtml",
        evidence_id=f"TWSE:{code}:{available.date()}:official-row",
        confirmation_status="confirmed",
        downside_candidate_status="eligible_for_validation",
    )


def test_downside_event_requires_complete_history_and_independent_gain() -> None:
    dates = ["2020-06-30", "2021-06-30", "2022-06-30", "2023-06-30"]
    labels: list[dict[str, object]] = []
    base: list[dict[str, object]] = []
    events: list[OfficialMaterialEvent] = []
    for decision in dates:
        for index in range(12):
            issuer_id = f"issuer-{index:02d}"
            code = f"{1000 + index}"
            labels.append({
                "issuer_id": issuer_id,
                "security_code": code,
                "market": "TWSE",
                "decision_date": decision,
                "generation_id": GENERATION,
                "adverse_outcome": index >= 8,
            })
            base.append({
                "issuer_id": issuer_id,
                "decision_date": decision,
                "metric_id": "base_noise",
                "metric_value": float(index % 2),
                "metric_available_at": f"{decision}T12:00:00",
                "evidence_family_id": "earnings_outcomes",
            })
            if index >= 8:
                events.append(_candidate_event(issuer_id, code, decision))
    coverage = {
        "TWSE": OfficialEventCoverage(
            market="TWSE",
            available_from="2019-01-01",
            available_to="2023-12-31",
            complete=True,
            source_url="https://openapi.twse.com.tw/official-archive",
        )
    }

    features, report = validate_downside_event_challenger(
        pd.DataFrame(labels), pd.DataFrame(base), events, coverage
    )

    assert report["status"] == "research_only"
    assert report["admitted_event_types"] == ["delisting"]
    assert report["quality_score_effect"] is None
    assert report["faces"] is None
    assert features["metric_id"].unique().tolist() == [
        "downside__official_event__delisting__count_12m"
    ]

    _, blocked = validate_downside_event_challenger(
        pd.DataFrame(labels),
        pd.DataFrame(base),
        events,
        {
            "TWSE": replace(
                coverage["TWSE"], available_from="2026-07-27", available_to="2026-07-27"
            )
        },
    )
    assert blocked["status"] == "research_only_insufficient_official_history"
    assert blocked["admitted_event_types"] == []
