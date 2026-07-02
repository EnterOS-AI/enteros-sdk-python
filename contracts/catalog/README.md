# catalog + marketplace-service contracts

The unified marketplace **catalog entry** envelope — one shape that lists ANY of the three
artifact kinds (`plugin` / `workspace-template` / `org-template`) — plus the
**marketplace-service SSOT** the server-side marketplace agent builds against (served
catalog, publish, install, entitlement). IDL is **JSON-Schema (draft 2020-12)** per RFC
[molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285).

| File | Role |
| --- | --- |
| `catalog-entry.schema.json` | JSON-Schema (2020-12) describing the per-listing envelope shape |
| `catalog-entry.contract.json` | A canonical instance (a `workspace-template` catalog entry) |
| `catalog.schema.json` | The **served catalog document** (the collection the storefront fetches / the agent produces): `schema_version` (const-pinned) + `generated_at` + `entries[]` of catalog-entry envelopes |
| `catalog.contract.json` | A canonical served-catalog instance (one plugin entry) |
| `publish-request.schema.json` | The **author → marketplace** submission (the SDK `publish` payload): kind + pinned `gitea://…#ref` source + listing metadata + optional `attestation` + optional `pricing` declaration |
| `publish-request.contract.json` | A canonical publish request (plugin, keyless-attested, subscription-priced) |
| `install-request.schema.json` | The **buy → install** delivery request: `entry_id`+`source`+`target`+idempotency; `mode` const-pinned `reconcile` |
| `install-request.contract.json` | A canonical install request (plugin into an org workspace) |
| `entitlement.schema.json` | The **who-owns-what** record: `status`/`grant_reason`/`granted_at`/`expires_at` + opaque `purchase_ref` |
| `entitlement.contract.json` | A canonical active entitlement |

## Marketplace-service surfaces (for the server-side agent)

`catalog-entry` describes ONE listing. The four sibling contracts describe the
cross-boundary shapes the **server-side marketplace agent** implements against:

- **`catalog`** — the served index the storefront consumes (read side).
- **`publish-request`** — how a listing is submitted (producer side; the `molecule-plugin` SDK emits it).
- **`install-request`** — how an entitled listing is delivered (reconcile-not-push, reusing the existing install engines).
- **`entitlement`** — the record that an org may install/use a listing (authorization data).

**Money stays out.** These are DATA/wire contracts only. Stripe/Connect/payouts are
owner-gated and live in the agent's payment layer, OUTSIDE this repo. The only
money-adjacent fields are `publish-request.pricing` (a seller DECLARATION) and
`entitlement.purchase_ref` (an OPAQUE join key) — neither carries payment data and this
repo performs no payment processing.

**Source refs — immutable at the authorization boundary.** `publish-request` and the
`catalog` listing carry a human-facing `gitea://…#<ref>` (a release tag or commit). The
marketplace agent RESOLVES that ref to an **immutable commit SHA** and records THAT in the
`install-request` and `entitlement` records — whose `source` is therefore constrained to a
SHA-only form (`#<7-64 hex>`, no branch/tag), so what actually gets delivered/authorized
can never move under the org. The schema enforces the SHA on the install/entitlement side;
the agent owns the tag→SHA resolution.

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
