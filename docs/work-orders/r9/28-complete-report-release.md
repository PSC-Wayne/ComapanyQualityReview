# T28 — 完整單一查詢報告與Release Evidence

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 只組裝已交付能力，驗證真實query→same-generation snapshot→complete report，不新增domain功能。

**Blocked by:** T04, T05, T06, T07, T08, T09, T10, T11, T12, T13, T14, T15, T16, T17, T18, T24, T25, T26, T27

**Generation:** `work-orders-r9`

**Frozen Spec SHA-256:** `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`

**Decision Map SHA-256:** `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`

**Delivery Plan SHA-256:** `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`

## Dispatch binding

- Parent SHA: `PM_REQUIRED_AT_DISPATCH` — PM replaces with exact protected-main SHA; unresolved means `BLOCKED`.
- Branch: `wo/T28-complete-report-release`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T28-complete-report-release`
- Attempt: `PM_REQUIRED_AT_DISPATCH`
- Worker: T28 Worker; isolated worktree; freeze candidate SHA after handoff.
- Review: Fresh Spec/Domain + Quality/Standards Reviewers; parallel read-only; same SHA/attempt.

## Filesystem ownership

**Owned paths (exclusive write):**

- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/report/complete/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/e2e/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/artifacts/release_evidence/

**Shared read-only inputs:**

- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md`
- Outputs/contracts of every ticket named in `Blocked by`.

**Forbidden writes:** every path outside owned paths; formal spec/planning/research docs; other worktrees; Hermes state; production/config/secrets/order/notification systems.


## R9 Fresh-context execution contract (normative; supersedes shorthand above)

### Bounded inputs and producer locators
- T04 `OfficialFinancialArtifacts` — locator `AnalysisSnapshot.sections.financial_artifacts`; producer schema `OfficialFinancialArtifacts.v1`; exact producer SHA must appear in dispatch bundle.
- T05 `CanonicalFinancialFacts` — locator `AnalysisSnapshot.sections.financial_facts`; producer schema `CanonicalFinancialFacts.v1`; exact producer SHA must appear in dispatch bundle.
- T06 `AuditFilingInventory` — locator `AnalysisSnapshot.sections.audit_inventory`; producer schema `AuditFilingInventory.v1`; exact producer SHA must appear in dispatch bundle.
- T07 `AuditGateDecision` — locator `AnalysisSnapshot.sections.audit_gate`; producer schema `AuditGateDecision.v1`; exact producer SHA must appear in dispatch bundle.
- T08 `HighRiskNoteRegister` — locator `AnalysisSnapshot.sections.high_risk_notes`; producer schema `HighRiskNoteRegister.v1`; exact producer SHA must appear in dispatch bundle.
- T09 `EarningsCapitalEfficiencyCandidate` — locator `AnalysisSnapshot.sections.earnings_candidate`; producer schema `EarningsCapitalEfficiencyCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T10 `CashBalanceAllocationCandidate` — locator `AnalysisSnapshot.sections.cash_candidate`; producer schema `CashBalanceAllocationCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T11 `IndustryRoute` — locator `AnalysisSnapshot.sections.industry_route`; producer schema `IndustryRoute.v1`; exact producer SHA must appear in dispatch bundle.
- T12 `PeerOutlookEvidence` — locator `AnalysisSnapshot.sections.peer_outlook`; producer schema `PeerOutlookEvidence.v1`; exact producer SHA must appear in dispatch bundle.
- T13 `BusinessMoatCandidate` — locator `AnalysisSnapshot.sections.business_moat`; producer schema `BusinessMoatCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T14 `GovernancePeopleCandidate` — locator `AnalysisSnapshot.sections.governance_people`; producer schema `GovernancePeopleCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T15 `TechnicalChipOverlay` — locator `AnalysisSnapshot.sections.technical_chip`; producer schema `TechnicalChipOverlay.v1`; exact producer SHA must appear in dispatch bundle.
- T16 `Pillar1AuditReliabilityCandidate` — locator `AnalysisSnapshot.sections.pillar1_audit`; producer schema `Pillar1AuditReliabilityCandidate.v1`; exact producer SHA must appear in dispatch bundle.
- T17 `ValuationUpsideDiagnostic` — locator `AnalysisSnapshot.sections.valuation_upside`; producer schema `ValuationUpsideDiagnostic.v1`; exact producer SHA must appear in dispatch bundle.
- T18 `DownsideStressDiagnostic` — locator `AnalysisSnapshot.sections.downside_stress`; producer schema `DownsideStressDiagnostic.v1`; exact producer SHA must appear in dispatch bundle.
- T24 `FinalQualityRating` — locator `AnalysisSnapshot.sections.final_quality`; producer schema `FinalQualityRating.v1`; exact producer SHA must appear in dispatch bundle.
- T25 `FinalUpsideRating` — locator `AnalysisSnapshot.sections.final_upside`; producer schema `FinalUpsideRating.v1`; exact producer SHA must appear in dispatch bundle.
- T26 `FinalDownsideRating` — locator `AnalysisSnapshot.sections.final_downside`; producer schema `FinalDownsideRating.v1`; exact producer SHA must appear in dispatch bundle.
- T27 `OverrideAuditRecord` — locator `AnalysisSnapshot.sections.override_audit`; producer schema `OverrideAuditRecord.v1`; exact producer SHA must appear in dispatch bundle.
- Compatibility: schema major must equal `v1`; unknown minor fields may be ignored only when required fields and semantics are unchanged; major mismatch or missing producer SHA => `BLOCKED_CONTRACT`.

