# Company Quality Research — Multi-Agent Delivery Operating Plan

> Status: PLANNING ONLY — no product implementation, repository initialization or agent execution is authorized.
> Owner: Wayne
> Date: 2026-07-23
> Product spec: `company-quality-product-spec-draft.md`
> Decision map: `company-quality-decision-map.md`

## 1. Purpose

Design a controlled delivery line for a large project in which multiple agents work concurrently without sharing writable state, every frozen candidate receives immediate independent review, and only one PM integrates accepted candidates into main.

The operating principle is:

> Parallel discovery and isolated implementation; exact-SHA review; serialized integration; cumulative verification.

Agent completion is not project completion. A Worker candidate, Reviewer PASS, integration and milestone completion are four separate facts.

## 2. Can `to-spec` be used now?

Yes, with a boundary:

- `wayfinder` resolves product decisions and fog.
- `to-spec` synthesizes the approved product behavior and acceptance contract.
- `to-tickets` splits the approved spec into dependency-aware vertical slices.
- Multi-agent execution begins only after Git, tracker, standards, tests and worktree prerequisites pass.

The current product spec is a draft because F1–F10 remain unresolved. It is useful for finding work boundaries, but it must not carry `ready-for-agent` status yet.

## 3. Current pre-flight facts

As of 2026-07-23:

- The project directory is not a Git repository.
- There is no configured issue tracker.
- There is no `AGENTS.md`, coding standard, product architecture or test harness.
- The directory contains research, Decision Map and Roadmap artifacts only.

Therefore all execution lanes are blocked. Planning may continue locally; no worktree, exact SHA or branch review claim is valid until repository setup is separately approved and completed.

## 4. End-to-end planning and delivery lifecycle

### Phase P0 — Wayfinding and owner decisions

Goal: resolve F1–F10 and any newly surfaced semantic decisions.

Allowed work:

- official research;
- domain modeling;
- one-question-at-a-time owner decisions;
- prototypes used only to clarify behavior;
- updates to the Decision Map.

Forbidden work:

- product code;
- implementation tickets marked ready;
- choosing model weights from seed cases;
- setting up production services.

Exit gate:

- every blocking semantic question is decided, deferred with an explicit safe contract, or ruled out of scope.

### Phase P1 — Spec freeze

Goal: convert the Decision Map into an approved product spec.

Process:

1. PM updates the draft spec.
2. Independent Spec Reviewer checks completeness, contradictions and scope creep.
3. Domain Reviewer checks financial/accounting/PIT correctness using the project finance skills.
4. PM revises; reviewers re-check changed bytes.
5. Wayne approves the test seam and spec.

Exit gate:

- one versioned spec is approved and marked suitable for ticketing, not yet implementation.

### Phase P2 — Delivery-system decisions

Goal: approve the engineering control plane before any product code.

Decisions required:

- initialize a new Git repo or connect an existing remote;
- issue tracker choice: local Markdown, GitHub or Linear;
- main branch and branch-protection policy;
- language/runtime and package layout;
- test, lint, type-check and build commands;
- secret handling and network policy;
- maximum Worker and Reviewer capacity;
- owner notification route;
- control-plane registry/Dashboard location.

Owner-selected integration authority:

- GitHub protected `main` plus merge queue is the sole authoritative main-line mechanism.
- A dedicated least-privilege integration bot is the only actor allowed to submit eligible PRs to the merge queue; it cannot bypass branch protection or direct-merge.
- Workers, Reviewers, PM sessions and Supervisor have no credential/path capable of direct `main` updates.
- Repository creation, GitHub authentication, branch protection and bot setup remain unexecuted until separately authorized.

Exit gate:

- the setup checklist is approved. Setup itself is a later, explicit task.

### Phase P3 — `to-tickets` decomposition

Goal: turn the approved spec into one ticket per tracer-bullet work order.

Ticket rules:

- one fresh context can finish one ticket;
- each ticket provides a narrow, verifiable end-to-end behavior;
- each ticket declares blockers explicitly;
- shared contract changes are serialized;
- tickets avoid overlapping writable paths;
- no ticket is `ready-for-agent` until its input contracts and owner decisions are frozen.

PM presents the proposed list to Wayne before publishing. Wayne may merge, split or reorder tickets.

### Phase E0 — Repository/control-plane bootstrap

Begins only after explicit authorization.

Expected outputs:

