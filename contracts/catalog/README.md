# catalog-entry contract

The unified marketplace **catalog entry** envelope — one shape that lists ANY of the three
artifact kinds (`plugin` / `workspace-template` / `org-template`) in the catalog. IDL is
**JSON-Schema (draft 2020-12)** per RFC
[molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285).

| File | Role |
| --- | --- |
| `catalog-entry.schema.json` | JSON-Schema (2020-12) describing the envelope shape |
| `catalog-entry.contract.json` | A canonical instance (a `workspace-template` catalog entry) |

## Shape

Common envelope fields describe the listing: `id`, `kind`, `slug`, `name`, `description`,
`version`, `source`, `publisher`, `tags`, `runtimes`, `tier`, `visibility`. `source` is a
**pinned** gitea source-contract string (`gitea://<owner>/<repo>[/<subpath>]#<ref>`) so an
entry always resolves to an immutable ref.

The per-kind **`spec`** is selected by a `oneOf` **keyed on `kind`**:

- `kind: plugin` → `pluginSpec` (`contributes` summary / `privileged` / `requires_secrets`)
- `kind: workspace-template` → `workspaceTemplateSpec` (`runtime` / `tier` / `models` / `plugins` / `env`)
- `kind: org-template` → `orgTemplateSpec` (`topology` / `workspace_count` / `defaults` / `composition`)

Because `kind` is pinned with a `const` in each `oneOf` branch, exactly one branch ever
matches — the discriminator is unambiguous.

## Phase boundary

**Price and entitlement are deliberately NOT in this envelope** — they are a catalog-layer
concern (Phase 2). This contract is schema-only: no CP, no DB, no money. The full artifact
manifests live in the sibling contracts (`../plugin-manifest/`, `../workspace-template/`,
`../org-template/`); the catalog `spec` carries the listing-relevant projection of each.
