# Company Quality Research — Frozen Product Specification

> Status: FROZEN FOR LOCAL TICKET PLANNING — IMPLEMENTATION NOT AUTHORIZED — NOT `ready-for-agent`
> Freeze date: 2026-07-23
> Freeze basis: owner decisions F1–F10/Q1–Q3 resolved; Owner Decision Conformance and Scoring/Domain reviews PASS; primary black-box seam approved by Wayne.
> Owner: Wayne
> Date: 2026-07-23
> Scope of this document: define product behavior and acceptance boundaries; no implementation is authorized.
> Decision authority: `company-quality-decision-map.md`
> Delivery operating model: `company-quality-multi-agent-delivery-plan.md`

## Problem Statement

Wayne needs a reproducible Taiwan listed/OTC company-analysis system that turns fragmented financial reports, auditor evidence, financial quality, business quality, governance, downside risks, valuation, recent technical structure and positioning evidence into one complete company report.

The system must not collapse unlike concepts into one opaque score. Company quality, upside opportunity and downside vulnerability have different semantics and must remain independently explainable. Every output must be point-in-time correct, traceable to authoritative source artifacts and honest about missing data, model disagreement and coverage.

The project is large enough that delivery must support several isolated agents working concurrently, with immediate independent review of every frozen candidate and serialized integration. That delivery mechanism is defined separately from the product behavior.

## Solution

Provide one company query containing stock code or company name, an optional explicit market filter, and an exact decision time. `market` is a filter and never a fallback hint: if supplied, resolution is confined to that single market; if omitted, the identity must still be unique across the governed listed/OTC and historical identity universe. `not_found`, `not_found_in_requested_market`, `ambiguous_identity` and `historical_identity_unresolved` return an identity-resolution envelope and must not generate an `AnalysisSnapshot` or publishable report. A successfully resolved query returns one immutable, generation-bound `AnalysisSnapshot` containing:

- company identity and market route;
- financial-report and auditor review;
- financial quality;
- business model, industry position, moat and industry-outlook/transformation evidence;
- governance, management, people and adaptability evidence;
- downside-risk register and stress tests;
- valuation and upside evidence;
- recent technical and chip/positioning evidence;
- peer comparison;
- source coverage, confidence and limitations;
- company-quality score from 0–100 or an explicit no-rating;
- upside rating from one to five stars or an explicit no-rating;
- three visible downside components plus a one-to-five crying-face composite or explicit no-rating;
- a separate Critical Event Bomb when authoritative material events bypass ordinary aggregation.

All report sections must bind to the same snapshot generation, source manifest, model versions and `as_of`. Critical source, audit-integrity or liquidity failures may cap, floor, veto or block publication according to an owner-approved governance policy.

## User Stories