- Git main with initial immutable planning baseline;
- issue tracker and labels;
- `AGENTS.md` and coding standards;
- baseline test/lint/type/build commands;
- worktree naming and registry convention;
- Worker/Reviewer charters;
- exact handoff schemas;
- no product behavior yet.

### Phase E1 onward — Reviewed implementation waves

Each wave starts only from current clean main, runs isolated Workers, performs exact-candidate reviews and integrates accepted candidates one at a time.

## 5. Recommended topology

### PM / Integrator — one persistent authority

Responsibilities:

- owns spec, dependencies, work orders and file ownership;
- creates/assigns lanes only after pre-flight;
- resolves overlap and shared-contract ordering;
- performs candidate admission and atomically records the two-axis review binding;
- consumes authoritative reviewer verdicts after Supervisor delivery/ACK handling;
- integrates one accepted candidate at a time;
- runs merged-byte cumulative gates;
- reports only decisions, blockers and verified milestones.

Forbidden:

- acting as a concurrent product Worker in shared files;
- treating Worker self-report as acceptance;
- merging unreviewed or stale bytes;
- turning into a manual polling loop.

### Worker Pod — isolated writer

Each pod has one Worker with:

- stable session ID and tmux name;
- one writable Git worktree and branch;
- exact parent SHA;
- one work order;
- owned paths and forbidden/shared paths;
- required tests and real semantic probes;
- pre-bound Spec and Quality reviewers.

Worker rules:

- one writer per worktree;
- no edits outside owned paths;
- no merge/rebase/reset or main writes;
- TDD where behavior is testable;
- commit a clean candidate;
- stop after `REVIEW_READY` and do not start another ticket implicitly.

### Spec/Domain Reviewer — read-only

Checks the exact parent-to-candidate diff against:

- approved spec and ticket acceptance criteria;
- financial/accounting/PIT semantics;
- source-authority and no-look-ahead rules;
- stated scope and non-goals;
- missing behavior and scope creep.

It never edits, commits, merges or fixes its own findings.

### Quality/Standards Reviewer — read-only

Checks the same exact candidate independently for:

- repository standards and architecture;
- correctness, security and failure behavior;
- tests and edge cases;
- maintainability and code smells;
- performance shape for full-history/full-universe paths;
- forbidden writes, secrets and unrelated changes.

It never edits, commits, merges or directs the Worker.

### Supervisor — bounded control-plane operator

Recommended once more than one pod is active.

Responsibilities:

- monitors session/process/worktree facts;
- is the only routine review-routing authority: atomically dispatches both pre-authorized review assignments, obtains ACKs, enforces deadlines and assigns approved spare lanes when needed;
- detects hung/stale/wrong-worktree lanes;
- resumes a proven stopped lane only within standing policy;
- deduplicates delayed async events;
- reconciles assignment IDs, revision attempts, source messages and late verdicts against the current binding;
- escalates only exhausted reviewer capacity, unacknowledged deadlines or unresolved control-plane incidents to PM.

Forbidden:

- product edits;
- review verdicts;
- merges;
- owner business decisions;
- retrying denied destructive commands.

### Watchdog — deterministic and silent

Polls cheaply, emits only changed anomaly signatures and sends routine findings to Supervisor, not Wayne.

## 6. Capacity model

To satisfy “Worker finishes → Reviewer starts immediately,” reviewers must be reserved before Worker dispatch.

Recommended starting capacity:

- 1 PM;
- 2 concurrent Worker Pods;
- 2 Spec/Domain Reviewer lanes;
- 2 Quality/Standards Reviewer lanes;
- 1 bounded Supervisor;
- 1 deterministic watchdog.

This permits two candidates to enter both review axes immediately without queueing. Before either Worker starts, the registry must reserve two axis-specific reviewer lanes and one approved spare route per axis or explicitly prove capacity for replacement. `REVIEW_READY` admission creates both assignments in one atomic binding; Supervisor must obtain both ACKs before either review is considered active. A missed ACK/deadline triggers bounded spare-lane reassignment rather than PM polling.

Scale rule:

- after one full wave proves stable, expand to 3 Worker Pods only if two additional reviewer lanes are available;
- maximum ready candidates must never exceed bound review capacity;
- if a reviewer is unavailable, PM does not dispatch the paired Worker or marks the candidate frozen and scales review capacity before the next wave;
- integration remains one-at-a-time regardless of Worker count;
- if two-axis ACK capacity cannot be proven, the paired Worker is not dispatched.

