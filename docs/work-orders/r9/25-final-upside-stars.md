# T25 — 正式12月Upside Stars Publication Slice

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 依G1 buckets與AuditGateDecision發布1-5星ordinal upside。

**Blocked by:** T07, T09, T10, T12, T13, T17, T23

**Generation:** `work-orders-r9`

**Frozen Spec SHA-256:** `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`

**Decision Map SHA-256:** `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`

**Delivery Plan SHA-256:** `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`

## Dispatch binding

- Parent SHA: `PM_REQUIRED_AT_DISPATCH` — PM replaces with exact protected-main SHA; unresolved means `BLOCKED`.
- Branch: `wo/T25-final-upside-stars`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T25-final-upside-stars`
- Attempt: `PM_REQUIRED_AT_DISPATCH`
- Worker: T25 Worker; isolated worktree; freeze candidate SHA after handoff.
- Review: Fresh Spec/Domain + Quality/Standards Reviewers; parallel read-only; same SHA/attempt.

## Filesystem ownership

**Owned paths (exclusive write):**

- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/ratings/upside/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/ratings/upside/

**Shared read-only inputs:**

- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md`
- Outputs/contracts of every ticket named in `Blocked by`.

**Forbidden writes:** every path outside owned paths; formal spec/planning/research docs; other worktrees; Hermes state; production/config/secrets/order/notification systems.


## R9 Fresh-context execution contract (normative; supersedes shorthand above)

### Bounded inputs and producer locators
- T07 `AuditGateDecision` — locator `AnalysisSnapshot.sections.audit_gate`; producer schema `AuditGateDecision.v1`; exact producer SHA must appear in dispatch bundle.
- T09 `EarningsCapitalEfficiencyCandidate` — locator `AnalysisSnapshot.sections.earnings_candidate`; producer schema `EarningsCapitalEfficiencyCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T10 `CashBalanceAllocationCandidate` — locator `AnalysisSnapshot.sections.cash_candidate`; producer schema `CashBalanceAllocationCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T12 `PeerOutlookEvidence` — locator `AnalysisSnapshot.sections.peer_outlook`; producer schema `PeerOutlookEvidence.v1`; exact producer SHA must appear in dispatch bundle.
- T13 `BusinessMoatCandidate` — locator `AnalysisSnapshot.sections.business_moat`; producer schema `BusinessMoatCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T17 `ValuationUpsideDiagnostic` — locator `AnalysisSnapshot.sections.valuation_upside`; producer schema `ValuationUpsideDiagnostic.v1`; exact producer SHA must appear in dispatch bundle.
- T23 `CalibrationFreezeManifest.v1` — filesystem locator `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/governance/calibration-freeze/decisions/<decision_id>.json`; dispatch bundle must bind `decision_id`, exact `decision_file_sha256`, `approved_policy_version`, and schema `CalibrationFreezeManifest.v1`.
- Compatibility: schema major must equal `v1`; unknown minor fields may be ignored only when required fields and semantics are unchanged; major mismatch or missing producer SHA => `BLOCKED_CONTRACT`.

### Bounded output
- Contract: `FinalUpsideRating.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/ratings/upside/contracts/FinalUpsideRating.schema.json`.
- Runtime locator: `AnalysisSnapshot.sections.final_upside`; immutable generation ID and producer candidate SHA are mandatory envelope fields.
- Required fields: `stars_1_5:null|int[1,5], horizon_months:literal[12], current_price:decimal[greater_than 0], valuation_route:oneof[relative,dcf,reverse_dcf,multi_model], scenario_summary:record{bear_upside_pct:decimal[-1e18,1e18],base_upside_pct:decimal[-1e18,1e18],bull_upside_pct:decimal[-1e18,1e18],model_disagreement_pct:decimal[0,1000]}, coverage:decimal[0,1], confidence:decimal[0,1], audit_gate_applied:record{state:oneof[clear,cap,no_rating,blocked],star_cap:null|int[1,5],reason_codes:list<string[0..4096]>[0..32]}, no_rating_reason:null|oneof[formal_disclaimer,formal_adverse,missing_frozen_policy,insufficient_coverage,authority_conflict], policy_version:semver, freeze_decision_id:string[1..128], freeze_decision_file_sha256:sha256`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries section coverage and confidence in `[0,1]`; rating tickets preserve nullable headline plus an explicit bounded `no_rating_reason`. T28 propagates every upstream no-rating reason without inventing a rating.

### Explicit non-goals
- Apply only frozen valuation/upside policy; do not first implement DCF, reverse DCF, peer model or scenarios.

### Ticket-specific failure disposition
- Missing frozen valuation diagnostic or audit gate blocks stars/no-rating as specified; 24/36 sensitivity never enters headline.

### Authority and PIT boundary
- Transform-only ticket: consumes PIT-admitted upstream artifacts; no direct external source and no timestamp rewriting.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/ratings/upside`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/ratings/upside` plus every previously integrated black-box seam test selected by PM manifest.
- Real-source probe — **NONE / NOT APPLICABLE**: transform/governance-only ticket consumes frozen PIT-admitted fixtures; direct network access is forbidden.
- Diff hygiene — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`.
- Non-empty candidate — **MANDATORY**: `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`.
- Generated/secret admission — **MANDATORY**: `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- PM dispatch manifest is atomic and immutable: `assignment_id`, `active_binding_generation`, `eligibility_generation`, `ticket_id=T25`, `ticket_generation=R9`, `parent_sha`, `branch`, `worktree`, `owned_paths`, `forbidden_paths`, `spec_sha=36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`, `decision_map_sha=cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`, `delivery_plan_sha=bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`, `ticket_set_digest`, `lease_expires_at`, `review_deadline_at`. Missing field => no dispatch.
- Worker emits `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>` only after every mandatory command exits 0.
- Each read-only reviewer first emits `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`; ACK mismatch invalidates verdict.
- Authoritative verdict source message: `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`; both axes must bind identical bytes.
- Revision limit is 3 attempts. Same Worker/session may revise only owned paths. If blocker_count fails to decrease between attempts, lease expires, ownership overlaps, or contract question changes product semantics, emit `OWNER_DECISION_NEEDED` and stop.
- PM performs serialized admission only: validate lease/ownership, non-empty diff, diff hygiene, generated/secret scan, tests/probes, atomic dual-axis bundle; enqueue protected-main merge queue; after merge rerun cumulative and same-generation seam on merged SHA before eligibility.
- Durable ingestion uses monotonically increasing `ingestion_seq`, persisted `reconciliation_watermark`, and `eligibility_generation`. Crash recovery replays source messages after watermark and recomputes eligibility from exact current bytes.
- Any late NOT_APPROVED first revokes eligibility fail-closed; PM evaluates finding reachability against current bytes. Only an unreachable finding superseded by a newer exact-byte dual PASS may remain history without demoting current state.

## Acceptance criteria

- [ ] 適用valuation route.
- [ ] peer/DCF/reverseDCF/scenarios.
- [ ] audit cases不提高低/no-rating.
- [ ] 24/36 sensitivity only.
- [ ] disagreement/coverage/confidence.
- [ ] Owned-path diff audit reports no write outside exclusive paths.
- [ ] Output includes source/formula/model/schema versions and explicit failure reasons.
