# E0 Control Plane

Status: E0 bootstrap only; product implementation is not authorized.

## Repository authority

- Public GitHub Organization repository: `PSC-Wayne/ComapanyQualityReview`.
- Active ruleset: `protected-main-merge-queue` (`19625505`), with no bypass actors.
- Protected `main` is authoritative.
- Required planning-integrity check: `E0 governance / verify`.
- Merge queue serializes integration.
- Integration GitHub App: `psc-wayne-cqr-integrator` (`4375855`), installation `148525506`, selected repository only.
- Machine-readable verification evidence: `docs/governance/e0-evidence.json`.
- A dedicated least-privilege Integration GitHub App may enqueue eligible PRs; it cannot bypass protection or direct-merge.

## Identity and permissions

- Workers: isolated branch/worktree, owned paths only; no main credentials.
- Reviewers: read-only exact-SHA exports; no writes or fixes.
- PM/Supervisor: registry and admission decisions; no direct main update.
- Integration App: repository contents/PR metadata only as required to enqueue eligible PRs; no administration/secrets/bypass permission.

## Authorization

E0 permits repository/control-plane setup only. T01–T28 remain blocked until Wayne issues a later explicit GO. Silence or timeout is not approval.

## Immutable planning bindings

- Frozen Spec SHA-256: `36edd6b2a1b04c6282a5c30c4b4c5d89ac2535c344d6496a0d8bd54fd2009161`
- Decision Map SHA-256: `cc34f1b5f93a28b967e58be2b45f25aca6f700eba72f443dcbb3f8b1ba318b54`
- Delivery Plan SHA-256: `bd2b949ab575b01c2553269dd99d67aa385c241c924f35b43cdc1f568bd7c3e0`
- R9 work-order set SHA-256: `f3f2167aff87623caf74c44135b852384035e8cf276ddd46221506c9995859fb`