A smaller machine may start with one pod; parallelism is not worth stale reviews or shared-state races.

## 7. Work-order contract

Every future work order must state all of the following:

1. Work-order name and stable ID.
2. User-visible goal.
3. Explicit non-goals.
4. Approved spec version and decision references.
5. Absolute worktree path, branch and expected parent SHA.
6. Absolute owned paths.
7. Forbidden/shared paths.
8. Input/output/domain contracts.
9. Source-authority and PIT constraints.
10. Acceptance behavior.
11. Failure/no-rating behavior.
12. Required focused tests.
13. Required full or cumulative tests.
14. Required semantic/real-source probes.
15. Mandatory versus optional probes.
16. Security, network and side-effect constraints.
17. Expected conflict zones and blockers.
18. Pre-bound Spec Reviewer and Quality Reviewer.
19. Exact `REVIEW_READY` schema.
20. Exact reviewer verdict schemas.
21. Revision-loop maximum and escalation condition.

Fresh agents receive the entire bounded work order in their prompt; they are never told to infer requirements from another agent's context.

## 8. Candidate and review protocol

### Reviewer isolation

- Reviewers never execute inside the Worker worktree.
- Each axis receives its own dedicated read-only reviewer worktree at the exact candidate SHA, or an exact-SHA sandbox exported from Git objects.
- Reviewer caches, bytecode, compiler outputs and probes are redirected to a unique path outside every repository/worktree, normally under `/tmp/<assignment_id>/`.
- Before and after review, each Reviewer attests repository root, reviewer role, branch/worktree identity, full HEAD SHA, expected parent, parent-to-candidate diff hash and cleanliness.
- Any repository-byte drift, wrong root/branch/HEAD, or write inside the sandbox invalidates the verdict and triggers an Abort gate for that assignment.

### Persistent binding identity

Every review lifecycle is keyed by:

```text
(work_order, candidate_sha, review_axis, revision_attempt)
```

Each axis also receives a unique `assignment_id`, expected Reviewer role/session, `active_binding_generation`, dispatch message ID, ACK deadline/message ID, review lease/deadline/heartbeat, replacement reason and authoritative verdict message ID. The registry stores active and superseded bindings append-only.

### Worker handoff

```text
REVIEW_READY | <WO> | attempt=<n> | parent=<full_sha> | commit=<full_sha> | tests=<exact commands/results> | semantic_probes=<results> | worktree_clean=true
```

### PM mechanical admission gate

Before creating a review binding, PM checks only:

- full SHA resolves;
- parent is correct;
- worktree is clean;
- diff is non-empty;
- changed paths are owned;
- `git diff --check` passes;
- no forbidden/generated/secret artifacts entered the candidate.

This is not code review. On PASS, PM atomically records both axis bindings for the same candidate/attempt. Supervisor is then the only component allowed to dispatch routine review assignments.

### Atomic dual-axis dispatch and ACK

1. Supervisor reads one admitted review bundle containing both axis bindings.
2. It dispatches Spec/Domain and Quality/Standards assignments as one logical operation; partial delivery remains `REVIEW_DISPATCH_INCOMPLETE`, never `REVIEWING`.
3. Each Reviewer must return an ACK containing assignment ID, role, attempt, candidate SHA, active-binding generation, isolated review path and accepted review lease/deadline before the configured ACK deadline.
4. Supervisor verifies both ACKs against the registry and only then marks both axes active.
5. Missing/invalid ACK, expired review lease, missed Reviewer heartbeat, verdict deadline or proven post-ACK hang all use the same atomic compare-and-swap replacement: the old `assignment_id` and bound Reviewer session become `SUPERSEDED` with a persisted replacement reason, a new `assignment_id`/role/session/lease is bound, and `active_binding_generation` advances in the same transaction. Only after that CAS succeeds may Supervisor dispatch the spare lane. Every later ACK/verdict from the superseded assignment is historical only. If replacement capacity is exhausted, Supervisor escalates to PM; it does not silently queue or poll forever.

Assignments:

```text
SPEC_REVIEW_ASSIGNMENT | assignment=<id> | <WO> | attempt=<n> | parent=<full_sha> | commit=<full_sha> | sandbox=<absolute_path> | spec=<version>
QUALITY_REVIEW_ASSIGNMENT | assignment=<id> | <WO> | attempt=<n> | parent=<full_sha> | commit=<full_sha> | sandbox=<absolute_path> | standards=<version>
```

