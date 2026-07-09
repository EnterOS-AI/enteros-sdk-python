# boot-token contract

SSOT for the **WS-A scoped workspace boot token** — the credential an ordinary
workspace box uses for its **pre-register** operations.

## Why it exists

A workspace box registers with the platform (`/registry/register`) only *after*
its runtime container starts, and gets its per-workspace token in that response.
But two things happen **before** register, in cloud-init:

1. **boot-event phone-home** → `POST /cp/tenants/boot-event` (provisioning progress)
2. **restore-on-boot** → the object-store *platform-proxy* restore (populates
   `/workspace` before the container mounts it)

Historically the box authenticated these with the raw tenant `admin_token`. The
founder ruling (2026-07-08) is that an ordinary box must **not** carry the tenant
admin credential — least privilege. This token replaces it for exactly those two
narrow, per-workspace, expiring purposes.

## Shape

An opaque, stateless HMAC bearer:

```
token = base64url(payload_json) + "." + base64url(HMAC-SHA256(key, base64url(payload_json)))
payload_json = {"wsid":…,"org":…,"exp":…,"scope":[…]}   // compact JSON, field order wsid,org,exp,scope
```

- **HMAC key = the per-tenant `admin_token`** — held by the CP
  (`org_instances.admin_token`) and the tenant platform box (`ADMIN_TOKEN` env),
  used as the signing key **only, never transmitted**. So the token conveys **no
  admin power**: a leak exposes at most one workspace's boot-events + snapshot,
  never the tenant. A per-tenant key gives per-tenant isolation for free.
- Delivered to the box in `MOLECULE_BOOT_TOKEN`; re-minted every provision.
- Scopes: `boot-event`, `restore`. A verifier MUST scope-check for its route.

## Who implements it

- **Minter:** `molecule-controlplane` `internal/boottoken` (mints at provision).
- **Verifiers:** `molecule-controlplane` (`/cp/tenants/boot-event`) and
  `molecule-core` (workspace-server, the object-store restore-on-boot route).

Each repo keeps its own small mint/verify implementation (no shared Go module
across the repo boundary — mirrors the `object-store` / `workspace-data` pattern)
and **pins to this contract via the `test_vectors`**: a golden test in each repo
asserts its `Verify` accepts each vector's token under its key and returns the
listed claims. Any construction drift between minter and verifier fails that test.

## Relationship to the object-store family

The `restore` scope authorizes the **platform-proxy** restore delivery mode of
[`contracts/object-store`](../object-store/README.md). That mode (unlike a
presigned URL) needs a bearer on the box; this token is that bearer. `boot-event`
is independent of object storage.

## Changing it

The `test_vectors` are frozen bytes — changing the construction is a **breaking**
change (existing in-flight tokens would fail to verify). Bump `schema_version`
(`boot-token/v2`), add new vectors, and land the minter + both verifiers together.
