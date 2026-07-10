# repo-meta contract

The **SSOT keystone** for org CI-enforcement (RFC: org CI-enforcement, **P1 keystone**).
`repo-meta.yaml` is the per-repository manifest that declares **what a repo is** and
**what it can do**; the meta-CI router reads it to decide which CI capability-bundles to
attach, and org-enforcement reads it to decide what a repo of a given layer is *required*
to carry. IDL is **JSON-Schema (draft 2020-12)**, mirroring the other SDK contracts.

> **Inert until consumed.** This contract only *defines* the manifest shape. It attaches
> no CI on its own — it is the schema the later meta-CI router + org-enforcement pieces
> read. Landing it first (schema-before-router) is the point of a keystone.

| File | Role |
| --- | --- |
| `repo-meta.schema.json` | JSON-Schema (2020-12) describing the `repo-meta.yaml` shape |
| `repo-meta.contract.json` | A canonical instance (a runtime-template repo: adapter + mcp-server-bake) |

## Purpose — SSOT for CI capability-attach

Before this contract there is no single place that says *"this repo is a Go service, so it
gets the go-service CI bundle"* or *"this repo is a runtime-template, so it must carry an
adapter-conformance check"*. That knowledge is scattered across per-repo workflow YAML,
each drifting on its own. `repo-meta.yaml` makes it **one declared fact per repo**, and the
meta-CI router derives the attached bundles from it. The manifest answers two questions:

- **`layer`** — *what kind of repo is this?* (the primary routing axis)
- **`capabilities`** — *what can it do?* (the set of CI bundles to attach)

## `layer` semantics (required, exactly one)

`layer` is a closed enum — the repo-kind axis org-enforcement scopes its required-bundle
rules by:

| `layer` | What it is |
| --- | --- |
| `service` | A deployable backend service repo (controlplane, core). Has **neither** `plugin.yaml` **nor** `config.yaml`. |
| `runtime-template` | A workspace runtime-template repo (`molecule-ai-workspace-template-*`) — carries an adapter, often an MCP bake. |
| `plugin` | A marketplace plugin repo (`molecule-ai-plugin-*`). |
| `org-template` | An org-template repo (`molecule-ai-org-template-*`). |
| `contract` | A contract / SSOT repo (this one; molecule-contracts-shaped). |

## `capabilities` semantics (open set, may be empty)

`capabilities` is the set of CI capability-bundles the router should attach. It **may be
empty** (a repo that opts into no bundles). The **KNOWN** vocabulary — each attaching a
specific bundle in the router — is:

| capability | Bundle it attaches |
| --- | --- |
| `go-service` | Go build / vet / test |
| `python-package` | ruff + pytest + build |
| `adapter` | SDK adapter-conformance |
| `mcp-server-bake` | MCP server image-bake + npm-resolution |
| `skills` | agentskills.io skill-lint |
| `settings-fragment` | settings/config fragment validation |
| `env-mutator` | Go env-mutator plugin-class checks |
| `docker-image` | image build + publish |

The list is **OPEN** for forward-compat: an unknown capability is **not** schema-rejected,
so a new bundle can be declared in a repo before this schema learns its name. But an unknown
capability **attaches no CI bundle** (the router no-ops on it) and the **validator warns**
(does not error) on it. To keep typos on KNOWN capabilities from masquerading as novel
capabilities, every capability MUST match a **kebab-case pattern** (`^(x-)?[a-z0-9]+(-[a-z0-9]+)*$`),
optionally `x-`-prefixed for an experimental bundle (`x-fuzz`). So `go_service`, `GoService`,
or a trailing-space `go-servcie ` fail the pattern outright; a clean-but-unknown `go-servcie`
passes the schema but is surfaced by the validator's warn-list (it is not in the KNOWN set).

## `waivers` — the time-boxed escape hatch (optional)

Each waiver is `{bundle, until, reason}`: suppress a named CI bundle **until** a date, and
the `reason` **must name a tracking issue**. Time-boxing is the whole point — a waiver
without an expiry is a permanent silent skip, which this contract forbids (`until` is
required and date-typed). On or after `until` the waiver is dead and the bundle re-attaches.

## Why a NEW file, not an extension of `plugin.yaml` / `config.yaml`

`plugin.yaml` (plugin-manifest) and `config.yaml` (workspace-template) are **tolerant
marketplace-artifact manifests** — `additionalProperties: true`, capturing heterogeneous
*published artifacts* — and they only exist in plugin / template repos. A **service** repo
(controlplane, core) has neither. CI-enforcement must cover **every** repo, including plain
services, so its manifest cannot live inside an artifact file that only some repos have.
`repo-meta.yaml` is therefore a first-class, universal file.

## Why STRICT (`additionalProperties: false`), unlike the marketplace contracts

The marketplace contracts are tolerant *by design* — they capture artifacts authored
elsewhere, and must never red on an additive field a newer artifact carries. `repo-meta` is
the opposite: it is a **routing** manifest **authored** for CI, and it is **strict**
(`additionalProperties: false` at the top level and inside each waiver). A mis-spelled
top-level key must be a **hard error** at manifest validation, not a silently-ignored field —
a routing manifest that swallows an unknown key would silently mis-route CI. The single
place we *are* permissive is the capability **value** vocabulary (open + pattern-guarded),
for the forward-compat reason above — and even there, the pattern catches the common typos.

## `molecule-ci` vendors this schema (kept honest by schema-sync)

`molecule-ci` carries a **vendored copy** of `repo-meta.schema.json` so the router can
validate `repo-meta.yaml` without a cross-repo fetch at CI time. This SSOT copy is
authoritative; the vendored copy is kept byte-honest by a **schema-sync** check (the vendor
must equal this file), exactly as the vendored delivery contracts mirror SDK main rather
than lead it.

## Validator

`molecule_plugin/validate_repo_meta.py` (exposed as `python -m molecule_plugin validate
repo-meta <dir>`) schema-validates a `repo-meta.yaml`, checks the `layer` enum, and **warns**
(does not error) on any capability outside the KNOWN vocabulary. Warnings are returned
distinctly from errors so CI can treat them as non-fatal. See `tests/test_repo_meta_contract.py`.

## Examples

### A runtime-template repo (adapter + mcp-server-bake) — the canonical instance

```yaml
schema_version: 1
layer: runtime-template
capabilities:
  - adapter
  - mcp-server-bake
  - docker-image
waivers:
  - bundle: mcp-server-bake
    until: 2026-09-01
    reason: "blocked on molecule-core#1234 — bake infra flake; re-enable once the runner image lands"
```

### A plugin repo

```yaml
schema_version: 1
layer: plugin
capabilities:
  - skills
  - env-mutator
```

### A Go service repo (no plugin.yaml, no config.yaml)

```yaml
schema_version: 1
layer: service
capabilities:
  - go-service
  - docker-image
```
