# T15 — 兩個月Technical與Chip Panel

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 呈現兩月adjusted OHLCV、三大法人、TDCC與董監質押並隔離headline ratings。

**Blocked by:** T03

**Generation:** `work-orders-r9`

**Frozen Spec SHA-256:** `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`

**Decision Map SHA-256:** `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`

**Delivery Plan SHA-256:** `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`

## Dispatch binding

- Parent SHA: `PM_REQUIRED_AT_DISPATCH` — PM replaces with exact protected-main SHA; unresolved means `BLOCKED`.
- Branch: `wo/T15-technical-chip`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T15-technical-chip`
- Attempt: `PM_REQUIRED_AT_DISPATCH`
- Worker: T15 Worker; isolated worktree; freeze candidate SHA after handoff.
- Review: Fresh Spec/Domain + Quality/Standards Reviewers; parallel read-only; same SHA/attempt.

## Filesystem ownership

**Owned paths (exclusive write):**

- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/market/technical_chip/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/market/technical_chip/

**Shared read-only inputs:**

- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md`
- Outputs/contracts of every ticket named in `Blocked by`.

**Forbidden writes:** every path outside owned paths; formal spec/planning/research docs; other worktrees; Hermes state; production/config/secrets/order/notification systems.


## R9 Fresh-context execution contract (normative; supersedes shorthand above)

### Bounded inputs and producer locators
- T03 `AdmittedFactSet` — locator `AnalysisSnapshot.sections.pit_admission`; producer schema `AdmittedFactSet.v1`; exact producer SHA must appear in dispatch bundle.
- Compatibility: schema major must equal `v1`; unknown minor fields may be ignored only when required fields and semantics are unchanged; major mismatch or missing producer SHA => `BLOCKED_CONTRACT`.

