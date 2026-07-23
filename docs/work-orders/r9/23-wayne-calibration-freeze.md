# T23 — Wayne G1 Calibration Freeze Owner Gate

**Status:** owner-gate-draft — not authorized; Wayne decision required after T22

**Objective:** PM packages exact T22 evidence; independent reviewers ACK evidence and semantics; Wayne alone explicitly approve/hold/revise. No Coding Worker.

**Blocked by:** T19, T22

## Authority bindings
- Frozen Spec: `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`
- Decision Map: `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`
- Delivery Plan: `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`
- R9 ticket set generation: `PM_REQUIRED_AT_DISPATCH`

## Roles
- PM assembles exact evidence only; PM cannot approve.

## Owned artifact paths
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/governance/calibration-freeze/packages/
- /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/governance/calibration-freeze/decisions/

## Roles and authority
- Independent evidence Reviewer and semantics Reviewer are read-only; each has stable session, sandbox, lease and deadline.
- Wayne is sole decision authority; silence/timeout is `hold`, never approval.
- No branch, worktree, Worker candidate SHA, commit, merge queue or Git integration applies to this owner gate.

## Shared read-only paths and inputs
- T22 `CalibrationValidationReport.v1` at `AnalysisSnapshot.sections.calibration_validation`; exact report SHA and policy version.
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/specs/company-quality-product-spec.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-decision-map.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/planning/company-quality-multi-agent-delivery-plan.md`
- `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/governance/calibration-freeze/schemas/` (T01-owned, read-only).

## Forbidden writes and actions
- No Coding Worker dispatch; no source/tests/.github/Git/GitHub edits; no score/threshold mutation by PM or Reviewer; no production/config/secret access.

## Bounded decision package and output
- Evidence package fields: `decision_package_id:string[1..128]`, `active_binding_generation:uint64`, `eligibility_generation:uint64`, `validation_report_sha256:sha256`, `candidate_policy_sha256:sha256`, `ticket_set_digest:sha256`, `frozen_spec_sha256:sha256`, `decision_map_sha256:sha256`, `delivery_plan_sha256:sha256`, `candidate_ranges:record{quality_bands:list<decimal[0,100]>[1..9 ascending],upside_stars:list<decimal[-1,10]>[exactly 4 ascending],downside_faces:list<decimal[0,100]>[exactly 4 ascending],bomb_materiality:decimal[0,1]}`, `pillar_weights:record{audit_reliability:literal[0.10],earnings_capital_efficiency:literal[0.25],cash_balance_allocation:literal[0.25],business_moat:literal[0.25],governance:literal[0.05],people_adaptability:literal[0.10],sum:literal[1]}`, `downside_component_weights:record{maximum_drawdown_vulnerability:decimal[0.25,0.40],permanent_capital_loss_vulnerability:decimal[0.25,0.40],material_adverse_event_vulnerability:decimal[0.25,0.40],sum:literal[1]}`, `anti_double_count_policy_version:semver`, `evidence_family_policy_scope:literal[quality_and_downside]`, `evidence_family_policy_locator:literal[AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership]`, `evidence_family_policy_canonicalization:literal[RFC8785_JCS]`, `evidence_family_policy_sha256:sha256`, `metrics:record{auc:null|decimal[0,1],brier:null|decimal[0,1],calibration_error:null|decimal[0,1]}`, `calibration_curves:list<record{bucket:string[1..32],predicted:decimal[0,1],observed:decimal[0,1],count:uint32}>[1..100]`, `leakage_checks:record{pit_join_pass:boolean,purge_pass:boolean,embargo_pass:boolean,survivorship_pass:boolean}`, `evidence_package_coverage:decimal[0,1]`, `rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`, `review_deadline_at:rfc3339_timezone_aware`.
- Output `CalibrationFreezeManifest.v1` at `/mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/governance/calibration-freeze/decisions/<decision_id>.json`; required fields `decision_id:string[1..128], evidence_package_sha256:sha256, validation_report_sha256:sha256, approved_policy_version:null|semver, approved_thresholds:null|record{quality_bands:list<decimal[0,100]>[1..9 ascending],upside_stars:list<decimal[-1,10]>[exactly 4 ascending],downside_faces:list<decimal[0,100]>[exactly 4 ascending],bomb_materiality:decimal[0,1]}, decision:oneof[approve,hold,revise], decided_by:literal[Wayne], decided_at:rfc3339_timezone_aware, independent_review_ack:string[1..256], pillar_weights:record{audit_reliability:literal[0.10],earnings_capital_efficiency:literal[0.25],cash_balance_allocation:literal[0.25],business_moat:literal[0.25],governance:literal[0.05],people_adaptability:literal[0.10],sum:literal[1]}, downside_component_weights:record{maximum_drawdown_vulnerability:decimal[0.25,0.40],permanent_capital_loss_vulnerability:decimal[0.25,0.40],material_adverse_event_vulnerability:decimal[0.25,0.40],sum:literal[1]}, anti_double_count_policy_version:semver, evidence_family_policy_scope:literal[quality_and_downside], evidence_family_policy_locator:literal[AnalysisSnapshot.sections.candidate_policy.anti_double_count_policy.evidence_family_ownership], evidence_family_policy_canonicalization:literal[RFC8785_JCS], evidence_family_policy_sha256:sha256, expiry:null|rfc3339_timezone_aware, evidence_package_coverage:decimal[0,1], rating_disposition:literal[NO_RATING_NOT_APPLICABLE]`. Missing field/hash mismatch => `hold`.

## Coverage and rating disposition
- Evidence package and manifest carry `evidence_package_coverage` in `[0,1]`; this gate’s `no_rating applicability` is explicitly `NO_RATING_NOT_APPLICABLE`; it emits no rating and fixes `rating_disposition=NO_RATING_NOT_APPLICABLE`.

- The finalized manifest payload MUST NOT contain its own complete-file SHA. PM writes detached sidecar `<decision_id>.json.sha256` only after closing the JSON bytes; sidecar format is `<sha256><two spaces><decision_id>.json`. T24–T26 receive `decision_file_sha256` from this detached sidecar in their dispatch bundle.
- Conditional invariant: `decision=approve` requires non-null `approved_policy_version` and `approved_thresholds`, both exact frozen weight records, `anti_double_count_policy_version`, `evidence_family_policy_scope=quality_and_downside`, `evidence_family_policy_locator`, `evidence_family_policy_canonicalization=RFC8785_JCS`, `evidence_family_policy_sha256`, two exact-byte reviewer PASS records and Wayne explicit APPROVE; otherwise state is `hold`.

- Policy hash invariant: PM resolves the semantic value at the T19 locator, serializes that value alone as RFC8785/JCS UTF-8, and requires `SHA-256(JCS(value))` to equal both T19 and package/manifest policy SHA. Raw JSON token spans, parent bytes or any other serializer are invalid and force `hold`.

## Explicit non-goals
- Do not implement code, choose values for Wayne, mutate T22 evidence, publish ratings, use silence as approval, or integrate Git bytes.

## Failure disposition
- Missing review ACK/hash or Wayne silence/timeout means hold; no policy version becomes eligible.

## Mandatory machine validation and owner protocol
- PM package validation — **MANDATORY**: `python tools/validate_json.py --schema docs/governance/calibration-freeze/schemas/CalibrationFreezePackage.v1.json --input "$DECISION_PACKAGE"`.
- Package hash binding — **MANDATORY**: `sha256sum --check "$DECISION_PACKAGE_SHA_MANIFEST"`.
- Decision manifest validation — **MANDATORY**: `python tools/validate_json.py --schema docs/governance/calibration-freeze/schemas/CalibrationFreezeManifest.v1.json --input "$DECISION_MANIFEST"`.
- Detached decision-file checksum — **MANDATORY**: `sha256sum "$DECISION_MANIFEST" > "$DECISION_MANIFEST.sha256" && sha256sum --check "$DECISION_MANIFEST.sha256"`; the SHA stays outside JSON payload.
- Reviewer ACK: `OWNER_REVIEW_ACK | decision_package_id=<id> | axis=EVIDENCE|SEMANTICS | reviewer_session=<id> | sandbox=<readonly> | package_sha=<sha> | lease_expires_at=<rfc3339> | deadline_at=<rfc3339>`.
- Reviewer verdict: `OWNER_REVIEW | PASS|NOT_APPROVED | decision_package_id=<id> | axis=<axis> | package_sha=<sha> | source_message_id=<id> | source_message_sha=<sha> | blocker_count=<n>`. Both PASS bind identical package bytes.
- Wayne action: `G1_DECISION | APPROVE|HOLD|REVISE | decision_package_id=<id> | package_sha=<sha> | approved_policy_version=<id|null> | decided_at=<rfc3339> | decision_message_id=<id> | decision_message_sha=<sha>`. Only APPROVE creates manifest eligibility.
- PM durable ledger stores monotonic `ingestion_seq`, `reconciliation_watermark`, `eligibility_generation`; crash replay recomputes status. Late NOT_APPROVED revokes eligibility fail-closed and requires reachability review.
- Revision limit 3 packages; non-decreasing blockers or changed product semantics => `OWNER_DECISION_NEEDED`, no automatic retry.

## Acceptance criteria
- [ ] Package, manifest, conditional-APPROVE and detached-hash commands exit 0 on complete fixture and fail on missing/mismatched fields.
- [ ] Two independent exact-byte review ACK/PASS records exist.
- [ ] Wayne explicit APPROVE is present; silence/timeout fixtures remain HOLD.
- [ ] Output manifest binds exact T22 and policy bytes; T24–T26 remain blocked otherwise.
- [ ] No Worker/worktree/Git/GitHub/integration action occurs.
