# T20 — 五年Survivorship-free Adverse/Control Cohort

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 建立含下市公司的五年母體、event taxonomy、controls與censoring，不校準。

**Blocked by:** T03, T04, T06

**Generation:** `work-orders-r9`

**Frozen Spec SHA-256:** `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`

**Decision Map SHA-256:** `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`

**Delivery Plan SHA-256:** `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`

## Dispatch binding

- Parent SHA: `PM_REQUIRED_AT_DISPATCH` — PM replaces with exact protected-main SHA; unresolved means `BLOCKED`.
- Branch: `wo/T20-adverse-control-cohort`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T20-adverse-control-cohort`
- Attempt: `PM_REQUIRED_AT_DISPATCH`
- Worker: T20 Worker; isolated worktree; freeze candidate SHA after handoff.
- Review: Fresh Spec/Domain + Quality/Standards Reviewers; parallel read-only; same SHA/attempt.

## Filesystem ownership

**Owned paths (exclusive write):**

- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/lab/cohort/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/lab/cohort/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/var/fixtures/cohort/

**Shared read-only inputs:**

- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md`
- Outputs/contracts of every ticket named in `Blocked by`.

**Forbidden writes:** every path outside owned paths; formal spec/planning/research docs; other worktrees; Hermes state; production/config/secrets/order/notification systems.


## R9 Fresh-context execution contract (normative; supersedes shorthand above)

### Bounded inputs and producer locators
- T03 `AdmittedFactSet` — locator `AnalysisSnapshot.sections.pit_admission`; producer schema `AdmittedFactSet.v1`; exact producer SHA must appear in dispatch bundle.
- T04 `OfficialFinancialArtifacts` — locator `AnalysisSnapshot.sections.financial_artifacts`; producer schema `OfficialFinancialArtifacts.v1`; exact producer SHA must appear in dispatch bundle.
- T06 `AuditFilingInventory` — locator `AnalysisSnapshot.sections.audit_inventory`; producer schema `AuditFilingInventory.v1`; exact producer SHA must appear in dispatch bundle.
- Compatibility: schema major must equal `v1`; unknown minor fields may be ignored only when required fields and semantics are unchanged; major mismatch or missing producer SHA => `BLOCKED_CONTRACT`.

