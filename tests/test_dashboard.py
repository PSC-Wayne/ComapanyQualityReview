from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

import jsonschema
import pytest

from company_quality.dashboard import (
    CompanyResearchDashboardFixture,
    render_company_research_dashboard,
)
from company_quality.lab.ai_event_layer import (
    AIEventEvidence,
    AIEventProposal,
    ProposedDimensionDelta,
    apply_ai_event_layer,
)
from company_quality.research_snapshot import (
    DownsideCoreResult,
    QualityCoreResult,
    UpsideCoreResult,
    build_company_research_snapshot,
)


ROOT = Path(__file__).parents[1]
CHECKED = "2026-07-27T12:00:00+08:00"


def _core():
    generation = "dashboard-g1"
    core = build_company_research_snapshot(
        issuer_id="issuer-2330",
        security_code="2330",
        market="TWSE",
        generated_at="2026-07-27T11:00:00+08:00",
        input_source_versions={"runtime": "ResearchRuntimeRefresh.v1"},
        quality=QualityCoreResult(
            generation, "research_only", 60.0, 0.8, "quality-2026.v1", "2026-07-27"
        ),
        upside=UpsideCoreResult(
            generation, "research_only", 0.7, 0.65, None,
            -0.1, 0.2, 0.4, 90.0, 120.0, 140.0,
            None, 0.75, "upside-2026.v1", "2026-07-27",
        ),
        downside=DownsideCoreResult(
            generation, "research_only", 30.0, None, 0.7,
            "downside-2026.v1", "2026-07-27",
        ),
    )
    # Fixed UI fixture only; production builders remain non-rating until authorized.
    return replace(
        core,
        upside=replace(core.upside, stars=3.0),
        downside=replace(core.downside, faces=2.5),
    )


def _overlay(ai_available: bool = True):
    core = _core()
    evidence = AIEventEvidence(
        evidence_id="twse-event",
        generation_id=core.generation_id,
        source_name="TWSE重大訊息",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        source_kind="official",
        independence_key="TWSE",
        published_at="2026-07-27T09:00:00+08:00",
        checked_at=CHECKED,
        supported_reason="官方事件已於本次更新確認",
        validity="confirmed_current",
    )
    return apply_ai_event_layer(
        core_snapshot=core,
        checked_at=CHECKED,
        ai_available=ai_available,
        proposal=AIEventProposal(
            ProposedDimensionDelta(10.0, ("twse-event",)),
            ProposedDimensionDelta(-0.5, ("twse-event",)),
            ProposedDimensionDelta(-0.5, ("twse-event",)),
        ),
        evidence=(evidence,),
    )


def _fixture(ai_available: bool = True) -> CompanyResearchDashboardFixture:
    return CompanyResearchDashboardFixture(
        company_name="台灣積體電路製造",
        snapshot=_overlay(ai_available),
        positive_factors=("營運現金流穩定", "毛利率優於同業", "官方事件本次確認"),
        negative_factors=("價格區間仍寬", "產業循環波動", "海外擴產成本"),
        missing_values=("次級市場中位數勝率缺值",),
        confidence_reduction_reasons=("價格預測區間偏寬", "產業歷史樣本有限"),
    )


def test_fixed_snapshot_renders_three_independent_models_and_required_metadata(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    output = tmp_path / "dashboard.html"
    rendered = render_company_research_dashboard(fixture, output_path=output)
    html = rendered.html

    assert output.read_text() == html
    assert html.count('<article class="card quality-card">') == 1
    assert html.count('<article class="card upside-card">') == 1
    assert html.count('<article class="card downside-card">') == 1
    assert "上漲機率" in html and "70.0%" in html
    assert "跑贏官方市場機率" in html and "65.0%" in html
    assert "12月報酬區間" in html and "-10.0% – 40.0%" in html
    assert "可能價格區間" in html and "90.0 – 140.0" in html
    assert "quality-2026.v1" in html
    assert "upside-2026.v1" in html
    assert "downside-2026.v1" in html
    assert "2026-07-27" in html and f"AI checked {CHECKED}" in html
    assert "https://openapi.twse.com.tw/v1/opendata/t187ap04_L" in html
    assert "營運現金流穩定" in html and "海外擴產成本" in html
    assert "次級市場中位數勝率缺值" in html
    assert "價格預測區間偏寬" in html
    assert "目標價" not in html
    assert "買進" not in html and "賣出" not in html and "總分" not in html
    assert rendered.recomputed_core_values is False
    assert rendered.recomputed_ai_delta is False

    payload = json.loads(json.dumps(asdict(fixture)))
    schema = json.loads((
        ROOT / "src/company_quality/contracts/CompanyResearchDashboardFixture.schema.json"
    ).read_text())
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_half_unit_visuals_keep_core_yellow_and_ai_effect_colors() -> None:
    html = render_company_research_dashboard(_fixture()).html

    assert html.count('class="rating-strip"') == 2
    assert 'class="half yellow"' in html
    assert 'class="half red"' in html
    assert 'class="half green"' in html
    assert "AI Δ -0.5" in html
    assert "核心 3.0，AI調整後 2.5" in html
    assert "核心 2.5，AI調整後 2.0" in html
    assert "core-chip" in html and "AI Δ +10.0" in html


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("formal", "正式"),
        ("research_only", "研究用途"),
        ("stale_reference", "過期參考"),
        ("data_insufficient", "資料不足"),
        ("industry_sample_insufficient", "產業樣本不足"),
    ],
)
def test_all_snapshot_states_are_explicit(status: str, label: str) -> None:
    fixture = _fixture()
    core = fixture.snapshot.core_snapshot
    changed_core = replace(
        core,
        status=status,
        quality=replace(core.quality, status=status),
        upside=replace(core.upside, status=status),
        downside=replace(core.downside, status=status),
    )
    changed_overlay = replace(fixture.snapshot, core_snapshot=changed_core)
    html = render_company_research_dashboard(
        replace(fixture, snapshot=changed_overlay)
    ).html

    assert label in html


def test_ai_unavailable_keeps_core_visible() -> None:
    html = render_company_research_dashboard(_fixture(ai_available=False)).html

    assert "AI_unavailable" in html
    assert "AI unavailable · Δ 0" in html
    assert "60.0" in html
    assert "70.0%" in html
    assert "30.0" in html
    assert "core-chip" in html


def test_dashboard_rejects_more_than_three_upstream_factors() -> None:
    fixture = replace(
        _fixture(),
        positive_factors=("a", "b", "c", "d"),
    )
    with pytest.raises(ValueError, match="at most three"):
        render_company_research_dashboard(fixture)
