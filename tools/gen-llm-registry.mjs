#!/usr/bin/env node
// gen-llm-registry.mjs — project the LLM-registry SSOT into its Go embed target.
//
// Source of truth: contracts/llm-registry/llm-registry.yaml (validated against
// contracts/llm-registry/llm-registry.schema.json by tests/test_llm_registry_contract.py).
// The Go binding gen/go/llmregistry/llmregistry.go `//go:embed`s the sibling
// gen/go/llmregistry/llm-registry.yaml; molecule-core embeds THAT via
// go.moleculesai.app/sdk/gen/go/llmregistry. This generator keeps the embed copy
// byte-identical to the contracts source so the two SDK copies can never drift —
// editing contracts/llm-registry/llm-registry.yaml is the ONLY edit that moves
// the registry everywhere.
//
// Dependency-free (Node stdlib only), like the sibling generators, so the CI
// drift gate needs only `node` — no npm install. The projection is a verbatim
// byte-copy: the registry's semantic integrity (schema + unique names + resolving
// runtime refs + RE2 regexes + RFC #340 native matrix) is enforced by the pytest
// conformance test with REAL pyyaml/jsonschema, not re-implemented here.
//
// Usage:
//   node tools/gen-llm-registry.mjs            # write gen/go/llmregistry/llm-registry.yaml
//   node tools/gen-llm-registry.mjs --check    # exit 1 if the embed copy is stale (no write)

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..");
const SRC = resolve(repoRoot, "contracts/llm-registry/llm-registry.yaml");
const OUT = resolve(repoRoot, "gen/go/llmregistry/llm-registry.yaml");

const check = process.argv.includes("--check");

const src = readFileSync(SRC, "utf8");

// Guard: never project an obviously-empty/decapitated SSOT into the embed.
if (!/^\s*schema_version\s*:/m.test(src) || !/^\s*providers\s*:/m.test(src) || !/^\s*runtimes\s*:/m.test(src)) {
  console.error("gen-llm-registry: FATAL — contracts/llm-registry/llm-registry.yaml is missing schema_version/providers/runtimes");
  process.exit(2);
}

let current = "";
try {
  current = readFileSync(OUT, "utf8");
} catch {
  current = "";
}

if (check) {
  if (current !== src) {
    console.error("gen-llm-registry --check: DRIFT — gen/go/llmregistry/llm-registry.yaml differs from contracts/llm-registry/llm-registry.yaml.");
    console.error("The embed copy is NEVER hand-edited. Regenerate with 'node tools/gen-llm-registry.mjs' and commit.");
    process.exit(1);
  }
  console.log("gen-llm-registry --check: OK — embed copy in sync with the contracts SSOT");
  process.exit(0);
}

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, src, "utf8");
console.error(`gen-llm-registry: wrote ${OUT} (byte-copy of contracts/llm-registry/llm-registry.yaml, ${src.length} bytes)`);
