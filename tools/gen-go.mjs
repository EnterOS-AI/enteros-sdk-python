#!/usr/bin/env node
// gen-go.mjs — generate the Go cloud-provider binding from the SSOT.
//
// Source of truth: contracts/cloudproviders.yaml (validated against
// contracts/cloudproviders.schema.json). Every VALUE below (the canonical id
// strings, the provisioner backend keys, the ordered All slice, the DefaultID)
// is DERIVED from that YAML instance — edit the YAML and re-run and the binding
// changes with it. The exported Go NAMES + doc prose are the module's public
// API surface and live here as presentation (the same split molecule-contracts'
// gen-go.mjs uses: values from the contract, names/docs in the generator).
//
// Output: gen/go/cloudprovider/cloudprovider.go — importable byte-stably as
// go.moleculesai.app/sdk/gen/go/cloudprovider. The output is deliberately
// BYTE-IDENTICAL to the retired molecule-go-sdk/cloudprovider/cloudprovider.go
// (the parity oracle), so every existing importer rebuilds with zero source
// churn. The moved-verbatim cloudprovider_test.go pins the behavior; the
// codegen-drift CI pins "gen/ is never hand-edited".
//
// Usage:
//   node tools/gen-go.mjs            # write gen/go/cloudprovider/cloudprovider.go
//   node tools/gen-go.mjs --check    # print to stdout, do not write

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { loadCloudProviders, localFirst, repoRoot } from "./lib/cloudproviders.mjs";
import { buildCommsModelIR, buildModelIR, pascal } from "./lib/comms-schema.mjs";

const OUT_PATH = resolve(repoRoot, "gen/go/cloudprovider/cloudprovider.go");

const data = loadCloudProviders();

// Go source & JSON share double-quoted escape semantics for these values.
const lit = (s) => JSON.stringify(s);

// --- presentation: exported Go const names + doc prose ----------------------
// Names/docs are the public API (irregular by design: AWS/GCP are initialisms,
// Hetzner is a proper noun, MoleculesServer is PascalCase). Values are derived.
const ID_CONST = {
  "molecules-server": {
    name: "MoleculesServer",
    doc: [
      'MoleculesServer is the local, self-hosted box (the "Molecules-Server").',
      "It is the IS-LOCAL member, backed by the provisioner LocalDocker backend",
      "(BackendLocal). It is selectable in the picker just like the clouds.",
    ],
  },
  aws: {
    name: "AWS",
    doc: [
      "AWS is the Amazon EC2 cloud backend (the historical implicit default — an",
      "empty provider string Normalizes to AWS).",
    ],
  },
  gcp: { name: "GCP", doc: ["GCP is the Google Compute Engine cloud backend."] },
  hetzner: { name: "Hetzner", doc: ["Hetzner is the Hetzner Cloud backend."] },
};

const BACKEND_CONST = {
  local: "BackendLocal",
  aws: "BackendAWS",
  gcp: "BackendGCP",
  hetzner: "BackendHetzner",
};

function idConstName(id) {
  const p = ID_CONST[id];
  if (!p) {
    console.error(`gen-go: no Go const presentation for provider id ${lit(id)} — add it to ID_CONST.`);
    process.exit(1);
  }
  return p.name;
}
function backendConstName(bk) {
  const n = BACKEND_CONST[bk];
  if (!n) {
    console.error(`gen-go: no Go const presentation for backend_key ${lit(bk)} — add it to BACKEND_CONST.`);
    process.exit(1);
  }
  return n;
}

// aligned() reproduces gofmt's column alignment for a run of [left,right] rows:
// left is padded to the widest left + one space.
function aligned(rows) {
  const w = Math.max(...rows.map(([l]) => l.length));
  return rows.map(([l, r]) => `${l.padEnd(w)} ${r}`);
}

// renderAlias mirrors the original literal shape: an alias that equals a known
// backend key renders as that Backend* const; anything else is a string literal.
function renderAlias(a) {
  return BACKEND_CONST[a] ? BACKEND_CONST[a] : lit(a);
}

const L = [];
const p = (...xs) => xs.forEach((x) => L.push(x));

// --- package doc (verbatim) --------------------------------------------------
p(
  "// Package cloudprovider is the single source of truth (SSOT) for the set of",
  "// CLOUD / COMPUTE BACKENDS a MoleculesAI tenant or workspace can run on — the",
  '// "where does this box physically run" axis: the local self-hosted box',
  "// (Molecules-Server) and the three clouds (AWS / GCP / Hetzner).",
  "//",
  "// This is DELIBERATELY DISTINCT from the LLM provider registry",
  "// (Anthropic/OpenAI/MiniMax/…). This package never mentions a model; it carries",
  "// only the compute-backend identity. Conflating the two is the long-standing",
  "// confusion this SSOT exists to end.",
  "//",
  "// Before this package the set was pasted independently in at least five places",
  "// that could silently drift:",
  "//   - controlplane internal/cloudprovider.Supported (org-create validation),",
  "//   - controlplane internal/provisioner normalizeProviderKey (backend routing),",
  "//   - controlplane internal/credits pricing tables (sweep.go),",
  "//   - core workspace-server internal/handlers/workspace_compute.go (canvas",
  '//     picker — a hand-maintained "deliberate mirror" of the CP list),',
  "//   - the app cloud-provider dropdown.",
  "//",
  "// It is wire/identity DATA only (ids, display labels, and the provisioner",
  "// backend key each id maps to) — NO provisioning logic, NO credentials, NO",
  "// per-deploy behaviour — which is exactly why it can live in the neutral SDK",
  "// that BOTH molecule-core (OSS) and molecule-controlplane (proprietary) import",
  "// without either depending on the other. The provisioner backends that ACT on",
  "// these ids (EC2 / GCP / Hetzner / LocalDocker) stay in their owning repo.",
  "package cloudprovider",
  "",
  'import "strings"',
  "",
);

