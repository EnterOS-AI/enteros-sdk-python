# credentials contract

Root-level SSOT for Molecule's **credential / privilege model** — the *types* of
credential a box or process holds and the *format* of each (canonical env var
name, aliases, what it grants, where it may live).

## Why it exists

The concierge's management MCP `AUTH_ERROR`ed (`MOLECULE_ORG_API_KEY is not set`)
even though the credential *was* on the container — because three repos used
**different names** for the org credential with nothing forcing agreement:

| Component | Name it used |
|---|---|
| core `conciergePlatformMCPEnv` (sets it) | `MOLECULE_ORG_API_KEY` |
| runtime `privileged_mcp_env` (forwards it into the MCP child) | `ORG_API_KEY` (unprefixed) — set/read by nobody |
| mcp-server management client (reads it) | `MOLECULE_ORG_API_KEY` (strict, no alias) |

The runtime forwarded a name no one produces and **stripped** the one the reader
needs. The SDK governed the MCP's *delivery* (`contracts/mcp`) but never the
**credential env-key names** — this contract is that missing forcing function.

## What it governs

- **`credentials[]`** — the taxonomy. Each entry: `privilege` type, canonical
  `env_key`, `aliases`, `grants`, `format`, `managed`, `holder`, `forbidden_on`.
  Types: `workspace-token`, `org-api-key`, `platform-api-key`, `admin-break-glass`,
  `cp-admin-token`, `config-boot-token`, `boot-token`, `llm-usage-token`.
- **`routing[]`** — the non-credential identity vars the creds ride with
  (`MOLECULE_ORG_ID`, `MOLECULE_ORG_SLUG`, tenant `MOLECULE_API_URL` vs CP
  `MOLECULE_CP_URL`).
- **`management_mcp_env`** — the const-pinned env a privileged management MCP child
  MUST receive. This is the exact drift seam: the runtime's forward-allowlist MUST
  forward these names, and the mcp-server MUST read them under these names.

## The two org-adjacent keys are NOT the same (do not collapse)

- **`MOLECULE_ORG_API_KEY`** — the *org-api-key*, what the management **tools**
  authenticate with (`create_workspace`, …). Strict, no alias.
- **`MOLECULE_API_KEY`** — the *platform-api-key*, the mcp-server **startup
  preflight** credential + the legacy tool surface.

A server with `MOLECULE_API_KEY` but no `MOLECULE_ORG_API_KEY` boots "connected"
and fails every management call — exactly the concierge symptom. Both are required.

## Implementers

- **core** `conciergePlatformMCPEnv` — sets `MOLECULE_ORG_API_KEY` + `MOLECULE_API_KEY`.
- **runtime** `privileged_mcp_env` — its forward-allowlist must forward `management_mcp_env.required`.
- **mcp-server** — reads them under the canonical names.
- **controlplane** — sets `ADMIN_TOKEN` / `MOLECULE_ADMIN_TOKEN` (concierge-only) + the boot token.

Each vendors this contract and a drift gate fails CI on a name mismatch — so the
concierge break class can't recur silently.

## Relationship to other contracts

`contracts/mcp` governs the mgmt-MCP *descriptor delivery* (name, tool, where it's
written); this governs the *credentials* it carries. `contracts/boot-token` is the
wire format of the `boot-token` entry; `contracts/object-store` is the restore
route that boot token authorizes. Coarse power today (`org-api-key == admin`);
fine-grained scoping is future work tracked against this contract.
