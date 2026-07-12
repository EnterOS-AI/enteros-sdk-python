# Adapter Socket Contract — the runtime-adapter SSOT

> **Status: DESCRIPTIVE (enforcement staged — see ADR-004 P1–P4).** This document
> is the canonical, single written record of the **runtime-adapter socket**: every
> method a runtime adapter MUST implement to satisfy the platform, plus the MAY
> methods it may add. It is **typed from the current working implementations** —
> `molecule_runtime.adapter_base.BaseAdapter` and the per-runtime render/read ports
> (`mcp_render.py`, `persona_render.py`, `loaded_mcp_tools_probe.py`) as they exist
> today. Nothing here is invented; each signature and return semantic below is
> derived from code in `molecule-ai-workspace-runtime` and the four official
> template adapters.
>
> **Anchor:** [ADR-004 — the SDK owns the adapter contract + registry; the shared
> runtime engine is runtime-agnostic](https://git.moleculesai.app/molecule-ai/molecule-core/-/blob/main/docs/adr/ADR-004-sdk-owns-adapter-contract-and-registry.md).
> ADR-004 §1/§2 mandate this contract as the SSOT for the socket + the official
> registry. It supersedes ADR-003 §2 (which placed per-runtime shape in the shared
> engine's dispatch tables). The distinct **workspace↔platform wire** contract
> (register/heartbeat) lives in `../workspace-comms/registry-contract.md` and is
> NOT re-specified here — this is the **adapter** seam.

## Why this exists (the seam ADR-004 names)

Molecule runs one agent codebase across many runtimes (claude-code, codex, hermes,
openclaw) and exposes the same capabilities (management MCP, A2A, memory, persona)
on all of them. Two adapter layers make that work, in opposite directions
(ADR-003): the **runtime adapts the agent to the platform**, and the **plugin
adapts its abilities to each runtime**. Today the *per-runtime shape* of the second
layer — MCP-config renderers, their inverse readers, the present-probe, and the
persona materializer — lives in the shared engine's dispatch tables
(`_RUNTIME_SPECS` / `_RUNTIME_READERS` / `_RUNTIME_PERSONA`), keyed by runtime name.
ADR-004 moves that shape **into the adapter** and makes the engine hold zero
per-runtime dispatch. This document is the socket every adapter (official or
third-party) implements so the engine can resolve one adapter
(`ADAPTER_MODULE` → `get_adapter`) and call the socket, never spelling a runtime
name.

## Reality-anchor: what an adapter is today

- Base class: `molecule_runtime.adapter_base.BaseAdapter` (ABC).
- Config passed to every method: `molecule_runtime.adapter_base.AdapterConfig`
  (dataclass — fields: `model`, `system_prompt`, `tools`, `runtime_config`,
  `config_path` default `/configs`, `workspace_id`, `prompt_files`, `a2a_port`,
  `heartbeat`).
- Discovery: production sets `ADAPTER_MODULE` in the template's Dockerfile;
  `adapters.get_adapter()` imports it and returns its `Adapter` symbol
  (`Adapter = <YourAdapter>` at module bottom — the convention all four official
  templates follow).
- Official adapters live in `molecule-ai-workspace-template-<runtime>/adapter.py`.
  Third-party adapters ship wherever their author wants and set their own
  `ADAPTER_MODULE`.

## MUST vs MAY

- **MUST (critical socket):** methods the platform/engine depend on. An adapter
  that does not provide a working answer for these fails conformance. Some MUSTs
  are `@abstractmethod` (no working default — every adapter overrides). Others are
  MUST-SATISFY: the base ships a correct dispatch default today, but the *behavior*
  is mandatory and, per ADR-004, its per-runtime shape moves into the adapter.
- **MAY (extra):** capabilities an adapter can opt into. The engine reads them when
  present and falls back to a platform default when absent. **The engine never
  depends on a MAY method existing** (ADR-004 §1: "extra adapter methods are
  permitted but are *extra*, never depended on by the engine").

Every method's **kind** below is one of: `abstract-MUST` (base has no working
default), `dispatch-MUST` (base has a working per-runtime dispatch default that
ADR-004 relocates into the adapter; behavior mandatory), or `MAY`.

---

## 1. Identity

The runtime's self-description. Consumed by the registry, the config UI, skill
`runtime:` gating (`load_skills(current_runtime=...)`), and the plugin pipeline's
`self.name().replace("-", "_")` dispatch key.

### `name() -> str` — `abstract-MUST`
```python
@staticmethod
@abstractmethod
def name() -> str: ...
```
The runtime identifier, hyphenated form (e.g. `"claude-code"`, `"codex"`,
`"hermes"`, `"openclaw"`). **MUST match the `runtime` field in `config.yaml`.** It
is the key every seam normalizes (`mcp_render.normalize_runtime` →
`claude-code` → `claude_code`) before dispatch. Static (no `self`) because it is
read before an instance exists.

### `display_name() -> str` — `abstract-MUST`
```python
@staticmethod
@abstractmethod
def display_name() -> str: ...
```
Human-readable name for UI display (e.g. `"Hermes Agent (Nous Research)"`). Static.

### `description() -> str` — `abstract-MUST`
```python
@staticmethod
@abstractmethod
def description() -> str: ...
```
Short description of what this adapter provides. Static.

### `get_config_schema() -> dict` — `MAY`
```python
@staticmethod
def get_config_schema() -> dict:
    return {}
```
JSON-Schema fragment for the `runtime_config` fields this adapter supports; the
Config-tab UI renders the form from it. Base returns `{}` (no adapter-specific
settings). Override to declare fields (e.g. hermes declares `model`).

---

## 2. Lifecycle

Called by `main.py` on the boot path, in order: `setup()` → `create_executor()`.
Both receive the shared `AdapterConfig` instance; `_common_setup()` fills
`config.system_prompt` on it before `create_executor` reads it.

### `setup(config: AdapterConfig) -> None` — `abstract-MUST` (async)
```python
@abstractmethod
async def setup(self, config: AdapterConfig) -> None: ...
```
One-time setup: validate config, prepare internal state, drive the plugin pipeline.
Called after deps are installed but before `create_executor()`. **MUST raise
`RuntimeError` if setup fails** (missing deps, bad config, unreachable runtime
surface) — that is how a workspace is marked unhealthy rather than silently
forwarding to a dead runtime. Adapters typically call
`self.install_plugins_via_registry(config, plugins)` here (or the shared
`self._common_setup(config)` which drives it) so plugins/skills/MCP get wired.
The `PrivilegedPluginInstallError` raised by the privileged (management-MCP)
install path MUST propagate out of `setup()` — boot fails closed + loud, never a
capability-less concierge.

### `create_executor(config: AdapterConfig) -> AgentExecutor` — `abstract-MUST` (async)
```python
@abstractmethod
async def create_executor(self, config: AdapterConfig) -> AgentExecutor: ...
```
Create and return an `a2a.server.agent_execution.AgentExecutor` ready for A2A
integration; its `execute()` is called by the A2A server's
`DefaultRequestHandler`. The executor MUST consume `config.system_prompt` (the
single base-built prompt) rather than re-reading a prompt file itself. The adapter
SHOULD store the returned executor as `self._executor` so the base
`pre_stop_state()` can serialize its `_session_id`.

**Prompt-application MUST (behavioral).** It is not enough to *receive*
`config.system_prompt` — the executor MUST carry it INTO the model turn: the
assembled prompt reaches the LLM as the system instruction (hermes → a
`{"role":"system"}` message; codex → `params["developerInstructions"]`;
claude-code → the SDK `system_prompt=` param). An executor that builds the config
correctly but drops `config.system_prompt` before the turn violates this MUST —
that is the live hermes persona-drop class. **The sole exception is the persona
sibling channel (§4):** a runtime whose CLI reads a native identity file and never
consumes `config.system_prompt` (openclaw, whose executor takes only
`workspace_id` + `heartbeat`) MUST instead deliver the persona via
`materialize_persona` writing the runtime's native identity file (SOUL.md). So the
invariant is a **disjunction** — EITHER the executor surfaces `config.system_prompt`
into its model-turn payload, OR `materialize_persona` (§4) writes the canonical
persona into the native identity file — and exactly one channel carries the persona
per runtime. The §8 conformance suite asserts this disjunction offline (no live
model): it builds the executor with a sentinel prompt and checks the sentinel
appears in the payload the executor would send, or in the native file
`materialize_persona` wrote.

**Tool-trace MUST (behavioral).** The executor MUST emit one `agent_log`
tool-call activity row per tool invocation, via the shared engine primitive
`molecule_runtime.tool_trace.emit_tool_call(name, summary=None, status="ok")`,
which POSTs `{activity_type:"agent_log", source_id/target_id:WORKSPACE_ID,
summary, status, method:name}` to `{PLATFORM_URL}/workspaces/{WORKSPACE_ID}/activity`.
Core turns these rows into BOTH the live MyChat progress line AND the persistent
`ToolTraceChips` it reconstructs server-side (core#2636). An adapter whose executor
invokes tools but emits none of these rows leaves the canvas unable to render what
the agent is doing — the pre-ADR-004 state where only claude-code emitted. The emit
is best-effort (never raises, short timeout); losing the telemetry MUST NOT abort the
tool or the turn. The §8 conformance suite asserts this offline: it stubs
`emit_tool_call`, drives one tool through the executor, and requires at least one emit
whose `method` is the tool name.

---

## 3. The MCP-config seam (the load-bearing part)

This is the **plugin→runtime shape** ADR-004 relocates from the shared engine's
`_RUNTIME_SPECS` / `_RUNTIME_READERS` dispatch tables into the adapter. Four
render/read/probe/enumerate methods + the native-config path/format metadata below
form the seam the RCA#2970 online gate and the core#3082 degrade gate read through.

**The runtime-agnostic descriptor** every method here speaks is the SSOT entry
shape pinned by `../mcp/mcp-plugin-delivery.contract.json` (`entry_shape`):
`name -> {command, args?, env?}`. The plugin is the SSOT for the descriptor;
each renderer re-derives its native file from that one descriptor.

**Native-config path / format / server-map key** — an adapter MUST declare, for its
runtime, the three facts the registry captures (see
`official-runtimes.registry.json`): the **native path pattern** the runtime reads
MCP servers from, the **format** (`json` / `toml` / `yaml`), and the **server-map
location** (a top-level `key`, a nested `key_path`, or a TOML `table`). ADR-004
**made the adapter the SSOT** for these facts (its socket methods resolve them) and
the registry the first-party mirror; they no longer live in an engine dispatch
table (`_RUNTIME_SPECS` is deleted). The delivery contract's `runtimes` block
remains the SSOT for the MCP-server descriptor + gate tool.

### `mcp_settings_path(config: AdapterConfig) -> str` — `socket-MUST`
```python
def mcp_settings_path(self, config: "AdapterConfig") -> str:
    from molecule_runtime.mcp_render import default_json_settings_path
    return str(default_json_settings_path(config.config_path))
```
Absolute native MCP-config file THIS runtime reads its `mcpServers` from. The base
default (ADR-004: **name-agnostic**, no `self.name()` dispatch) returns the generic
JSON `.claude/settings.json` under `config.config_path`; each official adapter
**OVERRIDES** it to return its own native file (`~/.codex/config.toml` for codex,
`~/.openclaw/openclaw.json` for openclaw, `~/.hermes/config.yaml` for hermes,
`.claude/settings.json` for claude-code) — the official four all override.
**Return semantics:** always an absolute path; never a different runtime's file.
Codex/openclaw/hermes ignore `config.config_path` and resolve `$HOME` (or
`HERMES_HOME`) — the signature is uniform even when the arg is unused.

### `register_mcp_server_hook(config, name, spec) -> None` — `dispatch-MUST`
```python
def register_mcp_server_hook(
    self, config: "AdapterConfig", name: str, spec: dict
) -> None: ...
```
The MCP-wiring PORT — wire the server `name -> spec` into THIS runtime's native
config. Base enriches the spec via `inject_privileged_env(name, spec)` (no-op for
non-management names; idempotent; descriptor-wins) then writes the generic JSON
`mcpServers` map via `mcp_render.render_json_mcp_servers` (name-agnostic default,
ADR-004 — no `self.name()` dispatch). **Semantics the render MUST honor:**
- **Additive + idempotent** — merge `name` in, never evict other servers or
  hand-written config; re-rendering the same `name` changes nothing.
- **Write only the file this runtime reads** — the #3159 mis-attribution class
  (a codex concierge's MCP written to `.claude/settings.json`, a file it never
  reads) is exactly what this forbids.
- **Fail-loud on an unverified native format** — raise `NotImplementedError`
  rather than guessing; the privileged-plugin install path turns that into a loud
  boot failure. The fail-loud stub belongs to that adapter, not the shared engine.

An adapter **MAY** override this when its native write needs work the shared
renderer can't do — e.g. **codex** and **openclaw** override to merge resolved
platform env (`MOLECULE_CP_URL`, `MOLECULE_ADMIN_TOKEN`, …) as literals into the
spec's `env` before writing (the stdio child needs them to reach the controlplane),
and openclaw owns its renderer directly so the install works on runtime versions
that predate the openclaw renderer. An override MUST preserve the additive /
idempotent / write-only-own-file / fail-loud semantics above.

### `management_mcp_present(config: AdapterConfig) -> bool` — `socket-MUST`
```python
def management_mcp_present(self, config: "AdapterConfig") -> bool:
    from molecule_runtime.mcp_render import json_mcp_servers_has
    from molecule_runtime.platform_agent_identity import MANAGEMENT_MCP_NAME
    return json_mcp_servers_has(
        Path(self.mcp_settings_path(config)), MANAGEMENT_MCP_NAME
    )
```
The runtime-agnostic answer to the RCA#2970 online gate's "is the management
`molecule-platform` MCP wired?" question, judged against the file THIS runtime
actually reads. `main.py` registers it as the gate probe via
`platform_agent_identity.register_mcp_present_probe`. **Return semantics — boolean,
fail-CLOSED:** a missing / unreadable / malformed / structurally-unexpected native
config yields `False`, so a genuinely MCP-less concierge stays degraded at the
gate. `True` only when `MANAGEMENT_MCP_NAME` (`"molecule-platform"`) is actually
declared in the runtime's native server map. **MAY** be overridden in lockstep with
`register_mcp_server_hook` (openclaw does, for the same runtime-version reason).

### `enumerate_loaded_mcp_tools(config: AdapterConfig) -> list[str] | None` — `socket-MUST` (async)
```python
async def enumerate_loaded_mcp_tools(
    self, config: "AdapterConfig"
) -> "list[str] | None":
    from molecule_runtime.loaded_mcp_tools_probe import enumerate_from_specs_async
    from molecule_runtime.mcp_render import read_json_mcp_servers
    servers = read_json_mcp_servers(Path(self.mcp_settings_path(config)))
    return await enumerate_from_specs_async(servers)
```
The runtime#181 seam that replaces core's hardcoded per-runtime enumeration switch.
Each adapter answers **for its own runtime, however it knows best**. The base
default (ADR-004: **name-agnostic**) reads the declared servers from the generic
JSON native config (`read_json_mcp_servers` on `mcp_settings_path`) and hands the
resolved `{name: spec}` map to the shared boot-safe engine
`loaded_mcp_tools_probe.enumerate_from_specs_async`, which stdio-spawns each to run
the MCP handshake (`initialize → notifications/initialized → tools/list`),
normalizing every `tools[].name` to `mcp__<server>__<tool>`. The official four all
**override** to read their own native config (e.g. **hermes** its
`~/.hermes/config.yaml` `mcp_servers:` block) and feed the **same** shared probe
engine — so the boot-safety / tri-state guarantees hold identically.

**TRI-STATE return (identical to the `loaded_mcp_tools` producer contract — this is
load-bearing):**
- **`None`** — nothing could be observed: no servers declared, or every probe
  failed / stalled / was unreadable. The producer is left unset → the heartbeat
  **OMITS** `loaded_mcp_tools` → core's ~90s grace window applies (fail-closed /
  degrade). **NEVER a guessed list.**
- **`[]`** — a server genuinely connected and advertised **zero** tools (a real,
  observed "connected-but-toolless" signal, distinct from "never observed").
- **`[ids]`** — the deduped, sorted union of observed `mcp__<server>__<tool>` ids
  (e.g. `["mcp__molecule-platform__provision_workspace", ...]` — the id the core
  gate keys on).

**BOOT-SAFE + NEVER-RAISES:** the default and every override are internally bounded
by the enumeration deadline (per-read 10s, per-server 20s, overall 45s) and map
every failure to `None`. An override MUST preserve the tri-state + never-raise +
boot-safety guarantees (reuse `enumerate_from_specs_async`, which provides them).

---

## 4. Persona

The sibling of the MCP seam: where the MCP seam gives a runtime its *tools*, this
gives it its *identity*. Relocated from `persona_render._RUNTIME_PERSONA` by
ADR-004 the same way.

### `materialize_persona(config: AdapterConfig) -> Path | None` — `dispatch-MUST`
```python
def materialize_persona(self, config: "AdapterConfig") -> "Any": ...
```
Materialize the workspace's canonical persona into THIS runtime's native identity
file, so the model boots with its intended identity even on runtimes whose
gateway/CLI reads a native identity file and never consumes the base-assembled
`config.system_prompt`. The base default (ADR-004: **name-agnostic**, no
`self.name()` dispatch) reads the persona runtime-agnostically from
`config.prompt_files` via `persona_render.read_canonical_persona` (falling back to
`system-prompt.md`), then writes it to the default identity file
`<config_path>/system-prompt.md` via `persona_render.write_persona`. Each official
adapter **OVERRIDES** to write its own native identity file: claude-code →
`system-prompt.md`, openclaw → `SOUL.md` (and clears the `BOOTSTRAP.md` /
`AGENTS.md` placeholders), codex → `AGENTS.md`, hermes → `~/.hermes/SOUL.md`
(its Layer-1 Agent Identity).

**Return semantics — best-effort, three outcomes:**
- Returns the **path written** on success.
- Returns **`None` (no-op)** when no persona is delivered (empty/whitespace) — the
  runtime's baked default is left untouched, never clobbered with an empty
  identity.
- **Fail-loud → downgraded to a warning:** an unverified native convention raises
  `NotImplementedError` (an adapter whose native identity file is not yet pinned),
  which the base caller **catches and logs as a warning, returning `None`** — a
  persona is NOT a privileged capability like the management MCP, so a missing
  native convention MUST NOT brick the boot. (All four official adapters — including
  hermes, which writes `~/.hermes/SOUL.md` — implement it; the stub is only for a
  not-yet-migrated adapter.) (Contrast
  the MCP seam, where the privileged case fails closed.)

---

## 5. MAY methods (extra — engine never depends on these)

All default to a no-op / off / platform-fallback, so an adapter that ignores them
still links cleanly. The engine reads them when present and applies its own default
when absent (ADR-004 §1).

| Method | Default | What it does |
|---|---|---|
| `capabilities() -> RuntimeCapabilities` | all-False `RuntimeCapabilities()` | Declares native ownership of cross-cutting capabilities (heartbeat, scheduler, session [durability], **session-lifecycle** [enumerate/switch native sessions — `provides_native_session_lifecycle`, distinct from the durability flag], status-mgmt, retry, activity-decoration, channel-dispatch). Platform/canvas skips its fallback (or hides the session switcher) for a flag the adapter does not own. Observability (A2A, activity_logs, broadcaster) is NEVER skipped. claude-code / hermes override. |
| `idle_timeout_override() -> int \| None` | `None` (→ global default, ~5min) | Per-A2A-dispatch silence window in SECONDS for SDKs with long synth turns. hermes returns `900`. |
| `get_config_schema() -> dict` | `{}` | (Also listed under Identity.) `runtime_config` field schema for the UI. |
| `memory_filename() -> str` | `"CLAUDE.md"` | File under `/configs` the runtime treats as durable memory. |
| `register_tool_hook(name, fn) -> None` | no-op | Runtimes with a dynamic in-process tool registry override to register a tool; filesystem-scan runtimes need nothing. |
| `register_subagent_hook(name, spec) -> None` | no-op | Sub-agent-capable runtimes override to register a sub-agent. |
| `append_to_memory_hook(config, filename, content) -> None` | writes `/configs/<filename>` (or the mailbox memory dir when the kernel is on), idempotent by first-line marker | Append plugin-injected memory. |
| `transcript_lines(since, limit) -> dict` (async) | `{runtime, supported: False, lines: [], cursor: since, more: False, source: None}` | "Look over the agent's shoulder" live transcript. claude-code overrides (reads `~/.claude/projects/<cwd>/<session>.jsonl`). Return shape is fixed; `supported: False` is the honest default. |
| `pre_stop_state() -> dict` | captures `session_id` (from `self._executor._session_id`) + up to 200 transcript lines | Pause/resume serialization (scrubbed, written to `/configs/.agent_snapshot.json`). |
| `restore_state(snapshot) -> None` | stores `snapshot["session_id"]` / `["transcript_lines"]` on `self` | Pause/resume restore before the A2A server starts. |
| `session_current() -> dict` (async) | `{runtime, supported, session}` — `session` a `SessionRef` from `self._executor._session_id` (the stable workspace-keyed id) or `None` | The ACTIVE session turns route to. `supported` mirrors `capabilities().provides_native_session_lifecycle`; the current session is reported honestly regardless. |
| `session_list() -> dict` (async) | `{runtime, supported: False, sessions: [current], active_id}` | Read side of the session-lifecycle capability. Honest single-session default; adapters override to enumerate their native store (claude-code JSONL projects / hermes+openclaw `sessionFile` / codex sessions) with `supported: True`. |
| `session_start(label?) -> dict` (async) | `{runtime, supported: False, session: None, started: False}` | Write side — begin a NEW native session (explicit clean slate; the sanctioned opt-out of the stable-resume BUG-3 default). Phase-1 base is an honest no-op; the active-session pointer + `subprocess_executor` indirection that route to it are a follow-up phase, so this changes NO existing routing (additive). |
| `session_resume(id) -> dict` (async) | `{runtime, supported: False, session: None, resumed: False}` | Write side — switch the active session to an existing native one (`id` from `session_list`). Same phasing as `session_start`. |
| `event_log` (property) | shared `DisabledEventLog` no-op | Pluggable in-process event-log backend; `main.py` overrides at boot. |
| `install_plugins_via_registry(config, plugins) -> list` (async) | drives the per-runtime adaptor pipeline for every plugin | The shared plugin driver — adapters CALL it from `setup()`; not typically overridden. |
| `inject_plugins(config, plugins) -> None` (async) | delegates to `install_plugins_via_registry` | Legacy compatibility hook. |
| `_common_setup(config) -> SetupResult` (async) | loads plugins/skills/tools/coordinator, builds + publishes `config.system_prompt` | The shared setup pipeline; adapters call it (or replicate the prompt-publish, as hermes does). |

An adapter MAY add **entirely new** methods beyond this table. Per ADR-004 they are
*extra*: the engine will never call them, so they carry no conformance obligation
and no platform coupling.

---

## 6. What the shared engine keeps (no runtime name)

Per ADR-004 §3, the engine (`molecule_runtime`) now keeps ONLY generic,
runtime-name-free helpers, called by adapters:

- `loaded_mcp_tools_probe.enumerate_from_specs_async(specs)` — the boot-safe stdio
  MCP probe engine (tri-state, bounded, never-raises). Speaks the MCP wire protocol
  directly, not any SDK's tool-list message. (The name-keyed
  `enumerate_loaded_mcp_tools_async` is deleted — adapters resolve their own specs
  and call this.)
- `mcp_render.default_json_settings_path` / `render_json_mcp_servers` /
  `json_mcp_servers_has` / `read_json_mcp_servers` — the generic JSON `mcpServers`
  read/write/present helpers the BaseAdapter default and any JSON-config adapter reuse.
- `persona_render.read_canonical_persona` / `write_persona` / `default_persona_path`
  — the generic persona INPUT reader + byte-shape writer + default identity path.
- `privileged_mcp_env.inject_privileged_env(name, spec)` — enriches the management
  MCP spec (no-op otherwise).
- `mcp_render.normalize_runtime(runtime)` — the `-`→`_` canonicalization.

The per-runtime dispatch tables (`_RUNTIME_SPECS`, `_RUNTIME_READERS`,
`_RUNTIME_PERSONA`) **have been deleted** — their per-runtime shape moved into each
template's adapter. A red-on-regression **ratchet**
(`molecule-ai-workspace-runtime/tests/test_engine_no_runtime_dispatch_ratchet.py`)
fails any change that re-introduces a `_RUNTIME_*` table or a runtime-name literal
into the engine (the drift can only shrink; it is now 0).

---

## 7. Relationship to existing SDK contracts (extend, do not duplicate)

This contract **extends** the SDK contract set; it does not restate what other
contracts already own.

- **`../mcp/mcp-plugin-delivery.contract.json`** already pins the descriptor
  `entry_shape` (`name->{command,args?,env?}`), the `mcp_server_name`
  (`molecule-platform`), the singular `required_tool` (`provision_workspace`, const,
  **never renamed**), the `loaded_mcp_tools_field`, the wiring `port`, and a
  per-runtime `runtimes` block (path / format / key|key_path|table / renderer /
  status). **This socket contract references those values rather than re-declaring
  them.** The companion `official-runtimes.registry.json` is reconciled with — and
  is the adapter-facing view of — that `runtimes` block (same four runtimes, same
  paths/formats/keys); when the delivery contract's `runtimes` block changes, the
  registry moves with it. The delivery contract remains the SSOT for the MCP-server
  *descriptor + gate tool*; this contract is the SSOT for the *adapter methods* that
  render/read it.
- **`../workspace-comms/registry-contract.md`** owns the workspace↔platform **wire**
  (register/heartbeat/discover/…), including where `mcp_server_present` /
  `loaded_mcp_tools` sit on the heartbeat payload and their nullable tri-state. This
  contract owns how the adapter **produces** those two values (the present-probe and
  the enumerate tri-state above); it does not restate the wire shape.
- **`runtime-id.schema.json`** owns the open RuntimeId shape. The registry here is
  the curated **official** set (the four natively-supported runtimes); third-party
  adapters implement the same socket without being listed.

## 8. Conformance (staged per ADR-004)

ADR-004 §4 ships a conformance suite FROM the SDK that, given any adapter, asserts
it satisfies this socket: identity present; `setup`/`create_executor` implemented;
the MCP seam renders → reads → present-probes in **lockstep** (round-trips its own
native config) and enumerates `loaded_mcp_tools` including the required management
tool; persona materializes into the declared native file; **prompt application —
the assembled `config.system_prompt` reaches the model turn** (the §2
`create_executor` MUST): the suite builds the executor with a sentinel prompt and
asserts the disjunction that EITHER the executor surfaces the sentinel into its
model-turn payload OR `materialize_persona` (§4) wrote it into the native identity
file (no live model — closes the hermes persona-drop gap); and tool-trace — the
executor emits an `agent_log` tool-call row (via
`molecule_runtime.tool_trace.emit_tool_call`) for each tool it invokes (stubbed +
driven offline; an adapter that runs a tool but emits nothing fails); and every seam
**fails closed** when the runtime is unmapped/unverified. An adapter that does not conform
fails **its own** CI; first-party support is proven by running the suite across the
`official-runtimes.registry.json` set. Enforcement is staged P1→P4 (see ADR-004
guardrail matrix); until then this document is descriptive and the engine dispatch
tables remain, guarded by the add-only ratchet.