// --- canonical id const block (derived values, local-first order) -----------
p(
  "// Canonical provider IDENTIFIERS — the wire/UI value persisted on an org or",
  "// workspace row and sent in the create / migrate API. These are the SSOT",
  "// spellings; every consumer renders/validates against them.",
  "const (",
);
for (const prov of localFirst(data.providers)) {
  for (const line of ID_CONST[prov.id].doc) p(`\t// ${line}`);
  p(`\t${idConstName(prov.id)} = ${lit(prov.id)}`);
}
p(")", "");

// --- backend key const block (derived values, local-first, gofmt-aligned) ---
p(
  "// Provisioner BACKEND KEYS — the key the controlplane provider registry",
  "// (provisioner.NewProviderRegistry / Select / Registered) routes on. For the",
  "// clouds the backend key EQUALS the id; for the local box the id",
  '// "molecules-server" maps to the historical backend key "local" — LocalDocker',
  '// registers under "local", and existing org rows persist provider="local", so',
  '// "local" (and the PROVISIONER_BACKEND spelling "docker") remain accepted',
  "// Aliases that normalize to the MoleculesServer id.",
  "const (",
);
{
  const seen = new Set();
  const rows = [];
  for (const prov of localFirst(data.providers)) {
    if (seen.has(prov.backend_key)) continue;
    seen.add(prov.backend_key);
    rows.push([backendConstName(prov.backend_key), `= ${lit(prov.backend_key)}`]);
  }
  for (const r of aligned(rows)) p(`\t${r}`);
}
p(")", "");

// --- Provider type (verbatim; no YAML data) ---------------------------------
p(
  "// Provider is one canonical entry: its wire id, human display label, the",
  "// provisioner backend key it routes to, whether it is the local self-hosted",
  "// box, and any alternate accepted wire spellings that normalize to ID.",
  "type Provider struct {",
  "\tID         string   // canonical wire/UI id (one of the id consts above)",
  '\tDisplay    string   // human label for pickers ("Molecules-Server","AWS",…)',
  "\tBackendKey string   // provisioner registry key (one of the Backend* consts)",
  "\tIsLocal    bool     // true only for the Molecules-Server local box",
  "\tAliases    []string // alternate accepted wire spellings → normalize to ID",
  "}",
  "",
);

// --- All slice (derived rows, SSOT order) -----------------------------------
p(
  "// All is the canonical, ORDERED list of every selectable provider — the SSOT a",
  "// UI dropdown renders and a create/migrate validator accepts. Order is the",
  "// preferred display order: the clouds first (AWS the historical default), then",
  "// the local self-hosted box.",
  "//",
  "// Adding/removing a member here is the ONE edit that changes the provider set",
  "// everywhere: CP validation + the app dropdown + (via CloudIDs) the core canvas",
  "// picker all derive from this list.",
  "var All = []Provider{",
);
for (const prov of data.providers) {
  let row = `\t{ID: ${idConstName(prov.id)}, Display: ${lit(prov.display)}, BackendKey: ${backendConstName(prov.backend_key)}, IsLocal: ${prov.is_local}`;
  if (prov.aliases && prov.aliases.length) {
    row += `, Aliases: []string{${prov.aliases.map(renderAlias).join(", ")}}`;
  }
  row += "},";
  p(row);
}
p("}", "");

// --- DefaultID (derived) ----------------------------------------------------
p(
  "// DefaultID is the implicit provider when none is specified: an empty/blank",
  "// provider string Normalizes to AWS (the historical default), preserving the",
  "// pre-multi-provider wire contract that an absent provider means AWS.",
  `const DefaultID = ${idConstName(data.default_id)}`,
  "",
);

