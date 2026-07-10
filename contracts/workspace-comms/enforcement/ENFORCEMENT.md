# Workspace-Comms wire contract — ENFORCEMENT

> Scope of this doc: how the workspace↔platform **register + heartbeat** wire
> contract is made *enforceable*, and specifically how the `kind=platform`
> fail-closed identity gate (RCA #2970 / core#3082 — `registry-contract.md`
> divergence #5) is closed from a **vacuous** check into a real one. This is the
> paired enforcement record for `../registry-contract.md` (the descriptive prose)
> and the `../register.schema.json` / `../heartbeat.schema.json` wire schemas.

## 0. What already ships (reconciling the stale "enforcement deferred" claim)

`registry-contract.md`'s **Status** header (L3) and **Enforcement (deferred)**
section (L63–79) are **stale**. They predate the enforcement that was built on
top of them and still point at the *retired* AST drift-checker. The real state:

| Leg | Artifact | Status |
| --- | --- | --- |
| Wire schema (SSOT) | `../register.schema.json`, `../heartbeat.schema.json` — derived byte-for-byte from the Go binding tags in `molecule-core workspace-server/internal/models/workspace.go` | **SHIPPED** |
| Generated typed models | `gen/{python,ts,go}/workspace_comms_gen.*` (TypedDicts / interfaces / structs) via `tools/lib/comms-schema.mjs` | **SHIPPED, committed** |
| Validate + codegen-drift gate | `.gitea/workflows/contracts-codegen-drift.yml` — all-required: `validate` (every `contracts/*/*.contract.json` vs its schema) + `codegen-drift` (gen/ == fresh regen) + `go-parity` | **SHIPPED, all-required** |
| Real-wire conformance (SDK) | `tests/test_workspace_comms_conformance.py` — captures the bytes `RemoteAgentClient` actually puts on the wire, validates vs the SSOT schema | **SHIPPED** |
| Real-wire conformance (runtime) | `molecule-ai-workspace-runtime/tests/test_workspace_comms_conformance.py` — drives the real `HeartbeatLoop` + register vs the same vendored schema | **SHIPPED** |
| Vendored-schema byte-sync | runtime `scripts/check-schemas-in-sync.sh` + `schema-sync.yml` / `consumer-drift.yml` | **SHIPPED** |
| ~~AST drift-checker~~ | ~~`molecule-ai-workspace-runtime/scripts/check_platform_comm_contract.py`~~ | **RETIRED / deleted** (see `consumer-drift.yml` L96–104) |

So the naive "author enforcement for the wire contract" job is **already done**.
`registry-contract.md` should be reconciled — see §4 — but that is a doc edit, not
new machinery.

## 1. The one real residual gap: the fail-closed gate is vacuous on the wire

The base wire schemas correctly type `mcp_server_present` and `loaded_mcp_tools`
as **optional** — because the Go tags are `,omitempty`/pointer and **non-platform
workspaces legitimately omit them**. Consequence: a `kind=platform` payload that
omits both fields still **validates** against the base schema, so the SDK/runtime
conformance gates prove only that a body *is well-formed* — they cannot prove the
highest-stakes path (a concierge being marked **online**) actually carries the
identity proof the controlplane gate requires. That is exactly the bypass RCA
#2970 / core#3082 exist to catch, and it is invisible to an unconditional-optional
schema. `register.schema.json` cannot express *required-WHEN-kind==platform-AND-
claiming-online* — draft-2020-12 can, but only as a **conditional**.

## 2. What this profile adds — and why it is NOT a second wire schema

`platform-identity-gate.schema.json` (this directory) is an **enforcement
profile**, not a wire-message schema. It does not restate the wire shape (the base
schemas remain the wire-validity SSOT). It encodes the **Go gate decision table**
as draft-2020-12 conditionals so a conformance test can answer *"would the
controlplane mark this concierge online / degraded / failed?"* — machine-checked
against the SAME literals the Go gate matches.

It is keyed on a `verdict` discriminator (`online` / `degraded` / `failed` /
`not_platform`) so ONE file expresses all four branches, each mirrored from a
specific Go site:

- **`not_platform`** — payload is not `kind=platform`; the gate does not apply,
  omitting the tri-states is *correct*. (This is the legitimate case the base
  optionality is FOR — asserted positively so a test can't conflate "optional" with
  "never required".)
- **`failed`** — `kind=platform` **and** `mcp_server_present === false`. This is the
  ONLY tri-state value that fails closed: `nil` is **allow** (legacy pre-#147
  runtime — `platformAgentMCPServerPresent`, `registry.go`) and `true` is allow.
  The profile therefore requires the literal `false`, **not** a blanket
  "require mcp_server_present=true". (Over-constraining to const-true would wrongly
  reject the legitimate legacy-nil concierge — the exact rollout hazard the Go
  comment at `registry.go` `platformAgentMCPServerPresent` warns about.)
- **`degraded`** — `kind=platform`, `mcp_server_present === true`, but
  `loaded_mcp_tools` does **not** contain `mcp__molecule-platform__provision_workspace`
  (omitted pre-first-turn, or present-without-it). Held in `provisioning`/`degraded`,
  **not** `failed` — the **OMITTED ≠ `[]`** distinction is load-bearing and
  legitimate here (turn-dependent; `registry.go` verified-ready loop). This is why
  the naive "if kind==platform then require loaded_mcp_tools contains X" is **wrong**:
  it would fail a just-booted concierge the Go gate deliberately only holds.
- **`online`** — the full verified-ready proof: `kind=platform`,
  `mcp_server_present === true`, and `loaded_mcp_tools` **contains** the required
  tool. Reachable ONLY on a **heartbeat** (the register struct has no
  `loaded_mcp_tools` field), so the profile requires `kind: heartbeat`. **This is
  the anti-vacuous positive assertion the base schema cannot express.**

The required tool id `mcp__molecule-platform__provision_workspace` is pinned as a
`const` composed from the cross-repo `../../mcp/mcp-plugin-delivery.contract.json`
literals (`mcp_server_name=molecule-platform`, `required_tool=provision_workspace`)
— the SAME SSOT `molecule-core`'s `conciergePlatformMCPProvisionWorkspaceTool` and
the runtime's `platform_agent_identity.MANAGEMENT_PROVISION_TOOL_ID` derive from, so
a rename reds this schema *and* the mcp-delivery drift gate together.

### Why it lives in `enforcement/` (a subdirectory)

The wire-model generator (`tools/lib/comms-schema.mjs`) globs
`workspace-comms/*.schema.json` **non-recursively** and turns every top-level schema
into a committed typed model (`gen/*/workspace_comms_gen.*`). This profile is a
**validation oracle**, not a wire type — emitting a `PlatformIdentityGate` struct
would be meaningless and would force a `gen/` regen. Placing it one level down in
`enforcement/` keeps it OUT of both the codegen glob AND the two-level `validate`
glob (`contracts/*/*.contract.json`), so adopting this file changes **no generated
output** and reds no existing gate. Its own enforcement is the dedicated conformance
test in §3.4, which every impl runs.

## 3. How each of the 3 impls conforms

Three independent implementations of one protocol (different HTTP libraries, no
shared base code — `registry-contract.md` L14–20). Conformance is proven per-impl by
capturing the **real produced bytes** and validating them, never by static code
shape.

### 3.1 Producer (SSOT) — `molecule-core`
The Go structs + gate handlers ARE the wire authority; the schemas are derived from
them. No conformance test is added here — instead the `const` literals in this
profile are byte-pinned to `molecule-core`'s
`conciergePlatformMCPProvisionWorkspaceTool` via the existing
`mcp_plugin_delivery_contract_test.go` (which already asserts
`required_tool==provision_workspace` and the composed `mcp__<server>__<tool>` id
against the shared mcp-delivery contract). Drift on the core side reds that test.

### 3.2 Consumer A (in-platform) — `molecule-ai-workspace-runtime`
This is the **sole** impl that produces the tri-states
(`molecule_runtime/platform_agent_identity.py`:
`identity_gate_payload()` → `mcp_server_present` always present + `loaded_mcp_tools`
only once a live turn/probe has observed it; `mcp_readiness_probe.py` makes it
turn-independent). It is already the CORRECT producer: it sets `mcp_server_present`
unconditionally and OMITS `loaded_mcp_tools` until proven — matching the
`degraded`→`online` progression this profile encodes.
**Conformance step (extension of the existing runtime conformance test):** drive
`identity_gate_payload()` on a simulated platform concierge and assert the merged
register/heartbeat body evaluates to the expected `verdict` under this profile:
- fresh concierge (no turn yet) → the heartbeat body is `degraded` (mcp present,
  no loaded tool) ✔ and MUST NOT validate as `online`;
- after `set_loaded_mcp_tools([...provision_workspace...])` → the body is `online` ✔.

### 3.3 Consumer B (off-platform) — `molecule-ai-sdk` `molecule_external_workspace`
`client.py` `register()`/`heartbeat()` never set either tri-state (they build a
plain-workspace body). **This is correct and must stay so** — the public
`/registry/register` path **403s `kind=platform`** (`registry.go` L914: "kind=
'platform' may only be assigned by the platform-agent install path"), so an external
SDK agent is *never* a platform concierge and MUST NOT send the tri-states. The SDK
is therefore a **producer of `not_platform` payloads only**.
**Conformance step (extension of the existing SDK conformance test
`tests/test_workspace_comms_conformance.py`):** assert the captured
`client.register()` / heartbeat body evaluates to `not_platform` under this profile
(kind absent, tri-states absent) — i.e. positively prove the SDK does not
accidentally emit a platform-branch body. **Do not** wire the SDK client to send the
tri-states.
> **CLAUDE.md Known-issues rule:** if a future change makes the SDK ever emit
> `kind=platform` (e.g. an in-network SDK path), **file a Gitea issue first** before
> changing `client.py` — silent SDK behavior changes break consumers.

### 3.4 The gate that ties it together (the ONE new artifact to add per repo)
Add `test_platform_identity_gate_conformance.py` to BOTH `molecule-ai-sdk/tests/`
and `molecule-ai-workspace-runtime/tests/` (each against its vendored byte-copy of
this profile). It:
1. loads `platform-identity-gate.cases.json`, strips the `$case` label, and asserts
   every `pass` element validates and every `fail` element does not (proves the
   profile itself is non-vacuous — this repo's copy already passes: 7 pass / 7 fail,
   validated 2026-07-09);
2. feeds each impl's **real captured** register/heartbeat body (from 3.2 / 3.3) into
   the profile and asserts the expected `verdict`.

This is the same capture-real-bytes discipline as the existing conformance tests —
an **extension** of them, not a new gate. No generator change, no new required CI
job (it runs under the existing `test` job in each repo); optionally add the profile
to a `validate`-style step that globs `enforcement/*.schema.json` if a standalone
required gate is wanted later.

## 4. Reconcile the stale descriptive doc (`../registry-contract.md`)

Doc-only edits (no machinery):
- **L3 Status header** — change `DESCRIPTIVE (enforcement deferred)` to note that
  the wire schemas + codegen + dual real-wire conformance gates are **SHIPPED**
  (§0), and that the AST drift-checker is **retired**.
- **L63–79 Enforcement (deferred)** — replace with the shipped reality (the table in
  §0), and point at this doc for the platform-identity fail-closed profile.
- **Divergence #5 (L57)** — annotate: the conditional-requiredness gap is now closed
  by `enforcement/platform-identity-gate.schema.json` (this profile) + the §3.4
  conformance test; the base schemas stay legitimately optional for the wire.
