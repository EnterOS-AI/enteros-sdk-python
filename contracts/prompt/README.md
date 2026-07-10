# prompt contracts

Prompt-assembly & persona-delivery contracts for the Molecule platform. IDL is
**JSON-Schema (draft 2020-12)** per RFC
[molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285)
§15. Each contract is one `*.schema.json` (the shape) plus one `*.contract.json`
(the canonical instance the schema validates).

## `prompt-assembly-delivery`

| File | Role |
| --- | --- |
| `prompt-assembly-delivery.schema.json` | JSON-Schema (2020-12) describing the contract shape |
| `prompt-assembly-delivery.contract.json` | The canonical contract instance (typed from the runtime) |

### What it governs

This is the **sibling of `../mcp/mcp-plugin-delivery`**. Where the MCP contract
pins how the management-MCP descriptor is delivered into each runtime's native
config (the concierge's **tools**), this contract pins how a workspace's **system
prompt is assembled** and how a concierge's **identity is delivered** (the
concierge's **prompt / persona**).

Today the platform's prompt/persona SSOT is **hardcoded in the shared runtime
engine** (`molecule_runtime.prompt`, `molecule_runtime.persona_render`,
`molecule_runtime.plugins`). This contract relocates that SSOT into
`molecule-contracts` so the engine can **consume** the assembly order and the
canonical base/guardrail text from here rather than embedding them. It is **typed
from the current working implementation** — nothing here is invented.

It captures four things:

1. **The prompt ASSEMBLY layer order** — the ordered layers
   `build_system_prompt` composes into `config.system_prompt`, in the exact
   sequence the code appends them. Position in the `assembly_order` array IS the
   layer order.
2. **The canonical BASE + GUARDRAIL text** — `BASE_PLATFORM_PROMPT` and
   `ORCHESTRATOR_ONLY_GUARDRAIL`, verbatim, as SSOT so the engine reads them from
   the contract instead of hardcoding string constants.
3. **The per-runtime persona-file convention** — a `runtimes` block kept
   consistent with `../adapter/official-runtimes.registry.json`'s `persona`
   blocks. What is reconciled (and what is not, by design): across the official
   runtimes the **`native_identity_file` and `status` match**; the **materializer
   descriptions differ in phrasing** (this contract names the concrete adapter
   class, e.g. `ClaudeCodeAdapter.materialize_persona`, where the registry writes
   the generic `adapter.materialize_persona (...)`), and this contract also lists
   **`google_adk`**, which is `not_yet_official` in the registry (persona
   convention pinned there, MCP native format still unverified). There is no gate
   enforcing byte-equality — this is a documentation-level mirror, not a codegen'd
   projection.
4. **The persona-DELIVERY convention** — a concierge's identity is delivered as
   an **always-on plugin rule** from the privileged management plugin
   (composition-based, concierge-only, runtime-agnostic — **no** per-template
   `system-prompt.md`, **no** `if kind == platform` branch).

### The assembly layer order (SSOT)

`assembly_order` is typed straight from
`molecule_runtime.prompt.build_system_prompt`, in append order:

| # | Layer | Gated? | Source |
| --- | --- | --- | --- |
| 1 | `base_frame` | always | `BASE_PLATFORM_PROMPT` (always first, every workspace) |
| 2 | `orchestrator_guardrail` | **concierge-only** | `ORCHESTRATOR_ONLY_GUARDRAIL`, gated on `platform_guardrail` |
| 3 | `platform_instructions` | if non-empty | resolved global→team→workspace instructions |
| 4 | `capabilities_preamble` | if `a2a_mcp` | generated from `platform_tools.registry` |
| 5 | `prompt_files` | always (fallback `system-prompt.md`) | `config.prompt_files` |
| 6 | `memory_snapshots` | if present | `MEMORY.md`/`USER.md`/`CLAUDE.md`/`AGENTS.md`/`GEMINI.md`/`SOUL.md` |
| 7 | `plugin_rules` | if non-empty | every plugin's `rules/*.md` — **the concierge identity rides here** |
| 8 | `plugin_prompts` | if non-empty | every plugin's root `*.md` prompt fragments |
| 9 | `skills` | if non-empty | each loaded skill's docs |
| 10 | `platform_tool_instructions` | always | A2A + HMA usage docs |
| 11 | `peers` | if non-empty | peer capability list |
| 12 | `delegation_failure_handling` | always | static delegation-failure block |

> **Note on ordering vs the task brief.** The brief sketched
> `… → prompt_files → plugin_rules → memory`. The code — which is authoritative —
> auto-loads the **memory snapshots (layer 6) BEFORE plugin_rules (layer 7)**.
> `assembly_order` is typed from the code, not the sketch.

### The concierge-guardrail gate (reconciled with the MCP degrade gate)

Layer 2 is injected **only** for a platform/concierge agent, gated on
`mcp_server_present()` — the **same** runtime-side platform-ness signal the MCP
delivery contract's degrade gate keys on. The gate is evaluated in
`BaseAdapter._common_setup` and passed as `platform_guardrail=`. **Invariant:** a
predicate error must never gag a worker nor crash boot, so it defaults to
`worker` (no guardrail) — pinned `default_on_error: false`.

### Persona DELIVERY vs persona MATERIALIZATION (the seam)

These are two different things and this contract owns only one of them:

- **DELIVERY (this contract's SSOT):** a concierge's identity is *composed in* as
  an always-on `rules/*.md` from the **privileged `molecule-platform-mcp`
  plugin** (`rules/concierge-identity.md`), which auto-globs into `plugin.rules`
  and folds into `build_system_prompt(plugin_rules=…)` → the **`## Platform
  Rules`** layer. Because that plugin is installable **only** on the org-root
  `kind=platform` concierge (server-side enforced in `molecule-core`), the
  concierge-only-ness comes from the plugin's **install scope, not a code
  branch** — no per-template `system-prompt.md`, no `if kind == platform`.
- **MATERIALIZATION (owned elsewhere — REFERENCED, not restated):** a runtime
  whose CLI reads a *native identity file* and ignores `config.system_prompt`
  receives the same canonical persona through `materialize_persona`. The
  per-runtime native file + materializer is the SSOT of
  **`../adapter/official-runtimes.registry.json`** (each runtime's `persona`
  block) and the adapter-socket method
  **`../adapter/adapter-socket.contract.md` §4**. The `runtimes` block here is the
  delivery-facing mirror of that, kept reconciled; it does not duplicate the
  socket's dispatch semantics. The disjunction ("executor surfaces
  `config.system_prompt` XOR `materialize_persona` writes the native file, exactly
  one channel per runtime") is owned by the socket contract §2/§4.

### Relationship to existing SDK contracts (extend, do not duplicate)

- **`../mcp/mcp-plugin-delivery.contract.json`** — the direct sibling: MCP
  descriptor delivery (tools). This contract mirrors its shape and reuses its
  platform-ness signal (`mcp_server_present`) as the guardrail gate.
- **`../adapter/official-runtimes.registry.json`** — SSOT for the per-runtime
  `persona` blocks (native identity file + materializer). The `runtimes` block
  here is reconciled with, and moves with, it.
- **`../adapter/adapter-socket.contract.md`** — SSOT for the adapter methods
  (`materialize_persona`, `create_executor`'s prompt-application MUST). This
  contract owns the *assembly order* and the *delivery convention*; the socket
  owns the *methods* that render/apply them.
- **`../workspace-template/`** and **`../org-template/`** carry `prompt_files`
  as template *payload* (the role content a template ships). This contract owns
  the *assembly order* those files slot into and the *base/guardrail frame* they
  are layered on top of — it does not restate the template payload shape.

### Migration relationship with the runtime engine (SSOT direction)

The canonical text and the layer order currently **live in the runtime engine**
(`molecule_runtime.prompt`), where `build_system_prompt` embeds them. This seed
**relocates the canonical SSOT here** and documents the intended
consume-from-here direction; it does **NOT** wire the engine to read from the
contract (that is a separate, coordinated migration). Until then, treat the two as
a deliberately-identical pair — the embedded `canonical_text` is verified
byte-identical to `BASE_PLATFORM_PROMPT` / `ORCHESTRATOR_ONLY_GUARDRAIL`; do not
edit one without the other.

### Notes / ambiguities flagged

- Several fields (`producer`, `consumers[]`, every `source`/`*_ref`) are
  **documentation / wiring pointers** (symbol names + prose), not
  machine-validated references — same modeling choice as the MCP sibling. Their
  referents are the conformance gate's job at the boundary, not this schema's.
- `assembly_order` models order **positionally** (array index). Layers 3–11 are
  conditionally emitted; only `base_frame`, `platform_tool_instructions`, and
  `delegation_failure_handling` are unconditional (`gated: false`).
- The `runtimes` block lists `hermes` with `native_identity_file: ~/.hermes/SOUL.md`
  (`status: implemented`) and includes `google_adk` (GEMINI.md,
  `status: convention-pinned`) even though google-adk is `not_yet_official` in the
  adapter registry — the persona convention there IS pinned; only its MCP native
  format is unverified.
