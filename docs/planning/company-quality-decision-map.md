# Company Quality Research — Decision Map

> Status: planning draft; not an implementation specification.
> Updated: 2026-07-23
> Owner: Wayne

## Destination

形成一份可交付 `to-spec` 的公司分析評分決策基線：對台灣上市或上櫃單一公司，在明確 as-of 與固定評估期限下，輸出可稽核的公司品質分數、上漲潛力星級、下跌風險哭臉及信心／資料覆蓋資訊。

## Direct source

- Original architecture image: `C:\Users\wayne.huang\Pictures\分析公司架構.png`
- Visual roadmap: `docs/roadmap/company-quality-roadmap.html`
- Draft product specification: `docs/planning/company-quality-product-spec-draft.md`
- Multi-agent delivery operating plan: `docs/planning/company-quality-multi-agent-delivery-plan.md`
- Project root: `D:\Claude_Code\Hermes\CompanyQualityResearch`
- Current repository state at planning start: empty directory; no Git repository, README, CONTEXT, tests, or product code.

## Research authority

- `../research/company-quality-scoring-primary-sources.md`
- `../research/taiwan-company-data-authority.md`
- `../research/upside-downside-rating-methods.md`

These research notes are method and authority inputs. They do not determine Wayne's product-governance choices.

## Decisions so far

### D1 — Separate the three headline outputs

Owner-confirmed headline separation:

1. `company_quality_score`: 0–100; measures company quality independent of current price.
2. `upside_rating`: 1–5 stars; fixed 12-month ordinal valuation/opportunity rating.
3. `downside_rating`: 1–5 crying faces; fixed 12-month ordinal drawdown/permanent-loss/material-adverse-event vulnerability, plus an independent Critical Event Bomb when triggered.

Rationale:

- A good company can be an unattractive stock at an excessive price.
- High upside and high downside can coexist.
- Price changes must not mechanically rewrite the company's underlying quality.

Status: owner-confirmed.

### D2 — Use a fixed 12-month primary horizon

Wayne selected 12 months because the product targets near-term potential and risk; forecasts beyond 12 months are too remote for the headline purpose.

- Star/cry ratings use a fixed 12-month primary horizon.
- Any 24/36-month view is sensitivity context only and cannot blend into headline ratings.
- Technical and positioning evidence remains a separate two-month panel and does not alter headline quality/stars/faces in the first release.

Status: owner-confirmed; supersedes the earlier provisional 24-month default.

### D3 — Ordinal symbols are not probabilities

- Five stars do not mean a stated probability of rising.
- Five crying faces do not mean a stated probability of loss.
- Any future probability output must be a separately calibrated model with an explicit event definition and horizon.

Status: research-supported design constraint.

### D4 — Preserve evidence before aggregation

Every rating snapshot must retain:

- as-of date and decision time;
- official source artifact and source hash;
- raw and canonical facts with lineage;
- metric and model versions;
- industry route and peer set as-of;
- model assumptions and sensitivity outputs;
- missing/not-applicable reasons;
- pre-override and post-override outputs;
- reason codes, confidence, coverage, and limitations.

Status: research-supported data-governance constraint.

### D5 — Prevent duplicate scoring by evidence family

- A raw fact may feed several diagnostics, but only one primary scoring entry for the same latent construct.
- Piotroski F-score, Beneish M-score, and Altman Z-score remain diagnostic/risk tools unless an industry-specific model explicitly promotes a non-overlapping component.
- Risk absence is not automatically a quality bonus.
- Moat drivers and financial outcomes on the same causal chain cannot both receive full independent weight.

Status: research-supported model-governance constraint.

### D6 — Downside rating is a governed multi-outcome composite

Wayne selected a composite of:

1. fixed-horizon maximum drawdown vulnerability;
2. permanent capital loss vulnerability;
3. material adverse fundamental events.

These components must remain separately observable beneath the headline crying-face rating.

Status: owner-confirmed.

### D7 — Downside aggregation uses governed ordinary components plus separate critical-event treatment

Owner-confirmed:

- Maximum-drawdown, permanent-capital-loss and material-adverse-event components remain separately visible.
- Formal ordinary composite weights use PIT temporal calibration constrained to 25%–40% per component; pre-calibration equal weighting is research-only and not publishable.
- Confirmed audit/liquidity/integrity hard gates may impose a stricter floor, cap publication or produce no-rating as specified in F4.
- Critical Event Bomb is an additional warning channel: it bypasses ordinary weight limits but does not replace, force or rewrite the calculated crying faces.
- Only exact ordinary weights/buckets, cap values within owner-approved ranges and Bomb materiality thresholds remain calibration parameters.