// --- lookup indexes + helpers (verbatim; the engine, no YAML data) ----------
p(
  "// byID and aliasToID are the O(1) lookup indexes built once from All — the",
  "// SSOT shape can never disagree with itself because both derive from the same",
  "// slice.",
  "var (",
  "\tbyID      = func() map[string]Provider {",
  "\t\tm := make(map[string]Provider, len(All))",
  "\t\tfor _, p := range All {",
  "\t\t\tm[p.ID] = p",
  "\t\t}",
  "\t\treturn m",
  "\t}()",
  "\taliasToID = func() map[string]string {",
  "\t\tm := make(map[string]string, len(All))",
  "\t\tfor _, p := range All {",
  "\t\t\tm[p.ID] = p.ID",
  "\t\t\tfor _, a := range p.Aliases {",
  "\t\t\t\tm[strings.ToLower(strings.TrimSpace(a))] = p.ID",
  "\t\t\t}",
  "\t\t}",
  "\t\treturn m",
  "\t}()",
  ")",
  "",
  '// Normalize lowercases + trims, resolves an Alias (e.g. "local"/"docker" →',
  '// "molecules-server") to its canonical id, and maps the EMPTY string to the',
  "// AWS default. An unknown non-empty value passes through unchanged (callers",
  "// then reject it via IsValidID / IsValidRequest) so a typo fails LOUD rather",
  "// than silently becoming AWS.",
  "func Normalize(id string) string {",
  "\tid = strings.ToLower(strings.TrimSpace(id))",
  '\tif id == "" {',
  "\t\treturn DefaultID",
  "\t}",
  "\tif canon, ok := aliasToID[id]; ok {",
  "\t\treturn canon",
  "\t}",
  "\treturn id",
  "}",
  "",
  "// ByID returns the canonical Provider for an id (after Normalize) and whether",
  "// it is a known provider.",
  "func ByID(id string) (Provider, bool) {",
  "\tp, ok := byID[Normalize(id)]",
  "\treturn p, ok",
  "}",
  "",
  "// IsValidID reports whether id (after Normalize) is a canonical provider.",
  "func IsValidID(id string) bool {",
  "\t_, ok := byID[Normalize(id)]",
  "\treturn ok",
  "}",
  "",
  "// IsValidRequest reports whether a request-supplied provider value is",
  "// acceptable: either the empty string (caller wants the default) or any valid",
  "// id (incl. an alias). Create/validation paths use this to reject a typo with a",
  "// clean 400 while still allowing an omitted provider.",
  "func IsValidRequest(id string) bool {",
  '\tif strings.TrimSpace(id) == "" {',
  "\t\treturn true",
  "\t}",
  "\treturn IsValidID(id)",
  "}",
  "",
  "// BackendKey maps an id (after Normalize) to its provisioner registry backend",
  '// key (e.g. "molecules-server" → "local"). Returns ok=false for an unknown id.',
  "func BackendKey(id string) (string, bool) {",
  "\tif p, ok := byID[Normalize(id)]; ok {",
  "\t\treturn p.BackendKey, true",
  "\t}",
  '\treturn "", false',
  "}",
  "",
  "// Display maps an id (after Normalize) to its human label. Returns ok=false for",
  "// an unknown id.",
  "func Display(id string) (string, bool) {",
  "\tif p, ok := byID[Normalize(id)]; ok {",
  "\t\treturn p.Display, true",
  "\t}",
  '\treturn "", false',
  "}",
  "",
  "// IDs returns every canonical provider id in All order — the full selectable",
  "// set (clouds + Molecules-Server). The returned slice is a fresh copy.",
  "func IDs() []string {",
  "\tout := make([]string, 0, len(All))",
  "\tfor _, p := range All {",
  "\t\tout = append(out, p.ID)",
  "\t}",
  "\treturn out",
  "}",
  "",
  "// CloudIDs returns the non-local (cloud) provider ids in All order — the subset",
  "// that has per-hour/per-GB cloud BILLING and that the core canvas mirror covers.",
  "// The local Molecules-Server box is excluded (it has no cloud cost). The",
  "// returned slice is a fresh copy.",
  "func CloudIDs() []string {",
  "\tout := make([]string, 0, len(All))",
  "\tfor _, p := range All {",
  "\t\tif !p.IsLocal {",
  "\t\t\tout = append(out, p.ID)",
  "\t\t}",
  "\t}",
  "\treturn out",
  "}",
);

const out = L.join("\n") + "\n";

if (process.argv.includes("--check")) {
  process.stdout.write(out);
  process.exit(0);
}
mkdirSync(dirname(OUT_PATH), { recursive: true });
writeFileSync(OUT_PATH, out, "utf8");
console.error(`gen-go: wrote ${OUT_PATH} (${data.providers.length} providers derived from contracts/cloudproviders.yaml)`);

