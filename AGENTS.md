# AGENTS.md — Company Quality Review

## Authorization boundary

- Current authorization is E0 control-plane bootstrap only.
- Do not implement T01–T28 without a new explicit Wayne GO and a current immutable PM dispatch manifest.
- Silence, timeout, planning PASS or repository availability is not implementation authorization.

## Delivery rules

- One writable worktree and one ticket per Worker.
- Reviewers are read-only and independently review the exact same candidate SHA.
- Any candidate-byte change restarts both Spec/Domain and Quality/Standards review axes.
- Only the least-privilege Integration GitHub App may enqueue eligible PRs into the merge queue.
- No Worker, Reviewer, PM or Supervisor may directly push or merge `main`.
- Integration is serialized; merged-byte cumulative verification is mandatory.
- Late blocking verdicts fail closed before semantic classification.

## Product safety

- Analysis-only. Never add trading, ordering, broker mutation or production-write capabilities.
- Preserve PIT/source authority, evidence lineage, missing/no-rating semantics and same-generation publication.
- Do not edit Frozen Spec, Decision Map or Delivery Plan from a product ticket.
- Never commit credentials, tokens, private keys or raw secret values.

## Technical baseline

- Python 3.11
- `uv` for Python/tool environment management
- `pytest` for tests
- GitHub Actions required checks
- Protected `main` and merge queue

Each work order's owned/forbidden paths and mandatory commands supersede generic convenience, but never supersede authorization or safety gates.