1. As an analyst, I want to query by stock code, so that I can analyse a known security directly.
2. As an analyst, I want to query by company name, so that I do not need to remember the code.
3. As an analyst, I want ambiguous names to return candidates instead of a guessed company, so that the wrong issuer is never analysed silently.
4. As an analyst, I want company, security, market and historical-name identity resolved as of the analysis time, so that renamed or delisted companies remain reproducible.
5. As an analyst, I want all admitted facts to show source, availability time and lineage, so that I can audit the report.
6. As an analyst, I want missing, unavailable, not-applicable and failed data distinguished, so that absent evidence is not treated as zero.
7. As an analyst, I want annual audit reports distinguished from quarterly review reports, so that their assurance levels are not conflated.
8. As an analyst, I want auditor opinion or review conclusion classified, so that modified opinions remain visible.
9. As an analyst, I want going-concern uncertainty, emphasis matters and other matters displayed separately, so that an unmodified opinion cannot hide a critical paragraph.
10. As an analyst, I want key audit matters shown as a dated timeline with affected accounts and recurrence, so that changes and persistent estimates can be inspected.
11. As an analyst, I want auditor changes, filing delays, corrections, restatements and version history, so that reporting-integrity events are explicit.
12. As an analyst, I want note-level risks such as related parties, guarantees, litigation, impairments, receivables, inventory, contract assets, goodwill and debt maturities, so that high-risk accounts are not lost in summary statements.
13. As an analyst, I want historical warning matches to use only filings available before the event, so that no look-ahead information contaminates the analysis.
14. As a model governor, I want delisting outcomes classified by cause, so that financial distress is not mixed with mergers, privatisations or market transfers.
15. As a model governor, I want adjusted-price drawdown events defined reproducibly, so that the adverse sample is stable.
16. As an analyst, I want growth, profitability, ROIC, cash conversion, working capital, solvency and capital allocation evidence shown separately, so that financial quality is explainable.
17. As a model governor, I want evidence families to own scoring contributions, so that correlated metrics do not receive duplicate weight.
18. As an analyst, I want business model, industry structure, competitive forces, moat drivers and concentrations documented with dated evidence, so that qualitative claims are falsifiable.
19. As an analyst, I want governance, management delivery, incentives, succession, people and innovation evidence separated into observed facts, inference and judgement, so that subjective conclusions remain reviewable.
20. As an analyst, I want a versioned downside-risk register with exposure, transmission path, buffer, severity and trigger, so that each risk has an explicit causal story.
21. As an analyst, I want maximum-drawdown, permanent-loss and material-adverse-event vulnerability displayed separately, so that the crying-face composite does not hide its components.
22. As an analyst, I want bear, base and bull stress scenarios with visible assumptions, so that downside is not a single-point estimate.
23. As an analyst, I want industry-appropriate valuation methods, reverse DCF and peer-relative evidence, so that the upside rating is not driven by one target price.
24. As an analyst, I want model disagreement and sensitivity shown, so that five stars are not mistaken for certainty or probability.
25. As an analyst, I want a two-month technical view with adequate warm-up data, so that indicators are mathematically valid while the display remains concise.
26. As an analyst, I want foreign, investment-trust and dealer flows, so that recent institutional positioning is visible.
27. As an analyst, I want large-holder ownership changes and director/supervisor/insider pledge changes, so that concentration and pledge pressure are visible.
28. As a model governor, I want technical and chip scores kept outside company quality, so that short-term market activity does not rewrite fundamental quality.
29. As an analyst, I want the quality score, stars, crying faces, technical/chip subscores, confidence and limitations on one final rating card, so that the result is concise without losing drill-down evidence.
30. As an analyst, I want every report section to use the same generation and `as_of`, so that mixed-time reports cannot be published.
31. As a reviewer, I want every displayed conclusion linked to raw facts, formulas and versions, so that I can independently reproduce it.
32. As a model governor, I want pre-override and post-override outputs, owner, reason and expiry preserved, so that manual intervention is auditable.
33. As a model governor, I want repeated overrides and model drift to trigger review, so that governance failures do not become normal operation.
34. As an operator, I want failed mandatory source or integrity gates to produce a clear no-rating or blocked report, so that the system fails closed.
35. As Wayne, I want the system to remain analysis-only, so that it never sends orders or acts as a broker.
36. As an analyst, I want an explicit-market query with no identity in that market to return `not_found_in_requested_market` without inspecting or falling back to another market, so that single-market semantics cannot silently drift.
37. As an analyst, I want a missing security to return `not_found` without a report, so that missing identity is never represented as missing financial data.
38. As an analyst, I want an ambiguous active or historical name to return `ambiguous_identity` with candidates, so that I must select the intended security before analysis.
39. As an analyst, I want an unresolved historical identity chain to return `historical_identity_unresolved` without a report, so that delisted and renamed companies are not guessed.
40. As an analyst, I want upside and downside headline ratings to use a fixed 12-month horizon, so that the product evaluates actionable near-term potential and risk rather than distant forecasts.
41. As an analyst, I want industry outlook and evidenced strategic transformation included in business quality, so that an as-of transition into a growing field can be recognised without using later share-price success.
42. As an analyst, I want missing mandatory auditor pages to produce prominent coverage limitations while available financial evidence and coverage-adjusted ratings continue, so that one missing section does not erase the rest of the analysis.
43. As an analyst, I want a KAM, emphasis matter or auditor change to count as negative evidence on first occurrence, so that the product does not wait for repeated warnings.
44. As an analyst, I want a Critical Event Bomb displayed separately from unchanged crying-face calculations, so that a severe event cannot be diluted or silently rewrite the model output.
45. As a model governor, I want first release limited to Taiwan listed/OTC general non-financial operating companies, so that specialised accounting models are not applied before specification.
46. As a model governor, I want human governance unable to type arbitrary replacement ratings, so that scores change only from evidence/recomputation or an approved model-policy version.