### Bounded output
- Contract: `TechnicalChipOverlay.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/market/technical_chip/contracts/TechnicalChipOverlay.schema.json`.
- Runtime locator: `AnalysisSnapshot.sections.technical_chip`; immutable generation ID and producer candidate SHA are mandatory envelope fields.
- Required fields: `window_start:date, window_end:date, price_series_ref:string[1..256], technical_signals:record{return_1m:null|decimal[-1e18,1e18],return_2m:null|decimal[-1e18,1e18],ma20_gap:null|decimal[-1e18,1e18],ma60_gap:null|decimal[-1e18,1e18],volatility_20d:null|decimal[-1e18,1e18]}, chip_signals:record{foreign_net_20d:null|decimal[-1e18,1e18],dealer_net_20d:null|decimal[-1e18,1e18],investment_trust_net_20d:null|decimal[-1e18,1e18],margin_balance_change:null|decimal[-1e18,1e18]}, insider_holding_changes:list<record{person_type:oneof[director,supervisor,manager,major_shareholder,other_insider],as_of:date,holding_change_shares:int64,holding_change_pct:null|decimal[-100,100],state:oneof[present,missing,not_applicable],reason:null|string[1..512],evidence_id:null|string[1..128]}>[0..256], pledge_changes:list<record{person_type:oneof[director,supervisor,manager,major_shareholder,other_insider],as_of:date,pledged_share_change:int64,pledged_ratio_change_pct:null|decimal[-100,100],state:oneof[present,missing,not_applicable],reason:null|string[1..512],evidence_id:null|string[1..128]}>[0..256], tdcc_as_of:date, tdcc_state:oneof[present,missing,not_applicable], tdcc_state_reason:null|string[1..512], tdcc_bands:list<record{band:string[1..32],holder_count:uint64,share_count:uint64,share_pct:decimal[0,100],previous_as_of:null|date,previous_share_pct:null|decimal[0,100],change_pct_points:null|decimal[-100,100],evidence_id:string[1..128]}>[0..32], tdcc_headline_ratios:record{gte_400_lots_share_pct:null|decimal[0,100],gte_1000_lots_share_pct:null|decimal[0,100],denominator_outstanding_shares:null|uint64,ratio_state:oneof[present,missing,not_applicable],reason:null|string[1..512],evidence_id:null|string[1..128]}, capital_event_adjustment:record{applied:boolean,rule_version:semver,corporate_action_ids:list<string[1..128]>[0..64],pre_event_denominator:null|uint64,post_event_denominator:null|uint64,adjustment_factor:null|decimal[0.000001,1000000]}, warmup_state:oneof[ready,insufficient_history,unavailable], available_at:rfc3339_timezone_aware, overlay_coverage:decimal[0,1], rating_disposition:literal[NO_RATING_NOT_APPLICABLE], independent_from_ratings:literal[true]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries an explicit coverage value in `[0,1]`. This ticket’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; this ticket does not issue a rating; `rating_disposition=NO_RATING_NOT_APPLICABLE`; missing mandatory evidence follows the ticket-specific blocked/unknown rule, never an implicit score.

### Explicit non-goals
- Do not publish final quality/stars/faces/Bomb, do not edit another ticket owned path, and do not change Frozen Spec/Decision Map/Delivery Plan.

### Ticket-specific failure disposition
- TDCC invariant: when `tdcc_state=present`, retain the complete official band distribution, one shared `tdcc_as_of`, and compute `>=400 lots` primary plus `>=1,000 lots` secondary ratios against `denominator_outstanding_shares`; cross-capital-event changes require governed adjustment metadata. Missing and N/A stay distinct and never fabricate zero change.
- Unavailable final daily bar is excluded until official availability; warm-up insufficient yields display warning and never changes ratings.

### Authority and PIT boundary
- Official read-only source probe is mandatory. Authority order follows Frozen Spec/Decision Map; capture official URL, content hash, available_at and retrieved_at; fail closed on unresolved same-rank conflict.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/market/technical_chip`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/market/technical_chip` plus every previously integrated black-box seam test selected by PM manifest.
- Real-source probe — **MANDATORY**: `python -m pytest -q -m authority_probe tests/market/technical_chip`; nonzero exit blocks REVIEW_READY.
- Diff hygiene — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`.
- Non-empty candidate — **MANDATORY**: `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`.
- Generated/secret admission — **MANDATORY**: `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- PM dispatch manifest is atomic and immutable: `assignment_id`, `active_binding_generation`, `eligibility_generation`, `ticket_id=T15`, `ticket_generation=R9`, `parent_sha`, `branch`, `worktree`, `owned_paths`, `forbidden_paths`, `spec_sha=36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`, `decision_map_sha=cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`, `delivery_plan_sha=bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`, `ticket_set_digest`, `lease_expires_at`, `review_deadline_at`. Missing field => no dispatch.
- Worker emits `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>` only after every mandatory command exits 0.
- Each read-only reviewer first emits `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`; ACK mismatch invalidates verdict.
- Authoritative verdict source message: `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`; both axes must bind identical bytes.
- Revision limit is 3 attempts. Same Worker/session may revise only owned paths. If blocker_count fails to decrease between attempts, lease expires, ownership overlaps, or contract question changes product semantics, emit `OWNER_DECISION_NEEDED` and stop.
- PM performs serialized admission only: validate lease/ownership, non-empty diff, diff hygiene, generated/secret scan, tests/probes, atomic dual-axis bundle; enqueue protected-main merge queue; after merge rerun cumulative and same-generation seam on merged SHA before eligibility.
- Durable ingestion uses monotonically increasing `ingestion_seq`, persisted `reconciliation_watermark`, and `eligibility_generation`. Crash recovery replays source messages after watermark and recomputes eligibility from exact current bytes.
- Any late NOT_APPROVED first revokes eligibility fail-closed; PM evaluates finding reachability against current bytes. Only an unreachable finding superseded by a newer exact-byte dual PASS may remain history without demoting current state.

## Acceptance criteria

- [ ] Fixtures verify full-band retention, as-of/change, 400/1,000-lot ratios, denominator and split/capital-event adjustment; missing/N-A fixtures remain distinct.

- [ ] final bar availability boundary.
- [ ] corporate actions.
- [ ] 法人/TDCC/pledge as-of.
- [ ] 缺資料不捏造.
- [ ] rating independence test.
- [ ] Owned-path diff audit reports no write outside exclusive paths.
- [ ] Output includes source/formula/model/schema versions and explicit failure reasons.
