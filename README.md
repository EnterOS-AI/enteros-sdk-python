# molecule-ai-sdk

The **Molecule AI SDK and contract SSOT**. One repo, three things:

1. **Two Python packages** (published together under the distribution name `molecule-ai-sdk` in Molecule's private Gitea package registry — **not** on public PyPI):
   - **`molecule_external_workspace`** — write an agent that runs *outside* the
     platform's Docker network and joins a Molecule AI org from another machine.
     It registers with the platform, pulls secrets, sends heartbeats, discovers
     peers (A2A), delegates, and detects pause/delete. Public API:
     `RemoteAgentClient`, `A2AServer`.
   - **`molecule_plugin`** — build installable **plugin** directories (rules,
     skills in agentskills.io format, per-runtime install adaptors) + validators
     and a `python -m molecule_plugin` CLI. (See [Plugin authoring](#plugin-authoring--molecule_plugin).)

2. **`contracts/` — the platform contract SSOT.** The JSON-Schema (draft 2020-12)
   IDL for every cross-boundary contract in the platform, plus the cloud-provider
   YAML SSOT. This is the former `molecule-contracts` repo, folded in and archived
   here 2026-07-01. See [Contracts](#contracts--the-ssot).

3. **`gen/` — generated bindings.** Go / TypeScript / Python types + constants
   emitted from `contracts/` by `tools/gen-*.mjs`. Consumed by `molecule-core`
   and `molecule-controlplane` (Go, via `go.moleculesai.app/sdk/gen/go/...`),
   the storefront (TS), and the runtime (Python). **Never hand-edited** — a
   fresh regen must match what's committed (enforced by CI).

```
molecule-ai-sdk/
├── molecule_external_workspace/   # remote-agent client (RemoteAgentClient / A2AServer)
├── molecule_plugin/               # plugin-authoring SDK + validators + CLI
├── contracts/                     # JSON-Schema IDL SSOT + cloudproviders.yaml
│   ├── mcp/  plugin-manifest/  workspace-template/  org-template/
│   ├── catalog/                   # catalog-entry + marketplace-service (catalog/publish/install/entitlement)
│   ├── provision-request/  promote-request/  workspace-comms/
│   └── cloudproviders.yaml + cloudproviders.schema.json
├── gen/{go,ts,python}/            # generated bindings (DO NOT EDIT)
├── tools/gen-{go,ts,python}.mjs   # the generators (Node — no Go/Py toolchain in CI)
├── template/                      # starter plugin scaffold
└── tests/
```

## Install

```bash
pip install \
  --index-url "https://git.moleculesai.app/api/packages/molecule-ai/pypi/simple" \
  molecule-ai-sdk==0.3.0
```

Use `--index-url` (the private registry as the **sole** index), not
`--extra-index-url` — for a first-party private package, an extra index invites
dependency-confusion (pip may resolve the name from public PyPI instead). If your
environment also needs public dependencies, configure the private registry to
proxy PyPI, or resolve public deps from a separately-scoped index. Authenticate
via `~/.netrc` (or `pip`'s keyring) — do **not** inline credentials in the URL.

Go consumers import the generated bindings via the vanity path (no PyPI needed):

```go
import molcontracts "go.moleculesai.app/sdk/gen/go/molcontracts"
```

## Contracts — the SSOT

Every contract is a **pair** under its `contracts/<domain>/` directory:

- **`*.schema.json`** — the rules (JSON-Schema draft 2020-12): fields, types,
  `required`, `enum`, `const` pins, `pattern`s. The enforceable definition.
- **`*.contract.json`** — one canonical **instance** that MUST validate against
  its sibling schema. It's the worked example, the CI anchor, and — for
  value-bearing contracts like `mcp-plugin-delivery` — the SSOT for the concrete
  values baked into `gen/`.

Direction: `*.contract.json ──validate──▶ *.schema.json`, and
`contracts/ ──codegen (tools/gen-*.mjs)──▶ gen/{go,ts,python}`. Each domain
directory under [`contracts/`](./contracts) carries its own `README.md`
describing that surface.

Four CI gates back this (`.gitea/workflows/contracts-codegen-drift.yml`):
`validate` (every instance validates against its schema), `codegen-drift`
(committed `gen/` equals a fresh regen), `contract-conformance` (cloudproviders
semantics), and `go-parity` (`gen/go` builds + vets + tests). Regenerate locally
after any contract edit and commit the result:

```bash
node tools/gen-go.mjs && node tools/gen-ts.mjs && node tools/gen-python.mjs
```

## Remote agents — `molecule_external_workspace`

```python
from molecule_external_workspace import RemoteAgentClient

client = RemoteAgentClient(
    platform_url="https://<org>.moleculesai.app",
    workspace_id="my-agent",
    # the auth token is minted on first register() and persisted client-side
)
```

The client wraps the workspace↔platform HTTP contract (register, pull secrets,
heartbeat, state-poll, A2A peer discovery, delegation, plugin install) — the same
surface captured in `contracts/workspace-comms/`. `A2AServer` is the receive side
for agent-to-agent messages.

## Plugin authoring — `molecule_plugin`

A Molecule AI plugin is a directory that bundles rules, skills, and per-runtime
install adaptors. Any plugin that conforms to the contract is installable on any
Molecule AI workspace whose runtime the plugin supports.

### Quick start

Copy the repo's `template/` directory to a new directory and edit it. If you
installed from the package registry (no repo checkout), fetch the scaffold from
`https://git.moleculesai.app/molecule-ai/molecule-ai-sdk/src/branch/main/template`.

```
my-plugin/
├── plugin.yaml              # name, version, runtimes, description
├── rules/my-rule.md         # optional — appended to CLAUDE.md at install
├── skills/my-skill/
│   ├── SKILL.md             # instructions injected into the system prompt
│   └── tools/do_thing.py    # optional LangChain @tool functions
└── adapters/
    ├── claude_code.py       # one-liner: `from molecule_plugin import AgentskillsAdaptor as Adaptor`
    └── codex.py             # same
```

Validate:

```python
from molecule_plugin import validate_manifest
errors = validate_manifest("my-plugin/plugin.yaml")
assert not errors, errors
```

### CLI

```bash
python -m molecule_plugin validate plugin    my-plugin/
python -m molecule_plugin validate workspace workspace-configs-templates/claude-code-default/
python -m molecule_plugin validate org       org-templates/molecule-dev/
python -m molecule_plugin validate channel   channels.yaml
python -m molecule_plugin validate my-plugin/   # kind defaults to 'plugin'
```

Exit code is 0 when valid, 1 when any errors are found — suitable for CI.
Add `-q` / `--quiet` to suppress success lines and emit only errors.

Programmatic equivalents:

```python
from molecule_plugin import (
    validate_plugin,
    validate_workspace_template,
    validate_org_template,
    validate_channel_file,
    validate_channel_config,
)
```

### Per-runtime adaptors — when to write a custom one

The default `AgentskillsAdaptor` handles the common shape: rules go into the
runtime's memory file (CLAUDE.md), skill dirs go into `/configs/skills/`. That
covers most plugins.

Write a custom adaptor when you need to:

- **Register runtime tools dynamically** — call `ctx.register_tool(name, fn)`.
- **Register runtime sub-agents** — call `ctx.register_subagent(name, spec)`.
- **Write to a non-standard memory file** — call `ctx.append_to_memory(filename, content)`.

Minimum custom adaptor:

```python
# adapters/codex.py
from molecule_plugin import InstallContext, InstallResult

class Adaptor:
    def __init__(self, plugin_name: str, runtime: str):
        self.plugin_name, self.runtime = plugin_name, runtime

    async def install(self, ctx: InstallContext) -> InstallResult:
        ctx.register_subagent("my-agent", {"prompt": "...", "tools": [...]})
        return InstallResult(plugin_name=self.plugin_name, runtime=self.runtime, source="plugin")

    async def uninstall(self, ctx: InstallContext) -> None:
        pass
```

### Resolution order (understood by the platform)

For `(plugin_name, runtime)`:

1. **Platform registry** — `workspace-template/plugins_registry/<plugin>/<runtime>.py`
   (curated; set by the Molecule AI team for quality-assured plugins).
2. **Plugin-shipped** — `<plugin_root>/adapters/<runtime>.py` (what this SDK helps you build).
3. **Raw-drop fallback** — copies plugin files into `/configs/plugins/<name>/`
   and surfaces a warning; no tools are wired.

You generally ship for path #2. If your plugin becomes popular enough to be
promoted to "default," the Molecule AI team PRs a copy of your adaptor into the
platform registry (path #1) so it survives upstream breakage.

### Supported runtimes

The canonical runtime list is the SSOT enum in
`contracts/plugin-manifest/plugin-manifest.schema.json`: `claude-code`, `codex`,
`hermes`, `openclaw`, `langgraph`, `autogen`, `crewai`, `deepagents`,
`gemini-cli`, `google-adk`, `external` (underscore aliases like `claude_code`
are accepted). See the live list with `curl $PLATFORM_URL/plugins`.

## Build and test

```bash
pip install -e '.[test]'   # base packages + pytest-asyncio
pytest -q
```