## Implementation Decisions

### Product boundary

- The first product is an analysis and research system, not an execution, portfolio-management or recommendation engine.
- Taiwan listed and OTC companies are the only market scope; unlisted companies are excluded. First release supports general non-financial operating companies with analysable revenue/reports. Banks, insurance, securities, REIT/asset routes, financial/pure holding companies, pre-commercial biotech and other specialised accounting/valuation routes remain unsupported until separately specified. A cyclical company is eligible only when its route provides cycle-aware normalisation and labels; otherwise it returns `unsupported_scope` rather than using the unadjusted general model.
- Each analysis uses one governed market route.
- Query input is `{identifier, market?, decision_time}`. An explicit market confines resolution to that market and never triggers cross-market fallback.
- Identity resolution statuses are `resolved`, `not_found`, `not_found_in_requested_market`, `ambiguous_identity` and `historical_identity_unresolved`; only `resolved` may create an `AnalysisSnapshot`.
- Delisted securities remain addressable through historical identity and archival data when evidence coverage permits.

### Primary contract

- The highest product seam is one behavior: `identifier + market? + decision_time → identity resolution → immutable AnalysisSnapshot → complete rendered report`.
- `decision_time` is a mandatory exact RFC3339 timezone-aware instant, normalized and stored in Asia/Taipei representation; another timezone is accepted only if it resolves to an unambiguous instant. Bare date-only input is rejected as `invalid_decision_time` and cannot create a snapshot. Source records that have only a date and no reliable publication time become admissible at exactly the next Asia/Taipei midnight.
- Unresolved identity returns only an identity-resolution envelope; it never produces a partial snapshot or report.
- All internal modules contribute to this snapshot rather than publishing unrelated partial generations.
- The snapshot preserves source-manifest reference, fact lineage, model versions, coverage, confidence, limitations, reason codes, hard flags and override state.

### Headline semantics

- Company quality is price-independent and expressed from 0–100 or no-rating.
- Upside is an ordinal star rating, not a probability.
- Downside is an ordinal crying-face rating with three separately visible components: maximum drawdown, permanent capital loss and material adverse events.
- Upside stars and all downside outcome/composite ratings use a fixed 12-month primary horizon. Any 24/36-month output is sensitivity context only and cannot blend into or replace headline ratings.
- Technical and chip evidence uses a two-month display horizon and remains independent: it never changes company quality, upside stars or downside crying faces in the first release.
- A Critical Event Bomb is a separate warning state in addition to the unchanged three downside components and crying-face composite; it does not replace or force the face count.

### Financial-report audit

- Financial-report integrity is a first-class quality/risk pillar and a source of hard gates.
- Annual audit and interim review conclusions remain separate types.
- Opinion type, going-concern paragraph, emphasis matters, other matters and KAMs remain separate fields.
- PDF/OCR extraction must retain page/coordinate evidence and confidence. Missing mandatory auditor-report pages/opinion-bearing sections emit `mandatory_audit_evidence_missing`, exact missing scope, coverage/confidence and limitations; every available section remains analysed and coverage-adjusted headline ratings remain publishable. Missing evidence never becomes zero/neutral.
- Company/report identity failure, source-authenticity failure or inability to establish admitted statement values remains blocked; that is distinct from a known report with missing/unreadable auditor pages.
- Disclaimer of opinion produces quality/upside no-rating and five crying faces. Adverse opinion caps quality within the governed 20–30 calibrated range, caps upside at one star without improving a lower/no-rating result, and sets crying faces at least five. Going-concern material uncertainty caps quality at 40, caps upside at two stars without improving a lower/no-rating result, and sets crying faces at least four. Qualified opinion uses a severity-dependent penalty/cap no higher than 60 and escalates for pervasive/core-account effects. Major correction/restatement/confirmed fraud/integrity failure caps quality within the governed 30–40 range, sets at least four crying faces and produces no-rating when statements are unreliable.
- A KAM, emphasis matter or auditor change contributes negative evidence on first occurrence; severity follows affected account, materiality, estimation uncertainty and corroboration. KAM alone is not proof of fraud, concealment or realised loss.
- Historical forensic matches are hypotheses until validated on a point-in-time adverse/control sample.