// ===========================================================================
// FOLDED molecule-contracts generator (JSON-Schema IDL kind). Emits the
// package `molcontracts` bindings under gen/go/molcontracts/ — BYTE-IDENTICAL to
// the retired molecule-contracts/gen/go output (the parity oracle). Only path
// resolution is re-rooted (inputs under contracts/, output under
// gen/go/molcontracts/); every emitted string is unchanged. Block-scoped so its
// helpers/consts never collide with the cloudprovider generator above.
// ===========================================================================
{
const contractsRoot = resolve(repoRoot, "contracts");
const CONTRACT_PATH = resolve(contractsRoot, "mcp/mcp-plugin-delivery.contract.json");
const OUT_PATH = resolve(repoRoot, "gen/go/molcontracts/contract_gen.go");
const COMMS_OUT_PATH = resolve(repoRoot, "gen/go/molcontracts/workspace_comms_gen.go");
const PROVISION_REQUEST_PATH = resolve(contractsRoot, "provision-request/provision-request.contract.json");
const PROVISION_REQUEST_OUT_PATH = resolve(repoRoot, "gen/go/molcontracts/provision_request_gen.go");
const PLUGIN_MANIFEST_SCHEMA_PATH = resolve(contractsRoot, "plugin-manifest/plugin-manifest.schema.json");
const SCHEMA_ASSETS_OUT_PATH = resolve(repoRoot, "gen/go/molcontracts/schema_assets_gen.go");

// --- read the canonical IDL instance ----------------------------------------
const raw = readFileSync(CONTRACT_PATH, "utf8");
let contract;
try {
  contract = JSON.parse(raw);
} catch (err) {
  console.error(`gen-go: ${CONTRACT_PATH} is not valid JSON: ${err.message}`);
  process.exit(1);
}

const provisionRequestRaw = readFileSync(PROVISION_REQUEST_PATH, "utf8");
let provisionRequest;
try {
  provisionRequest = JSON.parse(provisionRequestRaw);
} catch (err) {
  console.error(`gen-go: ${PROVISION_REQUEST_PATH} is not valid JSON: ${err.message}`);
  process.exit(1);
}

const pluginManifestSchemaRaw = readFileSync(PLUGIN_MANIFEST_SCHEMA_PATH, "utf8");
try {
  JSON.parse(pluginManifestSchemaRaw);
} catch (err) {
  console.error(`gen-go: ${PLUGIN_MANIFEST_SCHEMA_PATH} is not valid JSON: ${err.message}`);
  process.exit(1);
}

// --- helpers ----------------------------------------------------------------
const lit = (s) => JSON.stringify(s); // Go & JSON share double-quoted escape semantics here.

function reqStr(field) {
  const v = contract[field];
  if (typeof v !== "string") {
    console.error(`gen-go: contract field '${field}' missing or not a string (got ${JSON.stringify(v)}).`);
    process.exit(1);
  }
  return v;
}

// aligned() reproduces gofmt's column alignment for a run of single-line rows:
// each row is [left, right]; `left` is padded to the widest `left` + one space.
function aligned(rows) {
  const w = Math.max(...rows.map(([l]) => l.length));
  return rows.map(([l, r]) => `${l.padEnd(w)} ${r}`);
}

// alignCols reproduces gofmt alignment for N columns: every column except the
// last is padded to the widest cell in that column, joined by a single space.
function alignCols(rows) {
  const n = rows[0].length;
  const w = [];
  for (let c = 0; c < n - 1; c++) w[c] = Math.max(...rows.map((r) => r[c].length));
  return rows.map((r) => r.map((cell, c) => (c < n - 1 ? cell.padEnd(w[c]) : cell)).join(" "));
}

// --- scalar consts (ergonomic; values derived) ------------------------------
const SCALAR_CONSTS = [
  ["RequiredTool", "required_tool", "the singular tool verb the concierge management MCP must expose; the degrade gate fails closed if it is absent on the live surface (the #3082 phantom-verb invariant)."],
  ["MCPServerName", "mcp_server_name", "logical name of the management-mode MCP server descriptor."],
  ["SettingsKey", "key", "top-level key inside the settings file under which MCP servers are declared."],
  ["DefaultSettingsPath", "settings_path", "default (claude_code) settings file path the rendered MCP descriptor is written to."],
  ["LoadedMCPToolsField", "loaded_mcp_tools_field", "name of the field reporting the set of tools actually loaded from the MCP server."],
  ["RuntimePresentField", "runtime_present_field", "name of the runtime-reported boolean field indicating the MCP server is present."],
  ["LegacyBinaryPath", "legacy_binary_path", "filesystem path of the legacy MCP server binary older presence probes checked."],
];

// --- structural field specs for the full contract value ---------------------
// Each: [GoField, jsonKey]. Names/types are schema; values come from JSON.
const PORT_FIELDS = [
  ["Hook", "hook"], ["Impl", "impl"], ["PresentProbe", "present_probe"],
  ["Dispatch", "dispatch"], ["ResolverDefault", "resolver_default"],
];
const RUNTIME_FIELDS = [
  ["SettingsPath", "settings_path"], ["Format", "format"], ["Key", "key"],
  ["KeyPath", "key_path"],
  ["Table", "table"], ["Renderer", "renderer"], ["Status", "status"],
];

function emitPort(p) {
  const rows = aligned(PORT_FIELDS.map(([g, k]) => [`${g}:`, `${lit(p?.[k] ?? "")},`]));
  return "Port{\n" + rows.map((r) => `\t\t${r}`).join("\n") + "\n\t}";
}
function emitRuntime(r, indent) {
  const rows = aligned(RUNTIME_FIELDS.map(([g, k]) => [`${g}:`, `${lit(r?.[k] ?? "")},`]));
  return "{\n" + rows.map((x) => `${indent}\t${x}`).join("\n") + `\n${indent}}`;
}
function emitRuntimes(rs) {
  const keys = Object.keys(rs || {}).sort(); // deterministic order regardless of JSON key order
  // multiline values → gofmt does not align the map keys; single space after the colon.
  const entries = keys.map((k) => `\t\t${lit(k)}: ${emitRuntime(rs[k], "\t\t")},`).join("\n");
  return `map[string]Runtime{\n${entries}\n\t}`;
}
function emitConsumers() {
  const cs = Array.isArray(contract.consumers) ? contract.consumers : [];
  return `[]string{${cs.map(lit).join(", ")}}`;
}

// --- emit -------------------------------------------------------------------
const L = [];
L.push("// Code generated by tools/gen-go.mjs — DO NOT EDIT.");
L.push("//");
L.push("// Source of truth: mcp/mcp-plugin-delivery.contract.json (validated against");
L.push("// mcp/mcp-plugin-delivery.schema.json). Every value below is DERIVED from that");
L.push("// contract instance, never hand-written. Regenerate with:");
L.push("//");
L.push("//     node tools/gen-go.mjs");
L.push("//");
L.push("// A CI drift gate (.gitea/workflows/codegen-drift.yml) re-runs the generator and");
L.push("// fails if this file differs from a fresh regeneration, per RFC molecule-core#3285 §14.");
L.push("");
L.push("package molcontracts");
L.push("");
L.push("// Derived scalar string constants from the MCP plugin-delivery contract.");
L.push("const (");
SCALAR_CONSTS.forEach(([goName, field, doc], i) => {
  L.push(`\t// ${goName} is derived from contract field "${field}": ${doc}`);
  L.push(`\t${goName} = ${lit(reqStr(field))}`);
  if (i !== SCALAR_CONSTS.length - 1) L.push("");
});
L.push(")");
L.push("");
// --- types ---
L.push("// Port names the MCP-wiring PORT symbols on the runtime side (core#3159).");
L.push("type Port struct {");
aligned(PORT_FIELDS.map(([g, k]) => [g, `string \`json:${lit(k)}\``])).forEach((r) => L.push(`\t${r}`));
L.push("}");
L.push("");
L.push("// Runtime is a single runtime's native MCP-config delivery surface.");
L.push("type Runtime struct {");
aligned(RUNTIME_FIELDS.map(([g, k]) => {
  const tag = (k === "key" || k === "key_path" || k === "table") ? `${k},omitempty` : k;
  return [g, `string \`json:${lit(tag)}\``];
})).forEach((r) => L.push(`\t${r}`));
L.push("}");
L.push("");
L.push("// MCPPluginDeliveryContract is the full pinned MCP-plugin delivery surface.");
L.push("type MCPPluginDeliveryContract struct {");
alignCols([
  ["SettingsPath", "string", `\`json:"settings_path"\``],
  ["Key", "string", `\`json:"key"\``],
  ["EntryShape", "string", `\`json:"entry_shape"\``],
  ["MCPServerName", "string", `\`json:"mcp_server_name"\``],
  ["RequiredTool", "string", `\`json:"required_tool"\``],
  ["LoadedMCPToolsField", "string", `\`json:"loaded_mcp_tools_field"\``],
  ["LegacyBinaryPath", "string", `\`json:"legacy_binary_path"\``],
  ["RuntimePresentField", "string", `\`json:"runtime_present_field"\``],
  ["Producer", "string", `\`json:"producer"\``],
  ["Consumer", "string", `\`json:"consumer"\``],
  ["Consumers", "[]string", `\`json:"consumers"\``],
  ["Descriptor", "string", `\`json:"descriptor"\``],
  ["Port", "Port", `\`json:"port"\``],
  ["Runtimes", "map[string]Runtime", `\`json:"runtimes"\``],
]).forEach((r) => L.push(`\t${r}`));
L.push("}");
L.push("");
// --- value ---
L.push("// Contract is the full contract value, DERIVED from the JSON instance. Import");
L.push("// this instead of vendoring + re-parsing a JSON mirror (RFC core#3285 §10).");
L.push("var Contract = MCPPluginDeliveryContract{");
// single-line scalar fields form one gofmt alignment run:
aligned([
  ["SettingsPath:", `${lit(reqStr("settings_path"))},`],
  ["Key:", `${lit(reqStr("key"))},`],
  ["EntryShape:", `${lit(reqStr("entry_shape"))},`],
  ["MCPServerName:", `${lit(reqStr("mcp_server_name"))},`],
  ["RequiredTool:", `${lit(reqStr("required_tool"))},`],
  ["LoadedMCPToolsField:", `${lit(reqStr("loaded_mcp_tools_field"))},`],
  ["LegacyBinaryPath:", `${lit(reqStr("legacy_binary_path"))},`],
  ["RuntimePresentField:", `${lit(reqStr("runtime_present_field"))},`],
  ["Producer:", `${lit(reqStr("producer"))},`],
  ["Consumer:", `${lit(reqStr("consumer"))},`],
  ["Consumers:", `${emitConsumers()},`],
  ["Descriptor:", `${lit(reqStr("descriptor"))},`],
]).forEach((r) => L.push(`\t${r}`));
// multiline-value fields break the alignment run → single space after the colon:
L.push(`\tPort: ${emitPort(contract.port)},`);
L.push(`\tRuntimes: ${emitRuntimes(contract.runtimes)},`);
L.push("}");
L.push("");

const out = L.join("\n");

if (process.argv.includes("--check")) {
  process.stdout.write(out);
  process.exit(0);
}
mkdirSync(dirname(OUT_PATH), { recursive: true });
writeFileSync(OUT_PATH, out, "utf8");
console.error(`gen-go: wrote ${OUT_PATH} (scalars + full Contract value derived from ${CONTRACT_PATH})`);

// ===========================================================================
// provision-request contract value. Derived from the canonical instance so Go
// consumers can pin producer/consumer struct JSON tags without vendoring JSON.
// ===========================================================================

function reqProvisionEndpoint() {
  if (typeof provisionRequest.endpoint !== "string") {
    console.error(`gen-go: provision-request endpoint missing or not a string (got ${JSON.stringify(provisionRequest.endpoint)}).`);
    process.exit(1);
  }
  return provisionRequest.endpoint;
}

function provisionRequestFieldEntries() {
  const fields = provisionRequest.fields;
  if (!fields || typeof fields !== "object" || Array.isArray(fields)) {
    console.error("gen-go: provision-request fields missing or not an object.");
    process.exit(1);
  }
  return Object.entries(fields).map(([name, spec]) => {
    if (!spec || typeof spec !== "object" || Array.isArray(spec)) {
      console.error(`gen-go: provision-request field ${name} spec missing or not an object.`);
      process.exit(1);
    }
    if (typeof spec.type !== "string") {
      console.error(`gen-go: provision-request field ${name} type missing or not a string.`);
      process.exit(1);
    }
    if (typeof spec.cp_consumes !== "boolean") {
      console.error(`gen-go: provision-request field ${name} cp_consumes missing or not a boolean.`);
      process.exit(1);
    }
    if ("note" in spec && typeof spec.note !== "string") {
      console.error(`gen-go: provision-request field ${name} note is not a string.`);
      process.exit(1);
    }
    return [name, spec];
  });
}

function emitProvisionRequestField(spec) {
  const rows = [
    ["Type:", `${lit(spec.type)},`],
    ["CPConsumes:", `${spec.cp_consumes},`],
  ];
  if (spec.note) rows.push(["Note:", `${lit(spec.note)},`]);
  return `ProvisionRequestField{${aligned(rows).map((r) => `\n\t\t\t${r}`).join("")}\n\t\t}`;
}

const provisionFields = provisionRequestFieldEntries();
const P = [];
P.push("// Code generated by tools/gen-go.mjs — DO NOT EDIT.");
P.push("//");
P.push("// Source of truth: provision-request/provision-request.contract.json");
P.push("// (validated against provision-request/provision-request.schema.json). Every");
P.push("// value below is DERIVED from that contract instance, never hand-written.");
P.push("// Regenerate with:");
P.push("//");
P.push("//     node tools/gen-go.mjs");
P.push("//");
P.push("// A CI drift gate (.gitea/workflows/codegen-drift.yml) re-runs the generator and");
P.push("// fails if this file differs from a fresh regeneration, per RFC molecule-core#3285 §14.");
P.push("");
P.push("package molcontracts");
P.push("");
P.push("// ProvisionRequestEndpoint is the core -> control-plane provision endpoint.");
P.push(`const ProvisionRequestEndpoint = ${lit(reqProvisionEndpoint())}`);
P.push("");
P.push("// ProvisionRequestField describes one provision request wire field.");
P.push("type ProvisionRequestField struct {");
alignCols([
  ["Type", "string", `\`json:"type"\``],
  ["CPConsumes", "bool", `\`json:"cp_consumes"\``],
  ["Note", "string", `\`json:"note,omitempty"\``],
]).forEach((r) => P.push(`\t${r}`));
P.push("}");
P.push("");
P.push("// ProvisionRequestContract is the pinned core -> control-plane provision request surface.");
P.push("type ProvisionRequestContract struct {");
alignCols([
  ["Endpoint", "string", `\`json:"endpoint"\``],
  ["Fields", "map[string]ProvisionRequestField", `\`json:"fields"\``],
]).forEach((r) => P.push(`\t${r}`));
P.push("}");
P.push("");
P.push("// ProvisionRequest is the full contract value, DERIVED from the JSON instance.");
P.push("var ProvisionRequest = ProvisionRequestContract{");
aligned([
  ["Endpoint:", "ProvisionRequestEndpoint,"],
]).forEach((r) => P.push(`\t${r}`));
P.push("\tFields: map[string]ProvisionRequestField{");
for (const [name, spec] of provisionFields) {
  P.push(`\t\t${lit(name)}: ${emitProvisionRequestField(spec)},`);
}
P.push("\t},");
P.push("}");
P.push("");
P.push("// ProvisionRequestFieldNames lists provision request JSON fields in contract order.");
P.push("var ProvisionRequestFieldNames = []string{");
for (const [name] of provisionFields) {
  P.push(`\t${lit(name)},`);
}
P.push("}");
P.push("");

const provisionRequestOut = P.join("\n");

if (!process.argv.includes("--check")) {
  mkdirSync(dirname(PROVISION_REQUEST_OUT_PATH), { recursive: true });
  writeFileSync(PROVISION_REQUEST_OUT_PATH, provisionRequestOut, "utf8");
  console.error(`gen-go: wrote ${PROVISION_REQUEST_OUT_PATH} (${provisionFields.length} fields derived from ${PROVISION_REQUEST_PATH})`);
}

// ===========================================================================
// raw JSON-Schema assets. These let Go consumers compile the canonical schemas
// directly from the SDK instead of vendoring byte mirrors into each repo.
// ===========================================================================

function emitGoStringConst(lines, name, raw) {
  const chunks = raw.match(/[^\n]*\n|[^\n]+$/g) || [""];
  chunks.forEach((chunk, i) => {
    const suffix = i === chunks.length - 1 ? "" : " +";
    if (i === 0) lines.push(`const ${name} = ${lit(chunk)}${suffix}`);
    else lines.push(`\t${lit(chunk)}${suffix}`);
  });
}

const S = [];
S.push("// Code generated by tools/gen-go.mjs — DO NOT EDIT.");
S.push("//");
S.push("// Source of truth: plugin-manifest/plugin-manifest.schema.json. The schema");
S.push("// JSON below is DERIVED from that SDK SSOT file, never hand-written.");
S.push("// Regenerate with:");
S.push("//");
S.push("//     node tools/gen-go.mjs");
S.push("//");
S.push("// A CI drift gate (.gitea/workflows/codegen-drift.yml) re-runs the generator and");
S.push("// fails if this file differs from a fresh regeneration, per RFC molecule-core#3285 §14.");
S.push("");
S.push("package molcontracts");
S.push("");
S.push("// PluginManifestSchemaJSON is the canonical JSON-Schema for plugin.yaml manifests.");
S.push("// Consumers can compile it directly instead of embedding a vendored schema copy.");
emitGoStringConst(S, "PluginManifestSchemaJSON", pluginManifestSchemaRaw);
S.push("");

const schemaAssetsOut = S.join("\n");

if (!process.argv.includes("--check")) {
  mkdirSync(dirname(SCHEMA_ASSETS_OUT_PATH), { recursive: true });
  writeFileSync(SCHEMA_ASSETS_OUT_PATH, schemaAssetsOut, "utf8");
  console.error(`gen-go: wrote ${SCHEMA_ASSETS_OUT_PATH} (plugin manifest schema derived from ${PLUGIN_MANIFEST_SCHEMA_PATH})`);
}

// ===========================================================================
// workspace-comms models (Wave 2). Derived from workspace-comms/*.schema.json
// via the shared IR (tools/lib/comms-schema.mjs). The mcp output above is left
// BYTE-IDENTICAL — this is a strictly-additional second file in the same
// `package molcontracts`. Type/field names are STRUCTURAL (schema shape); the
// only string VALUES written are the `const`-pinned literals, derived from the
// schema, never hand-authored.
// ===========================================================================

const GO_SCALAR = { string: "string", int: "int", float: "float64", bool: "bool", any: "any" };

function goType(ref) {
  switch (ref.k) {
    case "scalar": return GO_SCALAR[ref.t];
    case "named": return ref.name;
    case "array": return "[]" + goType(ref.items);
    case "map": return "map[string]" + goType(ref.value);
    default: throw new Error(`gen-go: unknown TypeRef kind ${ref.k}`);
  }
}

// optional scalars (except `any`) and optional nested structs become pointers so
// absent is distinguishable from the zero value (the tri-state semantics the
// schemas lean on, e.g. *bool mcp_server_present). slices/maps are already
// nil-able, so they stay as-is with ,omitempty.
function goField(field) {
  const base = goType(field.type);
  let typeStr = base;
  let tag = `\`json:"${field.key}"\``;
  if (!field.required) {
    const ptr = field.type.k === "named" || (field.type.k === "scalar" && field.type.t !== "any");
    typeStr = ptr ? "*" + base : base;
    tag = `\`json:"${field.key},omitempty"\``;
  }
  return [pascal(field.key), typeStr, tag];
}

const ir = buildCommsModelIR(contractsRoot);

const G = [];
G.push("// Code generated by tools/gen-go.mjs — DO NOT EDIT.");
G.push("//");
G.push("// Source of truth: workspace-comms/*.schema.json (each validated against its");
G.push("// sibling *.contract.json instance by .gitea/workflows/validate-contracts.yml).");
G.push("// Every type, field and constant below is DERIVED from those schemas, never");
G.push("// hand-written. Regenerate with:");
G.push("//");
G.push("//     node tools/gen-go.mjs");
G.push("//");
G.push("// A CI drift gate (.gitea/workflows/codegen-drift.yml) re-runs the generator and");
G.push("// fails if this file differs from a fresh regeneration, per RFC molecule-core#3285 §14.");
G.push("");
G.push("package molcontracts");
G.push("");

if (ir.consts.length) {
  G.push("// Load-bearing string literals pinned by `const` in the workspace-comms schemas");
  G.push("// (e.g. the register/heartbeat/a2a response status and the JSON-RPC version).");
  G.push("// Consumers assert against these instead of re-typing the literal.");
  G.push("const (");
  ir.consts.forEach((c, i) => {
    G.push(`\t// ${c.name} is pinned by ${c.source}: ${c.doc}`);
    G.push(`\t${c.name} = ${lit(c.value)}`);
    if (i !== ir.consts.length - 1) G.push("");
  });
  G.push(")");
  G.push("");
}

for (const def of ir.types) {
  if (def.doc) G.push(`// ${def.name}: ${def.doc}`);
  else G.push(`// ${def.name} is derived from ${def.source}.`);
  if (def.fields.length === 0) {
    G.push(`type ${def.name} struct{}`);
    G.push("");
    continue;
  }
  G.push(`type ${def.name} struct {`);
  for (const field of def.fields) {
    if (field.doc) G.push(`\t// ${pascal(field.key)}: ${field.doc}`);
    const [name, typeStr, tag] = goField(field);
    G.push(`\t${name} ${typeStr} ${tag}`);
  }
  G.push("}");
  G.push("");
}

const commsOut = G.join("\n");

if (!process.argv.includes("--check")) {
  mkdirSync(dirname(COMMS_OUT_PATH), { recursive: true });
  writeFileSync(COMMS_OUT_PATH, commsOut, "utf8");
  console.error(`gen-go: wrote ${COMMS_OUT_PATH} (${ir.types.length} models + ${ir.consts.length} consts derived from workspace-comms/*.schema.json)`);
}

// ===========================================================================
// marketplace catalog contract models (Wave 3). Derived from the three artifact
// manifests (plugin-manifest/, workspace-template/, org-template/) + the unified
// catalog-entry envelope (catalog/) via the SAME shared IR walker (buildModelIR
// over the catalog surface dirs). The mcp + workspace-comms output above is left
// BYTE-IDENTICAL — this is a strictly-additional third file in the same
// `package molcontracts`. Type/field names are STRUCTURAL (schema shape); the
// RuntimeId is an open bounded/path-safe string generated from the adapter
// contract. The per-kind catalog `spec` is a oneOf keyed on
// `kind`; codegen models the discriminated spec types (CatalogEntryPluginSpec,
// CatalogEntryWorkspaceTemplateSpec, CatalogEntryOrgTemplateSpec) as named
// structs and the envelope's open `spec` field as map[string]any.
// ===========================================================================

const CATALOG_DIRS = ["plugin-manifest", "workspace-template", "org-template", "catalog"];
const CATALOG_OUT_PATH = resolve(repoRoot, "gen/go/molcontracts/catalog_gen.go");
const catalogIR = buildModelIR(contractsRoot, CATALOG_DIRS);

const C = [];
C.push("// Code generated by tools/gen-go.mjs — DO NOT EDIT.");
C.push("//");
C.push("// Source of truth: the marketplace catalog contract schemas");
C.push("// (plugin-manifest/, workspace-template/, org-template/, catalog/ — each");
C.push("// validated against its sibling *.contract.json instance by");
C.push("// .gitea/workflows/validate-contracts.yml). Every type, field and constant");
C.push("// below is DERIVED from those schemas, never hand-written. Regenerate with:");
C.push("//");
C.push("//     node tools/gen-go.mjs");
C.push("//");
C.push("// A CI drift gate (.gitea/workflows/codegen-drift.yml) re-runs the generator and");
C.push("// fails if this file differs from a fresh regeneration, per RFC molecule-core#3285 §14.");
C.push("");
C.push("package molcontracts");
C.push("");

if (catalogIR.consts.length) {
  C.push("// Load-bearing string literals pinned by `const` in the catalog contract schemas.");
  C.push("const (");
  catalogIR.consts.forEach((c, i) => {
    C.push(`\t// ${c.name} is pinned by ${c.source}: ${c.doc}`);
    C.push(`\t${c.name} = ${lit(c.value)}`);
    if (i !== catalogIR.consts.length - 1) C.push("");
  });
  C.push(")");
  C.push("");
}

for (const def of catalogIR.types) {
  if (def.doc) C.push(`// ${def.name}: ${def.doc}`);
  else C.push(`// ${def.name} is derived from ${def.source}.`);
  if (def.fields.length === 0) {
    C.push(`type ${def.name} struct{}`);
    C.push("");
    continue;
  }
  C.push(`type ${def.name} struct {`);
  for (const field of def.fields) {
    if (field.doc) C.push(`\t// ${pascal(field.key)}: ${field.doc}`);
    const [name, typeStr, tag] = goField(field);
    C.push(`\t${name} ${typeStr} ${tag}`);
  }
  C.push("}");
  C.push("");
}

const catalogOut = C.join("\n");

if (!process.argv.includes("--check")) {
  mkdirSync(dirname(CATALOG_OUT_PATH), { recursive: true });
  writeFileSync(CATALOG_OUT_PATH, catalogOut, "utf8");
  console.error(`gen-go: wrote ${CATALOG_OUT_PATH} (${catalogIR.types.length} models + ${catalogIR.consts.length} consts derived from the catalog contract schemas)`);
}

// ===========================================================================
// idle-prompt digest contract models (task #219, phase 1). Derived from the
// consolidated idle-prompt contract layer (idle-prompt/) via the SAME shared IR
// walker. The mcp + workspace-comms + catalog output above is left
// BYTE-IDENTICAL — this is a strictly-additional fourth file in the same
// `package molcontracts`. The layer pins the assembler policy surface (wake,
// sort, delta, empty/sleep, limits, failure, trust, header voice) plus the
// canonical contribution envelope, task-queue row shape, and goal-state
// cadence semantics; the canonical assembler implementation lives in
// molecule_runtime and consumes these bindings.
// ===========================================================================

const IDLE_PROMPT_DIRS = ["idle-prompt"];
const IDLE_PROMPT_OUT_PATH = resolve(repoRoot, "gen/go/molcontracts/idle_prompt_gen.go");
const idlePromptIR = buildModelIR(contractsRoot, IDLE_PROMPT_DIRS);

const IP = [];
IP.push("// Code generated by tools/gen-go.mjs — DO NOT EDIT.");
IP.push("//");
IP.push("// Source of truth: the idle-prompt digest contract schema");
IP.push("// (idle-prompt/ — validated against its sibling *.contract.json instance by");
IP.push("// .gitea/workflows/validate-contracts.yml). Every type, field and constant");
IP.push("// below is DERIVED from that schema, never hand-written. Regenerate with:");
IP.push("//");
IP.push("//     node tools/gen-go.mjs");
IP.push("//");
IP.push("// A CI drift gate (.gitea/workflows/codegen-drift.yml) re-runs the generator and");
IP.push("// fails if this file differs from a fresh regeneration, per RFC molecule-core#3285 §14.");
IP.push("");
IP.push("package molcontracts");
IP.push("");

if (idlePromptIR.consts.length) {
  IP.push("// Load-bearing string literals pinned by `const` in the idle-prompt contract schema.");
  IP.push("const (");
  idlePromptIR.consts.forEach((c, i) => {
    IP.push(`\t// ${c.name} is pinned by ${c.source}: ${c.doc}`);
    IP.push(`\t${c.name} = ${lit(c.value)}`);
    if (i !== idlePromptIR.consts.length - 1) IP.push("");
  });
  IP.push(")");
  IP.push("");
}

for (const def of idlePromptIR.types) {
  if (def.doc) IP.push(`// ${def.name}: ${def.doc}`);
  else IP.push(`// ${def.name} is derived from ${def.source}.`);
  if (def.fields.length === 0) {
    IP.push(`type ${def.name} struct{}`);
    IP.push("");
    continue;
  }
  IP.push(`type ${def.name} struct {`);
  for (const field of def.fields) {
    if (field.doc) IP.push(`\t// ${pascal(field.key)}: ${field.doc}`);
    const [name, typeStr, tag] = goField(field);
    IP.push(`\t${name} ${typeStr} ${tag}`);
  }
  IP.push("}");
  IP.push("");
}

const idlePromptOut = IP.join("\n");

if (!process.argv.includes("--check")) {
  mkdirSync(dirname(IDLE_PROMPT_OUT_PATH), { recursive: true });
  writeFileSync(IDLE_PROMPT_OUT_PATH, idlePromptOut, "utf8");
  console.error(`gen-go: wrote ${IDLE_PROMPT_OUT_PATH} (${idlePromptIR.types.length} models + ${idlePromptIR.consts.length} consts derived from the idle-prompt contract schema)`);
}

}
