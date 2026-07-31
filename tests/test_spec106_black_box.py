from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen

from company_quality.company_analysis.contracts import (
    CaseProbability,
    CompanyAnalysisRequest,
    DownsideCase,
    DownsideSection,
    DownsideSectionItem,
    EvidenceCitation,
    Finding,
    SourceCoverage,
    UpsideCase,
    build_single_company_research_report,
)
from company_quality.dashboard_jobs import AnalysisJobService
from company_quality.dashboard_server import make_server
from company_quality.identity import OfficialIdentitySource


SECTION_IDS = (
    "financial_deterioration",
    "unexplained_financial_anomalies",
    "recent_negative_news",
    "three_year_kam",
)
PROFILES = {
    "1101": ("TWSE", "11913502", "台灣水泥股份有限公司", "台泥", "complete"),
    "6488": ("TPEx", "28113286", "環球晶圓股份有限公司", "環球晶", "complete"),
    "2201": ("TWSE", "03557311", "裕隆汽車製造股份有限公司", "裕隆", "partial"),
    "8069": ("TPEx", "84149738", "元太科技工業股份有限公司", "元太", "blocked"),
    "9933": ("TWSE", "20817282", "中鼎工程股份有限公司", "中鼎", "complete"),
}
SOURCES = tuple(
    OfficialIdentitySource(
        market=market,
        url=f"https://official.test/{market.casefold()}",
        available_at="2026-01-01T00:00:00+08:00",
        rows=tuple(
            {
                "security_code": code,
                "issuer_id": issuer_id,
                "company_name": name,
                "short_name": short_name,
                "listing_date": "20000101",
            }
            for code, (row_market, issuer_id, name, short_name, _) in PROFILES.items()
            if row_market == market
        ),
    )
    for market in ("TWSE", "TPEx")
)


def _unavailable(reason: str) -> CaseProbability:
    return CaseProbability("unavailable", None, None, None, None, None, reason)


def _fact(finding_id: str, statement: str, evidence_id: str) -> Finding:
    return Finding(
        finding_id,
        "fact",
        "context",
        statement,
        Decimal("0.5"),
        (evidence_id,),
        (),
        (),
        None,
    )


def _section(
    section_id: str,
    generation_id: str,
    evidence_id: str,
    *,
    partial: bool = False,
) -> DownsideSection:
    titles = {
        "financial_deterioration": "財報惡化",
        "unexplained_financial_anomalies": "無法解釋財報異常",
        "recent_negative_news": "近期負面新聞",
        "three_year_kam": "三年KAM",
    }
    return DownsideSection(
        section_id=section_id,  # type: ignore[arg-type]
        title=titles[section_id],
        generation_id=generation_id,
        status="partial" if partial else "available",
        items=(
            DownsideSectionItem(
                item_id=f"{section_id}:fixture",
                severity="unknown" if partial else "low",
                confidence=None if partial else Decimal("0.7"),
                summary=f"{titles[section_id]} fixture judgement",
                evidence=("fixture admitted evidence",),
                counterevidence=("fixture counterevidence",),
                monitoring=("fixture monitoring condition",),
                invalidation=("fixture invalidation condition",),
                evidence_ids=() if partial else (evidence_id,),
            ),
        ),
        gaps=("news_transport_unavailable",) if partial else (),
    )


class _FixtureTransport:
    """Deterministic replacement for every external company/source transport."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def profile(self, security_code: str) -> tuple[str, str, str, str, str]:
        self.calls.append(security_code)
        return PROFILES[security_code]


class _FakeHermes:
    """Deterministic candidate producer used by the highest public seam."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def report(
        self,
        *,
        security_code: str,
        generation_id: str,
        as_of: str,
        profile: tuple[str, str, str, str, str],
    ):
        market, issuer_id, name, _, expected_status = profile
        self.calls.append((security_code, generation_id))
        request = CompanyAnalysisRequest(issuer_id, security_code, market, as_of)
        unavailable = _unavailable("未校準，Unavailable。")
        if expected_status == "blocked":
            return build_single_company_research_report(
                request=request,
                generation_id=generation_id,
                generated_at=as_of,
                citations=(),
                source_coverage=(
                    SourceCoverage(
                        "three_statement_html",
                        60,
                        59,
                        ("core_three_statements_incomplete",),
                    ),
                ),
                downside=DownsideCase(
                    generation_id, "blocked", "核心三表不足。", (), unavailable, Decimal("0")
                ),
                upside=UpsideCase(
                    generation_id,
                    "blocked",
                    "核心三表不足。",
                    (),
                    unavailable,
                    unavailable,
                    Decimal("0"),
                ),
                limitations=("core_three_statements_incomplete",),
                status="blocked",
            )

        evidence_id = f"fixture:{market}:{security_code}:financials"
        citation = EvidenceCitation(
            evidence_id,
            evidence_id,
            "official",
            f"https://official.test/{market.casefold()}/{security_code}",
            "a" * 64,
            "2025Q4",
            "2026-01-01T00:00:00+08:00",
            None,
            None,
            f"{name} fixture official statement",
            "html",
            "table-row:fixture",
        )
        downside_fact = _fact("downside:fixture", "fixture downside fact", evidence_id)
        upside_fact = _fact("upside:fixture", "fixture upside fact", evidence_id)
        valuation = Finding(
            "upside:valuation:scenario:base",
            "judgement",
            "context",
            "基準估值情境為research_only，不是正式目標價。",
            Decimal("0.5"),
            (),
            (upside_fact.finding_id,),
            (),
            "估值假設尚未正式校準。",
        )
        partial = expected_status == "partial"
        coverage = (
            SourceCoverage("three_statement_html", 60, 60, ()),
            SourceCoverage(
                "recent_negative_news",
                1,
                0 if partial else 1,
                ("news_transport_unavailable",) if partial else (),
            ),
        )
        return build_single_company_research_report(
            request=request,
            generation_id=generation_id,
            generated_at=as_of,
            citations=(citation,),
            source_coverage=coverage,
            downside=DownsideCase(
                generation_id,
                "research_only",
                "Downside mechanisms remain independent.",
                (downside_fact,),
                unavailable,
                Decimal("0.7"),
            ),
            upside=UpsideCase(
                generation_id,
                "research_only",
                "Upside remains independent.",
                (upside_fact, valuation),
                unavailable,
                unavailable,
                Decimal("0.7"),
            ),
            limitations=("fixture E2E; no real network",),
            downside_sections=tuple(
                _section(
                    section_id,
                    generation_id,
                    evidence_id,
                    partial=partial and section_id == "recent_negative_news",
                )
                for section_id in SECTION_IDS
            ),
            status="partial" if partial else "complete",
        )