### Data and PIT governance

- Authoritative source bytes are retained with retrieval time and hash.
- `effective_at`, `announced_at`, `available_at` and `retrieved_at` are distinct.
- Snapshot admission requires all of: unique resolved identity; `available_at <= decision_time`; and `valid_from <= decision_time < valid_to` (with open-ended `valid_to` represented explicitly).
- When a source supplies only a date, its facts are conservatively unavailable during that local date and become admissible at the next Asia/Taipei midnight unless an authoritative timestamp is recovered.
- A final daily market bar is not admissible intraday; it enters only after its official publication time, or under the same conservative next-midnight rule when no reliable time exists.
- Corrections and restatements create an append-only version chain; current values do not overwrite historical knowledge states.
- Conflicting authoritative versions with no resolvable precedence block the affected fact/section and cannot be selected arbitrarily.
- Identity, source, fact, metric, model and report versions are independently traceable.
- Missing-data states are typed and cannot silently become zero or neutral evidence.
- Filing-delay facts retain the historically applicable rule version, issuer/industry type, fiscal period, audit/review type, ordinary due time, holiday adjustment, approved extension, derived `statutory_due_at` and authority-observed `official_filed_at`. Auditor report date is not treated as filing time.

### Fixed company-quality pillars

Top-level quality weights are fixed and sum to 100%:

1. Financial-report reliability and audit completeness: 10%.
2. Earnings quality and capital efficiency: 25%.
3. Cash conversion, balance sheet and capital allocation: 25%.
4. Business model, industry position, moat and industry outlook: 25%.
5. Governance, management and shareholder alignment: 5%.
6. People, innovation and adaptability: 10%.

Audit hard gates/caps/floors are separate from its ordinary 10% contribution and cannot be averaged away. Industry transformation uses only decision-time evidence such as revenue mix, orders/backlog, customers, products, R&D, capex, margins and execution; later share-price appreciation is forbidden proof.

### Adverse-outcome laboratory

- The five-year laboratory uses a complete single-market historical universe that retains delisted securities rather than beginning from current constituents.
- It preserves all delisting causes as multi-label outcomes and uses contemporaneous non-adverse controls from the same eligible universe. Adverse classes explicitly include financial distress, fraud, going-concern failure, negative equity, bankruptcy/reorganisation and unresolved reporting/trading violations. Merger/private delistings are neutral structural controls unless evidence also supports one or more adverse labels; multi-label is allowed.
- Drawdown research uses a corporate-action and cash-distribution-adjusted daily-close wealth series, records the first -50% crossing per peak-to-trough episode, and starts another episode only after full recovery to the prior peak. Market-wide crashes retain the adverse label with separate market/industry-relative context.
- Observation windows, left history, right censoring, suspensions, missing archives and non-adverse structural delistings remain explicit.
- Case-study evidence cannot set weights or buckets; only temporal adverse/control validation may support calibration.

### Two-month technical and chip scope

- Every eligible report exposes a two-month display window for adjusted OHLCV and price/volume structure, with a separately governed warm-up long enough for every published indicator.
- The section contract includes trend/levels, deterministic technical metrics/tags, foreign/investment-trust/dealer flows, TDCC holder-band distribution/change, and director/supervisor/insider holding and pledge changes.
- Raw values, period coverage, source availability and confidence are mandatory section outputs; unavailable components are explicit and never fabricated.
- The full TDCC distribution is retained; 400 lots and above is the primary headline large-holder ratio and 1,000 lots and above is a secondary concentration metric, both with outstanding-share/capital-event handling.
- Technical/chip metrics remain independent panels and cannot modify company quality, stars or crying faces in the first release.

### Anti-double-counting

