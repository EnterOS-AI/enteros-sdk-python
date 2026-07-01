# provision-request contract

The **core → control-plane provision request** wire contract. IDL is **JSON-Schema (draft
2020-12)** per RFC [molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285)
§15. One `*.schema.json` (the shape) plus one `*.contract.json` (the canonical instance the
schema validates).

| File | Role |
| --- | --- |
| `provision-request.schema.json` | JSON-Schema (2020-12) describing the contract shape |
| `provision-request.contract.json` | The canonical contract instance (the wire-field manifest) |

## What it governs

`POST {cp}/cp/workspaces/provision` — the request molecule-core sends to the control-plane to
provision a workspace. Core's sender is `cpProvisionRequest` (`cp_provisioner.go`); the CP
receiver is `wsProvisionRequest` (`internal/handlers/workspace_provision.go`). The two are
**duplicated structs in two repos with no shared compile unit**, so a field added on the
sender silently does nothing if the receiver lacks it — exactly how `template_assets` was
dropped for weeks (RFC #2843; see memory `project_saas_restart_re_stub_config`).

The instance enumerates, per wire field: its `type` (scalar/shape kind) and `cp_consumes`
(whether the CP receiver decodes it). A `cp_consumes: false` field is a **declared-dead** wire
field (sent but ignored) and MUST carry a `note` — so dead channels are explicit, not silent.
The schema encodes that rule (`if cp_consumes == false then note required`).

## Two struct-pin guards (unchanged by this seed)

1. **PRODUCER PIN** — molecule-core `provisioner/provision_request_contract_test.go`:
   `cpProvisionRequest`'s JSON tags MUST equal the `fields` keys exactly.
2. **CONSUMER COMPLETENESS** — molecule-controlplane
   `handlers/provision_request_contract_test.go`: `wsProvisionRequest` MUST have a json tag
   for every `cp_consumes: true` field.

## SSOT direction (this seed) — `mcp-plugin-delivery` pattern

`provision_request.contract.json` previously lived as **two deliberately byte-identical
copies** — `molecule-core/workspace-server/internal/provisioner/` and
`molecule-controlplane/internal/handlers/` — each guarded by its own struct test but with **no
shared source of truth**. This directory makes `molecule-contracts` the SSOT, exactly as
[`mcp/`](../mcp/README.md) did for the plugin-delivery contract.

- **This seed does NOT modify the two consumer copies.** They remain in place (each still
  drives its own struct-pin test). Each consumer adds a lightweight, advisory
  **`contract-ssot-sync`** gate (a canonical-JSON compare of its mirror against this SSOT over
  the public raw endpoint, fail-closed on drift) — the same mechanism core already runs for
  `mcp-plugin-delivery`. Until a later coordinated consume-from-`gen/` step, treat the copies
  as a temporary, deliberately-identical set: do not edit one without the others.
- **No codegen bindings.** Like `plugin-manifest` / `org-template` / `workspace-template`,
  this is a **schema-only** contract: the `gen-*.mjs` generators target `mcp/` +
  `workspace-comms/` only, so nothing is emitted under `gen/`. `validate-contracts` (which
  auto-discovers every `*/*.contract.json`) is the enforcement that matters here.

## No-rename rule

Wire field names (the `fields` keys) are the contract. Renaming a key is a wire break that
both struct-pin tests catch on the producing/consuming side; the schema additionally pins the
full required key set and the `endpoint` const. Any change to the wire shape is a deliberate,
reviewed edit across the SSOT + both struct copies.
