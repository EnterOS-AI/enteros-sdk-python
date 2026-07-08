# workspace-data — durable-workspace snapshot/restore contract

JSON-Schema (draft 2020-12) IDL for the **provider-agnostic durable-workspace
snapshot/restore** mechanism: one `workspace-data.schema.json` (the shape +
pinned constants) plus one `workspace-data.contract.json` (the canonical
instance). It single-sources the constants the snapshot/restore mechanism is
currently duplicating across `molecule-controlplane`, so the box userdata timer,
the CP `workspacedata.Service`, and the `molecule_runtime` durability guard all
agree on one definition.

## The idea

A workspace's durable agent state — everything under `persisted_paths`,
**including the mailbox kernel's `/workspace/.molecule`** — is periodically
archived (`tar+zstd`) to object storage (Cloudflare **R2**) via a presigned PUT,
and restored via a presigned GET **before** the runtime container mounts
`/workspace`. So state survives instance recreate / auto-heal on **any** compute
provider. Durability rides object storage, **not** per-provider block volumes —
the compute provider (aws / hetzner / gcp / local / molecules-server) is
irrelevant. This is why it is provider-agnostic by construction.

## What it pins

| Block | Load-bearing pins |
|---|---|
| `ownership` | shape = this SDK; **implementation = `molecule-controlplane`** (box timer + `workspacedata.Service`); durability-credit consumer = **`molecule_runtime`** |
| `enable` | master gate `MOLECULE_WORKSPACE_DATA_PERSIST`; `default_today:false` (ships dark) vs `target_default:true`; the flip is **gated** on `default_on_gated_on` (wire local+aws · R2 bucket-policy cross-prefix deny · per-merge e2e · staging-first) |
| `selector` | per-workspace choice `MOLECULE_DATA_PERSISTENCE` — SSOT is **provision-request** (`data_persistence`); only cross-referenced here (protocol vs selector split) |
| `box_env` | the ONLY two box vars — presigned `MOLECULE_WORKSPACE_{RESTORE,SNAPSHOT}_URI`; the box never holds object-store creds |
| `cp_env` | CP-side R2 creds (`MOLECULE_WORKSPACE_DATA_{BUCKET,ENDPOINT,ACCESS_KEY_ID,SECRET_ACCESS_KEY}`) — never on the wire |
| `persisted_paths` | `["/workspace","/home/agent/.claude"]` (`/workspace/.molecule` ⊂ `/workspace`); `/configs` **excluded** (re-rendered each boot) |
| `archive` / `key_scheme` | `tar+zstd`; fixed per-workspace `workspace-data/{id}/latest.tar.zst` (one last-known-good image, overwritten) |
| `ttls` / `cadence` | restore GET 30m · snapshot PUT 7d (SigV4 max) · on-demand 15m; timer every ~10 min |
| `restore_ordering` | restore **before** container mount — non-negotiable |
| `durability_signal` | how the runtime guard credits **snapshot-durability**: base under a persisted path + `snapshot_uri` present + no `ws-snapshot-disabled` marker |
| `safety` | partial archives never overwrite `latest`; a failed restore drops the disabled marker so the timer won't clobber a good backup with an empty tree |
| `open` | tracked edges: no GC/retention (P3); **R2 bucket-policy security gap** (box ECR creds must be denied cross-prefix writes before default-on); `local`/`aws` still unwired to R2; snapshot durability is **periodic** (bounded loss) vs a live volume (zero loss) |

## Consumers (vendor + drift-gate, mirroring `provision-request`)

- **`molecule-controlplane`** (Go) — `workspacedata.Service` + `store.go` +
  the userdata template render their env keys / `PersistedPaths` / key scheme /
  TTLs from these constants; a byte-identical mirror `.contract.json` + const-pin
  test keep the Go consts == the instance.
- **`molecule_runtime`** (Python) — `mailbox_dir.verify_durability` reads
  `persisted_paths` + `box_env.snapshot_uri` to credit `snapshot-durable`
  (a third durability state alongside `durable` / `ephemeral`), drift-gated like
  `config_relay.py`'s runtime JSON-sync check.

## Status

`enable.default_today` is **false** — this contract codifies the mechanism as
SSOT (additive, zero behavior change). Flipping to `target_default` is the
separate rollout tracked by `enable.default_on_gated_on`.
