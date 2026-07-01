# promote-request contract

The **control-plane admin promote request** wire contract. IDL is **JSON-Schema (draft
2020-12)** per RFC [molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285)
§15. One `*.schema.json` (the shape) plus one `*.contract.json` (the canonical instance the
schema validates).

| File | Role |
| --- | --- |
| `promote-request.schema.json` | JSON-Schema (2020-12) describing the contract shape |
| `promote-request.contract.json` | The canonical contract instance (the wire-field manifest) |

## What it governs

`POST {cp}/cp/admin/promote` — the request to promote built components forward (or roll back)
across environments. The **producing SSOT** is CP's `PromoteRequest` struct
(`molecule-controlplane/internal/handlers/admin_promote.go`); `promote_request_contract_test.go`
asserts the struct's JSON tags equal these `fields` keys (set-equality). The
`molecule-admin-cli` and `molecule-mcp-admin` wrapper copies carry the same six fields and name
the CP file as canonical.

The six fields: `env`, `components`, `target_tag`, `dry_run`, `confirm`, `rollback_to` — see
the instance `note`s for allowed values, defaults, and the `confirm` foot-gun guard on a real
full-platform promote.

## SSOT direction (this seed) — `mcp-plugin-delivery` pattern

`promote_request.contract.json` lives in `molecule-controlplane/internal/handlers/` next to the
producing struct. This directory makes `molecule-contracts` the cross-repo SSOT, exactly as
[`mcp/`](../mcp/README.md) did for the plugin-delivery contract — so the CLI/MCP wrapper copies
have one public source to align to rather than a CP-internal path.

- **This seed does NOT modify the CP copy.** It remains in place and still drives
  `promote_request_contract_test.go`. CP adds a lightweight, advisory **`contract-ssot-sync`**
  gate (a canonical-JSON compare of its mirror against this SSOT over the public raw endpoint,
  fail-closed on drift) — the same mechanism core already runs for `mcp-plugin-delivery`.
- **No codegen bindings.** Like `provision-request` / `plugin-manifest`, this is a
  **schema-only** contract: the generators target `mcp/` + `workspace-comms/` only.
  `validate-contracts` (auto-discovers every `*/*.contract.json`) is the enforcement here.

## No-rename rule

The `fields` keys are the wire contract. Renaming a key is caught by the CP struct-pin test on
the producing side; the schema additionally pins the full required key set and the `endpoint`
const. Any change is a deliberate, reviewed edit across the SSOT + the CP struct + the wrapper
copies.
