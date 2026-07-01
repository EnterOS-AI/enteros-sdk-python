# org-template contract

Marketplace **org-template** contract — the publishable shape of an org-template `org.yaml`
(+ per-agent `workspace.yaml`) (`molecule-ai-org-template-*` repos). IDL is **JSON-Schema
(draft 2020-12)** per RFC [molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285).

| File | Role |
| --- | --- |
| `org-template.schema.json` | JSON-Schema (2020-12) describing the org-template shape |
| `org-template.contract.json` | A canonical instance (the Gemini Growth Team, inline composition) |

## Derived from

- `molecule-ai-org-template-molecule-dev/org.yaml` (+ `community-manager/workspace.yaml`) +
  `.molecule-ci/scripts/validate-org-template.py` (required `name`; must have at least
  `workspaces` or `defaults`; each workspace needs `name`; `plugins` must be a list; recurses
  `children`).
- `gemini-growth-team` and `mock-bigorg` `org.yaml` for the inline composition + deep nesting.

## Two composition styles, both tolerated

1. **Inline** — `workspaces` is a LIST of recursive workspace nodes with `children[]`
   (gemini-growth-team, mock-bigorg).
2. **Folder-tree** — `org.yaml` references per-agent `workspace.yaml` files via custom YAML
   tags (`!include`, `!external`) that resolve at platform load time (molecule-dev). Those
   tags are a YAML-load concern (the validator parses past them) and do not appear in this
   JSON contract — the schema models the **resolved** node tree.

`workspaces` accepts **both a list AND a map** (name→node). The recursive `workspaceNode`
($def, referencing itself via `children[]`) carries `name`(req), `role`, `runtime`, `tier`,
`model`, `files_dir`, `plugins[]`, `channels[]`, `schedules[]`, `initial_prompt(_file)`,
`idle_prompt(_file)`, `canvas{x,y}`, `children[]`. Modelled permissively
(`additionalProperties: true`) because org templates carry heterogeneous per-org config.