### Bounded output
- Contract: `AdverseControlCohort.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/lab/cohort/contracts/AdverseControlCohort.schema.json`.
- Runtime locator: `AnalysisSnapshot.sections.adverse_cohort`; immutable generation ID and producer candidate SHA are mandatory envelope fields.
- Required fields: `issuer_ids:list<string[0..4096]>[1..10000], control_ids:list<string[0..4096]>[1..10000], event_taxonomy:list<record{event_code:string[1..64],event_class:oneof[delisting,default,fraud,restatement,drawdown,other_adverse],authoritative_source_type:string[1..64]}>[1..64], delisting_states:record{forced_redemption:oneof[confirmed,not_confirmed,unknown],maturity:oneof[confirmed,not_confirmed,unknown],bankruptcy:oneof[confirmed,not_confirmed,unknown],other_delisting:oneof[confirmed,not_confirmed,unknown]}, censoring_rules:record{right_censor_at:rfc3339_timezone_aware,min_followup_days:uint32,missing_price_policy:oneof[confirmed_delisting_zero_contribution,block_unconfirmed]}, cohort_asof:rfc3339_timezone_aware, window_start_inclusive:date, window_end_exclusive:date, lookback_calendar_years:literal[5], window_boundary_policy:literal[asia_taipei_calendar_year_half_open_v1], universe_policy:literal[all_securities_listed_at_any_instant_during_window], delisted_included:literal[true], eligibility_version:semver, evidence_ids:list<string[0..4096]>[1..10000], cohort_coverage:decimal[0,1], rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries an explicit coverage value in `[0,1]`. This ticket’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; this ticket does not issue a rating; `rating_disposition=NO_RATING_NOT_APPLICABLE`; missing mandatory evidence follows the ticket-specific blocked/unknown rule, never an implicit score.

### Explicit non-goals
- Do not publish final quality/stars/faces/Bomb, do not edit another ticket owned path, and do not change Frozen Spec/Decision Map/Delivery Plan.

### Ticket-specific failure disposition
- Five-year universe invariant: derive `window_end_exclusive` as the Asia/Taipei local calendar date immediately after `cohort_asof`; derive `window_start_inclusive = add_calendar_years(window_end_exclusive, -5)` and admit `[window_start_inclusive, window_end_exclusive)`. `asia_taipei_calendar_year_half_open_v1` preserves month/day when valid; if the source is Feb-29 and target year is non-leap, it MUST clamp to Feb-28 and MUST NOT roll to Mar-01. Exact fixture: `window_end_exclusive=2024-02-29` gives `window_start_inclusive=2019-02-28`; `2025-03-01` gives `2020-03-01`. Include every security listed at any instant in the interval, including delisted names; current-survivor filtering is forbidden. Any other boundary result => `BLOCKED_CONTRACT`.
- Eligibility ambiguity, survivorship leakage or unavailable delisting evidence blocks affected cohort membership.

### Authority and PIT boundary
- Official read-only source probe is mandatory. Authority order follows Frozen Spec/Decision Map; capture official URL, content hash, available_at and retrieved_at; fail closed on unresolved same-rank conflict.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/lab/cohort`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/lab/cohort` plus every previously integrated black-box seam test selected by PM manifest.
- Real-source probe — **MANDATORY**: `python -m pytest -q -m authority_probe tests/lab/cohort`; nonzero exit blocks REVIEW_READY.
- Diff hygiene — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`.
- Non-empty candidate — **MANDATORY**: `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`.
- Generated/secret admission — **MANDATORY**: `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- PM dispatch manifest is atomic and immutable: `assignment_id`, `active_binding_generation`, `eligibility_generation`, `ticket_id=T20`, `ticket_generation=R9`, `parent_sha`, `branch`, `worktree`, `owned_paths`, `forbidden_paths`, `spec_sha=36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`, `decision_map_sha=cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`, `delivery_plan_sha=bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`, `ticket_set_digest`, `lease_expires_at`, `review_deadline_at`. Missing field => no dispatch.
- Worker emits `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>` only after every mandatory command exits 0.
- Each read-only reviewer first emits `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`; ACK mismatch invalidates verdict.
- Authoritative verdict source message: `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`; both axes must bind identical bytes.
- Revision limit is 3 attempts. Same Worker/session may revise only owned paths. If blocker_count fails to decrease between attempts, lease expires, ownership overlaps, or contract question changes product semantics, emit `OWNER_DECISION_NEEDED` and stop.
- PM performs serialized admission only: validate lease/ownership, non-empty diff, diff hygiene, generated/secret scan, tests/probes, atomic dual-axis bundle; enqueue protected-main merge queue; after merge rerun cumulative and same-generation seam on merged SHA before eligibility.
- Durable ingestion uses monotonically increasing `ingestion_seq`, persisted `reconciliation_watermark`, and `eligibility_generation`. Crash recovery replays source messages after watermark and recomputes eligibility from exact current bytes.
- Any late NOT_APPROVED first revokes eligibility fail-closed; PM evaluates finding reachability against current bytes. Only an unreachable finding superseded by a newer exact-byte dual PASS may remain history without demoting current state.

## Acceptance criteria

- [ ] Contract tests cover ordinary year, leap-day boundary, newly listed, delisted and right-censored cases and reject any cohort not exactly matching the governed five-calendar-year half-open window.

- [ ] delisted納入.
- [ ] 原因保留authority/labels.
- [ ] 同期controls.
- [ ] censoring/suspension/missing明示.
- [ ] seed cases不定模型.
- [ ] Owned-path diff audit reports no write outside exclusive paths.
- [ ] Output includes source/formula/model/schema versions and explicit failure reasons.
