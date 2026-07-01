# workspace-template contract

Marketplace **workspace-template** contract — the publishable shape of a workspace-template
`config.yaml` (`molecule-ai-workspace-template-*` repos). IDL is **JSON-Schema (draft 2020-12)**
per RFC [molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285).

| File | Role |
| --- | --- |
| `workspace-template.schema.json` | JSON-Schema (2020-12) describing the template shape |
| `workspace-template.contract.json` | A canonical instance (the Claude Code Agent template) |

## Derived from

- `molecule-ai-workspace-template-claude-code/config.yaml` + `.molecule-ci/scripts/validate-workspace-template.py`
  (required `name`/`runtime`/`template_schema_version`; `runtime` warns if outside the known set
  `{langgraph, claude-code, crewai, autogen, deepagents, hermes, gemini-cli, openclaw}`).
- `google-adk`, `seo-agent`, `platform-agent` `config.yaml` for the wider field surface
  (providers, runtime_config, schedules, skills, env).

## Deliberately tolerant

The real configs are **shape-inconsistent about where the model lives** — `google-adk` has
top-level `models[]` + `runtime_config.model`; `claude-code`/`seo-agent` have
`runtime_config.models[]` + top-level `model`; `platform-agent` has a top-level `provider`;
some have none. This schema models every observed location WITHOUT forcing one
(`additionalProperties: true` at the top and on nested objects), so a real config in any
style validates. The two `providers` shapes are typed separately by path: top-level
`providers[]` is a list of provider **objects**; `runtime_config.providers[]` is a list of
provider-name **strings**. `runtime` uses the canonical hyphen runtime enum (see
[`../plugin-manifest/README.md`](../plugin-manifest/README.md)).