- Every scoring input belongs to one primary evidence family.
- Multiple diagnostics may read one fact, but the latent construct receives one governed scoring contribution.
- Drivers and downstream outcomes on the same causal chain cannot both receive full independent weight.
- Audit hard gates, caps and floors are applied separately from ordinary weighted evidence.

### Valuation and risk

- Valuation methods are routed by industry/accounting model.
- No single target price directly assigns stars.
- Critical audit-integrity, going-concern, imminent-liquidity or source-identity failures may floor downside, cap quality or produce no-rating according to the approved policy.
- Maximum-drawdown, permanent-capital-loss and material-adverse-event components remain visible separately. Formal ordinary composite weights use PIT temporal calibration constrained to 25%–40% per component; pre-calibration equal-weight research is not a publishable formal composite.
- An authoritative, material and currently relevant event may emit a separate Critical Event Bomb that bypasses ordinary weight limits but leaves the calculated component/face outputs unchanged. Candidate triggers include systemic realised default/impairment, confirmed material misclassification/restatement/fraud, negative-equity/going-concern collapse or equivalent invalidation of ordinary aggregation. KAM alone cannot trigger it.
- Exact ordinary buckets and Bomb materiality thresholds must be calibrated on point-in-time holdouts rather than selected from seed cases.

### Publication and override

- A report is publishable only when all emitted sections bind to one generation and identity/authenticity/value gates pass. Known missing mandatory audit evidence follows the explicit coverage-adjusted partial-evidence policy rather than suppressing every rating.
- Only Wayne may approve an override, an independent Reviewer is mandatory and validity is at most 90 days.
- Override never rewrites model numeric scores/stars/faces. It may add annotation, block publication, add a Critical Event Bomb or impose a stricter risk floor; pre/post values, evidence and governance metadata are retained.
- Newly admitted financial reports, material information or governed source generations expire/reopen prior override state and trigger a new immutable recomputation/re-review. Numeric ratings change only from admitted facts, deterministic recomputation or an approved versioned model-policy change.
- Probability outputs are excluded unless a separately calibrated probability model is later approved.

## Testing Decisions

### Highest test seam

The preferred black-box acceptance seam is:

`query a company as of T → receive one AnalysisSnapshot → render the complete report`

This seam should prove identity, PIT selection, source binding, section completeness, rating/no-rating behavior and report generation together. Internal unit tests support it but do not replace it.

Wayne approved this as the single primary black-box seam. Module/unit/contract tests remain required but cannot replace this end-to-end acceptance seam.

### Required behavior tests

