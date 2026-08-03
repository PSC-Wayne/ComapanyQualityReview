"""Claim-bounded ESG, supply-chain, key-material and legal evidence.

The ESG OpenAPI feeds are official *windows* for the exact fields they publish.
Supplier-audit coverage does not establish supplier concentration; anti-competition
losses do not establish the absence of other litigation; the TWSE cyber feed is
context because the authority checklist has no generic cyber row.  Substantive
R37/R40/I-MFG-03 conclusions therefore require original report/note/event evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Literal, Mapping, Sequence, cast
from zoneinfo import ZoneInfo

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation, Market

_TAIPEI = ZoneInfo("Asia/Taipei")
ClaimScope = Literal[
    "supplier_audit_context",
    "anti_competition_loss_context",
    "cyber_breach_context",
]
ClaimType = Literal[
    "supplier_concentration",
    "key_material_commitment",
    "litigation_contingency",
]
Signal = Literal["risk", "counterevidence"]


@dataclass(frozen=True, slots=True)
class _Dataset:
    market: Market
    source_url: str
    claim_scope: ClaimScope
    value_fields: tuple[str, ...]


_COMMON_FIELDS = ("出表日期", "報告年度", "公司代號", "公司名稱")
_SUPPLIER_FIELDS = (
    "採購符合國際認可之產品責任標準者占整體採購之百分比，並依標準區分",
    "對供應商進行稽核之家數(家)",
    "對供應商進行稽核之百分比",
)
_ANTI_COMPETITION_FIELD = "因與反競爭行為條例相關的法律訴訟而造成的金錢損失總額(仟元)"
_CYBER_FIELDS = (
    "資訊外洩事件數量",
    "與個資相關的資訊外洩事件占比",
    "因資訊外洩事件而受影響的顧客數(人)",
)
_DATASETS: dict[str, _Dataset] = {
    "t187ap46_L_13": _Dataset(
        "TWSE",
        "https://openapi.twse.com.tw/v1/opendata/t187ap46_L_13",
        "supplier_audit_context",
        _SUPPLIER_FIELDS,
    ),
    "t187ap46_O_13": _Dataset(
        "TPEx",
        "https://www.tpex.org.tw/openapi/v1/t187ap46_O_13",
        "supplier_audit_context",
        _SUPPLIER_FIELDS,
    ),
    "t187ap46_L_20": _Dataset(
        "TWSE",
        "https://openapi.twse.com.tw/v1/opendata/t187ap46_L_20",
        "anti_competition_loss_context",
        (_ANTI_COMPETITION_FIELD,),
    ),
    "t187ap46_O_20": _Dataset(
        "TPEx",
        "https://www.tpex.org.tw/openapi/v1/t187ap46_O_20",
        "anti_competition_loss_context",
        (_ANTI_COMPETITION_FIELD,),
    ),
    # No verified TPEx parity and no generic checklist cyber row.
    "t187ap46_L_16": _Dataset(
        "TWSE",
        "https://openapi.twse.com.tw/v1/opendata/t187ap46_L_16",
        "cyber_breach_context",
        _CYBER_FIELDS,
    ),
}
_NA = frozenset({"", "-", "--", "N/A", "NA", "不適用", "未申報"})


class EsgEvidenceError(ValueError):
    """Raised when an official source cannot be admitted at its exact shape."""


def _instant(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise EsgEvidenceError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EsgEvidenceError(f"{field} must be timezone-aware")
    return parsed


def _roc_date(value: str) -> date:
    if len(value) != 7 or not value.isdigit():
        raise EsgEvidenceError("invalid 出表日期")
    try:
        return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:]))
    except ValueError as exc:
        raise EsgEvidenceError("invalid 出表日期") from exc


def _period(value: str) -> str:
    if not value.isdigit() or len(value) not in {2, 3}:
        raise EsgEvidenceError("invalid 報告年度")
    return value


@dataclass(frozen=True, slots=True)
class OpenApiRecord:
    market: Market
    dataset_id: str
    security_code: str
    reported_company_name: str
    report_year: str
    output_date: date
    fields: Mapping[str, str]
    claim_scope: ClaimScope
    citation: EvidenceCitation


@dataclass(frozen=True, slots=True)
class OpenApiParseResult:
    dataset_id: str
    status: Literal["available", "unresolved"]
    record: OpenApiRecord | None
    unresolved_reason: str | None

    def __post_init__(self) -> None:
        if self.status == "available" and self.record is None:
            raise EsgEvidenceError("available OpenAPI result requires a record")
        if self.status == "unresolved" and not self.unresolved_reason:
            raise EsgEvidenceError("unresolved OpenAPI result requires a reason")


def parse_openapi_payload(
    *,
    body: bytes,
    market: Market,
    dataset_id: str,
    security_code: str,
    company_name: str,
    source_url: str,
    retrieved_at: str,
    as_of: str,
) -> OpenApiParseResult:
    """Admit one exact company row; feed absence and N/A remain unresolved."""

    dataset = _DATASETS.get(dataset_id)
    if dataset is None:
        raise EsgEvidenceError(f"unsupported dataset: {dataset_id}")
    if market != dataset.market:
        raise EsgEvidenceError("dataset market mismatch")
    if source_url != dataset.source_url:
        raise EsgEvidenceError("dataset source URL mismatch")
    retrieved = _instant(retrieved_at, "retrieved_at")
    decision = _instant(as_of, "as_of")
    if retrieved > decision:
        raise EsgEvidenceError("retrieved_at after as_of")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EsgEvidenceError("invalid OpenAPI JSON") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise EsgEvidenceError("OpenAPI payload must be an array of objects")
    matches = [item for item in payload if str(item.get("公司代號", "")).strip() == security_code]
    if not matches:
        return OpenApiParseResult(
            dataset_id,
            "unresolved",
            None,
            f"current_feed_absence:{dataset_id}:{security_code};absence_is_not_zero_or_no_risk",
        )
    if len(matches) != 1:
        raise EsgEvidenceError("duplicate company rows in OpenAPI payload")
    row = cast(dict[str, object], matches[0])
    required = (*_COMMON_FIELDS, *dataset.value_fields)
    missing = tuple(field for field in required if field not in row)
    if missing:
        raise EsgEvidenceError("missing required fields: " + ",".join(missing))
    output_date = _roc_date(str(row["出表日期"]).strip())
    available_at = datetime.combine(output_date, datetime.min.time(), _TAIPEI)
    if available_at > decision:
        raise EsgEvidenceError("OpenAPI row after as_of")
    report_year = _period(str(row["報告年度"]).strip())
    reported_name = str(row["公司名稱"]).strip()
    if not reported_name or not company_name.strip():
        raise EsgEvidenceError("company name unavailable")
    values = {field: str(row[field]).strip() for field in dataset.value_fields}
    digest = sha256(body).hexdigest()
    excerpt = json.dumps(
        {field: str(row[field]).strip() for field in required},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    citation = EvidenceCitation(
        evidence_id=f"openapi:{market}:{dataset_id}:{security_code}:{report_year}:{digest[:16]}",
        source_id=f"openapi:{market}:{dataset_id}",
        source_tier="official",
        url=source_url,
        content_sha256=digest,
        period=report_year,
        available_at=available_at.isoformat(),
        page=None,
        coordinate=None,
        verbatim_excerpt=excerpt,
        source_format="json",
        locator=f"dataset:{dataset_id};公司代號:{security_code};報告年度:{report_year}",
    )
    record = OpenApiRecord(
        market=market,
        dataset_id=dataset_id,
        security_code=security_code,
        reported_company_name=reported_name,
        report_year=report_year,
        output_date=output_date,
        fields=values,
        claim_scope=dataset.claim_scope,
        citation=citation,
    )
    unavailable = tuple(field for field, value in values.items() if value.upper() in _NA)
    if len(unavailable) == len(values):
        return OpenApiParseResult(
            dataset_id,
            "unresolved",
            record,
            f"all_claim_fields_empty_or_na:{dataset_id}:{security_code};not_disclosed_is_not_zero",
        )
    return OpenApiParseResult(dataset_id, "available", record, None)


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    """A claim already extracted from a cited original report/note/event.

    ``terms`` records which claim-specific facts the excerpt actually contains;
    generic headings never satisfy the admission rules below.
    """

    claim_type: ClaimType
    signal: Signal
    terms: tuple[str, ...]
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if self.citation.source_tier not in {"official", "issuer_primary"}:
            raise EsgEvidenceError("original claim requires official or issuer-primary evidence")
        if not self.terms or not self.citation.verbatim_excerpt.strip():
            raise EsgEvidenceError("original claim requires terms and verbatim excerpt")


@dataclass(frozen=True, slots=True)
class OriginalSourceCoverage:
    litigation_note_complete: bool = False
    mops_event_query_complete: bool = False
    relevant_mops_event_evidence_ids: tuple[str, ...] = ()
    bounded_through: date | None = None


@dataclass(frozen=True, slots=True)
class EsgLegalEvidence:
    checks: tuple[ChecklistCheckResult, ...]
    citations: tuple[EvidenceCitation, ...]
    context_evidence_ids: tuple[str, ...]
    unresolved_reasons: tuple[str, ...]
    schema_version: Literal["EsgLegalEvidence.v1"] = "EsgLegalEvidence.v1"

    def check(self, check_id: str) -> ChecklistCheckResult:
        try:
            return next(item for item in self.checks if item.check_id == check_id)
        except StopIteration as exc:
            raise KeyError(check_id) from exc


def _unresolved(
    check_id: str,
    domain: Literal["risk", "industry"],
    reason: str,
    *,
    evidence_ids: Sequence[str] = (),
    observations: Sequence[str] = (),
    applicability: Literal["unresolved", "triggered"] = "unresolved",
) -> ChecklistCheckResult:
    return ChecklistCheckResult(
        check_id=check_id,
        domain=domain,
        applicability=applicability,
        status="unresolved",
        first_detectable_at=None,
        financial_period=None,
        observations=tuple(observations),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        supporting_evidence=(),
        counterevidence=(),
        inference_chain=("官方欄位／原始文件 → claim-specific boundary → 尚缺指定證據",),
        mechanism="資料缺口不得解讀為不存在風險。",
        leading_warnings=(),
        buffers=(),
        monitoring_metrics=(),
        monitoring_date=None,
        invalidation_or_resolution_conditions=("補齊本題指定原始文件、欄位、期間與反證。",),
        severity="not_applicable",
        confidence="low",
        unresolved_reasons=(reason,),
    )


def _evaluated(
    check_id: str,
    domain: Literal["risk", "industry"],
    claim: ClaimEvidence,
    *,
    mechanism: str,
    monitoring: tuple[str, ...],
) -> ChecklistCheckResult:
    triggered = claim.signal == "risk"
    return ChecklistCheckResult(
        check_id=check_id,
        domain=domain,
        applicability="triggered" if triggered else "not_triggered",
        status="evaluated",
        first_detectable_at=claim.citation.available_at,
        financial_period=claim.citation.period,
        observations=(claim.citation.verbatim_excerpt,),
        evidence_ids=(claim.citation.evidence_id,),
        supporting_evidence=(claim.citation.verbatim_excerpt,) if triggered else (),
        counterevidence=() if triggered else (claim.citation.verbatim_excerpt,),
        inference_chain=("原始年報／附註／重大訊息逐字原文 → 指定事實 → 清單題",),
        mechanism=mechanism,
        leading_warnings=monitoring,
        buffers=() if triggered else (claim.citation.verbatim_excerpt,),
        monitoring_metrics=monitoring,
        monitoring_date=None,
        invalidation_or_resolution_conditions=("新一期原始文件或重大事件更新目前事實。",),
        severity="high" if triggered and domain == "risk" else "medium" if triggered else "low",
        confidence="high",
        unresolved_reasons=(),
    )


def _claims(
    values: Sequence[ClaimEvidence], claim_type: ClaimType
) -> tuple[ClaimEvidence, ...]:
    return tuple(item for item in values if item.claim_type == claim_type)


def _admitted_supplier(claim: ClaimEvidence) -> bool:
    terms = set(claim.terms)
    if claim.signal == "risk":
        return bool(terms & {"single_source", "supplier_share", "no_qualified_alternative"})
    return {"dual_source", "qualified_alternative"}.issubset(terms)


def _admitted_key_material(claim: ClaimEvidence) -> bool:
    terms = set(claim.terms)
    actual = {
        "long_term_contract",
        "prepayment",
        "non_cancellable_commitment",
        "contract_amount",
        "contract_term",
    }
    if claim.signal == "risk":
        return bool(terms & actual)
    return {"explicit_no_key_material_commitment", "complete_commitment_note"}.issubset(terms)


def _admitted_litigation(claim: ClaimEvidence) -> bool:
    terms = set(claim.terms)
    if claim.signal == "risk":
        return {"case_identity", "status"}.issubset(terms) and bool(
            terms & {"amount", "provision", "licence_risk", "patent_risk"}
        )
    return {"explicit_no_material_case", "complete_contingency_note"}.issubset(terms)


def _anti_competition_observation(record: OpenApiRecord) -> tuple[str, Decimal | None]:
    raw = record.fields[_ANTI_COMPETITION_FIELD]
    try:
        value = None if raw.upper() in _NA else Decimal(raw.replace(",", ""))
    except InvalidOperation:
        value = None
    if value == 0:
        return (
            f"{record.report_year}年度反競爭訴訟金錢損失欄位為0；僅代表該欄位與年度，不代表無其他訴訟。",
            value,
        )
    if value is None:
        return (
            f"{record.report_year}年度反競爭訴訟金錢損失欄位空白、N/A或不可解析；維持未解決。",
            None,
        )
    return (f"{record.report_year}年度反競爭訴訟金錢損失為{value}仟元。", value)


def build_esg_legal_evidence(
    *,
    openapi: Sequence[OpenApiParseResult],
    claims: Sequence[ClaimEvidence],
    original_coverage: OriginalSourceCoverage | None = None,
) -> EsgLegalEvidence:
    """Build only R37, R40 and I-MFG-03; cyber remains explicit context."""

    coverage = original_coverage or OriginalSourceCoverage()
    records = tuple(item.record for item in openapi if item.record is not None)
    context_ids = tuple(dict.fromkeys(item.citation.evidence_id for item in records))
    reasons = tuple(
        dict.fromkeys(
            item.unresolved_reason
            for item in openapi
            if item.unresolved_reason is not None
        )
    )

    supplier_claims = tuple(item for item in _claims(claims, "supplier_concentration") if _admitted_supplier(item))
    if supplier_claims:
        r40 = _evaluated(
            "R40",
            "risk",
            supplier_claims[0],
            mechanism="單一或高度集中供應來源會放大中斷、交期、地緣與成本轉嫁風險。",
            monitoring=("最大供應商占比", "單一來源料號", "替代來源認證", "安全庫存"),
        )
    else:
        supplier_context = tuple(
            item.citation.evidence_id
            for item in records
            if item.claim_scope == "supplier_audit_context"
        )
        r40 = _unresolved(
            "R40",
            "risk",
            "供應商稽核家數或稽核百分比不證明供應商集中；尚缺年報／永續報告原文中的關鍵料源、占比與替代來源。",
            evidence_ids=supplier_context,
            observations=("OpenAPI供應商稽核欄位僅作供應鏈管理context。",) if supplier_context else (),
        )

    key_material_ids = tuple(
        item.citation.evidence_id for item in _claims(claims, "key_material_commitment")
    )
    admitted_key_material = tuple(
        item for item in _claims(claims, "key_material_commitment") if _admitted_key_material(item)
    )
    key_material = _unresolved(
        "I-MFG-03",
        "industry",
        (
            "已取得部分關鍵材料合約context，但仍須由製造業producer完成簽署承諾、長期／不可取消／預付款、取消條款與需求支持；單一附註不能完成本題。"
            if admitted_key_material
            else "ESG標題、一般關鍵字或current-feed absence不是實際合約；尚缺製造業producer要求的完整條款與需求支持。"
        ),
        evidence_ids=key_material_ids,
        observations=tuple(item.citation.verbatim_excerpt for item in admitted_key_material),
        applicability="triggered" if any(item.signal == "risk" for item in admitted_key_material) else "unresolved",
    )

    litigation_claims = tuple(item for item in _claims(claims, "litigation_contingency") if _admitted_litigation(item))
    risk_claim = next((item for item in litigation_claims if item.signal == "risk"), None)
    counter_claim = next((item for item in litigation_claims if item.signal == "counterevidence"), None)
    anti_records = tuple(item for item in records if item.claim_scope == "anti_competition_loss_context")
    anti_observations = tuple(_anti_competition_observation(item) for item in anti_records)
    anti_ids = tuple(item.citation.evidence_id for item in anti_records)
    positive_loss = any(value is not None and value > 0 for _, value in anti_observations)
    if risk_claim is not None:
        r37 = _evaluated(
            "R37",
            "risk",
            risk_claim,
            mechanism="訴訟或仲裁可能經由賠償、準備、禁制令、執照或專利限制傳導至現金與營運。",
            monitoring=("案件進度", "請求金額", "律師評估", "準備提列", "MOPS重大訊息"),
        )
    elif (
        counter_claim is not None
        and coverage.litigation_note_complete
        and coverage.mops_event_query_complete
        and not coverage.relevant_mops_event_evidence_ids
        and coverage.bounded_through is not None
    ):
        r37 = _evaluated(
            "R37",
            "risk",
            counter_claim,
            mechanism="完整或有事項附註與有界MOPS查詢在該範圍未觸發重大案件；範圍外仍不作不存在推論。",
            monitoring=("新訴訟／仲裁重大訊息", "或有事項附註", "期後事項"),
        )
    else:
        reason = (
            "反競爭損失為正僅觸發法律風險追查；尚缺案件、金額、進度、準備與MOPS重大訊息原文。"
            if positive_loss
            else "反競爭損失為零、空白或當期未命中不能推論無訴訟；尚缺完整或有事項附註與有界MOPS事件查詢。"
        )
        r37 = _unresolved(
            "R37",
            "risk",
            reason,
            evidence_ids=(
                *anti_ids,
                *(counter_claim.citation.evidence_id for counter_claim in ([counter_claim] if counter_claim else [])),
                *coverage.relevant_mops_event_evidence_ids,
            ),
            observations=tuple(item[0] for item in anti_observations),
            applicability="triggered" if positive_loss or coverage.relevant_mops_event_evidence_ids else "unresolved",
        )

    citations = tuple(
        {
            item.evidence_id: item
            for item in (
                *(record.citation for record in records),
                *(claim.citation for claim in claims),
            )
        }.values()
    )
    return EsgLegalEvidence(
        checks=(r37, r40, key_material),
        citations=citations,
        context_evidence_ids=context_ids,
        unresolved_reasons=reasons,
    )


__all__ = [
    "ClaimEvidence",
    "EsgEvidenceError",
    "EsgLegalEvidence",
    "OpenApiParseResult",
    "OpenApiRecord",
    "OriginalSourceCoverage",
    "build_esg_legal_evidence",
    "parse_openapi_payload",
]
