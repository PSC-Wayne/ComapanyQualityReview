# CompanyQualityResearch Live Roadmap

Read-only local dashboard for planning, Hermes agent activity, review findings, ticket Waves and separate planning/implementation progress.

## Safety

- Binds only to `127.0.0.1`.
- Reads Hermes `state.db` with SQLite `mode=ro`.
- Reads local ticket drafts and tracked review summaries.
- Exposes only `GET /api/status`; POST/PUT/PATCH/DELETE return 405.
- Does not initialize Git, call GitHub, dispatch agents, approve G0 or start product implementation.
- Old NOT_APPROVED results are kept as history but do not override a newer PM-verified binding.

## Start

From WSL:

```bash
cd /mnt/d/Claude_Code/Hermes/CompanyQualityResearch/docs/roadmap/live
python3 server.py --port 8766
```

Open from Windows:

`http://127.0.0.1:8766`

The page polls `/api/status` every five seconds while visible. If the bridge is offline, it falls back to `data/status.json` and labels itself `STATIC SNAPSHOT`.

## Refresh offline snapshot

```bash
python3 collector.py
```

## Authority and state semantics

- `Observed state` comes from Hermes `async_delegations`.
- `PM verified state`, current binding and supersession come from `config.json`.
- A Worker/Reviewer final is not automatically an integrated completion.
- Ticket planning progress and implementation progress are intentionally separate.
- Update `delegation_registry` when a new exact-hash review supersedes an older result.
