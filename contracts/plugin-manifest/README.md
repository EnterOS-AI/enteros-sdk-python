# plugin-manifest contract

Marketplace **plugin manifest** contract — the publishable shape of a `plugin.yaml`
(`molecule-ai-plugin-*` repos). IDL is **JSON-Schema (draft 2020-12)** per RFC
[molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285).
One `*.schema.json` (the shape) + one `*.contract.json` (the canonical instance the
schema validates).

| File | Role |
| --- | --- |
| `plugin-manifest.schema.json` | JSON-Schema (2020-12) describing the manifest shape |
| `plugin-manifest.contract.json` | A canonical instance (the privileged `molecule-platform` management-MCP plugin) |

## Derived from

The real artifacts and their CI validator:

- `molecule-ai-plugin-molecule-careful-bash/plugin.yaml` + `.molecule-ci/scripts/validate-plugin.py`
  (required `name`/`version`/`description`; `runtimes` must be a list; content = one of
  `SKILL.md`/`hooks`/`skills`/`rules`).
- `image-gen/plugin.yaml` (the `privileged` documentation — image-gen is explicitly **not** privileged),
  `gh-identity/plugin.yaml` and `molecule-hitl/plugin.yaml` (the `kind`/`entrypoint` and the
  `deepagents`/`langgraph`/`autogen` runtimes real plugins already declare).

## Design (VS-Code-shaped)

- **`engines`** — `{ molecule: "^x" }`, the minimum host version (like `engines.vscode`).
- **`contributes`** — an OPEN object (`additionalProperties: true`). Its KNOWN keys
  (`skills`/`hooks`/`rules`/`mcpServers`/`commands`, v1) are validated by shape; UNKNOWN
  contribution points (future `themes`/`tabs`/`canvasElements`) are **tolerated** so a newer
  plugin never fails validation on an additive contribution point. The top-level
  `skills`/`hooks`/`rules` string lists are the v0 shorthand the real `plugin.yaml` files use.
- **Canonical `runtimes` enum** — the SSOT reconciliation of the cross-artifact runtime
  drift. The **hyphen** form is canonical (`claude-code`, matching the templates); the legacy
  plugin **underscore** spellings (`claude_code`, `gemini_cli`) are accepted aliases that
  normalise to the hyphen form. The enum INCLUDES every runtime in use —
  `claude-code`, `codex`, `hermes`, `openclaw`, `langgraph`, `autogen`, `crewai`, `deepagents`,
  `gemini-cli`, `google-adk`, `external` — including `deepagents`/`langgraph`/`autogen`.