- Ambiguous company-name query returns `ambiguous_identity` candidates and does not generate a report.
- Explicit-market input with no identity in that market returns `not_found_in_requested_market` without inspecting/falling back to another market; market-omitted missing identity returns `not_found`; unresolved historical chains return `historical_identity_unresolved`; none generate a snapshot/report.
- Historical/delisted identity resolves as of the requested decision time and valid identity interval.
- A filing published after `decision_time` cannot enter facts, flags or ratings.
- A bare date-only query returns `invalid_decision_time` with no snapshot/report. Separately, a source event that only supplies a date is excluded throughout its local date and becomes admissible at exactly the next Asia/Taipei midnight unless an authoritative time is recovered; tests cover one microsecond before, exactly at, and one microsecond after that boundary.
- An intraday query cannot use the final daily bar before official availability.
- A fact is admitted only while its version interval is valid; unresolved conflicting authoritative versions block the affected output.
- A correction is visible only after its own `available_at`; prior snapshots preserve prior bytes.
- Annual audit and quarterly review are never mapped to the same assurance type.
- An unmodified opinion with going-concern uncertainty retains both facts.
- Missing/unreadable mandatory auditor-report pages/opinion-bearing sections preserve available analysis and publish coverage-adjusted headline ratings with `mandatory_audit_evidence_missing`, exact gap, coverage/confidence and limitations; identity/authenticity/admitted-value failure still blocks.
- Correlated diagnostics map to one primary evidence-family contribution.
- Technical/chip changes cannot alter company quality, upside stars or downside crying faces in the first release.
- Critical-risk floors cannot be reduced by technical or valuation strength.
- All displayed report sections share one generation and source manifest.
- No-rating states expose the exact failed gate rather than returning a fabricated score.
- Filing-delay conclusions reproduce `statutory_due_at` from the correct historical rule, issuer/industry type, period, assurance type, holiday and extension; `official_filed_at` comes from authority evidence and never from auditor report date.
- Special extensions and holiday roll-forwards produce deterministic due times.
- The five-year adverse laboratory includes delisted names, contemporaneous controls, adjusted wealth series and censoring metadata; current-survivor-only input fails the cohort gate.
- The technical/chip section proves the two-month display, adequate warm-up, adjusted OHLCV, three institutional-flow groups, TDCC distribution/change and insider/pledge changes; missing components remain explicit in coverage.
- A 12-month query/report never substitutes 24/36-month sensitivity for headline ratings.
- Quality top-level weights are exactly 10/25/25/25/5/10 and sum to 100%; audit hard gates apply outside ordinary weighting.
- A first-occurrence KAM/emphasis/auditor change produces negative evidence without being promoted to fraud or a Bomb absent corroboration.
- A Bomb is shown separately while the original three components/composite remain unchanged; authoritative materiality is required.
- TDCC output includes full distribution, >=400-lot primary and >=1,000-lot secondary ratios with capital-event handling.
- Unlisted or unsupported specialised-industry queries return an explicit unsupported-scope state rather than a general-route rating. A cyclical company without cycle-aware normalisation/labels also returns `unsupported_scope`.
- Overrides preserve original output, Wayne approval, independent review, reason/evidence, affected fields and <=90-day expiry; arbitrary numeric edits are rejected and new governed evidence triggers recomputation/re-review.

### Seed and reference cases

- 中鼎 9933 is used to test pre-event visibility, late-arriving debtor identity and anti-look-ahead behavior.
- 森崴能源 6806 is used to test delisted identity, unmodified opinion plus KAM, later going-concern uncertainty, negative net worth and fail-closed historical market data.
- Seed cases are regression fixtures for contracts, not sufficient samples for model calibration.

### Independent gates

- Contract/schema tests.
- Source/PIT lineage tests.
- Domain semantic tests.
- Formula and monotonicity tests.
- Adverse/control temporal validation.
- Full query-to-report tests.
- Real-authority smoke probes that do not write production state.
- Merged-byte integration tests after every accepted candidate.

## Owner Decisions and Remaining Calibration Boundary

F1–F10 and Q1–Q3 are owner-resolved in `company-quality-decision-map.md` and merged into this draft.

The following are governed calibration/specification tasks, not permission to change owner semantics:

1. Calibrate the exact adverse-opinion quality cap within 20–30 and severe integrity-event cap within 30–40.
2. Calibrate quality normalization/bands, upside-star buckets, downside ordinary weights/buckets and Critical Event Bomb materiality thresholds using PIT temporal adverse/control validation.
3. Specify indicator warm-up lengths, confidence/coverage measures and supported general-non-financial industry routing details.
4. Freeze field-level schemas and primary test-seam acceptance after independent decision-conformance review and Wayne approval.

No calibration may change the fixed 12-month horizon, top-level quality weights, independent technical/chip policy, Bomb display semantics, first-release market/industry scope or override boundary without a new owner decision.

## Out of Scope

- Product implementation in the planning phase.
- Git, issue-tracker, worktree or control-plane setup without explicit authorization.
- Trading orders, broker integration or automated buy/sell recommendations.
- Production deployment, scheduler activation or external notifications.
- Precise probabilities without a separately validated model.
- Using seed-case findings as direct weights or universal rules.
- Treating technical/chip signals as company quality.

## Further Notes

- The project currently contains planning/research artifacts only and is not a Git repository.
- No issue tracker, coding standards or test harness is configured yet.
- `to-spec` is being used locally because no issue tracker is configured; this frozen document is not a published `ready-for-agent` issue.
- `to-tickets` may next create local dependency-aware vertical-slice work-order drafts for Wayne review. It must not publish tickets or authorize implementation without a separate Wayne approval. Horizontal layer tickets should be avoided except for shared-contract expand/contract work.