Status: owner-confirmed; calibration boundaries do not reopen owner semantics.

### D8 — Financial-report audit is a major risk and scoring pillar

Wayne explicitly requires the system to inspect at least auditor opinion/review conclusion, going-concern uncertainty, key audit matters, emphasis/other matters, auditor changes, filing delays, corrections/restatements, notes and high-risk accounts. Annual audits and quarterly reviews must not be conflated.

Status: owner-confirmed.

### D9 — Build a five-year adverse-outcome financial-forensics laboratory

The research universe must include Taiwan stocks delisted within the most recent five years and stocks whose corporate-action-adjusted price suffered a peak-to-trough decline exceeding 50%. Their pre-event, point-in-time available financial reports must be studied for warning signs. 中鼎（9933）與森崴能源（6806）是已完成官方身分／事件驗證的 seed cases。

Status: owner-confirmed; F2/F3 event and taxonomy contracts are resolved, while calibrated thresholds remain governed research parameters.

### D10 — Add two-month technical and chip analysis

The query report must show a two-month technical view plus foreign/investment-trust/dealer trading, large-holder ownership-ratio changes, and director/supervisor share-pledge changes. Indicator calculation may use a longer warm-up window than the two-month display window.

Status: owner-confirmed.

### D11 — One query returns the complete analysis and ratings

A stock code or company-name query must resolve the company and return financial-report audit, financial quality, business, governance, downside risk, valuation, technical, chip, peer, confidence/coverage and final rating sections in one generation-bound analysis snapshot.

Status: owner-confirmed.

### D12 — Multi-agent delivery uses isolated writers, immediate exact-candidate review and serialized PM integration

Wayne requires multiple agents to work concurrently on this large project without sharing writable state. Each Worker will own one isolated worktree and produce a clean exact-SHA candidate. Every candidate will be reviewed immediately on two independent axes — Spec/Domain and Quality/Standards — and any change creates a new SHA that restarts both reviews. Only the PM may integrate reviewed candidates, one at a time, followed by cumulative merged-byte verification.

Status: owner-confirmed delivery requirement. Wayne selected GitHub protected `main` with merge queue and a dedicated least-privilege integration bot as the authoritative integration mechanism; repository/protection/bot setup remains unexecuted until separately approved.

## Proposed output contract

```yaml
analysis_snapshot:
  company: {market: listed_or_otc, security_code: string, identity_as_of: timestamp}
  as_of: timestamp
  primary_horizon: 12_months
  financial_report_audit:
    report_inventory: []
    auditor_opinions_and_review_conclusions: []
    going_concern_emphasis_other_matters: []
    key_audit_matters: []
    auditor_and_filing_integrity_events: []
    note_and_account_risk_flags: []
    historical_forensic_warning_matches: []
  quality:
    score: 0_to_100_or_null
    band: governed_label_or_null
    pillar_scores: []
  upside:
    stars: 1_to_5_or_null
    raw_location_metrics: {}
    valuation_methods: []
  downside:
    crying_faces: 1_to_5_or_null
    component_ratings: {max_drawdown: null, permanent_loss: null, adverse_events: null}
    critical_event_bomb:
      active: boolean
      trigger_evidence: []
      materiality: governed_measure_or_null
    risk_register: []
    stress_results: []
  technical:
    display_window: two_months
    warmup_window: governed_longer_window
    raw_metrics: {}
    tags: []
    subscore: null
  chip:
    institutional_flows: {}
    large_holder_changes: {}
    insider_and_pledge_changes: {}
    subscore: null
  confidence:
    evidence_confidence: governed_label
    data_coverage: governed_measure
    model_disagreement: governed_measure
  reason_codes: []
  hard_flags: []
  limitations: []
  source_manifest_ref: immutable_ref
  model_versions: []
  override:
    approved_by: wayne_or_null
    independent_review_ref: immutable_ref_or_null
    actions: [annotation_or_block_or_bomb_or_stricter_floor]
    expires_at: timestamp_or_null
    numeric_manual_edit_allowed: false
```

The schema shape is provisional. Semantics must be decided before field-level specification.

## Refined analysis architecture — Roadmap V2

The current visual authority is `docs/roadmap/company-quality-roadmap.html`, backed by `company-quality-roadmap-v2-data.js`. It contains 9 Waves and 74 visible Modules.

### Wave 0 — Query entry and authoritative data foundation

- Stock-code/company-name query and ambiguity handling.
- Single-market company/security/legal-entity identity.
- Industry/lifecycle/model routing.
- MOPS/TWSE/TPEx/TDCC raw acquisition, source hashes, PIT versioning, canonical facts and coverage.