ACK:

```text
REVIEW_ACK | assignment=<id> | axis=<spec|quality> | role=<reviewer_role> | binding_generation=<n> | attempt=<n> | commit=<full_sha> | sandbox=<absolute_path> | review_lease_until=<timestamp>
```

### Verdicts

```text
SPEC_REVIEW_RESULT | assignment=<id> | <WO> | attempt=<n> | commit=<full_sha> | PASS
SPEC_REVIEW_RESULT | assignment=<id> | <WO> | attempt=<n> | commit=<full_sha> | NOT_APPROVED
```

```text
QUALITY_REVIEW_RESULT | assignment=<id> | <WO> | attempt=<n> | commit=<full_sha> | PASS
QUALITY_REVIEW_RESULT | assignment=<id> | <WO> | attempt=<n> | commit=<full_sha> | NOT_APPROVED
```

Only Critical/Important findings block. Every blocker includes evidence, affected behavior and acceptance direction.

### Authoritative verdict and stale-event reconciliation

- A verdict is authoritative only when Reviewer role/session, assignment ID, review axis, revision attempt, candidate SHA, source message and current active binding all match.
- A new candidate SHA atomically supersedes/cancels every active old-SHA binding; new assignments use a new attempt and IDs.
- Late PASS for an old/superseded binding is historical only and can never advance current state.
- Durable ingestion of any late `NOT_APPROVED` immediately performs a fail-closed transaction before semantic classification: set `RECONCILIATION_PENDING`, increment `eligibility_generation`, revoke current `REVIEW_COMPLETE`, freeze/remove the queue item and invalidate any active integration intent/claim. The durable ingestion frontier advances in that same transaction.
- The authoritative reconciler then records whether each Critical/Important finding is still reachable in current bytes, already remediated or not applicable, with evidence and source message ID. Reconciliation is a mandatory integration-eligibility gate.
- If any finding remains reachable, state becomes `BLOCKED_BY_LATE_FINDING`; a new fixed SHA and fresh dual-axis review are required before re-enqueue. If all findings are proven remediated/not-applicable, a new eligibility generation may be issued only after the reconciliation watermark equals the durable ingestion frontier and both current PASS bindings are revalidated.
- Every integration apply/gate/record step revalidates `eligibility_generation`; a stale claimant cannot advance after late-blocker invalidation. If main already advanced, release readiness is revoked and an urgent correction/review work order is opened; the late blocker is never treated as informational only.
- Dashboard and queue state derive from the active binding and eligibility generation, not the most recently arrived message.

### Acceptance rule

- Both axes must PASS the same candidate SHA, revision attempt and active binding; `RECONCILIATION_PENDING` must be false; and the reconciliation watermark must equal the latest durable ingestion frontier with no reachable blocker.
- A verdict for an older SHA/attempt is historical only.
- Any code change creates a new SHA and restarts both review axes.
- Worker tests, PM admission and one reviewer PASS cannot substitute for the other PASS.

## 9. Revision loop

1. PM binds findings to the authoritative reviewed SHA/attempt and reconciles any applicable late NOT_APPROVED findings.
2. PM sends one evidence-rich correction to the same Worker at a safe completed-turn boundary.
3. Worker adds regression tests, fixes within original scope and commits a new SHA.
4. Registry atomically supersedes old bindings and increments `revision_attempt`.
5. Supervisor dispatches two new isolated assignments; both reviewers re-review the new SHA.
6. Maximum three revision cycles.
7. If blocker count does not decrease or three cycles fail, use the Escalation gate; do not loop forever.

Reviewers never fix candidate code and then approve their own changes.

## 10. Delivery state machine

1. `PLANNED`
2. `BLOCKED_BY_DECISION`
3. `READY_FOR_AGENT`
4. `ASSIGNED`
5. `IMPLEMENTING`
6. `REVIEW_READY`
7. `REVIEW_BINDING_CREATED`
8. `REVIEW_DISPATCH_INCOMPLETE`
9. `SPEC_REVIEW_ACKED` / `QUALITY_REVIEW_ACKED`
10. `SPEC_REVIEWING` / `QUALITY_REVIEWING`
11. `NOT_APPROVED`
12. `REVIEW_COMPLETE` — both authoritative exact-SHA/attempt reviews PASS
13. `INTEGRATION_QUEUED`
14. `INTEGRATION_CLAIMED`
15. `INTEGRATED`
16. `INTEGRATION_VERIFIED`
17. `MILESTONE_COMPLETE`
18. `SUPERSEDED` or `ABORTED`

