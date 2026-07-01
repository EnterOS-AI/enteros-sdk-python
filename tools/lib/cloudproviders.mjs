// cloudproviders.mjs — shared loader + validator for the cloud-provider SSOT.
//
// Reads contracts/cloudproviders.yaml and returns a normalized JS object that
// the three code generators (gen-go.mjs / gen-ts.mjs / gen-python.mjs) consume.
// It also enforces the SEMANTIC invariants that the JSON Schema cannot express
// (unique ids, alias uniqueness, exactly one is_local, default resolves, the
// migration-056 persist-set equality, backend_key == persist), so ALL THREE
// generators fail LOUD on a malformed SSOT rather than emitting bad bindings.
//
// Why a purpose-built YAML reader instead of a dependency: the codegen-drift CI
// runs `node tools/gen-*.mjs` with NO `npm install` (mirrors
// molecule-contracts' node-only gate). contracts/cloudproviders.yaml is a
// small, fully-controlled document, so a focused reader for its exact shape is
// reliable and dependency-free. The OUTPUT is independently gated three ways
// (the moved-verbatim Go behavior test, the drift gate, and the Python
// jsonschema conformance test that uses REAL pyyaml), so any parser
// misreading surfaces immediately.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const repoRoot = resolve(here, "..", "..");
export const YAML_PATH = resolve(repoRoot, "contracts/cloudproviders.yaml");

// The organizations.provider values migration 056 makes DB-legal:
//   molecule-controlplane/migrations/056_org_provider_local.up.sql
//   CHECK (provider IN ('', 'aws', 'hetzner', 'gcp', 'local'))
// {every provider.persist} ∪ {""} MUST equal this set exactly.
export const MIGRATION_056_CHECK_SET = ["", "aws", "gcp", "hetzner", "local"];

// ---------------------------------------------------------------------------
// Minimal YAML reader for the exact shape of contracts/cloudproviders.yaml:
//   top-level scalars (version / default_id / empty_normalizes_to)
//   providers: <sequence of maps> where each item is `- id: x` followed by
//   indented `key: value` lines; values are scalars or inline flow arrays
//   ([] or [a, b]). Full-line and trailing `#` comments are stripped.
// ---------------------------------------------------------------------------

function stripComment(line) {
  // Remove a trailing comment, honoring single/double quotes and [] brackets so
  // a `#` inside a quoted scalar or flow array is preserved. Our SSOT has none,
  // but this keeps the reader honest.
  let inS = false, inD = false, depth = 0;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "'" && !inD) inS = !inS;
    else if (c === '"' && !inS) inD = !inD;
    else if (!inS && !inD && (c === "[")) depth++;
    else if (!inS && !inD && (c === "]")) depth = Math.max(0, depth - 1);
    else if (c === "#" && !inS && !inD && depth === 0) {
      if (i === 0 || line[i - 1] === " " || line[i - 1] === "\t") return line.slice(0, i);
    }
  }
  return line;
}

function unquote(s) {
  s = s.trim();
  if (s.length >= 2 && ((s[0] === '"' && s.at(-1) === '"') || (s[0] === "'" && s.at(-1) === "'"))) {
    return s.slice(1, -1);
  }
  return s;
}

function coerceScalar(raw) {
  const s = raw.trim();
  if (s === "") return "";
  if (s.startsWith("[")) {
    // inline flow array
    const inner = s.replace(/^\[/, "").replace(/\]$/, "").trim();
    if (inner === "") return [];
    return inner.split(",").map((x) => unquote(x));
  }
  if (s === "true") return true;
  if (s === "false") return false;
  if (/^-?\d+$/.test(s)) return parseInt(s, 10);
  return unquote(s);
}

