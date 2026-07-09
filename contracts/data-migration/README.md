# data-migration — store-to-store object re-home

JSON-Schema (draft 2020-12) IDL for **re-homing a workspace's objects between two
object-store backends** (`data-migration.schema.json` + `.contract.json`). A
**sub-contract of the object-store family**: it moves the **store** (canonically
the global R2 → a tenant's own MinIO) with the **compute fixed** — the inverse of
`workspace-migration`.

## Why it exists

The R2→per-tenant-MinIO adoption needs each workspace's `latest.tar.zst` (later
image-gen blobs + attachments) copied from the global R2 to the tenant's MinIO
under the same key. Today the `ObjectStore` seam has `List`/`Get`/`Put`/`Delete`
but **no `Copy`, no store-pair, no checksum/verify/resume** — so the orchestration
is **net-new**. This contract is the SSOT that net-new implementation conforms to.

## What it pins

| Block | Load-bearing pins |
|---|---|
| `ownership` | shape = this SDK; impl = `molecule-controlplane` (net-new); **builds_on** `object-store` + `workspace-data` |
| `operation`/`direction` | store-to-store re-home; a `Backend` **pair** from `object-store` (canonical `r2→minio`) |
| `scope` | per-workspace; v1 = the snapshot key; later = image-gen blobs + attachments |
| `states` | `pending → copying → verifying → cutover → done`; terminal `{done, failed}` (mirrors workspace-migration) |
| `protocol` | copy = `Get(source)→Put(target)` composed over the op set; manifest unit = the `List` item `{key,size,created_at}`; **idempotent resume** (list-diff by key+size); **verify** (checksum+size) before **cutover** (flip the tenant endpoint only after verify) |
| `invariants` | verify-before-cutover · idempotent resume · source retained until verified cutover |
| `reuses` | key scheme + persisted paths from `workspace-data`, `Backend` enum from `object-store` — **referenced, not redefined** |
| `status` | `net-new-orchestration-not-yet-implemented` |

## Relationship to the family

```
object-store/          ← Backend enum + op set + delivery (foundation)
  ├─ workspace-data/    ← key scheme + persisted paths (what/where)
  ├─ workspace-migration/ ← move COMPUTE, store fixed
  └─ data-migration/    ← move STORE, compute fixed  (this)
```
