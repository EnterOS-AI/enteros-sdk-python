# workspace-migration — cross-provider compute move

JSON-Schema (draft 2020-12) IDL for the **data-safe cross-cloud workspace
migration** (`workspace-migration.schema.json` + `.contract.json`). A
**sub-contract of the object-store family**: it moves one workspace's **compute**
between providers `{aws, hetzner, gcp}` while the **object store stays fixed**.
Orthogonal to `data-migration` (which re-homes the *store* with compute fixed).

## The flow

The control-plane (async, ~15–20 min) snapshots the source to the object store,
provisions the target (which restores `/workspace` on boot), health-checks +
re-credentials it, **atomically cuts over** the tenant binding, then retires the
source. Driven by `POST /cp/admin/workspaces/:id/migrate-provider` (+ a status
GET). Implementation: `molecule-controlplane: internal/provisioner/workspace_migrator.go`.

## What it pins

| Block | Load-bearing pins |
|---|---|
| `ownership` | shape = this SDK; impl = `molecule-controlplane`; **builds_on** `object-store` + `workspace-data` |
| `operation`/`providers` | cross-provider compute move; `{aws,hetzner,gcp}` |
| `endpoints`/`request` | the two admin routes; `confirm:true` **required** (mutates two clouds); source resolved from trusted CP state (cp#711 guard), not the request |
| `states` | `snapshotting → snapshotted → provisioning_target → target_healthy → retiring_source → completed`; terminal `{completed, failed, rolled_back}` |
| `flow` | the 7 steps (snapshot+verify → provision/restore → revoke token → healthcheck → repoint → re-credential → retire) |
| `handoff` | **CONSUMES `object-store`/`workspace-data`**: on-demand presigned PUT/GET (`onDemandPresignTTL` 900s — tighter, they can leak into SSM history), freshness 900s, the `latest.tar.zst` key, the persisted paths |
| `invariants` | verify-before-destroy · target-verified-before-source-retire · atomic cutover · critical-path integrity · idempotency (one active migration/workspace) |
| `durability` | pre-cutover fail → `failed` (source stays); post-provision fail → `rolled_back`; 30m handler timeout; watchdog 5m/45m; the active-lock predicate |
| `state_table` | `workspace_migrations` (migration 051) |

## Status

Implemented in `molecule-controlplane`; this contract SSOTs its state machine +
invariants + the object-store handoff. A CP const-pin test would assert the Go
`migrationState` values / TTLs against the vendored mirror, drift-gated by the
per-pair sync gate.
