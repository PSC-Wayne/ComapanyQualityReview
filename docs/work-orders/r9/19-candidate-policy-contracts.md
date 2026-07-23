# T19 — Non-publishable Candidate Scoring Policies

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 把Audit Gate與各pillar/valuation/downside候選序列化成不可發布、可供PIT lab執行的policies。

**Blocked by:** T07, T09, T10, T12, T13, T14, T16, T17, T18

**Generation:** `work-orders-r9`

**Frozen Spec SHA-256:** `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`

**Decision Map SHA-256:** `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`

**Delivery Plan SHA-256:** `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`

## Dispatch binding

- Parent SHA: `PM_REQUIRED_AT_DISPATCH` — PM replaces with exact protected-main SHA; unresolved means `BLOCKED`.
- Branch: `wo/T19-candidate-policy-contracts`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T19-candidate-policy-contracts`
- Attempt: `PM_REQUIRED_AT_DISPATCH`
- Worker: T19 Worker; isolated worktree; freeze candidate SHA after handoff.
- Review: Fresh Spec/Domain + Quality/Standards Reviewers; parallel read-only; same SHA/attempt.

## Filesystem ownership

**Owned paths (exclusive write):**

- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/policies/candidate/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/contracts/candidate_policy.py
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/policies/candidate/

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
- T14 `GovernancePeopleCandidate` — locator `AnalysisSnapshot.sections.governance_people`; producer schema `GovernancePeopleCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T16 `Pillar1AuditReliabilityCandidate` — locator `AnalysisSnapshot.sections.pillar1_audit`; producer schema `Pillar1AuditReliabilityCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T17 `ValuationUpsideDiagnostic` — locator `AnalysisSnapshot.sections.valuation_upside`; producer schema `ValuationUpsideDiagnostic.v1`; exact producer SHA must appear in dispatch bundle.
- T18 `DownsideStressDiagnostic` — locator `AnalysisSnapshot.sections.downside_stress`; producer schema `DownsideStressDiagnostic.v1`; exact producer SHA must appear in dispatch bundle.
- Compatibility: schema major must equal `v1`; unknown minor fields may be ignored only when required fields and semantics are unchanged; major mismatch or missing producer SHA => `BLOCKED_CONTRACT`.

### Bounded output
- Contract: `CandidatePolicyBundle.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/policies/candidate/contracts/CandidatePolicyBundle.schema.json`.
- Runtime locator: `AnalysisSnapshot.sections.candidate_policy`; immutable generation ID and producer candidate SHA are mandatory envelope fields.
- Required fields: `pillar_weights:record{audit_reliability:literal[0.10],earnings_capital_efficiency:literal[0.25],cash_balance_allocation:literal[0.25],business_moat:literal[0.25],governance:literal[0.05],people_adaptability:literal[0.10],sum:literal[1]}, quality_policy:record{normalisation:oneof[robust_z,winsor_rank],bands:list<record{lower:decimal[0,100],upper:decimal[0,100],label:string[1..32]}>[2..10]}, upside_bucket_policy:record{horizon_months:literal[12],thresholds:list<decimal[-1,10]>[exactly 4 ascending],audit_gate_contract:literal[AuditGateDecision.v1]}, downside_bucket_policy:record{horizon_months:literal[12],component_weights:record{maximum_drawdown_vulnerability:decimal[0.25,0.40],permanent_capital_loss_vulnerability:decimal[0.25,0.40],material_adverse_event_vulnerability:decimal[0.25,0.40],sum:literal[1]},composite_thresholds:list<decimal[0,100]>[exactly 4 ascending],construct_names:list<literal[maximum_drawdown_vulnerability,permanent_capital_loss_vulnerability,material_adverse_event_vulnerability]>[exactly 3]}, anti_double_count_policy:record{version:semver,evidence_family_policy_locator:literal[AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership],evidence_family_policy_canonicalization:literal[RFC8785_JCS],evidence_family_policy_sha256:sha256,evidence_family_ownership:list<record{evidence_family_id:string[1..128],primary_component:oneof[audit_reliability,earnings_capital_efficiency,cash_balance_allocation,business_moat,governance,people_adaptability,maximum_drawdown_vulnerability,permanent_capital_loss_vulnerability,material_adverse_event_vulnerability,hard_gate_only],excluded_from:list<oneof[audit_reliability,earnings_capital_efficiency,cash_balance_allocation,business_moat,governance,people_adaptability,maximum_drawdown_vulnerability,permanent_capital_loss_vulnerability,material_adverse_event_vulnerability]>[0..9],disposition:oneof[single_owner,excluded_hard_gate,excluded_duplicate],policy_rule_id:string[1..128],evidence_ids:list<string[1..128]>[1..64]}>[1..256]}, bomb_policy:record{allowed_event_types:list<oneof[formal_adverse_opinion,formal_disclaimer,confirmed_fraud,default,insolvency,major_regulatory_action,other_governed]>[1..7],requires_authoritative:true,requires_material:true,requires_current_relevance:true}, champion_id:string[1..128], challenger_ids:list<string[0..4096]>[1..32], policy_version:semver, publishable:literal[false], policy_coverage:decimal[0,1], rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries an explicit coverage value in `[0,1]`. This ticket’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; this ticket does not issue a rating; `rating_disposition=NO_RATING_NOT_APPLICABLE`; missing mandatory evidence follows the ticket-specific blocked/unknown rule, never an implicit score.

