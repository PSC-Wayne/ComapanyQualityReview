# T10 — 現金、資產負債與資本配置Candidate Pillar

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 產出Pillar3候選分項與cash/balance/capital-allocation section。

**Blocked by:** T05, T08

**Generation:** `work-orders-r9`

**Frozen Spec SHA-256:** `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`

**Decision Map SHA-256:** `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`

**Delivery Plan SHA-256:** `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`

## Dispatch binding

- Parent SHA: `PM_REQUIRED_AT_DISPATCH` — PM replaces with exact protected-main SHA; unresolved means `BLOCKED`.
- Branch: `wo/T10-cash-balance-allocation`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T10-cash-balance-allocation`
- Attempt: `PM_REQUIRED_AT_DISPATCH`
- Worker: T10 Worker; isolated worktree; freeze candidate SHA after handoff.
- Review: Fresh Spec/Domain + Quality/Standards Reviewers; parallel read-only; same SHA/attempt.

## Filesystem ownership

**Owned paths (exclusive write):**

- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/scoring/cash_balance/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/scoring/cash_balance/

**Shared read-only inputs:**

- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md`
- Outputs/contracts of every ticket named in `Blocked by`.

**Forbidden writes:** every path outside owned paths; formal spec/planning/research docs; other worktrees; Hermes state; production/config/secrets/order/notification systems.


## R9 Fresh-context execution contract (normative; supersedes shorthand above)

### Bounded inputs and producer locators
- T05 `CanonicalFinancialFacts` — locator `AnalysisSnapshot.sections.financial_facts`; producer schema `CanonicalFinancialFacts.v1`; exact producer SHA must appear in dispatch bundle.
- T08 `HighRiskNoteRegister` — locator `AnalysisSnapshot.sections.high_risk_notes`; producer schema `HighRiskNoteRegister.v1`; exact producer SHA must appear in dispatch bundle.
- Compatibility: schema major must equal `v1`; unknown minor fields may be ignored only when required fields and semantics are unchanged; major mismatch or missing producer SHA => `BLOCKED_CONTRACT`.

### Bounded output
- Contract: `CashBalanceAllocationCandidate.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/scoring/cash_balance/contracts/CashBalanceAllocationCandidate.schema.json`.
- Runtime locator: `AnalysisSnapshot.sections.cash_candidate`; immutable generation ID and producer candidate SHA are mandatory envelope fields.
- Required fields: `cash_conversion:record{cfo_to_ebit:null|decimal[-1e18,1e18],fcf_to_net_income:null|decimal[-1e18,1e18],working_capital_days:null|decimal[-1e18,1e18]}, leverage:record{net_debt_to_ebitda:null|decimal[-1e18,1e18],debt_to_equity:null|decimal[-1e18,1e18],interest_coverage:null|decimal[-1e18,1e18]}, liquidity:record{current_ratio:null|decimal[-1e18,1e18],quick_ratio:null|decimal[-1e18,1e18],cash_ratio:null|decimal[-1e18,1e18]}, dilution:record{five_year_share_change_pct:null|decimal[-1e18,1e18],convertible_overhang_pct:null|decimal[-1e18,1e18]}, allocation:record{capex_to_sales:null|decimal[-1e18,1e18],dividend_payout:null|decimal[-1e18,1e18],buyback_pct:null|decimal[-1e18,1e18],acquisition_spend:null|decimal[-1e18,1e18]}, evidence_family_ids:list<string[0..4096]>[1..64], coverage:decimal[0,1], candidate_score:null|decimal[0,100], rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries an explicit coverage value in `[0,1]`. This ticket’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; this ticket does not issue a rating; `rating_disposition=NO_RATING_NOT_APPLICABLE`; missing mandatory evidence follows the ticket-specific blocked/unknown rule, never an implicit score.

### Explicit non-goals
- Do not publish final quality/stars/faces/Bomb, do not edit another ticket owned path, and do not change Frozen Spec/Decision Map/Delivery Plan.

### Ticket-specific failure disposition
- Missing cash/debt/dilution evidence yields component null and coverage reduction; no cash-flow or leverage fabrication.

### Authority and PIT boundary
- Transform-only ticket: consumes PIT-admitted upstream artifacts; no direct external source and no timestamp rewriting.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/scoring/cash_balance`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/scoring/cash_balance` plus every previously integrated black-box seam test selected by PM manifest.
- Real-source probe — **NONE / NOT APPLICABLE**: transform/governance-only ticket consumes frozen PIT-admitted fixtures; direct network access is forbidden.
- Diff hygiene — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`.
- Non-empty candidate — **MANDATORY**: `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`.
- Generated/secret admission — **MANDATORY**: `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- PM dispatch manifest is atomic and immutable: `assignment_id`, `active_binding_generation`, `eligibility_generation`, `ticket_id=T10`, `ticket_generation=R9`, `parent_sha`, `branch`, `worktree`, `owned_paths`, `forbidden_paths`, `spec_sha=36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`, `decision_map_sha=cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`, `delivery_plan_sha=bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`, `ticket_set_digest`, `lease_expires_at`, `review_deadline_at`. Missing field => no dispatch.
- Worker emits `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>` only after every mandatory command exits 0.
- Each read-only reviewer first emits `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`; ACK mismatch invalidates verdict.
- Authoritative verdict source message: `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`; both axes must bind identical bytes.
- Revision limit is 3 attempts. Same Worker/session may revise only owned paths. If blocker_count fails to decrease between attempts, lease expires, ownership overlaps, or contract question changes product semantics, emit `OWNER_DECISION_NEEDED` and stop.
- PM performs serialized admission only: validate lease/ownership, non-empty diff, diff hygiene, generated/secret scan, tests/probes, atomic dual-axis bundle; enqueue protected-main merge queue; after merge rerun cumulative and same-generation seam on merged SHA before eligibility.
- Durable ingestion uses monotonically increasing `ingestion_seq`, persisted `reconciliation_watermark`, and `eligibility_generation`. Crash recovery replays source messages after watermark and recomputes eligibility from exact current bytes.
- Any late NOT_APPROVED first revokes eligibility fail-closed; PM evaluates finding reachability against current bytes. Only an unreachable finding superseded by a newer exact-byte dual PASS may remain history without demoting current state.

## Acceptance criteria

- [ ] cash conversion/working capital/debt/liquidity/solvency/FCF分開.
- [ ] 資本配置保留decision-time evidence.
- [ ] balance/cash checks.
- [ ] 缺值null+reason.
- [ ] 標示NON_PUBLISHABLE_CANDIDATE.
- [ ] Owned-path diff audit reports no write outside exclusive paths.
- [ ] Output includes source/formula/model/schema versions and explicit failure reasons.
