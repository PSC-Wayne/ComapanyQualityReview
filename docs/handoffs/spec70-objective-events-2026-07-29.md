# Spec 70 Objective Events / Pre-OOS Handoff

Updated: 2026-07-29 09:04 +08:00

## Resume binding

- Repository: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/spec70-objective-events`
- Branch: `feat/spec70-objective-events`
- Starting HEAD before this handoff: `9b840310aa1e9870b37a708a1b2ef59bffad29bb`
- Tracking: `origin/main`
- GitHub issue: `#70`
- Research/decision comment: <https://github.com/PSC-Wayne/ComapanyQualityReview/issues/70#issuecomment-5106569234>

This was Lean research work, not a governance/admission workflow. Final OOS remains unread. No model, stars, or release candidate was frozen or published.

## 2026-07-29 continuation outcome — CMoney industry approximation

Wayne authorized a temporary same-decision-year CMoney exchange-industry approximation until qualified TEJ effective-dated history becomes available. The approximation is explicitly not exact PIT.

Identity-bound exclusion:

- the 18 affected `issuer_id` values were excluded as whole companies, across every security, market, and decision date;
- excluded: 18 issuers, 24 security-market combinations, 85 pre-OOS observations;
- retained: 1,781 issuers, 1,788 security-market combinations, 9,957 pre-OOS observations;
- all retained observations joined to one same-year CMoney classification.

Industry-route sample result:

- 56 market-industry groups were observed;
- no group reached the pre-registered 500 training-observation requirement using 2017-2020 history;
- the largest group was TPEx industry 28 with 433 training observations;
- therefore no formal exact-industry candidate was structurally eligible, regardless of later holdout size.

A single fixed, non-tuned diagnostic added standardized market-industry one-hot features to the anchored event candidate. Common 2021-2022 holdout after the issuer exclusions: 3,436 observations.

| Metric | Exclude-18 incumbent | CMoney-industry one-hot | Industry gate |
|---|---:|---:|---|
| MAE | `0.2939066155` | `0.3023548356` | FAIL; required `<= 0.2793760747` |
| No-company MAE | `0.2940800786` | `0.2940800786` | baseline |
| Spearman | `0.3295431971` | `0.1190788137` | both PASS (`>= 0.10`) |
| Direction accuracy | `0.6245634459` | `0.5721769499` | — |
| Naive direction accuracy | `0.5905122235` | `0.5905122235` | — |
| Direction improvement | `3.4051 pp` | `-1.8335 pp` | both FAIL (`>= 5 pp`) |
| Overall outperform AUC | `0.6389173164` | `0.6097166385` | industry FAIL (`>= 0.62`) |
| TPEx AUC | `0.6669312332` | `0.6275462798` | industry PASS |
| TWSE AUC | `0.6196281050` | `0.5947248056` | both FAIL (`>= 0.62`) |
| p10-p90 coverage | `0.8125727590` | `0.7977299185` | both PASS (75%-85%) |

The industry diagnostic was materially worse than the incumbent and failed the unchanged structural, MAE, direction, overall-AUC, and TWSE-AUC gates. Bounded research stopped without tuning. Status remains `research_only`; Final OOS remains unread; no stars were frozen or published.

Research-only local artifacts:

- `/tmp/spec70-post-identity-readiness/cmoney-same-year-industry-approx.parquet`
- `/tmp/spec70-post-identity-readiness/cmoney-same-year-industry-sample-counts.csv`
- `/tmp/spec70-post-identity-readiness/pre-oos-candidates-v8-cmoney-industry-approx.parquet`
- `/tmp/spec70-post-identity-readiness/pre-oos-candidates-v8-cmoney-industry-approx-report.json`
- `/tmp/spec70-cmoney-industry-approx.py`

## Original owner decision at handoff time

Do not continue model implementation until Wayne selects one contract:

1. Preserve the strict company-only contract and provide/authorize an authoritative historical PIT industry dataset.
2. Preserve current data and gates; retain upside output as `research_only` with no formal stars.
3. Change the core upside contract to permit market/technical/macro predictors for absolute-return MAE. This reverses the confirmed display-only rule for technical/chip inputs.
4. Relax the formal MAE, direction, or per-market AUC gates. This changes pre-registered acceptance criteria.

Recommended: option 1. If no historical PIT industry source will be obtained, option 2.

## Best current pre-OOS candidate

Candidate design:

- baseline-anchored ridge, penalty `1000`;
- temporal no-company median is the anchor;
- model learns company-specific residual deltas only;
- includes `log1p(12-month distinct official material-announcement days)`;
- no title sentiment, LLM severity, news inference, technical indicators, or chip data.

Common temporal holdout: 2021-2022, 3,462 observations.

| Metric | Result | Gate |
|---|---:|---|
| Spearman | `0.3342542402` | PASS (`>= 0.10`) |
| Overall official-benchmark outperform AUC | `0.6395193669` | PASS (`>= 0.62`) |
| TPEx AUC | `0.6675982340` | PASS |
| TWSE AUC | `0.6199222351` | FAIL by about `0.000078` |
| p10-p90 coverage | `0.8139803582` | PASS (75%-85%) |
| Direction accuracy | `0.6253610630` | — |
| Naive direction accuracy | `0.5895436164` | — |
| Direction improvement | `3.5817 pp` | FAIL (requires `5 pp`) |
| Candidate MAE | `0.2935609252` | FAIL |
| No-company temporal-median MAE | `0.2872766568` | baseline |
| Required 5%-better MAE | `<= 0.2729128240` | gate |
| MAE gap to gate | `0.0206481012` | FAIL |

