#!/usr/bin/env node
// gen-registry.mjs — generate the container-registry bindings from the SSOT.
//
// Source of truth: contracts/registry.yaml (validated against
// contracts/registry.schema.json). Every VALUE emitted below (the canonical
// prefix/host/owner, the env-var + CI-var seam names, the retention cap) is
// DERIVED from that YAML — edit the YAML, re-run, and the bindings change with
// it. This mirrors gen-go.mjs's split: VALUES from the contract, doc prose here.
//
// Outputs (NEVER hand-edited — pinned by .gitea/workflows/registry-ssot-drift.yml):
//   gen/registry/registry.env     — a `source`-able fragment for CI / compose /
//                                   shell scripts (MOLECULE_IMAGE_REGISTRY=…,
//                                   MOLECULE_REGISTRY=…, retention knobs).
//   gen/go/registry/registry.go   — package registry: the Go consts CP + core
//                                   re-export instead of baking their own host.
//
// Dependency-free (Node stdlib only), like the sibling generators, so the CI
// drift gate needs only `node` — no npm install. registry.yaml is a small,
// fully-controlled document, so a focused reader for its exact key shape is
// reliable; the output is independently gated by the drift job + the pytest
// conformance test (which parses the YAML with REAL pyyaml).
//
// Usage:
//   node tools/gen-registry.mjs            # write gen/registry + gen/go/registry
//   node tools/gen-registry.mjs --check    # print to stdout, do not write

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..");
const YAML_PATH = resolve(repoRoot, "contracts/registry.yaml");
const ENV_OUT = resolve(repoRoot, "gen/registry/registry.env");
const GO_OUT = resolve(repoRoot, "gen/go/registry/registry.go");

const check = process.argv.includes("--check");

// --- focused reader for the exact shape of contracts/registry.yaml ----------
// Extracts the specific scalar keys the bindings need. Keys are addressed by
// (indent, name) so a nested `host:` under `registry:` is unambiguous. Values
// are unquoted scalars or inline flow arrays ([a, b]).
const lines = readFileSync(YAML_PATH, "utf8").split(/\r?\n/);

function stripComment(line) {
  let inS = false, inD = false, depth = 0;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "'" && !inD) inS = !inS;
    else if (c === '"' && !inS) inD = !inD;
    else if (!inS && !inD && c === "[") depth++;
    else if (!inS && !inD && c === "]") depth = Math.max(0, depth - 1);
    else if (c === "#" && !inS && !inD && depth === 0) {
      if (i === 0 || line[i - 1] === " " || line[i - 1] === "\t") return line.slice(0, i);
    }
  }
  return line;
}
function unquote(s) {
  s = s.trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    return s.slice(1, -1);
  }
  return s;
}
function parseFlowArray(s) {
  s = s.trim();
  if (!s.startsWith("[") || !s.endsWith("]")) return null;
  const inner = s.slice(1, -1).trim();
  if (inner === "") return [];
  return inner.split(",").map((x) => unquote(x));
}

// Build a list of {indent, key, raw} for scalar `key: value` lines.
const rows = [];
for (const rawLine of lines) {
  const line = stripComment(rawLine);
  if (!line.trim()) continue;
  const m = line.match(/^(\s*)([A-Za-z0-9_]+):\s?(.*)$/);
  if (!m) continue;
  rows.push({ indent: m[1].length, key: m[2], raw: m[3] });
}

// get(indent, key[, afterKey@indent]) — first matching row. For the simple,
// unique keys we need this is sufficient (registry.yaml has one of each).
function get(indent, key) {
  const r = rows.find((x) => x.indent === indent && x.key === key);
  return r ? unquote(r.raw) : undefined;
}

const D = {
  host: get(2, "host"),
  owner: get(2, "owner"),
  prefix: get(2, "prefix"),
  push_host: get(2, "push_host") || "",
  auth_kind: get(4, "kind"),
  username_env: get(4, "username_env") || "",
  password_env: get(4, "password_env") || "",
  env_var: get(0, "env_var"),
  ci_var: get(0, "ci_var"),
  ci_push_host_var: get(0, "ci_push_host_var") || "",
  keep_max_versions: get(2, "keep_max_versions"),
  keep_tags: (() => {
    const r = rows.find((x) => x.indent === 2 && x.key === "keep_tags");
    return r ? parseFlowArray(r.raw) || [] : [];
  })(),
  pin_source: get(2, "pin_source") || "",
};

// --- sanity: the contract's prefix MUST equal host/owner -------------------
if (`${D.host}/${D.owner}` !== D.prefix) {
  console.error(
    `gen-registry: INVARIANT VIOLATION — prefix (${D.prefix}) != host/owner (${D.host}/${D.owner})`
  );
  process.exit(1);
}
for (const [k, v] of Object.entries(D)) {
  if (v === undefined) {
    console.error(`gen-registry: missing required key '${k}' in contracts/registry.yaml`);
    process.exit(1);
  }
}

