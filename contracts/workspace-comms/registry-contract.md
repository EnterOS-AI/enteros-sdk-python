# Workspace-Comms Contract — `/registry` + `/workspaces` lifecycle

> **Status: DESCRIPTIVE (enforcement deferred).** This document is the canonical,
> single written record of the workspace↔platform HTTP comms protocol, **typed from
> the current working implementations**. It is the reference of record — it replaces
> protocol prose scattered across three codebases and the partial AST drift-checker
> (`molecule-ai-workspace-runtime/scripts/check_platform_comm_contract.py`).
>
> It is **not** machine-enforced yet, and deliberately so: codegen + a conformance
> gate are deferred until drift demonstrably costs us something (see *Enforcement*
> below). When that day comes, the JSON-Schema + generated models grow alongside this
> file. Until then: **if you change the protocol, update this doc.**

- **Producer (server):** `molecule-core` — `workspace-server/internal/handlers/{registry,discovery,delegation,secrets}.go`, routes `internal/router/router.go:457-470`, payloads `internal/models/workspace.go`, auth `internal/middleware/wsauth_middleware.go`.
- **Consumer A (in-platform):** `molecule-ai-workspace-runtime` — `molecule_runtime/{platform_auth,coordinator,mcp_heartbeat,runtime_inbox,platform_inbound_auth}.py` (uses `httpx`).
- **Consumer B (off-platform):** `molecule-ai-sdk` — `molecule_external_workspace/{client,a2a_server,inbound}.py` (uses `requests`).

These are **three independent implementations of one protocol** (different HTTP
libraries, no shared base code). That is the standing risk this document exists to
contain.

## Endpoints

| Endpoint | Method · Path | Auth (bearer bound to) | Identity placement | Response / status contract |
|---|---|---|---|---|
| **register** | `POST /registry/register` | `id` — **absent on first-ever** (token minted in response), mandatory thereafter | self in body `id` | `auth_token` minted ONCE; `platform_inbound_secret` every call; `url`⇔`delivery_mode` conditional; `kind=platform` → 403 on public path |
| **heartbeat** | `POST /registry/heartbeat` | `workspace_id` | self in body | `monthly_spend` cumulative/clamped; `loaded_mcp_tools` OMITTED ≠ `[]`; `agent_card` backfill-only; fails **open** (no secret) on auth-DB hiccup |
| **update_card** | `POST /registry/update-card` | `workspace_id` | self in body | `agent_card.url` SSRF-rejected; broadcasts `AGENT_CARD_UPDATED` |
| **discover** | `GET /registry/discover/:id` | `X-Workspace-ID` caller + matching bearer (or CP session) | caller in header, target in path | `url` is the load-bearing field; 403 `CanCommunicate`; **503 fail-CLOSED** on auth-DB down |
| **peers** | `GET /registry/:id/peers` | path `:id` | self in path | array never null; parent-scoped siblings; self stripped; `status!='removed'` |
| **check_access** | `POST /registry/check-access` | **none** (boolean predicate) | both in body | `{allowed:bool}` — producer-only; neither consumer calls it |
| **pull_secrets** | `GET /workspaces/:id/secrets/values` | `:id` | self in path | flat decrypted `{KEY:value}`; **500 fail-CLOSED** on auth-DB; partial-decrypt → fail-loud, never a partial bundle |
| **poll_state** | `GET /workspaces/:id/state` | `:id` | self in path | **404 == deleted** ("shut down"); `paused` flag; the status code *is* the contract |
| **a2a_inbound** | `POST /workspaces/:id/a2a` | **caller** (≠ target) or admin/org | caller in header, target in path | A2A JSON-RPC envelope; `queued` push-async; 413 body cap. **SDK receive-side does NO app-auth** |
| **a2a_queue_state** | `GET /workspaces/:id/a2a/queue/:queue_id` | queue caller or workspace | self in path | `response_body` only when `completed`; 404 existence-non-inferring (after auth) |
| **delegate** | `POST /workspaces/:id/delegate` | `:id` (source) or admin/org | **source in path, target in body** — never swapped | 202 `{delegation_id,status:'delegated'}`; idempotent on `(workspace_id, idempotency_key)`; 30-min ceiling |

