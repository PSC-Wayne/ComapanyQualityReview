from hashlib import sha256
from types import SimpleNamespace
from typing import Any, cast

import fitz

from company_quality.company_analysis.checklist_evidence import (
    collect_checklist_document_evidence,
)
from company_quality.company_analysis.checklist_analysis import (
    _annual_audit_filings,
    _document_checks,
    _placeholder_checks,
)


NOTE_HEADINGS = (
    "一、收入認列", "二、應收帳款", "三、存貨", "四、合約資產",
    "五、不動產、廠房及設備", "六、商譽", "七、借款", "八、流動性風險",
    "九、受限制資產", "十、關係人交易", "十一、背書保證", "十二、或有事項",
    "十三、重大承諾", "十四、所得稅", "十五、金融工具", "十六、股份基礎給付",
    "十七、每股盈餘", "十八、部門資訊", "十九、期後事項",
)


def _audit(tmp_path, period: str, include_notes: bool = False):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 70), "查核意見 無保留意見", fontname="china-ts", fontsize=11)
    page.insert_text((50, 100), "關鍵查核事項", fontname="china-ts", fontsize=11)
    page.insert_text((50, 130), "收入認列估計與資產減損係本期關鍵查核事項。", fontname="china-ts", fontsize=11)
    if include_notes:
        for index, heading in enumerate(NOTE_HEADINGS):
            page.insert_text(
                (50, 170 + index * 20), heading,
                fontname="china-ts", fontsize=9,
            )
    path = tmp_path / f"{period}.pdf"
    document.save(path)
    document.close()
    digest = sha256(path.read_bytes()).hexdigest()
    return SimpleNamespace(
        market="TWSE",
        security_code="2330",
        period=period,
        pdf_path=path,
        pdf_sha256=digest,
        pdf_source_url=f"https://mops.twse.com.tw/{period}.pdf",
        available_at="2026-03-31T18:00:00+08:00",
        opinion_type="unmodified",
    )


def test_collects_three_year_opinions_kams_and_all_minimum_notes(tmp_path) -> None:
    audits = (
        _audit(tmp_path, "112Q4"),
        _audit(tmp_path, "113Q4"),
        _audit(tmp_path, "114Q4", include_notes=True),
    )

    result = collect_checklist_document_evidence(cast(Any, audits))

    assert len(result.audit_opinion_citations) == 3
    assert len(result.kam_citations) == 3
    assert len(result.note_citations) == 19
    assert {item[0] for item in result.note_citations} == {
        f"N{number:02d}_{slug}"
        for number, slug in (
            (1, "revenue_recognition"), (2, "receivables"), (3, "inventory"),
            (4, "contract_assets"), (5, "ppe"), (6, "goodwill_intangibles"),
            (7, "borrowings_bonds"), (8, "liquidity"), (9, "restricted_cash"),
            (10, "related_parties"), (11, "guarantees"),
            (12, "contingencies_litigation"), (13, "commitments"),
            (14, "income_tax"), (15, "financial_instruments"),
            (16, "share_based_payments"), (17, "eps"), (18, "segments"),
            (19, "subsequent_events"),
        )
    }
    assert result.unreadable_periods == ()
    assert result.audit_opinion_types == (
        ("112Q4", "unmodified"), ("113Q4", "unmodified"), ("114Q4", "unmodified")
    )
    assert result.audit_text_search_complete_periods == ("112Q4", "113Q4", "114Q4")
    assert all(item.coordinate is not None for item in result.kam_citations)

    rows = {item.check_id: item for item in _document_checks(
        _placeholder_checks("missing"), result
    )}
    assert all(rows[f"N{number:02d}_{slug}"].status == "evaluated" for number, slug in (
        (1, "revenue_recognition"), (2, "receivables"), (3, "inventory"),
        (4, "contract_assets"), (5, "ppe"), (6, "goodwill_intangibles"),
        (7, "borrowings_bonds"), (8, "liquidity"), (9, "restricted_cash"),
        (10, "related_parties"), (11, "guarantees"),
        (12, "contingencies_litigation"), (13, "commitments"),
        (14, "income_tax"), (15, "financial_instruments"),
        (16, "share_based_payments"), (17, "eps"), (18, "segments"),
        (19, "subsequent_events"),
    ))
    assert rows["A01_auditor_opinion"].status == "evaluated"
    assert rows["A02_going_concern"].applicability == "not_triggered"
    assert rows["A03_emphasis_and_other_matters"].applicability == "not_triggered"
    assert rows["A04_three_year_kam"].status == "evaluated"


def test_hash_mismatch_is_unreadable_and_never_admitted(tmp_path) -> None:
    audit = _audit(tmp_path, "114Q4", include_notes=True)
    audit.pdf_sha256 = "0" * 64

    result = collect_checklist_document_evidence(cast(Any, (audit,)))

    assert result.unreadable_periods == ("114Q4",)
    assert result.audit_opinion_citations == ()
    assert result.kam_citations == ()
    assert result.note_citations == ()


def test_fallback_document_collection_selects_annual_audits_only(tmp_path) -> None:
    annual = _audit(tmp_path, "114Q4", include_notes=True)
    quarter = _audit(tmp_path, "115Q1")
    bundle = SimpleNamespace(
        periods=(
            SimpleNamespace(is_annual=True, audit=annual),
            SimpleNamespace(is_annual=False, audit=quarter),
        )
    )

    assert _annual_audit_filings(cast(Any, bundle)) == (annual,)
