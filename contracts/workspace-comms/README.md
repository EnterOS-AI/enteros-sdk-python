# Workspace-Comms contracts

Machine-enforced contracts for the workspace↔platform HTTP comms protocol
(`/registry/*` + the A2A envelope). IDL is **JSON-Schema (draft 2020-12)** per RFC
[molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285)
§15. Each contract is one `*.schema.json` (the shape) plus one `*.contract.json` (a
canonical example instance the schema validates), mirroring the `mcp/` pipeline.

This is **Wave 2** of the molecule-contracts SSOT consolidation: it promotes the
**descriptive** prose in [`registry-contract.md`](./registry-contract.md) into
**enforced** schema, derived from the canonical Go wire structs in `molecule-core`
(`workspace-server/internal/models/workspace.go` + `internal/handlers/{registry,a2a_proxy,discovery}.go`)
— the producer is the SSOT, the schema follows the surface, never the reverse.

## Contracts

| File pair | Wire authority (molecule-core) | Governs |
| --- | --- | --- |
| `register.schema.json` / `.contract.json` | `models.RegisterPayload` + `registry.go` Register response | `POST /registry/register` request + result |
| `heartbeat.schema.json` / `.contract.json` | `models.HeartbeatPayload` + `models.RuntimeMetadata` + `registry.go` Heartbeat response | `POST /registry/heartbeat` request + ack |
| `a2a-envelope.schema.json` / `.contract.json` | `a2a_proxy.go` message/send normalization + `buildConciergeWarmupBody` | A2A v0.3 JSON-RPC `message/send` request + queued ack |
| `agent-card.schema.json` / `.contract.json` | `agent_card json.RawMessage` (today untyped everywhere) | The minimal shared `{name}` card sub-shape |
| `channel-provenance.schema.json` / `.contract.json` | `internal/channels/manager.go` `HandleInbound` (structured `params.metadata`) **+** lark-channel-molecule `bridge.py` `_build_payload` (in-band text header) | **DESCRIPTIVE** — the channel-bridge provenance attached to inbound A2A turns; documents BOTH variant shapes in use today (see below) |

Each request/response contract instance models **both directions** under `request`
and `response` keys, so one file pins the full round-trip shape.

## Derivation rules (so the schema stays honest to the wire)

- **Requiredness mirrors the Go binding tags.** `binding:"required"` → `required`;
  `,omitempty` / pointer fields → optional. So only `id`+`agent_card` are required on
  register, only `workspace_id` on heartbeat.
- **Tri-state booleans stay booleans (absent ≠ false).** `mcp_server_present` is `*bool`
  on the wire: `nil`=allow / `false`=fail-closed / `true`=ok (RCA #2970). Likewise
  `loaded_mcp_tools` **OMITTED is not `[]`** — an absent list on a `mcp_server_present=true`
  beat fails the #3082 gate loud. The schema models these as optional booleans/arrays;
  the *semantics* of absence live in the producer (and are documented in the field text).
- **`const` / `enum` pins the load-bearing literals.** `register.response.status` ==
  `"registered"`, `heartbeat.response.status` == `"ok"`, `a2a response.status` ==
  `"queued"`, `delivery_mode` ∈ {push, poll}. Drift off these fails CI — the same
  mechanism that makes the mcp `required_tool` `const` load-bearing.
- **A2A v0.3 discriminator is `kind`, not `type`.** Every `params.message.parts[]` item
  requires `kind`; a `type`-keyed part is dropped by the receiver's v0.3 validator
  (#2345). The schema requires `kind`, so a `type`-only part fails validation.

## The shared `agent_card` sub-shape

`agent_card` is `json.RawMessage` on every payload today — **untyped, and each of the
three independent impls ships a different card** (registry-contract.md divergence #6).
`agent-card.schema.json` pins the **one** universally-present, load-bearing field —
`name` (non-empty) — and leaves the rest open (`additionalProperties: true`) so a real
A2A card still validates. The same minimal sub-shape is **inlined** under `$defs/agentCard`
in `register`/`heartbeat` so each schema validates **offline** (the CI gate runs
`check-jsonschema --schemafile <schema> <instance>` per file, with no cross-file `$ref`
resolution). `agent-card.schema.json` is the canonical declaration; the inlined copies
are kept in lockstep with it.

## Channel provenance (descriptive)

`channel-provenance.schema.json` is a **DESCRIPTIVE** capture (enforcement deferred —
same status ladder as `registry-contract.md`, same capture-first precedent as
molecule-contracts#4) of what channel bridges ALREADY put on an inbound A2A
`message/send` turn. Two producers, two **variant** shapes, both documented as-is:

- **molecule-core channel manager** (`workspace-server/internal/channels/manager.go`
  `HandleInbound`) — a structured object at `params.metadata` (a **sibling** of
  `params.message`, not the `message.metadata` bag): `source` / `channel_id` /
  `chat_id` / `user_id` / `username` / `message_id` + Redis-loaded `history`
  + the adapter's `extra` passthrough. It also stamps
  `params.message.messageId = channel-<type>-<message_id>`.
- **lark-channel-molecule bridge** (`lark_channel_molecule/bridge.py`
  `_build_payload`) — no structured metadata at all: a one-line text header
  `[lark-channel] brand=… chat_id=… chat_type=… sender_open_id=… message_id=…`
  prepended to the message text inside the single text part (peer A2A
  `send_a2a_message` takes a plain string).

The divergence (placement AND field names) is deliberate to record, not to resolve:
the unified, runtime-stamped provenance lane is the PR-2 local-event-socket work
(molecule-ai-workspace-runtime#215). When it lands, capture the unified shape here
and demote these two variants to the legacy record (divergence #9 in
`registry-contract.md`).

## CI

- **`validate-contracts`** (`.gitea/workflows/validate-contracts.yml`) now globs
  **`*/*.contract.json`** (was `mcp/*.contract.json`) and validates each against its
  sibling schema — so these contracts are enforced exactly like the mcp one. Fail-closed
  on any invalid instance or any contract missing its schema.
- **`codegen-drift`** now covers these contracts: the three generators in `tools/` emit a
  second file per language — `gen/<lang>/workspace_comms_gen.<ext>` — of **model bindings**
  (Go structs / TS interfaces / Python `TypedDict`s) **derived from these `*.schema.json`
  shapes** via the shared walker `tools/lib/comms-schema.mjs`, with the load-bearing `const`
  literals (`status` ∈ {registered, ok, queued}, `jsonrpc` = 2.0) emitted as importable
  constants. The mcp `contract_gen.<ext>` output stays byte-identical; the drift gate
  re-runs all three generators unchanged. See `tools/README.md` ("workspace-comms models").

## SSOT direction / what repoints next

These schemas are the SSOT the three independent impls converge on. The generated models
now exist (`gen/<lang>/workspace_comms_gen.<ext>`); what remains is repointing each
consumer onto them:

- **Python consumers** (`molecule-ai-workspace-runtime/molecule_runtime` and
  `molecule-ai-sdk/molecule_external_workspace`) repoint onto the generated
  Python `TypedDict`s so they cannot drift from each other.
- **TS consumers** (the channel surfaces + `mcp-server`) repoint onto the generated TS
  interfaces.
- The AST drift-checker
  `molecule-ai-workspace-runtime/scripts/check_platform_comm_contract.py` **retires** once
  a generated-model + conformance gate lands here (the advisory→soak→required ladder in
  registry-contract.md *Enforcement* and RFC #3285 §14).

Treat `registry-contract.md` (descriptive prose + divergence register) and these schemas
(enforced shape) as the paired record: **if you change the protocol, update both** (and
regenerate `gen/`).