Dashboard must show observed activity separately from PM-verified lifecycle. A late tool/user envelope cannot regress an `INTEGRATED` candidate.

## 11. Gate taxonomy

### Pre-flight gates

Block entry before partial work:

- approved spec and ticket exist;
- Git main is clean;
- parent SHA/branch/worktree/cwd match;
- Worker owns all writable paths;
- both reviewers are reserved;
- mandatory source credentials and safe network access are available;
- baseline tests are known.

Failure: fix prerequisite and retry; do not start coding.

### Revision gates

- Spec/Domain review;
- Quality/Standards review;
- merged-byte integration gate.

Failure: return evidence to producer, new SHA, re-review; maximum three cycles.

### Escalation gates

Escalate to Wayne only when:

- two valid business interpretations change architecture or acceptance;
- authoritative sources conflict and cannot be resolved;
- review loops fail to converge;
- destructive/security/credential approval is required;
- a scope change invalidates approved tickets;
- resource limits require reducing project scope or parallelism.

Routine test failures, review findings and recoverable control-plane stalls do not go to Wayne.

### Abort gates

Stop and preserve evidence when:

- a lane writes outside its worktree/owned paths;
- source/PIT integrity is violated;
- a destructive production or secret action is attempted;
- repository state cannot be proven safe;
- a mandatory gate is impossible and no approved recovery exists;
- context/process corruption makes candidate identity uncertain.

## 12. GitHub-fenced durable serialized integration

### Authoritative main and enforcement

- GitHub protected `main` is the sole authoritative main ref. Local refs/worktrees are caches and may never declare integration complete.
- Branch rules require merge queue, required CI/semantic checks, current approvals and no direct force-push/deletion.
- Workers, Reviewers, PM and Supervisor cannot update protected `main` directly and do not possess a merge-capable credential.
- A dedicated least-privilege integration bot is the sole submitter to merge queue. It cannot bypass branch protection, merge directly, dismiss reviews or weaken required checks.
- The bot accepts requests only from the current fenced PM/controller generation after independently validating queue eligibility, candidate/PR head OID, reconciliation frontier, required verdict provenance and request signature.

### Queue and eligibility contract

- The local control-plane integration queue is durable, dependency-aware and keyed by `(work_order, candidate_sha)`; GitHub PR number/head OID and merge-queue identity are added before submission.
- Enqueue is idempotent and allowed only when both authoritative review axes PASS the same active binding, `RECONCILIATION_PENDING=false`, the reconciliation watermark equals the durable ingestion frontier with no reachable late blocker, and the current `eligibility_generation` is recorded.
- Each queue record retains candidate parent, both assignment/verdict IDs/source messages, durable ingestion frontier, reconciliation watermark, eligibility generation, dependencies, enqueue sequence, `PREPARED_INTENT`, PR/head OID, GitHub queue/merge OIDs, PM claim, authoritative GitHub main OID and disposition.
- Dependency order overrides FIFO; among simultaneously unblocked records, enqueue sequence is FIFO.
- Duplicate handoffs/events cannot create a second PR submission or integration attempt.

### PM generation fencing and claim lifecycle

- Exactly one integration-controller generation is authoritative. Durable controller state contains `pm_owner_id`, monotonically increasing `pm_generation`, fencing token, lease expiry and heartbeat.
- Only the current controller generation may claim one eligible unclaimed item and request a prepared intent. The integration bot rejects stale generation/token/lease or changed eligibility/frontier.
- PM heartbeats renew the bounded lease while orchestration is active. A paused/crashed owner cannot retain control forever.
- Takeover requires lease expiry plus positive evidence that the old controller is no longer authoritative. CAS increments `pm_generation`, issues a new fencing token and transfers/reclaims orchestration state.
- A recovered old PM has no direct-main credential and its stale token is rejected by the integration bot. It may inspect history only.
- If old-owner liveness cannot be disproved safely, takeover is blocked and escalated.

### Prepared intent and merge-queue submission