Gate: the request resolves uniquely and every admitted fact is reproducible as-of the analysis time.

### Wave 1 — Financial-report audit and historical forensics core

- Five-year report/auditor-report completeness inventory.
- Annual audit-opinion versus quarterly review-conclusion classification.
- Going-concern uncertainty, emphasis/other matters and KAM timeline.
- Auditor/firm changes, filing delay, correction/restatement and version history.
- Note-level related-party, contingent-liability, litigation, guarantee, impairment and accounting-estimate review.
- High-risk accounts: receivables, inventory, contract assets, goodwill, capitalisation, restricted cash and debt maturity.
- Five-year delisting universe and five-year adjusted-price MDD >50% universe.
- Pre-event PIT filing panels, warning taxonomy and adverse-versus-control validation.
- 中鼎 and 森威能源 as seed cases after official identity/event verification.

Gate: every warning is evidence-linked to an event-preceding report version and exact page/coordinate; case-study findings are not promoted to a model without out-of-sample validation.

### Wave 2 — Verifiable financial quality

Growth, profitability, ROIC, cash conversion, working capital, solvency/refinancing, capital allocation and a financial-quality pillar that explicitly consumes audit-risk flags.

Gate: formulas, applicability and evidence owners are fixed; audit-integrity red flags cannot be averaged away silently.

### Wave 3 — Business quality and moat

Business model, industry/TAM/cycle, Five Forces, moat drivers, customer/product/channel concentration, supply/technology dependencies and as-of peers.

Gate: qualitative claims are dated, sourced and falsifiable; drivers do not duplicate financial outcomes.

### Wave 4 — Governance, people and adaptability

Control/board/related parties, management delivery, incentives, succession, workforce/culture and innovation/technology resilience.

Gate: observed facts, inference and analyst judgement remain separate; governance and reporting-integrity flags receive explicit treatment.

### Wave 5 — Downside risk and stress testing

Versioned risk register, audit-risk input, maximum-drawdown vulnerability, permanent-loss vulnerability, material-adverse-event vulnerability, coherent stress scenarios, critical-risk floors/vetoes and composite crying-face rating.

Gate: every risk has exposure/transmission/buffer/severity/trigger; critical audit/liquidity risks can floor, veto or block a rating.

### Wave 6 — Valuation, market expectations and upside stars

Industry-specific valuation route, DCF/FCFE/DDM, reverse DCF, controlled relative valuation, SOTP/rNPV/asset routes, scenario/sensitivity/base rates, model consensus/uncertainty and ordinal star buckets.

Gate: no single target price directly determines stars; assumptions and model disagreement remain visible.

### Wave 7 — Two-month technical and chip analysis

- Two-month official adjusted-price OHLCV display with sufficient pre-roll for indicators.
- Trend, moving averages, support/resistance, RSI, MACD, Bollinger, ATR and deterministic pattern tags.
- Foreign, investment-trust and dealer net trading.
- TDCC large-holder ratio changes with a governed holder-band definition.
- Director/supervisor/insider shareholding and pledge changes.
- Separate technical and chip subscores with reason codes and confidence.

Gate: the display window is two months but warm-up is sufficient; technical/chip evidence does not rewrite company quality.

### Wave 8 — Scoring, query result and publication

Quality pillars, anti-double-counting, weights/caps/penalties/vetoes, short-horizon versus fundamental aggregation policy, PIT champion/challenger validation, immutable query snapshot, complete navigable report, final rating card and independent review.

Gate: one generation binds source bytes, facts, models, scores and rendered report; lineage, coverage, monotonicity, sensitivity and independent-review gates pass.

## Owner decision frontier — 2026-07-23 update

Researchable facts remain resolved from authority rather than delegated to Wayne. Confirmed owner decisions are frozen here; explicitly unresolved subpoints remain open and must not be guessed during specification or ticketing.

### F1 — Headline semantics and horizon

Owner-confirmed:

- Company quality remains price-independent and describes the current structural quality state.
- Upside stars and downside outcomes use a fixed 12-month primary horizon. Wayne considers longer than 12 months too remote for the product's purpose.
- Technical/chip remains a two-month display/assessment panel.
- Any 24/36-month view is sensitivity context only and cannot replace or blend into the headline 12-month rating.

Status: confirmed.

### F2 — MDD >50% event contract

Owner-confirmed:

- Use a corporate-action and cash-distribution-adjusted daily close wealth series, not intraday extremes.
- Record the first -50% threshold crossing per independent peak-to-trough drawdown episode.
- A new independent episode requires full recovery to the prior peak.
- Market-wide crashes remain adverse observations but receive separate market/industry-relative context; they are not silently removed.
- Suspensions, delisting and missing prices remain explicit and cannot be filled with invented zero returns.

Status: confirmed.

### F3 — Five-year delisting outcome taxonomy

Owner-confirmed:

- Preserve every delisting and its cause.
- Merger and privatisation are neutral/structural controls when no adverse financial label applies.
- Financial distress, fraud, going-concern failure, negative equity, bankruptcy/reorganisation and unresolved reporting/trading violations are adverse outcomes.
- Multi-label is allowed: a privatisation/structural event can also carry financial-distress labels when pre-event evidence supports both.

Status: confirmed.

### F4 — Audit hard gates and first-occurrence treatment

Owner-confirmed:

- Missing mandatory auditor-report evidence does not suppress analysis of available financial-report content. The missing portion is explicitly marked with coverage/limitation evidence. Whether headline ratings remain publishable in this state is still Q1 below.
- Disclaimer of opinion: quality and upside are no-rating; downside is five crying faces; limitation remains visible.
- Adverse opinion: quality cap remains within the approved 20–30 severe range, upside at most one star, downside at least five crying faces. Exact cap is a governed calibration parameter unless Wayne later fixes one value.
- Going-concern material uncertainty: quality cap 40, upside at most two stars, downside at least four crying faces.
- Qualified opinion: severity-dependent penalty and quality cap at 60; pervasive/core-account effects escalate.
- Major correction, restatement, confirmed fraud or filing-integrity failure: quality cap remains within the approved 30–40 range, downside at least four crying faces, and unreliable statements produce no-rating with the reason shown.
- A KAM, emphasis matter or auditor change is negative evidence on its first occurrence; the system must not wait for recurrence before scoring it. Severity depends on the affected account, materiality, estimation uncertainty and corroborating evidence. A KAM alone is not proof of fraud, concealment or realised loss.

Status: confirmed except exact calibrated cap values.

### F5 — Company-quality pillars and fixed top-level weights

Owner-confirmed top-level weights (sum = 100%):

1. Financial-report reliability and audit completeness: 10%.
2. Earnings quality and capital efficiency: 25%.
3. Cash conversion, balance sheet and capital allocation: 25%.
4. Business model, industry position, moat and industry outlook: 25%.
5. Governance, management and shareholder alignment: 5%.
6. People, innovation and adaptability: 10%.

Industry outlook and strategic transformation are first-class evidence. A claimed AI/new-industry transition must be scored from information available at decision time — revenue/order/backlog/customer/product/R&D/capex/margin/execution evidence — and never from later share-price appreciation alone.

Audit hard gates/caps/floors remain separate from the ordinary 10% weighted contribution and cannot be averaged away.

Status: confirmed.

### F6 — Large-holder ownership bands

Owner-confirmed:

- Retain and display the full official TDCC holder-band distribution.
- Primary headline large-holder ratio uses 400 lots and above.
- 1,000 lots and above is a secondary concentration metric.
- Use ratios to outstanding/eligible shares with explicit capital-event handling rather than comparing raw share counts blindly.
- First release does not allow large-holder metrics to alter company quality.

Status: confirmed.

### F7 — Technical/chip relationship to headline ratings

Owner selected Option A:

- Technical and chip subscores are independent panels.
- They do not alter company quality, upside stars or downside crying faces in the first release.
- The report may describe timing disagreement, for example strong fundamental upside with weak technical state, without changing the headline rating.
- Any later bounded adjustment requires separate PIT evidence and a new owner decision.

Status: confirmed.

### F8 — Downside aggregation and Critical Event Bomb

Owner-confirmed:

- Maximum-drawdown, permanent-capital-loss and material-adverse-event components remain separately visible.
- Before calibration, equal-weight output may be researched but is not a publishable formal composite.
- Formal weights use PIT temporal adverse/control calibration with each ordinary component constrained to 25%–40%.
- Critical events may bypass ordinary component weight limits and produce a separate `Critical Event Bomb`; a severe realised default/loss or authoritative evidence of material misclassification/concealment must not be diluted to one-third of the composite.
- Data insufficiency produces no-rating, never a neutral three-face fill.

The Bomb is displayed independently from the crying-face composite as resolved in Q2 below. KAM alone does not prove concealment; event confirmation/materiality and authoritative accounting evidence are required.

Status: confirmed; exact materiality/trigger thresholds remain governed calibration parameters.

### F9 — First-release company/industry scope