// --- gen/registry/registry.env ---------------------------------------------
const envOut = [
  "# Code generated by tools/gen-registry.mjs — DO NOT EDIT.",
  "# Source of truth: contracts/registry.yaml. Regenerate with:",
  "#   node tools/gen-registry.mjs",
  "#",
  "# `source` this fragment (or read it with a KEY=VALUE parser) to derive every",
  "# registry reference from the ONE SSOT. Both seams below carry the SAME prefix:",
  "#   MOLECULE_IMAGE_REGISTRY — the Go runtime override (CP + core RegistryPrefix)",
  "#   MOLECULE_REGISTRY       — the CI publisher IMAGE_NAME derivation var",
  "",
  `MOLECULE_REGISTRY_PREFIX=${D.prefix}`,
  `MOLECULE_REGISTRY_HOST=${D.host}`,
  `MOLECULE_REGISTRY_OWNER=${D.owner}`,
  `MOLECULE_REGISTRY_PUSH_HOST=${D.push_host}`,
  `MOLECULE_REGISTRY_AUTH_KIND=${D.auth_kind}`,
  `MOLECULE_REGISTRY_USERNAME_ENV=${D.username_env}`,
  `MOLECULE_REGISTRY_PASSWORD_ENV=${D.password_env}`,
  "",
  "# The two derivation seams — both default to the canonical prefix. A deploy",
  "# or CI run overrides EITHER to switch registries with no code edit.",
  `${D.env_var}=${D.prefix}`,
  `${D.ci_var}=${D.prefix}`,
  "",
  "# Retention (enforced by operator-config/ops/registry-retention-prune.sh).",
  `MOLECULE_REGISTRY_KEEP_MAX_VERSIONS=${D.keep_max_versions}`,
  `MOLECULE_REGISTRY_KEEP_TAGS=${D.keep_tags.join(",")}`,
  `MOLECULE_REGISTRY_PIN_SOURCE=${D.pin_source}`,
  "",
].join("\n");

// --- gen/go/registry/registry.go -------------------------------------------
const goLit = (s) => JSON.stringify(s);
const tagsLit = "[]string{" + D.keep_tags.map((t) => goLit(t)).join(", ") + "}";
const goOut = [
  "// Code generated by tools/gen-registry.mjs — DO NOT EDIT.",
  "// Source of truth: contracts/registry.yaml.",
  "",
  "// Package registry is the generated Go binding for the MoleculesAI container",
  "// image registry SSOT (contracts/registry.yaml). CP + core provisioners",
  "// re-export Prefix() as the baked default their RegistryPrefix() falls back to",
  "// when MOLECULE_IMAGE_REGISTRY is unset, so all three planes share ONE default.",
  "package registry",
  "",
  "// EnvVar is the environment variable a deploy sets to override the baked",
  "// default registry prefix (read by CP + core RegistryPrefix()).",
  `const EnvVar = ${goLit(D.env_var)}`,
  "",
  "// CIVar is the Gitea Actions org/repo variable CI publishers derive",
  "// IMAGE_NAME from (fallback: DefaultPrefix).",
  `const CIVar = ${goLit(D.ci_var)}`,
  "",
  "// DefaultPrefix is the canonical host[/owner] every image ref formats against.",
  `const DefaultPrefix = ${goLit(D.prefix)}`,
  "",
  "// Host is the bare docker-login registry host (no /owner suffix).",
  `const Host = ${goLit(D.host)}`,
  "",
  "// Owner is the registry namespace/owner path segment.",
  `const Owner = ${goLit(D.owner)}`,
  "",
  "// PushHost is the optional CF-bypass push endpoint (empty = push to Host).",
  `const PushHost = ${goLit(D.push_host)}`,
  "",
  "// KeepMaxVersions is the retention cap: max versions kept per package.",
  `const KeepMaxVersions = ${parseInt(D.keep_max_versions, 10)}`,
  "",
  "// KeepTags are tag values whose version is never pruned by retention GC.",
  "func KeepTags() []string {",
  `\treturn ${tagsLit}`,
  "}",
  "",
];

if (check) {
  process.stdout.write("=== gen/registry/registry.env ===\n" + envOut + "\n");
  process.stdout.write("=== gen/go/registry/registry.go ===\n" + goOut.join("\n") + "\n");
} else {
  mkdirSync(dirname(ENV_OUT), { recursive: true });
  mkdirSync(dirname(GO_OUT), { recursive: true });
  writeFileSync(ENV_OUT, envOut, "utf8");
  writeFileSync(GO_OUT, goOut.join("\n"), "utf8");
  console.log(`wrote ${ENV_OUT}`);
  console.log(`wrote ${GO_OUT}`);
}