### Bounded output
- Contract: `CompleteAnalysisReport.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/report/complete/contracts/CompleteAnalysisReport.schema.json`.
- Runtime locator: `AnalysisSnapshot.sections.complete_report`; immutable generation ID and producer candidate SHA are mandatory envelope fields.
- Required fields: `query:record{identifier:string[1..128],market:oneof[TWSE,TPEx],decision_time:rfc3339_timezone_aware}, generation_id:uuid, snapshot_hash:sha256, identity:record{issuer_id:string[1..64],security_id:string[1..64],market:oneof[TWSE,TPEx]}, audit:record{inventory_ref:string[1..256],gate_ref:string[1..256],high_risk_notes_ref:string[1..256]}, financial_quality:record{canonical_facts_ref:string[1..256],earnings_candidate_ref:string[1..256],cash_candidate_ref:string[1..256],audit_pillar_ref:string[1..256]}, business_industry_moat:record{industry_route_ref:string[1..256],peer_outlook_ref:string[1..256],business_moat_ref:string[1..256]}, governance_people:record{governance_people_ref:string[1..256]}, valuation_upside:record{diagnostic_ref:string[1..256],final_rating_ref:string[1..256]}, downside_risk_stress:record{diagnostic_ref:string[1..256],final_rating_ref:string[1..256]}, technical_chip:record{overlay_ref:string[1..256],independent_from_ratings:true}, quality:record{final_rating_ref:string[1..256]}, override:record{audit_record_ref:null|string[1..256]}, coverage:record{overall:decimal[0,1],by_section:map<oneof[identity,audit,financial_quality,business_industry_moat,governance_people,valuation_upside,downside_risk_stress,technical_chip,quality,override],decimal[0,1]>[1..10]}, confidence:record{overall:decimal[0,1],by_section:map<oneof[identity,audit,financial_quality,business_industry_moat,governance_people,valuation_upside,downside_risk_stress,technical_chip,quality,override],decimal[0,1]>[1..10]}, limitations:list<string[1..512]>[0..128], evidence_manifest:list<record{evidence_id:string[1..128],source_url:https_url,content_sha256:sha256,available_at:rfc3339_timezone_aware,retrieved_at:rfc3339_timezone_aware}>[1..10000], data_versions:list<record{component:string[1..64],version:string[1..128],producer_sha:sha256}>[1..128], analysis_time:rfc3339_timezone_aware, no_rating_propagation:list<record{section:string[1..64],reason_code:string[1..64]}>[0..32]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries section coverage and confidence in `[0,1]`; rating tickets preserve nullable headline plus an explicit bounded `no_rating_reason`. T28 propagates every upstream no-rating reason without inventing a rating.

### Explicit non-goals
- Assemble existing same-generation sections only; do not implement missing upstream domain features.

### Ticket-specific failure disposition
- Any generation/hash mismatch or missing mandatory section blocks report release; assembler never fills upstream gaps.

### Authority and PIT boundary
- Transform-only ticket: consumes PIT-admitted upstream artifacts; no direct external source and no timestamp rewriting.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/e2e`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/e2e` plus every previously integrated black-box seam test selected by PM manifest.
- Real-source probe — **NONE / NOT APPLICABLE**: transform/governance-only ticket consumes frozen PIT-admitted fixtures; direct network access is forbidden.
- Diff hygiene — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`.
- Non-empty candidate — **MANDATORY**: `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`.
- Generated/secret admission — **MANDATORY**: `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- PM dispatch manifest is atomic and immutable: `assignment_id`, `active_binding_generation`, `eligibility_generation`, `ticket_id=T28`, `ticket_generation=R9`, `parent_sha`, `branch`, `worktree`, `owned_paths`, `forbidden_paths`, `spec_sha=36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`, `decision_map_sha=cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`, `delivery_plan_sha=bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`, `ticket_set_digest`, `lease_expires_at`, `review_deadline_at`. Missing field => no dispatch.
- Worker emits `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>` only after every mandatory command exits 0.
- Each read-only reviewer first emits `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`; ACK mismatch invalidates verdict.
- Authoritative verdict source message: `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`; both axes must bind identical bytes.
- Revision limit is 3 attempts. Same Worker/session may revise only owned paths. If blocker_count fails to decrease between attempts, lease expires, ownership overlaps, or contract question changes product semantics, emit `OWNER_DECISION_NEEDED` and stop.
- PM performs serialized admission only: validate lease/ownership, non-empty diff, diff hygiene, generated/secret scan, tests/probes, atomic dual-axis bundle; enqueue protected-main merge queue; after merge rerun cumulative and same-generation seam on merged SHA before eligibility.
- Durable ingestion uses monotonically increasing `ingestion_seq`, persisted `reconciliation_watermark`, and `eligibility_generation`. Crash recovery replays source messages after watermark and recomputes eligibility from exact current bytes.
- Any late NOT_APPROVED first revokes eligibility fail-closed; PM evaluates finding reachability against current bytes. Only an unreachable finding superseded by a newer exact-byte dual PASS may remain history without demoting current state.

## Acceptance criteria

- [ ] final card完整.
- [ ] failure states契約.
- [ ] authority+cumulative+secret gates.
- [ ] 結論可下鑽.
- [ ] 不deploy/schedule/notify/order.
- [ ] Owned-path diff audit reports no write outside exclusive paths.
- [ ] Output includes source/formula/model/schema versions and explicit failure reasons.
