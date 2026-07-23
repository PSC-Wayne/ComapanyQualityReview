# T22 — PIT Temporal Calibration與Validation Report

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 用candidate policies與12月labels做時間切分、holdout、false signal、lead time與穩定性驗證。

**Blocked by:** T16, T17, T18, T19, T21

**Generation:** `work-orders-r9`

**Frozen Spec SHA-256:** `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`

**Decision Map SHA-256:** `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`

**Delivery Plan SHA-256:** `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`

## Dispatch binding

- Parent SHA: `PM_REQUIRED_AT_DISPATCH` — PM replaces with exact protected-main SHA; unresolved means `BLOCKED`.
- Branch: `wo/T22-temporal-calibration`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T22-temporal-calibration`
- Attempt: `PM_REQUIRED_AT_DISPATCH`
- Worker: T22 Worker; isolated worktree; freeze candidate SHA after handoff.
- Review: Fresh Spec/Domain + Quality/Standards Reviewers; parallel read-only; same SHA/attempt.

## Filesystem ownership

**Owned paths (exclusive write):**

- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/calibration/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/calibration/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/artifacts/calibration_candidate/

**Shared read-only inputs:**

- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md`
- Outputs/contracts of every ticket named in `Blocked by`.

**Forbidden writes:** every path outside owned paths; formal spec/planning/research docs; other worktrees; Hermes state; production/config/secrets/order/notification systems.


## R9 Fresh-context execution contract (normative; supersedes shorthand above)

### Bounded inputs and producer locators
- T16 `Pillar1AuditReliabilityCandidate` — locator `AnalysisSnapshot.sections.pillar1_audit`; producer schema `Pillar1AuditReliabilityCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T17 `ValuationUpsideDiagnostic` — locator `AnalysisSnapshot.sections.valuation_upside`; producer schema `ValuationUpsideDiagnostic.v1`; exact producer SHA must appear in dispatch bundle.
- T18 `DownsideStressDiagnostic` — locator `AnalysisSnapshot.sections.downside_stress`; producer schema `DownsideStressDiagnostic.v1`; exact producer SHA must appear in dispatch bundle.
- T19 `CandidatePolicyBundle` — locator `AnalysisSnapshot.sections.candidate_policy`; producer schema `CandidatePolicyBundle.v1`; exact producer SHA must appear in dispatch bundle.
- T21 `OutcomeLabelSet` — locator `AnalysisSnapshot.sections.outcome_labels`; producer schema `OutcomeLabelSet.v1`; exact producer SHA must appear in dispatch bundle.
- Compatibility: schema major must equal `v1`; unknown minor fields may be ignored only when required fields and semantics are unchanged; major mismatch or missing producer SHA => `BLOCKED_CONTRACT`.

### Bounded output
- Contract: `CalibrationValidationReport.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/calibration/contracts/CalibrationValidationReport.schema.json`.
- Runtime locator: `AnalysisSnapshot.sections.calibration_validation`; immutable generation ID and producer candidate SHA are mandatory envelope fields.
- Required fields: `policy_version:semver, train_windows:list<record{start:date,end:date,issuer_count:uint32}>[1..32], holdout_windows:list<record{start:date,end:date,issuer_count:uint32}>[1..32], purge_days:uint16, embargo_days:uint16, metrics:record{auc:null|decimal[0,1],brier:null|decimal[0,1],calibration_error:null|decimal[0,1],precision_at_top:null|decimal[0,1]}, calibration_curves:list<record{bucket:string[1..32],predicted:decimal[0,1],observed:decimal[0,1],count:uint32}>[1..100], champion_verdict:oneof[pass,fail,blocked], challenger_results:list<record{challenger_id:string[1..128],metrics_hash:sha256,verdict:oneof[better,worse,inconclusive]}>[0..32], threshold_candidates:record{quality_bands:list<decimal[0,100]>[1..9 ascending],upside_stars:list<decimal[-1,10]>[exactly 4 ascending],downside_faces:list<decimal[0,100]>[exactly 4 ascending],bomb_materiality:decimal[0,1]}, leakage_checks:record{pit_join_pass:boolean,purge_pass:boolean,embargo_pass:boolean,survivorship_pass:boolean,same_generation_pass:boolean}, validation_coverage:decimal[0,1], rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries an explicit coverage value in `[0,1]`. This ticket’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; this ticket does not issue a rating; `rating_disposition=NO_RATING_NOT_APPLICABLE`; missing mandatory evidence follows the ticket-specific blocked/unknown rule, never an implicit score.

### Explicit non-goals
- Do not publish final quality/stars/faces/Bomb, do not edit another ticket owned path, and do not change Frozen Spec/Decision Map/Delivery Plan.

### Ticket-specific failure disposition
- Leakage, failed purge/embargo or absent producer version makes champion_verdict=blocked; no freeze package may be issued.

### Authority and PIT boundary
- Transform-only ticket: consumes PIT-admitted upstream artifacts; no direct external source and no timestamp rewriting.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/calibration`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/calibration` plus every previously integrated black-box seam test selected by PM manifest.
- Real-source probe — **NONE / NOT APPLICABLE**: transform/governance-only ticket consumes frozen PIT-admitted fixtures; direct network access is forbidden.
- Diff hygiene — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`.
- Non-empty candidate — **MANDATORY**: `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`.
- Generated/secret admission — **MANDATORY**: `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- PM dispatch manifest is atomic and immutable: `assignment_id`, `active_binding_generation`, `eligibility_generation`, `ticket_id=T22`, `ticket_generation=R9`, `parent_sha`, `branch`, `worktree`, `owned_paths`, `forbidden_paths`, `spec_sha=36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`, `decision_map_sha=cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`, `delivery_plan_sha=bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`, `ticket_set_digest`, `lease_expires_at`, `review_deadline_at`. Missing field => no dispatch.
- Worker emits `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>` only after every mandatory command exits 0.
- Each read-only reviewer first emits `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`; ACK mismatch invalidates verdict.
- Authoritative verdict source message: `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`; both axes must bind identical bytes.
- Revision limit is 3 attempts. Same Worker/session may revise only owned paths. If blocker_count fails to decrease between attempts, lease expires, ownership overlaps, or contract question changes product semantics, emit `OWNER_DECISION_NEEDED` and stop.
- PM performs serialized admission only: validate lease/ownership, non-empty diff, diff hygiene, generated/secret scan, tests/probes, atomic dual-axis bundle; enqueue protected-main merge queue; after merge rerun cumulative and same-generation seam on merged SHA before eligibility.
- Durable ingestion uses monotonically increasing `ingestion_seq`, persisted `reconciliation_watermark`, and `eligibility_generation`. Crash recovery replays source messages after watermark and recomputes eligibility from exact current bytes.
- Any late NOT_APPROVED first revokes eligibility fail-closed; PM evaluates finding reachability against current bytes. Only an unreachable finding superseded by a newer exact-byte dual PASS may remain history without demoting current state.

## Acceptance criteria

- [ ] temporal split/purge/embargo.
- [ ] quality bands/upside buckets/downside weights/Bomb thresholds候選.
- [ ] 單調/壓力期穩定.
- [ ] FP/FN/lead time/coverage.
- [ ] T22只產生NON_PUBLISHABLE validation report，不要求或產生freeze；T23只能在T22完成後建立Wayne G1 decision。
- [ ] Owned-path diff audit reports no write outside exclusive paths.
- [ ] Output includes source/formula/model/schema versions and explicit failure reasons.
