# T01 — 建立可執行 Golden Path與共同測試骨架

**Status:** draft-for-wayne-review — implementation not authorized

**Objective:** 以受控fixture建立唯一query→identity→immutable AnalysisSnapshot→rendered report主seam及共同execution/test envelope。

**Blocked by:** G0 authorization only

**Generation:** `work-orders-r9`

**Frozen Spec SHA-256:** `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`

**Decision Map SHA-256:** `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`

**Delivery Plan SHA-256:** `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`

## Dispatch binding

- Parent SHA: `PM_REQUIRED_AT_DISPATCH` — PM replaces with exact protected-main SHA; unresolved means `BLOCKED`.
- Branch: `wo/T01-golden-path`
- Worktree: `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.worktrees/T01-golden-path`
- Attempt: `PM_REQUIRED_AT_DISPATCH`
- Worker: T01 Worker; isolated worktree; freeze candidate SHA after handoff.
- Review: Fresh Spec/Domain + Quality/Standards Reviewers; parallel read-only; same SHA/attempt.

## Filesystem ownership

**Owned paths (exclusive write):**

- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/pyproject.toml
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/runtime/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/report_shell/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/golden_path/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tests/contracts/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/.github/workflows/ci.yml
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tools/admission_scan.py
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/tools/validate_json.py
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/governance/calibration-freeze/schemas/

**Shared read-only inputs:**

- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md`
- Outputs/contracts of every ticket named in `Blocked by`.

**Forbidden writes:** every path outside owned paths; formal spec/planning/research docs; other worktrees; Hermes state; production/config/secrets/order/notification systems.


## R9 Fresh-context execution contract (normative; supersedes shorthand above)

### Bounded inputs and producer locators
- External request `{identifier:string, market:TWSE|TPEx|null, decision_time:RFC3339 timezone-aware}` plus G0 dispatch manifest.
- Compatibility: schema major must equal `v1`; unknown minor fields may be ignored only when required fields and semantics are unchanged; major mismatch or missing producer SHA => `BLOCKED_CONTRACT`.

### Bounded output
- Contract: `GoldenPathResult.v1`; schema source `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/src/company_quality/runtime/contracts/GoldenPathResult.schema.json`.
- Runtime locator: `AnalysisSnapshot.sections.golden_path`; immutable generation ID and producer candidate SHA are mandatory envelope fields.
- Required fields: `query:record{identifier:string[1..128],market:null|oneof[TWSE,TPEx],decision_time:rfc3339_timezone_aware}, generation_id:uuid, snapshot_hash:sha256, report_hash:sha256, error_code:null|oneof[invalid_decision_time,identity_ambiguous,unsupported_scope,blocked_contract,generation_mismatch], foundation_artifacts:record{admission_scan_path:literal[tools/admission_scan.py],validate_json_path:literal[tools/validate_json.py],freeze_package_schema_path:literal[docs/governance/calibration-freeze/schemas/CalibrationFreezePackage.v1.json],freeze_manifest_schema_path:literal[docs/governance/calibration-freeze/schemas/CalibrationFreezeManifest.v1.json]}, contract_coverage:decimal[0,1], rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`. Optional fields must be explicitly nullable in schema; undeclared fields are rejected by contract tests.

### Coverage and rating disposition
- Output schema carries an explicit coverage value in `[0,1]`. This ticket’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; this ticket does not issue a rating; `rating_disposition=NO_RATING_NOT_APPLICABLE`; missing mandatory evidence follows the ticket-specific blocked/unknown rule, never an implicit score.

### Explicit non-goals
- Do not publish final quality/stars/faces/Bomb, do not edit another ticket owned path, and do not change Frozen Spec/Decision Map/Delivery Plan.

### Ticket-specific failure disposition
- Any seam mismatch, generation mismatch or report hash mismatch blocks release; return deterministic error_code.

### Authority and PIT boundary
- Transform-only ticket: consumes PIT-admitted upstream artifacts; no direct external source and no timestamp rewriting.

### Mandatory verification commands
- Focused — **MANDATORY**: `python -m pytest -q tests/golden_path`.
- Cumulative — **MANDATORY**: `python -m pytest -q tests/contracts tests/golden_path` plus every previously integrated black-box seam test selected by PM manifest.
- Real-source probe — **NONE / NOT APPLICABLE**: transform/governance-only ticket consumes frozen PIT-admitted fixtures; direct network access is forbidden.
- Diff hygiene — **MANDATORY**: `git diff --check "$PARENT_SHA" "$CANDIDATE_SHA"`.
- Non-empty candidate — **MANDATORY**: `test -n "$(git diff --name-only "$PARENT_SHA" "$CANDIDATE_SHA")"`.
- Generated/secret admission — **MANDATORY**: `python tools/admission_scan.py --candidate "$CANDIDATE_SHA" --forbid-secrets --forbid-unowned --manifest "$ASSIGNMENT_MANIFEST"`.

### Atomic assignment, review and PM ingestion protocol
- **Authorization gate:** G0/G1 timeout or silence is not approval. No Worker may start or continue without an explicit current-generation PM dispatch and all required owner gates.
- PM dispatch manifest is atomic and immutable: `assignment_id`, `active_binding_generation`, `eligibility_generation`, `ticket_id=T01`, `ticket_generation=R9`, `parent_sha`, `branch`, `worktree`, `owned_paths`, `forbidden_paths`, `spec_sha=36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`, `decision_map_sha=cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`, `delivery_plan_sha=bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`, `ticket_set_digest`, `lease_expires_at`, `review_deadline_at`. Missing field => no dispatch.
- Worker emits `REVIEW_READY | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | parent_sha=<sha> | candidate_sha=<sha> | diff_manifest_sha=<sha> | tests_manifest_sha=<sha> | probes_manifest_sha=<sha> | worktree=<absolute>` only after every mandatory command exits 0.
- Each read-only reviewer first emits `REVIEW_ACK | assignment_id=<id> | axis=SPEC|QUALITY | reviewer_role=<role> | reviewer_session=<stable-id> | sandbox=<absolute-readonly-path> | candidate_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`; ACK mismatch invalidates verdict.
- Authoritative verdict source message: `SPEC_REVIEW|QUALITY_REVIEW | PASS|NOT_APPROVED | assignment_id=<id> | active_binding_generation=<n> | eligibility_generation=<n> | candidate_sha=<sha> | source_session=<id> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`; both axes must bind identical bytes.
- Revision limit is 3 attempts. Same Worker/session may revise only owned paths. If blocker_count fails to decrease between attempts, lease expires, ownership overlaps, or contract question changes product semantics, emit `OWNER_DECISION_NEEDED` and stop.
- PM performs serialized admission only: validate lease/ownership, non-empty diff, diff hygiene, generated/secret scan, tests/probes, atomic dual-axis bundle; enqueue protected-main merge queue; after merge rerun cumulative and same-generation seam on merged SHA before eligibility.
- Durable ingestion uses monotonically increasing `ingestion_seq`, persisted `reconciliation_watermark`, and `eligibility_generation`. Crash recovery replays source messages after watermark and recomputes eligibility from exact current bytes.
- Any late NOT_APPROVED first revokes eligibility fail-closed; PM evaluates finding reachability against current bytes. Only an unreachable finding superseded by a newer exact-byte dual PASS may remain history without demoting current state.

## Acceptance criteria

- [ ] T01交付 `tools/admission_scan.py`、`tools/validate_json.py`、`CalibrationFreezePackage.v1.json`、`CalibrationFreezeManifest.v1.json`，並以 `tests/contracts/` 驗證valid/invalid package、manifest及conditional APPROVE fixtures。

- [ ] fixture完成identity→snapshot→report.
- [ ] snapshot/report generation/decision_time/manifest/model一致.
- [ ] 重跑semantic deterministic.
- [ ] CI驗證unit/contract/primary-seam/secret scan.
- [ ] 不存在mutation/live-trading capability.
- [ ] Owned-path diff audit reports no write outside exclusive paths.
- [ ] Output includes source/formula/model/schema versions and explicit failure reasons.