### Explicit non-goals
- Do not publish final quality/stars/faces/Bomb, do not edit another ticket owned path, and do not change Frozen Spec/Decision Map/Delivery Plan.

### Ticket-specific failure disposition
- Canonical slice-hash invariant: resolve the semantic JSON value at `evidence_family_policy_locator`, serialize that value alone with RFC 8785 JSON Canonicalization Scheme (JCS) UTF-8 bytes, and set `evidence_family_policy_sha256 = SHA-256(JCS(value))`. Raw token spans, parent-bundle bytes, whitespace-preserving serialization and implementation-specific key order are forbidden.
- Evidence-family invariant: each `evidence_family_id` appears exactly once and has exactly one `primary_component`; `excluded_from` has unique values and never contains the primary. `single_owner` iff `excluded_from=[]` and primary is not `hard_gate_only`; `excluded_hard_gate` iff primary=`hard_gate_only` and `excluded_from` is non-empty; `excluded_duplicate` iff primary is not hard-gate and `excluded_from` is non-empty. No split/multi-owner mode is permitted.
- Missing producer contract blocks affected candidate policy; bundle remains NON_PUBLISHABLE and cannot emit headline ratings.

### Authority and PIT boundary
- Transform-only ticket: consumes PIT-admitted upstream artifacts; no direct external source and no timestamp rewriting.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/policies/candidate`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/policies/candidate` plus every previously integrated black-box seam test selected by PM manifest.
- Real-source probe — **NONE / NOT APPLICABLE**: transform/governance-only ticket consumes frozen PIT-admitted fixtures; direct network access is forbidden.
- Diff hygiene — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`.
- Non-empty candidate — **MANDATORY**: `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`.
- Generated/secret admission — **MANDATORY**: `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- PM dispatch manifest is atomic and immutable: `assignment_id`, `active_binding_generation`, `eligibility_generation`, `ticket_id=T19`, `ticket_generation=R9`, `parent_sha`, `branch`, `worktree`, `owned_paths`, `forbidden_paths`, `spec_sha=36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`, `decision_map_sha=cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`, `delivery_plan_sha=bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`, `ticket_set_digest`, `lease_expires_at`, `review_deadline_at`. Missing field => no dispatch.
- Worker emits `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>` only after every mandatory command exits 0.
- Each read-only reviewer first emits `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`; ACK mismatch invalidates verdict.
- Authoritative verdict source message: `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`; both axes must bind identical bytes.
- Revision limit is 3 attempts. Same Worker/session may revise only owned paths. If blocker_count fails to decrease between attempts, lease expires, ownership overlaps, or contract question changes product semantics, emit `OWNER_DECISION_NEEDED` and stop.
- PM performs serialized admission only: validate lease/ownership, non-empty diff, diff hygiene, generated/secret scan, tests/probes, atomic dual-axis bundle; enqueue protected-main merge queue; after merge rerun cumulative and same-generation seam on merged SHA before eligibility.
- Durable ingestion uses monotonically increasing `ingestion_seq`, persisted `reconciliation_watermark`, and `eligibility_generation`. Crash recovery replays source messages after watermark and recomputes eligibility from exact current bytes.
- Any late NOT_APPROVED first revokes eligibility fail-closed; PM evaluates finding reachability against current bytes. Only an unreachable finding superseded by a newer exact-byte dual PASS may remain history without demoting current state.

## Acceptance criteria

- [ ] RFC8785/JCS fixtures prove whitespace/key-order/escaping-equivalent policy values yield the same SHA, while any semantic field/list-order change yields a different SHA; raw-token and parent-bundle hashes are rejected.

- [ ] Contract tests include quality/downside single-owner positives, hard-gate exclusion, duplicate exclusion, and reject duplicate family IDs, multi-owner encoding, primary-in-excluded_from, empty/non-empty conditional mismatches and any split mode.

- [ ] 權重骨架10/25/25/25/5/10.
- [ ] audit引用T07 contract.
- [ ] downside候選每項25%-40%.
- [ ] headline12月/24-36 sensitivity.
- [ ] T19可直接執行.
- [ ] Owned-path diff audit reports no write outside exclusive paths.
- [ ] Output includes source/formula/model/schema versions and explicit failure reasons.