## Cross-cutting invariants

1. **Token mint-once.** Bearer comes only from `register()`'s response `auth_token`; minted once per workspace; persisted client-side at `<configs>/.auth_token` mode `0600` (atomic, flock-guarded); reused.
2. **Origin on SaaS.** `Origin: <PLATFORM_URL>` is required or the edge WAF silently rewrites to canvas → 404.
3. **Strict binding.** A token authenticates the *specific* workspace it claims (C18 / #761) — A's token can never auth as B.
4. **Identity-placement asymmetry.** Asserting *your own* id → `X-Workspace-ID` header / source-in-path; a *target* id → body or `:id`-as-target.
5. **Bypass ordering.** Org-token + `ADMIN_TOKEN` bypass per-row `CanCommunicate`, checked *before* the narrow per-workspace token validation.
6. **Retry asymmetry.** 429 auto-retry only on idempotent GETs (Retry-After honored, jittered backoff cap 30s); POST/DELETE never auto-retried.
7. **Fail-direction split.** `secrets`/`state`/`discover` fail-**CLOSED** on auth-DB error (secret material / routing at stake); `heartbeat`/`a2a` fail-**OPEN** (no secret returned).

## Known divergences (typed from reality — decisions tracked separately)

These are real disagreements / under-specifications found across the three impls. The
proposed canonical decision is noted; the contentious ones are filed as issues.

1. **`register.url` has three meanings** — producer (required for push / ignored for poll), external runtime (`url=''`+`poll`), SDK (`'remote://no-inbound'`, undocumented by the producer). → canonicalize one no-inbound form.
2. **`delivery_mode` default trap** — producer defaults missing → `push` → rejects no-inbound SDK agents with `url_required_for_push`. → bind `delivery_mode` ⇔ `url`.
3. **`A2AServer` inbound unauthenticated** *(security — filed separately)* — SDK receive-side does zero app-layer auth; producer never signs its proxied inbound call. Open RPC if the agent is directly reachable.
4. **`platform_inbound_secret`** delivered by producer on register + every heartbeat, **never read by the SDK** — gap or push-only?
5. **Nullable tri-states** — `mcp_server_present` (nil=allow/false=fail-closed/true) and `loaded_mcp_tools` (OMITTED ≠ `[]`) are never sent by external/SDK → silently bypass the fail-closed identity gate.
6. **`agent_card` has no shared shape** — `RawMessage`/dict everywhere; each impl ships a different card. → pin a minimal canonical sub-schema (required `{name}`).
7. **Status-code semantics are prose** — consumers hard-code `404=deleted`, `410=cursor-lost` etc.; a producer code change silently mis-behaves the client. → first-class typed outcomes when enforcement lands.
8. **`delegate idempotency_key`** is consumer-derived (`sha256(task+minute)`) but producer-opaque → two consumers could compute different keys → dedup miss.

## Enforcement (deferred)

This artifact is **descriptive**. The decision (2026-06-26) is to capture the contract
from reality now and add enforcement only when drift warrants it. The deferred,
incremental ladder — none of which is committed by adopting this doc:

1. *(cheapest enforcement, if/when wanted)* generate one shared Python model from this
   contract that **both** consumers import, so they cannot drift from each other.
2. producer `httptest` schema-conformance + consumer model-roundtrip + wire record-replay
   (a 3-leg gate that subsumes the AST drift-checker and covers response shapes/status
   codes it cannot reach).
3. advisory → soak → required rollout (RFC molecule-core#3285 §14 pattern), then retire
   `check_platform_comm_contract.py`.

Rationale and the full surface mapping live in the design note
`molecule-rfc-registry-comms-ssot.html`. Applies the RFC #3285 producer-as-SSOT thesis
to the comms layer — deliberately *capture-first, enforce-later*.
