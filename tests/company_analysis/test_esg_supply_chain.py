from __future__ import annotations

from datetime import date
from hashlib import sha256
import json

import pytest

from company_quality.company_analysis.contracts import EvidenceCitation
from company_quality.company_analysis.esg_supply_chain import (
    ClaimEvidence,
    EsgEvidenceError,
    OriginalSourceCoverage,
    build_esg_legal_evidence,
    parse_openapi_payload,
)

AS_OF = "2026-08-03T12:00:00+08:00"
RETRIEVED_AT = "2026-08-03T11:00:00+08:00"


def _payload(dataset_id: str, value: str, *, code: str = "2330") -> bytes:
    common = {"出表日期": "1150803", "報告年度": "114", "公司代號": code, "公司名稱": "台積電"}
    if dataset_id.endswith("13"):
        common.update(
            {
                "採購符合國際認可之產品責任標準者占整體採購之百分比，並依標準區分": "N/A",
                "對供應商進行稽核之家數(家)": "25",
                "對供應商進行稽核之百分比": value,
            }
        )
    elif dataset_id.endswith("20"):
        common["因與反競爭行為條例相關的法律訴訟而造成的金錢損失總額(仟元)"] = value
    elif dataset_id.endswith("16"):
        common.update(
            {
                "資訊外洩事件數量": value,
                "與個資相關的資訊外洩事件占比": "0.00%",
                "因資訊外洩事件而受影響的顧客數(人)": "0",
            }
        )
    return json.dumps([common], ensure_ascii=False).encode()


def _citation(evidence_id: str, excerpt: str, *, family: str = "annual-report") -> EvidenceCitation:
    return EvidenceCitation(
        evidence_id=evidence_id,
        source_id=evidence_id,
        source_tier="issuer_primary",
        url=f"https://issuer.example/{family}.pdf",
        content_sha256=sha256(excerpt.encode()).hexdigest(),
        period="114",
        available_at="2026-03-31T18:00:00+08:00",
        page=42,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="pdf",
        locator="page:42",
    )


@pytest.mark.parametrize(
    ("market", "dataset_id", "url"),
    [
        ("TWSE", "t187ap46_L_13", "https://openapi.twse.com.tw/v1/opendata/t187ap46_L_13"),
        ("TPEx", "t187ap46_O_13", "https://www.tpex.org.tw/openapi/v1/t187ap46_O_13"),
    ],
)
def test_supplier_audit_source_shape_is_endpoint_and_market_specific(market, dataset_id, url) -> None:
    result = parse_openapi_payload(
        body=_payload(dataset_id, "100.00%"),
        market=market,
        dataset_id=dataset_id,
        security_code="2330",
        company_name="台積電",
        source_url=url,
        retrieved_at=RETRIEVED_AT,
        as_of=AS_OF,
    )

    assert result.status == "available"
    assert result.record is not None
    assert result.record.claim_scope == "supplier_audit_context"
    assert result.record.fields["對供應商進行稽核之百分比"] == "100.00%"
    assert result.record.citation.source_format == "json"
    assert result.record.citation.locator == f"dataset:{dataset_id};公司代號:2330;報告年度:114"


def test_wrong_shape_fails_closed_but_current_feed_absence_stays_unresolved() -> None:
    with pytest.raises(EsgEvidenceError, match="missing required fields"):
        parse_openapi_payload(
            body=json.dumps([{"公司代號": "2330"}]).encode(), market="TWSE",
            dataset_id="t187ap46_L_13", security_code="2330", company_name="台積電",
            source_url="https://openapi.twse.com.tw/v1/opendata/t187ap46_L_13",
            retrieved_at=RETRIEVED_AT, as_of=AS_OF,
        )
    other_company_only = parse_openapi_payload(
        body=_payload("t187ap46_L_13", "50%", code="2317"), market="TWSE",
        dataset_id="t187ap46_L_13", security_code="2330", company_name="台積電",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap46_L_13",
        retrieved_at=RETRIEVED_AT, as_of=AS_OF,
    )
    assert other_company_only.status == "unresolved"
    assert other_company_only.unresolved_reason is not None
    assert "current_feed_absence" in other_company_only.unresolved_reason
    empty = parse_openapi_payload(
        body=b"[]", market="TWSE", dataset_id="t187ap46_L_13",
        security_code="2330", company_name="台積電",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap46_L_13",
        retrieved_at=RETRIEVED_AT, as_of=AS_OF,
    )
    assert empty.status == "unresolved"
    assert empty.unresolved_reason is not None
    assert "current_feed_absence" in empty.unresolved_reason


def test_na_claim_fields_remain_unresolved_and_are_not_zero() -> None:
    result = parse_openapi_payload(
        body=_payload("t187ap46_L_20", "N/A"), market="TWSE",
        dataset_id="t187ap46_L_20", security_code="2330", company_name="台積電",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap46_L_20",
        retrieved_at=RETRIEVED_AT, as_of=AS_OF,
    )

    assert result.status == "unresolved"
    assert result.record is not None
    assert result.unresolved_reason is not None
    assert "not_disclosed_is_not_zero" in result.unresolved_reason
    row = build_esg_legal_evidence(openapi=(result,), claims=()).check("R37")
    assert row.status == "unresolved"
    assert "空白、N/A或不可解析" in row.observations[0]


