"""Read-only HTML renderer for fixed company-research snapshot fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Sequence

from company_quality.lab.ai_event_layer import (
    AIAdjustedCompanyResearchSnapshot,
    DimensionAdjustment,
)


_STATUS_LABELS = {
    "formal": "正式",
    "research_only": "研究用途",
    "stale_reference": "過期參考",
    "data_insufficient": "資料不足",
    "industry_sample_insufficient": "產業樣本不足",
}


@dataclass(frozen=True, slots=True)
class CompanyResearchDashboardFixture:
    company_name: str
    snapshot: AIAdjustedCompanyResearchSnapshot
    positive_factors: tuple[str, ...]
    negative_factors: tuple[str, ...]
    missing_values: tuple[str, ...]
    confidence_reduction_reasons: tuple[str, ...]
    schema_version: str = "CompanyResearchDashboardFixture.v1"


@dataclass(frozen=True, slots=True)
class RenderedCompanyResearchDashboard:
    generation_id: str
    html: str
    source_schema_version: str
    recomputed_core_values: bool = False
    recomputed_ai_delta: bool = False


def _require_top_three(items: Sequence[str], name: str) -> None:
    if len(items) > 3 or any(not item.strip() for item in items):
        raise ValueError(f"{name} must contain at most three non-empty upstream factors")


def _number(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _range(low: float | None, high: float | None, *, percent: bool = False) -> str:
    if low is None or high is None:
        return "—"
    return f"{_percent(low)} – {_percent(high)}" if percent else f"{low:,.1f} – {high:,.1f}"


def _status(value: str) -> str:
    try:
        return _STATUS_LABELS[value]
    except KeyError as exc:
        raise ValueError(f"unsupported snapshot status: {value}") from exc


def _delta_label(adjustment: DimensionAdjustment) -> str:
    if adjustment.status == "AI_unavailable":
        return "AI unavailable · Δ 0"
    sign = "+" if adjustment.raw_delta > 0 else ""
    return f"AI Δ {sign}{adjustment.raw_delta:.1f}"


def _rating_segments(
    adjustment: DimensionAdjustment,
    *,
    icon: str,
) -> str:
    core = adjustment.core_value
    adjusted = adjustment.adjusted_value
    if core is None or adjusted is None:
        return '<span class="missing-rating">—</span>'
    core_halves = min(10, max(0, round(core * 2)))
    adjusted_halves = min(10, max(0, round(adjusted * 2)))
    halves: list[str] = []
    for index in range(10):
        if index < min(core_halves, adjusted_halves):
            color = "yellow"
        elif adjusted_halves != core_halves and index < max(core_halves, adjusted_halves):
            color = adjustment.delta_color
        else:
            color = "empty"
        halves.append(f'<span class="half {color}"></span>')
    symbols = "".join(
        f'<span class="rating-symbol" aria-hidden="true"><span class="icon">{icon}</span>{halves[index]}{halves[index + 1]}</span>'
        for index in range(0, 10, 2)
    )
    return (
        f'<div class="rating-strip" aria-label="核心 {core:.1f}，AI調整後 {adjusted:.1f}">'
        f"{symbols}</div>"
    )


def _items(items: Sequence[str], empty: str) -> str:
    content = items or (empty,)
    return "".join(f"<li>{escape(item)}</li>" for item in content)


def render_company_research_dashboard(
    fixture: CompanyResearchDashboardFixture,
    *,
    output_path: Path | None = None,
) -> RenderedCompanyResearchDashboard:
    for name, items in (
        ("positive_factors", fixture.positive_factors),
        ("negative_factors", fixture.negative_factors),
        ("missing_values", fixture.missing_values),
        ("confidence_reduction_reasons", fixture.confidence_reduction_reasons),
    ):
        _require_top_three(items, name)
    overlay = fixture.snapshot
    core = overlay.core_snapshot
    if (
        overlay.generation_id != core.generation_id
        or overlay.quality.core_value != core.quality.score
        or overlay.stars.core_value != core.upside.stars
        or overlay.downside_faces.core_value != core.downside.faces
    ):
        raise ValueError("dashboard fixture core/AI snapshot mismatch")

    sources = "".join(
        f'<li><a href="{escape(item.source_url, quote=True)}">{escape(item.source_name)}</a>'
        f'<span>{escape(item.published_at)} · checked {escape(item.checked_at)}</span></li>'
        for item in overlay.verified_evidence
    ) or "<li>本次沒有通過門檻的AI事件來源</li>"
    ai_class = "unavailable" if overlay.ai_status == "AI_unavailable" else "available"
    quality_delta_class = overlay.quality.delta_color
    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(fixture.company_name)}｜公司研究快照</title>
<style>
:root{{--bg:#f4f1e9;--panel:#fffdf8;--ink:#1f2933;--muted:#667085;--line:#d9d2c3;--yellow:#f4c95d;--green:#49a56e;--red:#d95c5c;--empty:#e8e5de;--radius:16px}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,"Noto Sans TC",system-ui,sans-serif}}main{{max-width:1240px;margin:auto;padding:32px 22px 56px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:22px}}h1{{font-size:30px;margin:0 0 8px}}h2{{font-size:18px;margin:0 0 16px}}h3{{font-size:14px;margin:20px 0 8px;color:var(--muted)}}.meta,.subtle{{color:var(--muted);font-size:13px}}.status{{padding:7px 11px;border:1px solid var(--line);border-radius:999px;background:var(--panel);font-weight:700}}.model-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:0 8px 24px rgba(55,47,35,.05)}}.core-value{{font-size:34px;font-weight:800}}.core-chip{{display:inline-block;background:var(--yellow);padding:4px 9px;border-radius:8px}}.delta{{display:inline-block;margin-left:8px;padding:4px 9px;border-radius:8px;color:#fff}}.delta.yellow{{background:var(--yellow);color:var(--ink)}}.delta.green{{background:var(--green)}}.delta.red{{background:var(--red)}}.metric{{display:flex;justify-content:space-between;gap:15px;border-top:1px solid var(--line);padding:11px 0;font-size:14px}}.metric strong{{text-align:right}}.rating-strip{{display:flex;gap:5px;margin:12px 0}}.rating-symbol{{width:27px;height:27px;position:relative;display:inline-flex;overflow:hidden}}.icon{{position:absolute;inset:0;font-size:24px;line-height:27px;color:#b7b0a4;z-index:1}}.half{{position:relative;width:50%;height:100%;z-index:2;mix-blend-mode:color}}.half.yellow{{background:var(--yellow)}}.half.green{{background:var(--green)}}.half.red{{background:var(--red)}}.half.empty{{background:transparent}}.explain-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:16px}}ul{{margin:0;padding-left:20px}}li{{margin:7px 0}}.sources li{{display:flex;flex-direction:column}}a{{color:#246b4b}}.ai-state.unavailable{{color:var(--red);font-weight:800}}.ai-state.available{{color:var(--green);font-weight:800}}@media(max-width:850px){{.model-grid,.explain-grid{{grid-template-columns:1fr}}header{{flex-direction:column}}}}
</style>
</head>
<body><main>
<header><div><h1>{escape(fixture.company_name)}</h1><div class="meta">{escape(core.market or '—')} · {escape(core.security_code or '—')} · generation {escape(core.generation_id)}</div></div><div class="status">{escape(_status(core.status))}</div></header>
<section class="model-grid" aria-label="三套獨立核心模型">
<article class="card quality-card"><h2>品質核心</h2><div><span class="core-value core-chip">{_number(core.quality.score)}</span><span class="delta {quality_delta_class}">{escape(_delta_label(overlay.quality))}</span></div><div class="metric"><span>AI調整後</span><strong>{_number(overlay.quality.adjusted_value)}</strong></div><div class="metric"><span>信心</span><strong>{_percent(core.quality.confidence)}</strong></div><div class="metric"><span>狀態</span><strong>{escape(_status(core.quality.status))}</strong></div><div class="subtle">模型 {escape(core.quality.model_version)} · 資料 {escape(core.quality.data_as_of)}</div></article>
<article class="card upside-card"><h2>上漲潛力核心</h2><div class="metric"><span>上漲機率</span><strong>{_percent(core.upside.positive_return_probability)}</strong></div><div class="metric"><span>跑贏官方市場機率</span><strong>{_percent(core.upside.official_benchmark_outperform_probability)}</strong></div><div class="metric"><span>12月報酬區間</span><strong>{_range(core.upside.p10_return, core.upside.p90_return, percent=True)}</strong></div><div class="metric"><span>可能價格區間</span><strong>{_range(core.upside.p10_price, core.upside.p90_price)}</strong></div><h3>核心星與AI調整</h3>{_rating_segments(overlay.stars, icon='★')}<div class="delta {overlay.stars.delta_color}">{escape(_delta_label(overlay.stars))}</div><div class="metric"><span>狀態</span><strong>{escape(_status(core.upside.status))}</strong></div><div class="subtle">模型 {escape(core.upside.model_version)} · 資料 {escape(core.upside.data_as_of)}</div></article>
<article class="card downside-card"><h2>下行風險核心</h2><div class="metric"><span>風險分數</span><strong>{_number(core.downside.risk_score)}</strong></div><h3>核心哭臉與AI調整</h3>{_rating_segments(overlay.downside_faces, icon='●')}<div class="delta {overlay.downside_faces.delta_color}">{escape(_delta_label(overlay.downside_faces))}</div><div class="metric"><span>信心</span><strong>{_percent(core.downside.confidence)}</strong></div><div class="metric"><span>狀態</span><strong>{escape(_status(core.downside.status))}</strong></div><div class="subtle">模型 {escape(core.downside.model_version)} · 資料 {escape(core.downside.data_as_of)}</div></article>
</section>
<section class="explain-grid"><article class="card"><h2>前三個正向因素</h2><ul>{_items(fixture.positive_factors,'沒有已提供的正向因素')}</ul></article><article class="card"><h2>前三個負向因素</h2><ul>{_items(fixture.negative_factors,'沒有已提供的負向因素')}</ul></article><article class="card"><h2>缺值</h2><ul>{_items(fixture.missing_values,'沒有缺值')}</ul></article><article class="card"><h2>信心降低原因</h2><ul>{_items(fixture.confidence_reduction_reasons,'沒有額外信心折減')}</ul></article></section>
<section class="card" style="margin-top:16px"><h2>AI事件層</h2><div class="ai-state {ai_class}">{escape(overlay.ai_status)}</div><div class="meta">AI checked {escape(overlay.checked_at)}</div><ul class="sources">{sources}</ul></section>
</main></body></html>"""
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
    return RenderedCompanyResearchDashboard(
        generation_id=core.generation_id,
        html=html,
        source_schema_version=fixture.schema_version,
    )


__all__ = [
    "CompanyResearchDashboardFixture", "RenderedCompanyResearchDashboard",
    "render_company_research_dashboard",
]
