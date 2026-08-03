from datetime import date

from company_quality.company_analysis.guidance_industry import (
    _IRRecord,
    _StoredArtifact,
    _verified_issuer_guidance_facts,
)


def _artifact() -> _StoredArtifact:
    return _StoredArtifact(
        body=b"%PDF-test",
        digest="a" * 64,
        source_url="https://mops.twse.com.tw/presentation.pdf",
        available_at="2026-07-16T14:00:00+08:00",
        retrieved_at="2026-07-31T10:00:00+08:00",
    )


def _record(code: str, filename: str) -> _IRRecord:
    return _IRRecord(code, "公司", date(2026, 7, 16), "14:00", "法說", filename)


def test_tsmc_verified_guidance_requires_exact_markers_and_numbers() -> None:
    pages = (
        "2026年第三季業績展望 合併營收美金446億元到458億元 毛利率65到67 營業利益率56到58",
        "未來展望 2026 年美元合併營收成長略高於40%",
    )

    facts = _verified_issuer_guidance_facts(
        "2330", pages, _artifact(), _record("2330", "233020260716M001.pdf")
    )

    assert {item.fact_id for item in facts} == {
        "issuer:quarter-guidance", "issuer:annual-growth-guidance"
    }
    assert all(item.citation.source_tier == "issuer_primary" for item in facts)


def test_aspeed_verified_guidance_and_product_profile() -> None:
    pages = (
        "公司簡介 無晶圓廠IC設計公司 BMC 智慧AV",
        "產品路線圖 Design-in Production-ready Ramp-up AST2700 AST1840",
        "2026年第三季營運展望 匯率31.6 營收41億元至43億元 毛利率67%至68%",
        "本期淨利 Note one-time FX loss while 3Q25 has FX gain",
    )

    facts = _verified_issuer_guidance_facts(
        "5274", pages, _artifact(), _record("5274", "527420260529M001.pdf")
    )

    assert {item.fact_id for item in facts} == {
        "issuer:quarter-guidance",
        "issuer:product-roadmap",
        "issuer:business-model",
        "issuer:fx-one-time",
    }