def test_supplier_audit_percentage_never_proves_r40_supplier_concentration() -> None:
    audit = parse_openapi_payload(
        body=_payload("t187ap46_L_13", "100.00%"), market="TWSE",
        dataset_id="t187ap46_L_13", security_code="2330", company_name="台積電",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap46_L_13",
        retrieved_at=RETRIEVED_AT, as_of=AS_OF,
    )
    evidence = build_esg_legal_evidence(openapi=(audit,), claims=())

    row = evidence.check("R40")
    assert row.status == "unresolved"
    assert row.applicability == "unresolved"
    assert audit.record.citation.evidence_id in row.evidence_ids
    assert "稽核百分比" in row.unresolved_reasons[0]


def test_r40_requires_explicit_original_supplier_concentration_or_counterevidence() -> None:
    concentrated = ClaimEvidence(
        claim_type="supplier_concentration",
        signal="risk",
        terms=("single_source", "no_qualified_alternative"),
        citation=_citation("annual:supplier-risk", "關鍵原料A目前為單一供應來源，尚無合格替代供應商。"),
    )
    diversified = ClaimEvidence(
        claim_type="supplier_concentration",
        signal="counterevidence",
        terms=("dual_source", "qualified_alternative"),
        citation=_citation("annual:supplier-buffer", "關鍵原料A已完成雙來源認證，第二供應商已取得量產資格。"),
    )

    triggered = build_esg_legal_evidence(openapi=(), claims=(concentrated,)).check("R40")
    not_triggered = build_esg_legal_evidence(openapi=(), claims=(diversified,)).check("R40")

    assert (triggered.status, triggered.applicability) == ("evaluated", "triggered")
    assert (not_triggered.status, not_triggered.applicability) == ("evaluated", "not_triggered")
    assert not_triggered.counterevidence


def test_key_material_row_rejects_esg_heading_and_requires_actual_terms() -> None:
    heading = ClaimEvidence(
        claim_type="key_material_commitment",
        signal="risk",
        terms=("esg_heading",),
        citation=_citation("sustainability:heading", "永續供應鏈與關鍵材料管理"),
    )
    actual = ClaimEvidence(
        claim_type="key_material_commitment",
        signal="risk",
        terms=("non_cancellable_commitment", "prepayment", "contract_amount"),
        citation=_citation("annual:key-material", "矽晶圓長期採購合約不可取消，已預付新台幣30億元。"),
    )

    unresolved = build_esg_legal_evidence(openapi=(), claims=(heading,)).check("I-MFG-03")
    triggered = build_esg_legal_evidence(openapi=(), claims=(actual,)).check("I-MFG-03")

    assert unresolved.status == "unresolved"
    assert "實際合約" in unresolved.unresolved_reasons[0]
    assert (triggered.status, triggered.applicability) == ("evaluated", "triggered")


def test_anti_competition_zero_is_only_metric_year_and_not_no_litigation() -> None:
    loss = parse_openapi_payload(
        body=_payload("t187ap46_L_20", "0.000"), market="TWSE",
        dataset_id="t187ap46_L_20", security_code="2330", company_name="台積電",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap46_L_20",
        retrieved_at=RETRIEVED_AT, as_of=AS_OF,
    )
    row = build_esg_legal_evidence(openapi=(loss,), claims=()).check("R37")

    assert row.status == "unresolved"
    assert row.applicability == "unresolved"
    assert "僅代表該欄位與年度" in row.observations[0]
    assert "no litigation" not in " ".join((*row.observations, *row.counterevidence)).lower()


def test_r37_triggered_and_not_triggered_require_original_notes_and_mops_coverage() -> None:
    litigation = ClaimEvidence(
        claim_type="litigation_contingency",
        signal="risk",
        terms=("case_identity", "amount", "status", "provision"),
        citation=_citation("note:litigation", "專利訴訟案號123，請求金額5億元，審理中，已提列準備1億元。", family="financial-note"),
    )
    no_material_case = ClaimEvidence(
        claim_type="litigation_contingency",
        signal="counterevidence",
        terms=("explicit_no_material_case", "complete_contingency_note"),
        citation=_citation("note:no-material-litigation", "截至期末無尚未結案之重大訴訟或仲裁。", family="financial-note"),
    )
    triggered = build_esg_legal_evidence(openapi=(), claims=(litigation,)).check("R37")
    unresolved = build_esg_legal_evidence(openapi=(), claims=(no_material_case,)).check("R37")
    not_triggered = build_esg_legal_evidence(
        openapi=(), claims=(no_material_case,),
        original_coverage=OriginalSourceCoverage(
            litigation_note_complete=True,
            mops_event_query_complete=True,
            relevant_mops_event_evidence_ids=(),
            bounded_through=date(2026, 8, 3),
        ),
    ).check("R37")

    assert (triggered.status, triggered.applicability) == ("evaluated", "triggered")
    assert unresolved.status == "unresolved"
    assert (not_triggered.status, not_triggered.applicability) == ("evaluated", "not_triggered")


def test_twse_cyber_metrics_are_context_only_without_inventing_a_checklist_row() -> None:
    cyber = parse_openapi_payload(
        body=_payload("t187ap46_L_16", "0"), market="TWSE",
        dataset_id="t187ap46_L_16", security_code="2330", company_name="台積電",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap46_L_16",
        retrieved_at=RETRIEVED_AT, as_of=AS_OF,
    )
    evidence = build_esg_legal_evidence(openapi=(cyber,), claims=())

    assert cyber.record.claim_scope == "cyber_breach_context"
    assert {row.check_id for row in evidence.checks} == {"R37", "R40", "I-MFG-03"}
    assert cyber.record.citation.evidence_id in evidence.context_evidence_ids