def _post(base: str, identifier: str) -> dict[str, object]:
    request = Request(
        base + "/api/analyses",
        data=json.dumps({"identifier": identifier, "market": None}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        assert response.status == 202
        return json.load(response)


def _get(base: str, path: str) -> dict[str, object]:
    with urlopen(base + path, timeout=5) as response:
        return json.load(response)


def _assert_no_composite_or_visual_rating(value: object) -> None:
    forbidden = {"combined_score", "composite_score", "risk_score", "stars", "faces"}
    if isinstance(value, dict):
        assert forbidden.isdisjoint(value)
        for item in value.values():
            _assert_no_composite_or_visual_rating(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_composite_or_visual_rating(item)


def test_query_http_job_poll_same_generation_result_for_five_general_cases(
    tmp_path: Path,
) -> None:
    transport = _FixtureTransport()
    hermes = _FakeHermes()

    def analyze(**kwargs: object) -> dict[str, object]:
        code = str(kwargs["identifier"])
        profile = transport.profile(code)
        report = hermes.report(
            security_code=code,
            generation_id=str(kwargs["generation_id"]),
            as_of=str(kwargs["as_of"]),
            profile=profile,
        )
        return {
            "generation_id": kwargs["generation_id"],
            "identity": {
                "security_code": code,
                "market": profile[0],
                "issuer_id": profile[1],
                "company_name": profile[2],
            },
            "evidence_status": report.status,
            "research_report": report,
            "filing_store_stats": {"hits": 1, "misses": 0, "saved": 0, "corruptions": 0},
        }

    service = AnalysisJobService(
        database_path=tmp_path / "jobs.sqlite3",
        output_root=tmp_path / "outputs",
        identity_sources=lambda: SOURCES,
        analyzer=analyze,
    )
    service.start()
    server = make_server(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/", timeout=5) as response:
            html = response.read().decode()
        for label in (
            "財報趨勢與惡化",
            "重大財報異常",
            "近期負面事件與新聞",
            "三年關鍵查核事項（KAM）",
            "上漲潛力",
            "估值情境",
            "12個月絕對正報酬",
        ):
            assert label in html
        assert "currentGeneration" in html
        assert "SingleCompanyResearchReport.v4" in html
        assert "legacy fallback" not in html
        assert "星等" not in html and "表情" not in html

        for code, (_, _, _, _, expected_status) in PROFILES.items():
            created = _post(base, code)
            job_id = str(created["job_id"])
            for _ in range(200):
                job = _get(base, f"/api/analyses/{job_id}")
                if job["status"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.01)
            assert job["status"] == "succeeded"
            result = _get(base, f"/api/analyses/{job_id}/result")
            report = result["research_report"]

            assert result["generation_id"] == created["generation_id"]
            assert report["generation_id"] == created["generation_id"]
            assert report["valuation"]["generation_id"] == created["generation_id"]
            assert report["status"] == expected_status
            assert result["identity"]["market"] == PROFILES[code][0]
            assert tuple(item["section_id"] for item in report["downside_sections"]) == SECTION_IDS
            assert all(
                item["generation_id"] == created["generation_id"]
                for item in report["downside_sections"]
            )
            for section in report["downside_sections"]:
                assert section["status"] in {"available", "partial", "blocked"}
                for item in section["items"]:
                    assert set(
                        (
                            "severity",
                            "confidence",
                            "evidence",
                            "counterevidence",
                            "monitoring",
                            "invalidation",
                        )
                    ) <= set(item)
                    assert item["evidence"] and item["counterevidence"]
                    assert item["monitoring"] and item["invalidation"]
            if expected_status == "blocked":
                assert report["valuation"]["status"] == "blocked"
            else:
                assert report["valuation"]["status"] == "research_only"
                assert report["valuation"]["findings"]
                assert not any(
                    item["finding_id"].startswith("upside:valuation:")
                    for item in report["upside"]["findings"]
                )
            assert report["upside"]["positive_return_probability"]["status"] == "unavailable"
            assert report["upside"]["benchmark_outperform_probability"]["status"] == "unavailable"
            assert report["downside"]["twelve_month_drawdown_probability"]["status"] == "unavailable"
            _assert_no_composite_or_visual_rating(report)

        assert transport.calls == list(PROFILES)
        assert [code for code, _ in hermes.calls] == list(PROFILES)
    finally:
        server.shutdown()
        server.server_close()
        service.stop()
