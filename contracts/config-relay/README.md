# Config + Plugin Relay contracts

Transient Cloudflare R2 delivery contract for the Molecule platform
(`cf-r2-relay-config-secret-delivery`). IDL is **JSON-Schema (draft 2020-12)** per RFC
[molecule-core#3285](https://git.moleculesai.app/molecule-ai/molecule-core/issues/3285)
§15: one `*.schema.json` (the shape) plus one `*.contract.json` (the canonical instance
the schema validates). The `validate` job in `contracts-codegen-drift.yml` checks the
instance against the schema.

## `config-relay`

The control plane stages a freshly-provisioned workspace's
`{config.yaml + prompts/* + secret files + system-prompt.md}` **and** its **resolved
plugin trees** as **ONE** transient R2 object, injects a short-TTL single-object
presigned HTTPS GET into the box env, and **deletes** the object the moment the box
acks provision-ready. The box holds **no** durable cloud credential — only the
minutes-long presigned URL.

This is the marketplace-grade **uniform delivery channel**: config and plugins ride the
same object, so a private third-party plugin is resolved **server-side** by the CP (with
a CP-held per-plugin credential) and delivered transiently — the box never holds the
plugin repo's credential.

### Fields (SSOT)

| field | meaning |
|-------|---------|
| `relay_uri_env` / `relay_sha256_env` / `relay_ack_token_env` | box-facing env keys: presigned GET, integrity digest, one-time ack bearer |
| `bundle_shape` / `path_charset` | `{path: base64(content)}`; every path validated on write (CP) and re-validated on unpack (box) |
| `integrity` / `fail_closed` | `sha256` over the raw body; a mismatch or exhausted-retry fetch **aborts boot** |
| `plugin_drop_prefix` | `.relay-plugins/<name>/…` — the bundle namespace for resolved plugin trees (disjoint from config paths) |
| `plugin_declared_scheme` / `plugin_declared_env` | `presign://<name>` in `MOLECULE_DECLARED_PLUGINS` resolves the relay drop with no network + no box-held plugin cred |
| `ack` / `delete_on_ack` | `POST /cp/workspaces/{workspace_id}/relay-ack` (Bearer ack token) → CP **deletes** the object; the bundle never persists |

### Producers / Consumers

- **Producers** — `molecule-controlplane`: `internal/configrelay` (`Stage`/`InjectEnv`/
  `DeleteOnReady`/`ReapAbandoned`), `internal/pluginresolve` (`Resolver.ResolveDeclared`
  — server-side plugin fetch + `presign://` rewrite), and the provision + relay-ack
  handlers.
- **Consumers** — `molecule-ai-workspace-runtime`: `molecule_runtime/config_relay.py`
  (`run_config_relay_prelude` — fetch → verify → unpack → ack) and
  `molecule_runtime/plugin_sources.py` (`_fetch_presign` — resolve the relay drop into
  the uniform build-then-swap install).

The runtime constant `molecule_runtime.plugin_sources.RELAY_PLUGIN_DROP_SUBDIR` and the
CP constant `configrelay.PluginDropPrefix` are both pinned to `plugin_drop_prefix`
(`.relay-plugins`) by this contract.
