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
  runtimes real plugins declare).
- `molecule-ai-workspace-runtime/molecule_runtime/plugin_daemons.py` (runtime#216) — the
  parser/supervisor whose accepted entry shape `contributes.daemons` mirrors verbatim
  (`{name, command, args?, env?, cwd?}`; malformed entries are SKIPPED with a warning,
  never a boot failure) — and `lark-channel-molecule/plugin.yaml`, the first real
  daemon-declaring plugin (`{name: lark-bridge, command: bash, args: [daemon-bootstrap.sh]}`).

## Design (VS-Code-shaped)

- **`engines`** — `{ molecule: "^x" }`, the minimum host version (like `engines.vscode`).
- **`contributes`** — an OPEN object (`additionalProperties: true`). Its KNOWN keys
  (`skills`/`hooks`/`rules`/`mcpServers`/`commands` v1; `daemons`, runtime#216) are validated
  by shape; UNKNOWN contribution points (future `themes`/`tabs`/`canvasElements`) are
  **tolerated** so a newer plugin never fails validation on an additive contribution point.
  The top-level `skills`/`hooks`/`rules` string lists are the v0 shorthand the real
  `plugin.yaml` files use.
- **`contributes.daemons`** — long-running plugin daemons the workspace runtime spawns at
  boot, restarts with backoff, and kills with the workspace (e.g. a channel bridge). The
  entry shape deliberately mirrors `mcpServerContribution` (`name` + `command`/`args?`/`env?`,
  plus plugin-dir-relative `cwd?`); requiredness mirrors the runtime's `_entry_problem`
  checks. Captured DESCRIPTIVELY from `plugin_daemons.py` — the runtime's validation is
  skip-not-reject, so a malformed entry never fails a plugin install; this schema pins the
  well-formed shape.
- **Canonical `runtimes` enum** — the SSOT reconciliation of the cross-artifact runtime
  drift. The **hyphen** form is canonical (`claude-code`, matching the templates); the legacy
  plugin **underscore** spelling (`claude_code`) is an accepted alias that
  normalises to the hyphen form. The enum is the supported runtime set —
  `claude-code`, `codex`, `hermes`, `openclaw`, `crewai`, `google-adk`, `external`.
