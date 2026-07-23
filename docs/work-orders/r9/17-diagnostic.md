# T17 — G1前 Valuation與Upside Diagnostic

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 建立NON_PUBLISHABLE valuation routing、relative/DCF/reverseDCF、12m scenarios與model disagreement candidate。

**Blocked by:** T03, T05, T09, T10, T12, T13

## Authority bindings
- Frozen Spec: `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`
- Decision Map: `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`
- Delivery Plan: `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`
- R9 ticket set generation: `PM_REQUIRED_AT_DISPATCH`

## Worker and Reviewer ownership
- Worker: Valuation Diagnostic Worker; isolated worktree; exact SHA handoff.
- SPEC Reviewer: read-only Frozen Spec/Decision Map conformance.
- QUALITY Reviewer: read-only schema, PIT, tests and failure semantics.
- PM: sole serialized integration authority after dual PASS.

## Dispatch binding
- Parent SHA: `PM_REQUIRED_AT_DISPATCH`; branch `wo/T17-diagnostic`; worktree `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T17-diagnostic`.
- G0/G1 timeout or silence is not approval.

## Owned paths
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/valuation/diagnostic/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/valuation/diagnostic/

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
- T03 `AdmittedFactSet` — locator `AnalysisSnapshot.sections.pit_admission`, select `fact_type=official_close_price` whose `available_at <= decision_time`; schema `AdmittedFactSet.v1`; exact producer SHA in dispatch bundle.
- T05 `CanonicalFinancialFacts` — locator `AnalysisSnapshot.sections.financial_facts`; producer schema `CanonicalFinancialFacts.v1`; exact SHA in dispatch bundle.
- T09 `EarningsCapitalEfficiencyCandidate` — locator `AnalysisSnapshot.sections.earnings_candidate`; producer schema `EarningsCapitalEfficiencyCandidate.v1`; exact SHA in dispatch bundle.
- T10 `CashBalanceAllocationCandidate` — locator `AnalysisSnapshot.sections.cash_candidate`; producer schema `CashBalanceAllocationCandidate.v1`; exact SHA in dispatch bundle.
- T12 `PeerOutlookEvidence` — locator `AnalysisSnapshot.sections.peer_outlook`; producer schema `PeerOutlookEvidence.v1`; exact SHA in dispatch bundle.
- T13 `BusinessMoatCandidate` — locator `AnalysisSnapshot.sections.business_moat`; producer schema `BusinessMoatCandidate.v1`; exact SHA in dispatch bundle.
- Schema major must equal v1; missing producer SHA or required field => `BLOCKED_CONTRACT`.

### Bounded output
- Contract `ValuationUpsideDiagnostic.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/valuation/diagnostic/contracts/ValuationUpsideDiagnostic.schema.json`; runtime locator `AnalysisSnapshot.sections.valuation_upside`.
- Required fields: `current_price:record{value:decimal[greater_than 0],currency:literal[TWD],price_time:rfc3339_timezone_aware,fact_id:string[1..128],available_at:rfc3339_timezone_aware}, route:oneof[relative,dcf,reverse_dcf,multi_model], relative_value:null|record{peer_ids:list<string[0..4096]>[1..50],multiple:oneof[pe,pb,ev_ebitda],issuer_multiple:decimal[-1e18,1e18],peer_median:decimal[-1e18,1e18],implied_value:decimal[greater_than 0],upside_pct:decimal[-1e18,1e18]}, dcf:null|record{forecast_years:int[5,10],revenue_growth:list<decimal[-1,5]>[5..10],operating_margin:list<decimal[-1,1]>[5..10],wacc:decimal[0,1],terminal_growth:decimal[-0.1,0.1],net_debt:decimal[-1e18,1e18],shares:decimal[greater_than 0],implied_value:decimal[greater_than 0],upside_pct:decimal[-1e18,1e18]}, reverse_dcf:null|record{current_price:decimal[greater_than 0],implied_revenue_cagr:decimal[-1,5],implied_terminal_margin:decimal[-1,1],wacc:decimal[0,1],feasibility:oneof[plausible,stretched,implausible]}, scenarios:record{bear:record{value:decimal[greater_than 0],upside_pct:decimal[-1e18,1e18],assumption_ids:list<string[0..4096]>[1..32]},base:record{value:decimal[greater_than 0],upside_pct:decimal[-1e18,1e18],assumption_ids:list<string[0..4096]>[1..32]},bull:record{value:decimal[greater_than 0],upside_pct:decimal[-1e18,1e18],assumption_ids:list<string[0..4096]>[1..32]}}, model_disagreement:record{range_pct:decimal[0,1000],max_model:string[1..32],min_model:string[1..32]}, horizon_months:literal[12], sensitivity_24_36:null|record{isolated:true,month24_upside_pct:decimal[-1e18,1e18],month36_upside_pct:decimal[-1e18,1e18],headline_eligible:false}, evidence_ids:list<string[0..4096]>[1..128], coverage:decimal[0,1], rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries an explicit coverage value in `[0,1]`. This ticket’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; this ticket does not issue a rating; `rating_disposition=NO_RATING_NOT_APPLICABLE`; missing mandatory evidence follows the ticket-specific blocked/unknown rule, never an implicit score.

### Explicit non-goals
- Do not publish final quality/stars/faces/Bomb, do not edit another ticket owned path, and do not change Frozen Spec/Decision Map/Delivery Plan.

### Ticket-specific failure disposition
- Unavailable valuation model input disables that route; model disagreement remains visible; no model may substitute invented assumptions.

### Authority and PIT boundary
- Valuation uses the T03 PIT-admitted official current close price/location plus financial/peer/business evidence and 12-month headline assumptions; 24/36 remain isolated sensitivity.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/valuation/diagnostic`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/valuation/diagnostic` plus PM-selected integrated seam tests.
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
