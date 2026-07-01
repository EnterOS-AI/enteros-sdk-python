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
// go.moleculesai.app/sdk/cloudprovider. The output is deliberately
// BYTE-IDENTICAL to the retired molecule-go-sdk/cloudprovider/cloudprovider.go
// (the parity oracle), so every existing importer rebuilds with zero source
// churn. The moved-verbatim cloudprovider_test.go pins the behavior; the
// codegen-drift CI pins "gen/ is never hand-edited".
//
// Usage:
//   node tools/gen-go.mjs            # write gen/go/cloudprovider/cloudprovider.go
//   node tools/gen-go.mjs --check    # print to stdout, do not write

import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { loadCloudProviders, localFirst, repoRoot } from "./lib/cloudproviders.mjs";

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