Formal freeze remains blocked by MAE, direction improvement, and strict TWSE AUC.

## Work completed

### Objective financial expansion

- Added the already-admitted upside trend `upside__debt_ratio_improvement__trend` in the research artifacts.
- Tested `net_margin_after_tax` and `eps_after_tax`.
- Expanded levels did not materially improve the formal candidate and were not admitted.
- Source and test edits used for that probe were restored; they are intentionally not product changes.

### Model families tested

- Existing ridge residual family.
- Baseline-anchored ridge.
- Extra Trees.
- HistGradientBoosting with MAE loss.

The fixed nonlinear probes were worse than the anchored linear candidate. No broad tuning grid was run.

### Official material-event history

Materialized official MOPS daily announcements:

- query range: 2016-07-01 through 2022-06-30;
- event timestamps observed: 2016-06-30 through 2022-06-30 because each daily result includes the prior day after 17:30;
- 2,191 calendar query dates;
- 388,765 TWSE/TPEx announcements;
- sources:
  - `https://mops.twse.com.tw/mops/api/t05st02`
  - `https://mopsov.twse.com.tw/mops/web/ajax_t05st02`

The new API rate-limited the WSL IP after roughly 500 requests. The official legacy daily endpoint completed the remaining history. Market identity was taken from official `sii_fm*` / `otc_fm*` form IDs.

Objective event ablations:

- 3-month announcement count;
- 12-month announcement count;
- 12-month distinct announcement days;
- `log1p` transforms were used for the linear probes because counts were highly skewed.

The best event feature was 12-month distinct announcement days. It improved AUC/ranking and slightly improved MAE, but did not clear formal gates.

### PIT industry blocker

- Repository contains the industry routing contract but no authoritative historical classification artifact.
- Current TWSE/TPEx/FinLab company classifications must not be backfilled into 2017-2022; that would introduce future leakage.
- FinLab cache inspected in this session contained a 2023 snapshot, not an effective-dated history.
- Complete 2016H2-2022H1 MOPS announcements contained only two subjects explicitly mentioning an industry-class change, insufficient to establish every issuer's PIT class, especially later-delisted issuers.
- Do not infer missing historical classes from current classifications without explicit owner acceptance of that approximation.

## Current research artifacts

These were verified present at handoff time under `/tmp/spec70-post-identity-readiness/`:

- `mops-events-2016h2-2022h1.parquet`
- `pre-oos-event-features.parquet`
- `pre-oos-candidates-v7-events.parquet`
- `pre-oos-candidates-v4-expanded-financial.parquet`
- `pre-oos-candidates-v4-expanded-financial-report.json`
- `pre-oos-candidates-v6-baseline-anchored.parquet`
- `pre-oos-selection-labels.parquet`
- `adjusted-close.parquet`
- `pre-oos-valuation.parquet`
- `real-pit-features-expanded-plus-trend.parquet`

`/tmp` is not a release location and may disappear after reboot/cleanup. These are research evidence only, not product artifacts.

Temporary research scripts used in this session:

- `/tmp/fetch-mops-events.py`
- `/tmp/fetch-mops-events-old.py`
- `/tmp/build-mops-event-features.py`
- `/tmp/spec70-baseline-anchored.py`
- `/tmp/spec70-event-ablation.py`
- `/tmp/spec70-nonlinear-pre-oos.py`

They are not production code and should not be copied into `src/` without a selected owner contract, focused tests, and a minimal implementation review.

## Superseded background-process notices

Three delayed process notifications arrived after the main research finished:

- v3 trend attempt failed on the wrong report key (`scopes`);
- v3 trend attempt failed by requiring adverse-label columns in an upside trend artifact;
- corrected v3 trend generation succeeded;
- v4 expanded-financial generation succeeded.

The two failures were prerequisite-script mistakes and were superseded. The successful v3/v4 metrics are also superseded by the anchored event candidate above.

## Repository state and intentional non-changes

Before creating this handoff, the feature/test probes had been restored and the worktree was clean at HEAD `9b840310aa1e9870b37a708a1b2ef59bffad29bb`.

No production model code, source adapters, dashboard code, release artifacts, or final-OOS files were changed in this workstream. Only this durable handoff should be committed on `feat/spec70-objective-events`.

## Next-session start

1. Read this handoff and issue #70, especially the linked decision comment.
2. Confirm Wayne's selected option; do not infer approval from silence.
3. Recheck that Final OOS has not been read.
4. If option 1 is selected, define the historical industry source contract first. Minimum fields:
   - issuer/security identity;
   - market;
   - official industry identifier/name;
   - `effective_from`;
   - `effective_to` or open-ended current interval;
   - authority/source reference;
   - coverage for issuers later delisted.
5. Rebuild only pre-OOS candidates and run the existing frozen gates once.
6. If no candidate passes all gates, remain `research_only`; do not inspect Final OOS or publish stars.
7. If option 3 or 4 is selected, update the authoritative spec/acceptance contract before model work.

## Stop conditions

Stop and ask Wayne if:

- the chosen industry source lacks effective dates or delisted-issuer coverage;
- a proposal requires technical/chip inputs to enter the core model without option 3 approval;
- any gate relaxation is proposed without option 4 approval;
- the next step would inspect Final OOS before a valid pre-OOS freeze.
