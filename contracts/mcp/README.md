# MCP contracts

MCP tool/capability contracts for the Molecule platform. IDL is **JSON-Schema (draft
2020-12)** per RFC [molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285)
§15. Each contract is one `*.schema.json` (the shape) plus one `*.contract.json` (the
canonical instance the schema validates).

## `mcp-plugin-delivery`

| File | Role |
| --- | --- |
| `mcp-plugin-delivery.schema.json` | JSON-Schema (2020-12) describing the contract shape |
| `mcp-plugin-delivery.contract.json` | The canonical contract instance (the migrated data) |

### What it governs

This contract records how the **concierge management-mode MCP server** descriptor
(`mcp_server_name: molecule-platform`) is delivered into each runtime's native settings
file, and — critically — the singular tool verb the concierge **must** expose for the
platform to consider it healthy.

- The management MCP must expose **`provision_workspace`**.
- The **degrade gate** enforces this at the boundary: if the live MCP surface does not
  expose `required_tool`, the concierge is marked degraded / fails closed. The Go side
  derives the gate's required tool from this contract (`platform_agent.go`,
  `conciergePlatformMCPRequiredTool`, test `TestSSOT_DegradeGateToolDerivesFromContract`).

### The singular `required_tool` field

`required_tool` is **a single string**, not a list. Its value is **`provision_workspace`**.
The schema pins it with `"const": "provision_workspace"`, so any drift fails schema
validation.

### No-rename rule

**`provision_workspace` MUST NEVER be renamed.** Renaming the verb is exactly the `#3082`
phantom-verb regression class RFC §15 flagged: a contract was once authored against
`create_workspace`, a verb the management-mode MCP never exposed. The migration here is
**1:1 — semantics preserved, no rename.** Any future capability change must add a verb on
the live surface first; the contract follows the surface, never the reverse.

### Migration relationship with `molecule-core` (SSOT direction)

The same contract data currently **also** lives in `molecule-core` at
`contracts/mcp-plugin-delivery.contract.json`, where the Go derive test reads it. That
copy is intentionally left in place by this seed.

- **Intended direction:** `molecule-contracts` becomes the **SSOT**. In a later,
  coordinated P2 step, `molecule-core` will **consume / regenerate** its copy from here
  (codegen output under `gen/`, enforced by a regenerate-and-diff CI gate) rather than
  hand-maintaining it.
- **This task does NOT modify `molecule-core`.** It only relocates the canonical schema +
  instance here and documents the intended consume-from-here direction. Until the core
  consumption step lands, treat the two copies as a temporary, deliberately-identical pair;
  do not edit one without the other.

### Field reference

The instance carries exactly the fields core's contract has (no invented fields):

| Field | Type | Meaning |
| --- | --- | --- |
| `settings_path` | string | Default (claude_code) settings file the descriptor is written to |
| `key` | string | Top-level key under which MCP servers are declared (`mcpServers`) |
| `entry_shape` | string | Shorthand for the entry shape (`name->{command,args?,env?}`) |
| `mcp_server_name` | string | Logical name of the management MCP descriptor (`molecule-platform`) |
| `required_tool` | string (`const`) | **The singular verb the concierge must expose — `provision_workspace`** |
| `loaded_mcp_tools_field` | string | Field name reporting tools actually loaded |
| `legacy_binary_path` | string | Path the legacy presence probe checked (`/opt/molecule-mcp-server`) |
| `runtime_present_field` | string | Runtime-reported presence field (`mcp_server_present`) |
| `producer` | string | Adapter that emits the descriptor (`MCPServerAdaptor`) |
| `consumer` | string | Primary consumer of the rendered descriptor |
| `consumers` | string[] | Full list of consumers/derivers |
| `descriptor` | string | Prose describing the runtime-agnostic descriptor + wiring PORT |
| `port` | object | The MCP-wiring PORT: `hook`, `impl`, `present_probe`, `dispatch`, `resolver_default` (all strings) |
| `runtimes` | object | Per-runtime render targets, keyed by runtime id; each has `settings_path`, `format`, `renderer`, `status`, and `key` (JSON runtimes) or `table` (TOML runtimes) |

### Notes / ambiguities flagged

- Several string fields (`producer`, `consumer`, `consumers[]`, `port.*`,
  `descriptor`) are **documentation / wiring pointers** (symbol names and prose), not
  machine-validated references. They are modeled faithfully as strings; their *referents*
  are not checked by this schema — that is the conformance gate's job at the boundary.
- `runtimes` entries are heterogeneous by design: JSON-keyed runtimes carry `key`
  (`mcpServers`) while the TOML runtime (`codex`) carries `table` (`mcp_servers`). Both are
  modeled as optional; the four common fields (`settings_path`, `format`, `renderer`,
  `status`) are required. `settings_path`/`format` may legitimately be the literal string
  `unverified` for not-yet-verified runtimes (e.g. `hermes`).