1. Current PM claims one eligible queue item and proves the GitHub PR head OID matches the reviewed candidate and the authoritative GitHub `main` OID matches the intended base.
2. Registry durably writes `PREPARED_INTENT` before any GitHub mutation. It includes work order, candidate/PR head OID, expected base main OID, eligibility generation, ingestion/reconciliation watermarks, both verdict IDs, PM generation/token hash and unique submission key.
3. Integration bot re-reads current authoritative state and rejects any mismatch, pending reconciliation, stale lease/generation or changed GitHub head/base.
4. Bot submits that exact PR to GitHub merge queue using the unique prepared intent; it never performs a local `git update-ref` or direct merge.
5. GitHub merge queue rebases/synthesizes against current protected main and runs required merged-byte CI/semantic/source gates. A conflict or changed PR head creates new bytes and requires fresh dual-axis review before a new intent.
6. Successful protected-branch update is identified by GitHub PR state plus authoritative merge commit OID, not by bot/PM self-report.

### Crash and cross-system reconciliation

GitHub ref state and registry cannot share one transaction; recovery is therefore explicit and deterministic. On startup/takeover, the current controller and bot reconcile every nonterminal prepared intent:

- **GitHub main unchanged, PR not queued/merged, eligibility still valid:** resubmit the same idempotent intent or mark it safely aborted.
- **PR queued/checks running:** resume observation; do not create another submission.
- **PR merged and GitHub exposes merge commit OID, but registry receipt/dequeue missing:** verify merged PR/head, required checks, base lineage and current eligibility evidence, then record `INTEGRATED`/receipt and dequeue idempotently.
- **GitHub main changed for unrelated work before submission:** invalidate the prepared intent and regenerate/revalidate against current main; do not reuse the old base proof.
- **PR head, verdict binding, eligibility generation or reconciliation frontier changed:** abort/supersede intent; require a new candidate or new review binding as appropriate.
- **State cannot be classified uniquely:** Abort/Escalation gate; never guess, force-push or roll back protected main automatically.

Every bot/registry transition records GitHub event/delivery IDs and OIDs so replay is idempotent. If a reachable late blocker arrives after GitHub merge, release readiness is revoked and an urgent correction work order is mandatory; protected history is not silently rewritten.

Reviewer PASS is not queue admission. Queue admission is not GitHub merge. GitHub merge is not milestone/release completion.

## 13. Proposed execution workstreams

These are planning workstreams, not published tickets. `to-tickets` will split them into smaller tracer bullets after the product spec and architecture are approved.

### Foundation stream — serialized first

Delivers the highest seam without scoring:

- company/security identity and query ambiguity;
- source artifact/manifest;
- decision-time and PIT version resolver;
- canonical fact lineage;
- typed coverage/missing states;
- immutable empty-section AnalysisSnapshot;
- one query-to-snapshot acceptance test.

Reason for serialization: every later stream depends on these shared contracts.

### Parallel Wave A — raw evidence contracts

#### Pod A1 — Financial-report audit evidence vertical slice

End-to-end report inventory, annual audit/interim review type, opinion, going concern, emphasis/other matters, KAM, filing-integrity events, evidence coordinates and report section. It produces typed evidence and coverage only; it does not assign penalties, floors, caps or pillar weights.

Blocked by: foundation contracts. It is explicitly not blocked by F4/F5 scoring policy.

#### Pod A2 — Technical/chip evidence vertical slice

End-to-end two-month adjusted market view, institutional flows, full TDCC holder-band distribution, insider/pledge events, raw metrics, coverage and independent report section. Governed primary holder bands and headline aggregation remain later policy.

Blocked by: foundation contracts. Raw/full-distribution evidence is not blocked by F6/F7.

### Parallel Wave B — fundamental evidence contracts

#### Pod B1 — Financial-quality evidence vertical slice

End-to-end growth, profitability, ROIC, cash conversion, solvency and capital-allocation facts, evidence-family ownership and report section without frozen weights.

Blocked by: foundation contracts.

#### Pod B2 — Business/governance evidence vertical slice

End-to-end business, industry, moat, concentration, governance, management, people and adaptability evidence/report section, initially limited to the approved first-release route.

Blocked by: foundation and F9 first-release industry route.

### Parallel Wave C — provisional diagnostics, not publication ratings

#### Pod C1 — Downside/stress diagnostic slice

Risk register, three raw downside outcome constructs, stress scenarios and reason evidence. Any displayed ordinal output is explicitly provisional/non-publishable.