Owner-confirmed:

- Scope is Taiwan listed and OTC companies only; unlisted companies are out of scope.
- First release supports general non-financial operating companies with analysable revenue and financial reports.
- Banks, insurance, securities, REIT/asset routes, financial/pure holding companies, pre-commercial biotech and other specialised accounting/valuation routes remain excluded until separately specified.
- Cyclical companies may enter only with cycle-aware normalisation and labels.

Status: confirmed.

### F10 — Publication and override governance

Owner-confirmed:

- Only Wayne may approve a headline override.
- An independent Reviewer is mandatory.
- Override validity is at most 90 days.
- Pre-override and post-override outputs, owner, reason, evidence, affected fields, effective time and expiry are immutable audit records.
- A newly detected financial report, material information disclosure or other governed source generation triggers a fresh model recomputation and independent re-review rather than silently carrying the old override forward.
- Repeated overrides trigger model-governance review.

Manual override cannot directly edit numeric scores/stars/faces; Q3 below records the resolved annotation/block/Bomb/stricter-floor boundary.

Status: confirmed.

## Resolved owner clarifications

### Q1 — Missing mandatory auditor evidence and headline ratings — RESOLVED

Owner decision:

- Continue full analysis of every available financial-report section.
- Publish coverage-adjusted quality score, upside stars and downside crying faces rather than forcing all headline fields to no-rating solely because mandatory auditor evidence is missing.
- Prominently emit `mandatory_audit_evidence_missing`, identify the missing report/pages/sections, expose coverage/confidence and prevent the gap from becoming zero or neutral evidence.
- This partial-evidence policy does not apply when company/report identity, source authenticity or admitted statement values themselves cannot be established; those failures remain blocked.

Status: confirmed.

### Q2 — Critical Event Bomb semantics — RESOLVED

Owner decision:

- Bomb is a separate, prominent red critical-event state displayed in addition to the crying-face panel.
- Bomb does not replace the crying faces and does not force the composite to five faces.
- All three downside components and the originally calculated composite remain visible unchanged, making any model under-reaction observable rather than silently rewritten.
- Bomb bypasses ordinary component-weight limits as a separate warning channel.
- It requires authoritative, material and currently relevant event evidence. A KAM alone is insufficient; candidate triggers include realised/default/impairment exposure of systemic materiality, confirmed material misclassification/restatement/fraud, negative-equity/going-concern collapse, or equivalent events that invalidate ordinary aggregation.

Status: confirmed; exact materiality thresholds require PIT calibration and governance.

### Q3 — Manual score editing — RESOLVED

Owner decision:

- Wayne cannot type an arbitrary replacement quality score, star count or crying-face count.
- With independent Reviewer approval, Wayne may add an annotation, block publication, add a Critical Event Bomb or impose a stricter risk floor.
- New financial reports/material information trigger recomputation under a new immutable generation and independent review.
- Numeric ratings change only from newly admitted facts, deterministic recomputation or an approved/versioned model-policy change.
- Override records retain the pre-override model output and expire within 90 days.

Status: confirmed.

## Not yet specified

- Quality normalisation and band boundaries under the fixed 10/25/25/25/5/10 top-level weights.
- Exact star and ordinary crying-face bucket boundaries.
- Minimum PIT historical sample/event count and calibrated Bomb materiality thresholds.
- Detailed UI/report layout and interaction behavior beyond the confirmed single-query full-analysis structure.
- Tracker and multi-session control-plane details.
- Probability models, if any.

## Out of scope for this planning phase

- Product code or production data acquisition.
- Implementation tickets before semantics are approved.
- Trading orders or buy/sell recommendations.
- Treating technical/positioning signals as company quality.
- Publishing precise probabilities without a separately calibrated probability model.

## MP Skills route

1. `research` + finance authority skills: audit-opinion authority, adverse-universe method and the 中鼎／森崴 seed-case dossiers are complete and independently verified.
2. `grill-with-docs` + `domain-modeling`: F1–F10 and Q1–Q3 owner decisions resolved; calibration details remain governed work.
3. `wayfinder`: this local decision map is the current fallback because no issue tracker/control plane is configured in the empty project.
4. `to-spec`: owner decisions are merged into the local draft; freeze/publish only after decision-conformance review, primary test-seam approval and final Wayne approval.
5. `to-tickets`: only after the frozen spec is approved; present tracer-bullet granularity and blocking edges to Wayne before publication.
6. `prototype` / `codebase-design` / `implement + tdd`: later, with prototype separated from production.
7. `code-review`: exact parent/candidate review after a complete candidate exists.