function parseYaml(text) {
  const out = { providers: [] };
  let mode = "top"; // "top" | "providers"
  let cur = null;
  const rawLines = text.split(/\r?\n/);
  for (const rawLine of rawLines) {
    const line = stripComment(rawLine);
    if (line.trim() === "") continue;
    const indent = line.length - line.trimStart().length;
    const body = line.trim();

    if (indent === 0) {
      mode = "top";
      const m = body.match(/^([A-Za-z0-9_]+):\s*(.*)$/);
      if (!m) throw new Error(`cloudproviders.yaml: cannot parse top-level line: ${rawLine}`);
      const [, key, val] = m;
      if (key === "providers") {
        mode = "providers";
        out.providers = [];
      } else {
        out[key] = coerceScalar(val);
      }
      continue;
    }

    if (mode === "providers") {
      if (body.startsWith("- ")) {
        cur = {};
        out.providers.push(cur);
        const kv = body.slice(2).trim();
        const m = kv.match(/^([A-Za-z0-9_]+):\s*(.*)$/);
        if (!m) throw new Error(`cloudproviders.yaml: cannot parse list item: ${rawLine}`);
        cur[m[1]] = coerceScalar(m[2]);
      } else if (cur) {
        const m = body.match(/^([A-Za-z0-9_]+):\s*(.*)$/);
        if (!m) throw new Error(`cloudproviders.yaml: cannot parse provider field: ${rawLine}`);
        cur[m[1]] = coerceScalar(m[2]);
      } else {
        throw new Error(`cloudproviders.yaml: provider field before any '- ' item: ${rawLine}`);
      }
    }
  }
  return out;
}

function fail(msg) {
  console.error(`cloudproviders SSOT invariant violation: ${msg}`);
  process.exit(1);
}

// loadCloudProviders reads + validates the SSOT and returns the normalized data.
export function loadCloudProviders() {
  const data = parseYaml(readFileSync(YAML_PATH, "utf8"));

  if (!Array.isArray(data.providers) || data.providers.length === 0) {
    fail("no providers defined");
  }

  const ids = new Set();
  const aliases = new Set();
  let localCount = 0;
  const persistSet = new Set([""]);

  for (const p of data.providers) {
    for (const req of ["id", "display", "backend_key", "persist"]) {
      if (typeof p[req] !== "string" || p[req] === "") {
        fail(`provider ${JSON.stringify(p.id)} missing required string field '${req}'`);
      }
    }
    if (typeof p.is_local !== "boolean") {
      fail(`provider ${JSON.stringify(p.id)} field 'is_local' must be a boolean`);
    }
    if (p.aliases === undefined) p.aliases = [];
    if (!Array.isArray(p.aliases)) fail(`provider ${JSON.stringify(p.id)} aliases must be an array`);
    if (ids.has(p.id)) fail(`duplicate provider id ${JSON.stringify(p.id)}`);
    ids.add(p.id);
    if (p.is_local) localCount++;
    persistSet.add(p.persist);
    if (p.backend_key !== p.persist) {
      fail(`provider ${JSON.stringify(p.id)}: backend_key (${p.backend_key}) must equal persist (${p.persist}) for every current row`);
    }
  }

  // aliases: unique, and not colliding with any id or another alias.
  for (const p of data.providers) {
    for (const a of p.aliases) {
      if (ids.has(a)) fail(`alias ${JSON.stringify(a)} on ${p.id} collides with a provider id`);
      if (aliases.has(a)) fail(`alias ${JSON.stringify(a)} is defined more than once`);
      aliases.add(a);
    }
  }

  if (localCount !== 1) fail(`exactly one provider must have is_local:true, found ${localCount}`);

  if (typeof data.default_id !== "string" || !ids.has(data.default_id)) {
    fail(`default_id ${JSON.stringify(data.default_id)} does not resolve to a provider id`);
  }
  if (data.empty_normalizes_to !== undefined && data.empty_normalizes_to !== data.default_id) {
    fail(`empty_normalizes_to (${data.empty_normalizes_to}) must equal default_id (${data.default_id})`);
  }

  // {persist} ∪ {""} == migration-056 CHECK set, exactly.
  const got = [...persistSet].sort();
  const want = [...MIGRATION_056_CHECK_SET].sort();
  if (got.length !== want.length || got.some((v, i) => v !== want[i])) {
    fail(`persist set ∪ {""} = [${got.join(", ")}] must equal the migration-056 CHECK set [${want.join(", ")}]`);
  }

  return data;
}

// localFirst returns providers sorted is_local-first (stable within), preserving
// the SSOT order otherwise. This is the const-block order (local box first, then
// the clouds in SSOT order) — distinct from All order (SSOT order as-is).
export function localFirst(providers) {
  return [...providers].sort((a, b) => Number(b.is_local) - Number(a.is_local));
}