Blocked by: audit, financial-quality and business/governance evidence plus F2/F3 event semantics. It is not a frozen final crying-face policy.

#### Pod C2 — Valuation/upside diagnostic slice

Valuation routing, reverse DCF, relative valuation, sensitivities, model disagreement and provisional/non-publishable ordinal evidence.

Blocked by: financial quality, business/industry route and F1/F9 semantics.

### Serialized Wave D — provisional scoring/calibration contract

One shared-contract Worker defines configurable candidate pillars, evidence-family aggregation, candidate weights/buckets, caps/floors/veto inputs, confidence measures and validation interfaces. These are champion/challenger candidates, not frozen publication governance.

Blocked by: evidence and diagnostic contracts plus enough of F1/F4/F5/F7/F8/F10 to define candidate policies.

### Wave E — adverse/control temporal calibration before freeze

The PIT forensic validation lab builds the complete five-year adverse/control cohort, adjusted wealth paths, temporal splits, lead-time/false-positive/coverage metrics and compares provisional champion/challenger policies.

Blocked by: foundation, audit/financial/business evidence, F2/F3 cohort semantics and provisional scoring/calibration interfaces.

It must complete before downside weights, star/cry buckets or final scoring governance are frozen.

### Serialized Wave F — frozen scoring and publication governance

Wayne reviews calibration evidence and freezes approved quality pillars, weights, buckets, caps, penalties, critical-risk floors/veto/no-rating rules, technical/chip relationship, confidence and override policy.

Blocked by: Wave E validation and unresolved F1/F4/F5/F7/F8/F10 decisions.

Only one Worker may modify the frozen shared scoring/publication contract at a time.

### Parallel Wave G — complete report and independent validation

#### Pod G1 — Complete query/report

One query renders all sections and final rating card from one immutable generation using only frozen publication governance.

#### Pod G2 — End-to-end independent validation

Black-box PIT, lineage, monotonicity, failure-mode, full-history/performance and source smoke gates against the frozen integrated candidate.

Both are blocked by frozen Wave F governance and stable component contracts.

### Final serialized release-readiness wave

- merged query-to-report acceptance;
- full-history/performance and source smoke gates;
- security/failure-mode review;
- independent release-correctness review;
- documentation and operator readiness;
- no production activation without a separate owner decision.

## 14. Shared-file and overlap policy

- Shared schema, registry, migration, scoring and public report contracts are serialized.
- Parallel Workers may consume shared contracts but may not modify them.
- If two tickets require the same shared contract change, PM promotes it to one prerequisite ticket.
- If a wide refactor is unavoidable, use expand → isolated migration batches → contract; keep old and new forms compatible until all batches pass.
- Workers cannot claim failures from concurrent branches as “unrelated”; PM verifies merged bytes at integration.

## 15. Progress accounting

Progress is evidence-based:

- 10% approved specification and acceptance contract;
- 50% exact-SHA candidates with both review axes PASS;
- 20% serialized integration and cumulative regression;
- 15% end-to-end/runtime/source validation;
- 5% documentation and release readiness.

A branch, Worker final or unit-test count is not project completion.

For each work order report separately:

- implementation candidate exists;
- Spec PASS;
- Quality PASS;
- integrated;
- integration verified.

## 16. Owner notification policy

Notify Wayne only for:

- a required product/semantic decision;
- architecture or scope change;
- mandatory gate irreducibly blocked;
- destructive/security/credential approval;
- major cross-workstream integration conflict;
- agreed milestone or completion threshold.

Do not notify for:

- every Worker update;
- routine review assignment;
- transient watcher recovery;
- normal NOT_APPROVED correction loops;
- stale async events already superseded by current bytes.

## 17. Planning outputs required before implementation

1. Wayne resolves or explicitly defers F1–F10.
2. Primary query-to-report test seam is approved.
3. Product spec is reviewed and approved.
4. Git/repository/tracker setup approach is approved.
5. Architecture/runtime conventions are decided.
6. `to-tickets` draft is presented to Wayne.
7. Wayne approves granularity and blockers.
8. Only then are tickets published as `ready-for-agent` and Worker/Reviewer lanes created.

## 18. Explicit current stop point

The current effort stops after planning documents are written and reviewed. It does not:

- initialize Git;
- create worktrees or branches;
- configure a tracker;
- spawn coding Workers;
- write product code;
- run migrations;
- activate external services.
