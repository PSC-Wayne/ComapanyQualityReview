# T16 — 普通 Audit Pillar 1 Reliability Candidate

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 以T06/T07/T08建立普通10% audit reliability candidate，與hard gate證據嚴格隔離。

**Blocked by:** T06, T07, T08

## Authority bindings
- Frozen Spec: `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`
- Decision Map: `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`
- Delivery Plan: `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`
- R9 ticket set generation: `PM_REQUIRED_AT_DISPATCH`

## Worker and Reviewer ownership
- Worker: Audit reliability Worker; isolated worktree; exact SHA handoff.
- SPEC Reviewer: read-only Frozen Spec/Decision Map conformance.
- QUALITY Reviewer: read-only schema, PIT, tests and failure semantics.
- PM: sole serialized integration authority after dual PASS.

## Dispatch binding
- Parent SHA: `PM_REQUIRED_AT_DISPATCH`; branch `wo/T16-reliability`; worktree `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T16-reliability`.
- G0/G1 timeout or silence is not approval.

## Owned paths
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/audit/reliability/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/audit/reliability/

## Shared read-only paths
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md
- Upstream producer paths named below.

## Forbidden paths
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/research/
- Every sibling ticket owned path, Hermes state/logs, production services/configuration and secrets.

## R9 Fresh-context execution contract (normative)

### Bounded inputs and producer locators
- T06 `AuditFilingInventory` — locator `AnalysisSnapshot.sections.audit_inventory`; producer schema `AuditFilingInventory.v1`; exact SHA in dispatch bundle.
- T07 `AuditGateDecision` — locator `AnalysisSnapshot.sections.audit_gate`; producer schema `AuditGateDecision.v1`; exact SHA in dispatch bundle.
- T08 `HighRiskNoteRegister` — locator `AnalysisSnapshot.sections.high_risk_notes`; producer schema `HighRiskNoteRegister.v1`; exact SHA in dispatch bundle.
- Schema major must equal v1; missing producer SHA or required field => `BLOCKED_CONTRACT`.

### Bounded output
- Contract `Pillar1AuditReliabilityCandidate.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/audit/reliability/contracts/Pillar1AuditReliabilityCandidate.schema.json`; runtime locator `AnalysisSnapshot.sections.pillar1_audit`.
- Required fields: `ordinary_score:null|decimal[0,100], ordinary_weight:literal[0.10], completeness:decimal[0,1], timeliness:decimal[0,1], consistency:decimal[0,1], evidence_family_ids:list<string[0..4096]>[1..64], hard_gate_excluded_evidence_ids:list<string[0..4096]>[0..64], coverage:decimal[0,1], rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries an explicit coverage value in `[0,1]`. This ticket’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; this ticket does not issue a rating; `rating_disposition=NO_RATING_NOT_APPLICABLE`; missing mandatory evidence follows the ticket-specific blocked/unknown rule, never an implicit score.

### Explicit non-goals
- Do not publish final quality/stars/faces/Bomb, do not edit another ticket owned path, and do not change Frozen Spec/Decision Map/Delivery Plan.

### Ticket-specific failure disposition
- Missing audit inventory/gate/note inputs yields Pillar1 candidate null and lower coverage; hard-gate evidence cannot also raise ordinary 10% score.

### Authority and PIT boundary
- Transform-only ticket: consumes PIT-admitted upstream artifacts; no direct external source and no timestamp rewriting.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/audit/reliability`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/audit/reliability` plus PM-selected integrated seam tests.
- Real-source probe — **NONE / NOT APPLICABLE**: consumes PIT-admitted upstream contracts; direct network forbidden.
- Diff gates — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`; `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`; `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- Dispatch manifest requires `assignment_id`, `active_binding_generation`, `eligibility_generation`, ticket/parent/branch/worktree/owned/forbidden paths, all authority SHAs, current R9 ticket_set_digest, lease and review deadline. Missing field blocks dispatch.
- `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>`.
- `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`.
- `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`.
- Revision limit is 3 attempts by same Worker on owned paths. Non-decreasing blockers, expired lease, overlap or semantic question => `OWNER_DECISION_NEEDED`.
- PM validates lease/ownership/non-empty diff/diff hygiene/generated-secret gate/tests/probes/atomic dual PASS; serialized merge queue; merged-SHA cumulative+black-box seam before eligibility.
- Durable ingestion persists monotonic `ingestion_seq`, `reconciliation_watermark`, `eligibility_generation`; replay after crash. Any late NOT_APPROVED first revokes eligibility fail-closed until reachability proves superseded exact-byte dual PASS makes it historical.

## Acceptance criteria
- [ ] Output contract validates all bounded fields and rejects undeclared/missing required fields.
- [ ] All inputs bind exact producer artifacts and versions.
- [ ] Focused/cumulative/diff/admission commands exit 0.
- [ ] Failure fixtures prove no fabrication and correct section-level block/no-rating behavior.
- [ ] REVIEW_READY, dual ACK/verdict and PM ingestion schemas validate exact bytes.
- [ ] No G0/G1, Git/GitHub or product implementation side effect occurs before authorization.
