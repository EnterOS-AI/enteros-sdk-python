# object-store — provider-agnostic storage adapter contract

JSON-Schema (draft 2020-12) IDL for the **object-storage adapter layer**: one
`object-store.schema.json` (shape + pinned constants) + one
`object-store.contract.json` (the canonical instance). This is the **foundation
of the object-store contract family** — `workspace-data` (snapshot protocol),
`data-migration`, and `workspace-migration` all build on it.

## The idea

The layer is **governed by this contract**; **MinIO / R2 / S3 are just
adapters** behind one operation set. A deployment swaps backends with config
(`MOLECULE_OBJECT_STORE_BACKEND`), no code change — the interfaces
(`ObjectStore` / `Presigner` in `molecule-controlplane: internal/workspacedata/`)
and the backend selector (`internal/workspacedata/backend.go`) are the runtime
realization of this SSOT.

## The key dimension: delivery mode

The contract exposes **how a workspace box moves bytes to/from the store**, which
is what lets a co-located per-tenant MinIO be a first-class adapter:

| mode | who | how | box creds |
|---|---|---|---|
| **`presigned-direct`** | R2, S3 | box curls a CP-minted presigned URL to a **global** store reachable from every box | short-lived presigned URL |
| **`platform-proxy`** | **MinIO** (per-tenant, loopback-only) | box streams via the tenant platform's existing **:8080** path (private-IP same-cloud / CF-tunnel cross-cloud); platform reads/writes its own `localhost:9000` | its **existing platform auth token** |

`platform-proxy` needs **no new SG rule, no MinIO exposure, and works
cross-cloud** — because it reuses the one path a workspace box already has to its
tenant. Caveat: bytes transit the platform; cross-cloud rides the CF tunnel's
size/time limits.

## What it pins

| Block | Load-bearing pins |
|---|---|
| `ownership` | shape = this SDK; adapters = `molecule-controlplane`; consumers = workspace-data + the two migration contracts |
| `operations` | the adapter op set every backend satisfies: put / put_with_content_type / get / list / delete / presign_get / presign_put |
| `backends` | selector `MOLECULE_OBJECT_STORE_BACKEND` (default **r2**, unknown → r2); enum `{r2, minio, s3}` |
| `addressing` | r2 = virtual-hosted/`auto`; **minio = path-style**/`us-east-1`; s3 = virtual-hosted/region |
| `delivery` | modes `{presigned-direct, platform-proxy}`; by-backend map; the box-facing env / platform reach for each |
| `config` | per-usage endpoint/creds env (workspace-data / config-relay / image-gen) + the fallback chain (relay + image-gen default to workspace-data) — **CP-side only, never on the box** |
| `creds_boundary` | the invariant across both modes: **the box never holds object-store creds** (why per-tenant MinIO removes the R2 bucket-policy prerequisite) |

## Consumers (vendor + drift-gate)

- **`molecule-controlplane`** (Go) — `internal/workspacedata/{backend,s3store,service}.go` are the adapter impls; a const-pin test asserts the package consts (`BackendEnv`, the backend enum, addressing) against a vendored mirror, kept == SDK by `.gitea/scripts/check-contract-ssot-sync.sh` (the per-pair-base gate).
- The **workspace-data / data-migration / workspace-migration** contracts reference this one (delivery mode, operations).

## Status

`backends.default = r2` — behavior-preserving. MinIO/S3 are opt-in via
`MOLECULE_OBJECT_STORE_BACKEND` (the selector is landed in
`molecule-controlplane` #1211). The `platform-proxy` MinIO delivery + per-tenant
provisioning is the follow-on that conforms to this contract.
