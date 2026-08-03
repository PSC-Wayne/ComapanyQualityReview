"""Claim-bounded producers for the eight previously missing Growth checks.

The producers consume already materialized, point-in-time facts.  They do not
fetch data and they deliberately do not derive receivable, inventory, debt
maturity, covenant, or other working-capital/solvency conclusions owned by the
risk producers.  Every required component needs its own evidence handle;
missing components, horizons, lineage, and non-positive growth denominators
fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal, Mapping, Sequence

from company_quality.company_analysis.checklist_contracts import ChecklistCheckResult
from company_quality.company_analysis.contracts import EvidenceCitation

GrowthCheckId = Literal["G08", "G14", "G15", "G16", "G17", "G18", "G20", "G21"]


@dataclass(frozen=True, slots=True)
class GrowthProducerSpec:
    check_id: GrowthCheckId
    required_facts: tuple[str, ...]
    monitoring: tuple[str, ...]
    mechanism: str


GROWTH_PRODUCER_SPECS: dict[GrowthCheckId, GrowthProducerSpec] = {
    "G08": GrowthProducerSpec(
        "G08",
        (
            "prior_basic_eps", "current_basic_eps", "prior_attributable_profit",
            "current_attributable_profit", "prior_weighted_average_shares",
            "current_weighted_average_shares", "prior_diluted_shares",
            "current_diluted_shares", "treasury_share_change",
            "capital_reduction_change", "prior_net_debt", "current_net_debt",
        ),
        ("歸母淨利", "基本／稀釋EPS", "加權平均／稀釋股數", "庫藏股／減資", "淨負債"),
        "EPS若成長快於歸母淨利，須以股數、庫藏股、減資與淨負債脈絡解釋，不能當作營運成長。",
    ),
    "G14": GrowthProducerSpec(
        "G14",
        (
            "prior_ppe", "current_ppe", "prior_cip", "current_cip",
            "prior_revenue", "current_revenue", "promise_type", "promise_date",
            "measurement_date",
        ),
        ("PPE", "在建工程", "營收", "官方完工／量產承諾日", "稼動率／減損"),
        "只有到達原始官方完工或ramp承諾日後，固定資產增加而營收未跟上才觸發逾期檢查。",
    ),
    "G15": GrowthProducerSpec(
        "G15",
        (
            "annual_periods", "annual_ocf", "annual_capex", "unrestricted_cash",
            "growth_claim", "growth_claim_horizon",
        ),
        ("3A／5A FCF", "不受限制現金", "資金runway", "原始成長主張與期間"),
        "長期負FCF與高速成長主張必須同時呈現3年、5年現金結果及僅由既有現金推算的runway。",
    ),
    "G16": GrowthProducerSpec(
        "G16",
        (
            "prior_rd_expense", "current_rd_expense", "prior_capitalized_development",
            "current_capitalized_development", "prior_product_revenue",
            "current_product_revenue", "product_identity",
        ),
        ("研發費用", "資本化開發成本", "資本化比例", "指定產品營收", "後續減損"),
        "研發投入須合併費用化與資本化開發成本，並連到可識別產品收入，不能只看費用率。",
    ),
    "G17": GrowthProducerSpec(
        "G17",
        (
            "opening_contract_liabilities", "contract_liability_additions",
            "revenue_recognized_from_contract_liabilities", "refunds",
            "closing_contract_liabilities", "next_period_conversion",
            "cancellation_or_refund_terms",
        ),
        ("合約負債roll-forward", "退款／取消條款", "次期轉收入"),
        "合約負債增加只有在期初至期末變動、退款權及次期實際轉收入完整時才可判讀。",
    ),
    "G18": GrowthProducerSpec(
        "G18",
        (
            "prior_backlog", "current_backlog", "pipeline", "binding_backlog",
            "cancellable_backlog", "performance_period", "pricing_adjustment_terms",
            "expected_backlog_margin", "backlog_cash_collected",
        ),
        ("具約束力backlog", "可取消額", "履約期", "調價", "毛利", "收現"),
        "Pipeline不是backlog；backlog必須沿取消、履約、價格、毛利與收現鏈判讀。",
    ),
    "G20": GrowthProducerSpec(
        "G20",
        (
            "geography", "currency", "prior_local_revenue", "current_local_revenue",
            "prior_translated_revenue", "current_translated_revenue", "local_profit",
            "translation_fx_effect", "local_tax", "remittance_restriction",
        ),
        ("地區原幣營收", "換算營收", "FX效果", "地區利潤", "當地稅負", "匯回限制"),
        "海外成長須以原幣為主並分開換算效果、當地獲利、稅負與匯回限制。",
    ),
    "G21": GrowthProducerSpec(
        "G21",
        (
            "acquisition_effective_date", "organic_revenue", "acquired_revenue",
            "consideration", "contingent_consideration", "goodwill",
            "acquisition_debt", "shares_issued", "post_deal_revenue",
            "post_deal_profit", "post_deal_cash_flow",
        ),
        ("有機／併購營收", "對價／或有對價", "商譽", "收購負債／發股", "收購後實績"),
        "併購成長須分離有機與收購營收，並以交易對價、商譽、融資／發股及收購後實際財務結果驗證。",
    ),
}


@dataclass(frozen=True, slots=True)
class GrowthCheckInput:
    check_id: GrowthCheckId
    financial_period: str
    available_at: str
    facts: Mapping[str, object]
    evidence_by_fact: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class GrowthCheckAssessment:
    checks: tuple[ChecklistCheckResult, ...]
    limitations: tuple[str, ...]
    citations: tuple[EvidenceCitation, ...] = ()

    @property
    def by_check_id(self) -> dict[str, ChecklistCheckResult]:
        return {item.check_id: item for item in self.checks}


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _decimals(value: object, field: str) -> tuple[Decimal, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a sequence")
    return tuple(_decimal(item, field) for item in value)


def _unresolved(
    check_id: GrowthCheckId,
    *reasons: str,
    item: GrowthCheckInput | None = None,
) -> ChecklistCheckResult:
    spec = GROWTH_PRODUCER_SPECS[check_id]
    return ChecklistCheckResult(
        check_id=check_id,
        domain="growth",
        applicability="unresolved",
        status="unresolved",
        first_detectable_at=item.available_at if item else None,
        financial_period=item.financial_period if item else None,
        observations=(),
        evidence_ids=tuple(dict.fromkeys(item.evidence_by_fact.values())) if item else (),
        supporting_evidence=(),
        counterevidence=(),
        inference_chain=("claim-specific facts → 完整性／期間／分母檢查 → 維持未解決",),
        mechanism=spec.mechanism,
        leading_warnings=spec.monitoring,
        buffers=(),
        monitoring_metrics=spec.monitoring,
        monitoring_date=None,
        invalidation_or_resolution_conditions=("補齊本題指定期間、組成與原始來源後重新判定。",),
        severity="not_applicable",
        confidence="low",
        unresolved_reasons=tuple(reasons) or ("權威證據不足。",),
    )


def _evaluated(
    item: GrowthCheckInput,
    *,
    triggered: bool,
    observations: Sequence[str],
) -> ChecklistCheckResult:
    spec = GROWTH_PRODUCER_SPECS[item.check_id]
    evidence_ids = tuple(dict.fromkeys(item.evidence_by_fact[name] for name in spec.required_facts))
    return ChecklistCheckResult(
        check_id=item.check_id,
        domain="growth",
        applicability="triggered" if triggered else "not_triggered",
        status="evaluated",
        first_detectable_at=item.available_at,
        financial_period=item.financial_period,
        observations=tuple(observations),
        evidence_ids=evidence_ids,
        supporting_evidence=("本題指定期間、組成與來源均已取得。",) if triggered else (),
        counterevidence=() if triggered else ("完整同口徑資料未達本題現象。",),
        inference_chain=("原始來源facts → 同口徑組成／期間 → 清單現象判定",),
        mechanism=spec.mechanism,
        leading_warnings=spec.monitoring,
        buffers=("本producer不替代營運資金、債務到期或契約風險producer。",),
        monitoring_metrics=spec.monitoring,
        monitoring_date=None,
        invalidation_or_resolution_conditions=("後續同口徑實際數據或原始承諾更新。",),
        severity="not_applicable",
        confidence="high",
        unresolved_reasons=(),
    )


def _growth(prior: Decimal, current: Decimal) -> Decimal | None:
    return None if prior <= 0 else current / prior - 1


def _produce_g08(item: GrowthCheckInput) -> ChecklistCheckResult:
    f = item.facts
    eps = _growth(_decimal(f["prior_basic_eps"], "prior_basic_eps"), _decimal(f["current_basic_eps"], "current_basic_eps"))
    profit = _growth(
        _decimal(f["prior_attributable_profit"], "prior_attributable_profit"),
        _decimal(f["current_attributable_profit"], "current_attributable_profit"),
    )
    if eps is None or profit is None:
        return _unresolved("G08", "EPS與歸母淨利成長率只允許正數分母；零、負數或虧損轉折須維持未解決並改用文字描述。", item=item)
    observations = (
        f"基本EPS成長={eps:.2%}；歸母淨利成長={profit:.2%}。",
        f"加權平均股數{f['prior_weighted_average_shares']}→{f['current_weighted_average_shares']}；"
        f"稀釋股數{f['prior_diluted_shares']}→{f['current_diluted_shares']}。",
        f"庫藏股變動={f['treasury_share_change']}；減資變動={f['capital_reduction_change']}；"
        f"淨負債{f['prior_net_debt']}→{f['current_net_debt']}（僅作資本結構context）。",
    )
    return _evaluated(item, triggered=eps > profit, observations=observations)


def _produce_g14(item: GrowthCheckInput) -> ChecklistCheckResult:
    f = item.facts
    promise = _date(f["promise_date"], "promise_date")
    measured = _date(f["measurement_date"], "measurement_date")
    asset_prior = _decimal(f["prior_ppe"], "prior_ppe") + _decimal(f["prior_cip"], "prior_cip")
    asset_current = _decimal(f["current_ppe"], "current_ppe") + _decimal(f["current_cip"], "current_cip")
    revenue_prior = _decimal(f["prior_revenue"], "prior_revenue")
    revenue_current = _decimal(f["current_revenue"], "current_revenue")
    if measured < promise:
        return _evaluated(
            item,
            triggered=False,
            observations=(f"{f['promise_type']}承諾日={promise}；衡量日={measured}尚未到期，不以後來結果回填。",),
        )
    return _evaluated(
        item,
        triggered=asset_current > asset_prior and revenue_current <= revenue_prior,
        observations=(
            f"{f['promise_type']}承諾日={promise}；衡量日={measured}。",
            f"PPE+CIP {asset_prior}→{asset_current}；營收{revenue_prior}→{revenue_current}。",
        ),
    )


def _produce_g15(item: GrowthCheckInput) -> ChecklistCheckResult:
    f = item.facts
    periods = tuple(str(value) for value in f["annual_periods"])  # type: ignore[union-attr]
    ocf = _decimals(f["annual_ocf"], "annual_ocf")
    capex = _decimals(f["annual_capex"], "annual_capex")
    if len(periods) < 5 or len(ocf) != len(periods) or len(capex) != len(periods):
        return _unresolved("G15", "rolling 3A/5A FCF需要至少五個同口徑年度及逐年OCF、CAPEX。", item=item)
    fcf = tuple(cash - abs(spend) for cash, spend in zip(ocf, capex, strict=True))
    three = sum(fcf[-3:], Decimal("0"))
    five = sum(fcf[-5:], Decimal("0"))
    annual_burn = -three / Decimal("3") if three < 0 else Decimal("0")
    cash = _decimal(f["unrestricted_cash"], "unrestricted_cash")
    runway = cash / annual_burn if annual_burn > 0 else None
    return _evaluated(
        item,
        triggered=three < 0 and five < 0 and bool(str(f["growth_claim"]).strip()),
        observations=(
            f"{periods[-5]}~{periods[-1]}：3A累計FCF={three}；5A累計FCF={five}。",
            f"不受限制現金={cash}；以3A平均負FCF估算runway={'不適用' if runway is None else f'{runway:.2f}年'}。",
            f"成長主張={f['growth_claim']}；主張期間={f['growth_claim_horizon']}；不以主張取代實際FCF。",
        ),
    )


def _produce_g16(item: GrowthCheckInput) -> ChecklistCheckResult:
    f = item.facts
    prior_expense = _decimal(f["prior_rd_expense"], "prior_rd_expense")
    current_expense = _decimal(f["current_rd_expense"], "current_rd_expense")
    prior_cap = _decimal(f["prior_capitalized_development"], "prior_capitalized_development")
    current_cap = _decimal(f["current_capitalized_development"], "current_capitalized_development")
    prior_total, current_total = prior_expense + prior_cap, current_expense + current_cap
    current_ratio = current_cap / current_total if current_total > 0 else None
    return _evaluated(
        item,
        triggered=current_total > prior_total,
        observations=(
            f"研發費用{prior_expense}→{current_expense}；資本化開發{prior_cap}→{current_cap}；"
            f"總投入{prior_total}→{current_total}；本期資本化比例={'不適用' if current_ratio is None else f'{current_ratio:.2%}'}。",
            f"產品={f['product_identity']}；產品營收{f['prior_product_revenue']}→{f['current_product_revenue']}。",
        ),
    )


def _produce_g17(item: GrowthCheckInput) -> ChecklistCheckResult:
    f = item.facts
    opening = _decimal(f["opening_contract_liabilities"], "opening_contract_liabilities")
    additions = _decimal(f["contract_liability_additions"], "contract_liability_additions")
    revenue = _decimal(f["revenue_recognized_from_contract_liabilities"], "revenue_recognized_from_contract_liabilities")
    refunds = _decimal(f["refunds"], "refunds")
    closing = _decimal(f["closing_contract_liabilities"], "closing_contract_liabilities")
    if opening + additions - revenue - refunds != closing:
        return _unresolved("G17", "合約負債roll-forward無法勾稽：期初＋新增－轉收入－退款不等於期末。", item=item)
    return _evaluated(
        item,
        triggered=closing > opening,
        observations=(
            f"roll-forward：期初{opening}+新增{additions}-轉收入{revenue}-退款{refunds}=期末{closing}。",
            f"次期實際轉收入={f['next_period_conversion']}；取消／退款條款={f['cancellation_or_refund_terms']}。",
        ),
    )


def _produce_g18(item: GrowthCheckInput) -> ChecklistCheckResult:
    f = item.facts
    prior = _decimal(f["prior_backlog"], "prior_backlog")
    current = _decimal(f["current_backlog"], "current_backlog")
    return _evaluated(
        item,
        triggered=current > prior,
        observations=(
            f"backlog={current}（前期={prior}）；pipeline={f['pipeline']}，pipeline不得視為backlog。",
            f"具約束力={f['binding_backlog']}；可取消={f['cancellable_backlog']}；履約期={f['performance_period']}；"
            f"調價={f['pricing_adjustment_terms']}；預期毛利={f['expected_backlog_margin']}；已收現={f['backlog_cash_collected']}。",
        ),
    )


def _produce_g20(item: GrowthCheckInput) -> ChecklistCheckResult:
    f = item.facts
    prior = _decimal(f["prior_local_revenue"], "prior_local_revenue")
    current = _decimal(f["current_local_revenue"], "current_local_revenue")
    local_growth = _growth(prior, current)
    if local_growth is None:
        return _unresolved("G20", "地區原幣成長率只允許正數分母；零或負數基期須維持未解決並使用絕對額描述。", item=item)
    return _evaluated(
        item,
        triggered=local_growth > 0,
        observations=(
            f"{f['geography']}原幣{f['currency']}營收{prior}→{current}，成長={local_growth:.2%}；"
            f"換算營收{f['prior_translated_revenue']}→{f['current_translated_revenue']}；FX效果={f['translation_fx_effect']}。",
            f"地區利潤={f['local_profit']}；當地稅={f['local_tax']}；資金匯回限制={f['remittance_restriction']}。",
        ),
    )


def _produce_g21(item: GrowthCheckInput) -> ChecklistCheckResult:
    f = item.facts
    acquired = _decimal(f["acquired_revenue"], "acquired_revenue")
    return _evaluated(
        item,
        triggered=acquired > 0,
        observations=(
            f"收購生效日={f['acquisition_effective_date']}；有機營收={f['organic_revenue']}；併購營收={acquired}。",
            f"對價={f['consideration']}；或有對價={f['contingent_consideration']}；商譽={f['goodwill']}；"
            f"收購負債={f['acquisition_debt']}；發行股數={f['shares_issued']}。",
            f"收購後實績：營收={f['post_deal_revenue']}；利潤={f['post_deal_profit']}；現金流={f['post_deal_cash_flow']}。",
        ),
    )


_PRODUCERS = {
    "G08": _produce_g08,
    "G14": _produce_g14,
    "G15": _produce_g15,
    "G16": _produce_g16,
    "G17": _produce_g17,
    "G18": _produce_g18,
    "G20": _produce_g20,
    "G21": _produce_g21,
}


def build_growth_check_assessment(
    inputs: Sequence[GrowthCheckInput],
    *,
    citations: Sequence[EvidenceCitation] = (),
) -> GrowthCheckAssessment:
    """Run all eight producers, preserving absent inputs as explicit gaps."""

    by_id: dict[str, GrowthCheckInput] = {}
    for item in inputs:
        if item.check_id not in GROWTH_PRODUCER_SPECS:
            raise ValueError(f"unsupported growth check: {item.check_id}")
        if item.check_id in by_id:
            raise ValueError(f"duplicate growth check input: {item.check_id}")
        by_id[item.check_id] = item

    rows: list[ChecklistCheckResult] = []
    for check_id, spec in GROWTH_PRODUCER_SPECS.items():
        item = by_id.get(check_id)
        if item is None:
            rows.append(_unresolved(check_id, f"{check_id}尚未提供producer輸入；需要：{','.join(spec.required_facts)}。"))
            continue
        missing = tuple(name for name in spec.required_facts if name not in item.facts)
        if missing:
            rows.append(_unresolved(check_id, "缺少指定組成／期間：" + ",".join(missing), item=item))
            continue
        missing_lineage = tuple(
            name for name in spec.required_facts if not str(item.evidence_by_fact.get(name, "")).strip()
        )
        if missing_lineage:
            rows.append(_unresolved(check_id, "缺少指定原始來源：" + ",".join(missing_lineage), item=item))
            continue
        try:
            rows.append(_PRODUCERS[check_id](item))
        except (TypeError, ValueError, InvalidOperation) as exc:
            rows.append(_unresolved(check_id, f"指定輸入不可解析：{exc}", item=item))

    cited_ids = {item.evidence_id for item in citations}
    if citations:
        referenced = {evidence_id for row in rows for evidence_id in row.evidence_ids}
        missing_citations = sorted(referenced - cited_ids)
        if missing_citations:
            raise ValueError("growth checks cite missing report evidence: " + ",".join(missing_citations))
    limitations = tuple(dict.fromkeys(reason for row in rows for reason in row.unresolved_reasons))
    return GrowthCheckAssessment(tuple(rows), limitations, tuple(citations))


__all__ = [
    "GROWTH_PRODUCER_SPECS",
    "GrowthCheckAssessment",
    "GrowthCheckId",
    "GrowthCheckInput",
    "GrowthProducerSpec",
    "build_growth_check_assessment",
]
