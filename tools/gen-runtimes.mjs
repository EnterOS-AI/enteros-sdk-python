#!/usr/bin/env node
// Generate RuntimeId schemas and language bindings from the adapter contracts.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const runtimeSchemaPath = resolve(repoRoot, "contracts/adapter/runtime-id.schema.json");
const registryPath = resolve(
  repoRoot,
  "contracts/adapter/official-runtimes.registry.json",
);
const runtimeSchema = JSON.parse(readFileSync(runtimeSchemaPath, "utf8"));
const registry = JSON.parse(readFileSync(registryPath, "utf8"));

function fail(message) {
  throw new Error(`gen-runtimes: ${message}`);
}

if (
  runtimeSchema.type !== "string" ||
  runtimeSchema.minLength !== 1 ||
  !Number.isInteger(runtimeSchema.maxLength) ||
  runtimeSchema.maxLength < 1 ||
  typeof runtimeSchema.pattern !== "string" ||
  typeof runtimeSchema.not?.pattern !== "string"
) {
  fail("runtime-id.schema.json must define a bounded string pattern");
}

const idPattern = new RegExp(runtimeSchema.pattern);
const disallowedPattern = new RegExp(runtimeSchema.not.pattern);
const officialEntries = Object.entries(registry.runtimes ?? {});
if (officialEntries.length === 0) fail("official runtime registry is empty");

const official = officialEntries.map(([key, value]) => {
  if (!value || typeof value.name !== "string") {
    fail(`official runtime ${JSON.stringify(key)} has no canonical name`);
  }
  return value.name;
});
const aliases = Object.fromEntries(
  officialEntries
    .filter(([key, value]) => key !== value.name)
    .map(([key, value]) => [key, value.name]),
);

function validRuntimeId(value) {
  const match = typeof value === "string" ? idPattern.exec(value) : null;
  return (
    typeof value === "string" &&
    value.length <= runtimeSchema.maxLength &&
    match !== null &&
    match[0] === value &&
    !disallowedPattern.test(value)
  );
}

for (const id of [...official, ...Object.keys(aliases)]) {
  if (!validRuntimeId(id)) fail(`invalid registry runtime id ${JSON.stringify(id)}`);
}
if (new Set(official).size !== official.length) fail("official ids must be unique");
for (const [alias, target] of Object.entries(aliases)) {
  if (!official.includes(target)) fail(`alias ${alias} points outside the official set`);
}

const runtimeDefinition = {
  type: runtimeSchema.type,
  minLength: runtimeSchema.minLength,
  maxLength: runtimeSchema.maxLength,
  pattern: runtimeSchema.pattern,
  not: runtimeSchema.not,
  description:
    "Open, bounded, path-safe runtime identifier. Official first-party support is discovered separately; known aliases normalize without restricting third-party IDs.",
};

function matchingBrace(text, start) {
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i += 1) {
    const char = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') inString = true;
    else if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  fail("unterminated runtimeId object");
}

function syncSchema(relativePath) {
  const path = resolve(repoRoot, "contracts", relativePath);
  const original = readFileSync(path, "utf8");
  const runtimeKey = original.indexOf('"runtimeId"');
  if (runtimeKey < 0) fail(`${relativePath} has no runtimeId definition`);
  const open = original.indexOf("{", runtimeKey);
  if (open < 0) fail(`${relativePath} runtimeId is not an object`);
  const close = matchingBrace(original, open);
  const keyIndent = original
    .slice(original.lastIndexOf("\n", runtimeKey) + 1, runtimeKey)
    .match(/^\s*/)[0];
  const rendered = JSON.stringify(runtimeDefinition, null, 2)
    .split("\n")
    .map((line, index) => (index === 0 ? line : `${keyIndent}${line}`))
    .join("\n");
  const updated = `${original.slice(0, open)}${rendered}${original.slice(close + 1)}`;
  const parsed = JSON.parse(updated);
  if (JSON.stringify(parsed.$defs?.runtimeId) !== JSON.stringify(runtimeDefinition)) {
    fail(`${relativePath} RuntimeId did not synchronize`);
  }
  writeFileSync(path, updated, "utf8");
}

for (const schema of [
  "plugin-manifest/plugin-manifest.schema.json",
  "workspace-template/workspace-template.schema.json",
  "org-template/org-template.schema.json",
  "catalog/catalog-entry.schema.json",
  "catalog/catalog.schema.json",
  "catalog/publish-request.schema.json",
]) {
  syncSchema(schema);
}

const source =
  "contracts/adapter/runtime-id.schema.json and official-runtimes.registry.json";
const header = `Generated from ${source} by tools/gen-runtimes.mjs. DO NOT EDIT.`;
const maxLength = runtimeSchema.maxLength;
const pattern = runtimeSchema.pattern;

const pythonOfficial = official.map((id) => `    ${JSON.stringify(id)},`).join("\n");
const pythonAliases = Object.entries(aliases)
  .map(([alias, target]) => `    ${JSON.stringify(alias)}: ${JSON.stringify(target)},`)
  .join("\n");
const pythonRuntimeSchema = JSON.stringify(runtimeDefinition, null, 4);
const python = `# ${header}

import re

RUNTIME_ID_MAX_LENGTH = ${maxLength}
RUNTIME_ID_PATTERN = ${JSON.stringify(pattern)}
RUNTIME_ID_DISALLOWED_PATTERN = ${JSON.stringify(runtimeSchema.not.pattern)}
RUNTIME_ID_SCHEMA = ${pythonRuntimeSchema}
_RUNTIME_ID_RE = re.compile(RUNTIME_ID_PATTERN)
_RUNTIME_ID_DISALLOWED_RE = re.compile(RUNTIME_ID_DISALLOWED_PATTERN)

OFFICIAL_RUNTIME_IDS = (
${pythonOfficial}
)
RUNTIME_ID_ALIASES = {
${pythonAliases}
}
OFFICIAL_RUNTIME_IDS_WITH_ALIASES = frozenset((*OFFICIAL_RUNTIME_IDS, *RUNTIME_ID_ALIASES))


def is_valid_runtime_id(runtime_id: object) -> bool:
    """Return whether runtime_id is a bounded, path-safe RuntimeId."""
    return (
        isinstance(runtime_id, str)
        and len(runtime_id) <= RUNTIME_ID_MAX_LENGTH
        and _RUNTIME_ID_RE.fullmatch(runtime_id) is not None
        and _RUNTIME_ID_DISALLOWED_RE.search(runtime_id) is None
    )


def normalize_runtime_id(runtime_id: str) -> str:
    """Normalize a known alias and preserve every other valid RuntimeId."""
    if not isinstance(runtime_id, str):
        raise TypeError("runtime id must be a string")
    if not is_valid_runtime_id(runtime_id):
        raise ValueError(f"invalid runtime id: {runtime_id!r}")
    return RUNTIME_ID_ALIASES.get(runtime_id, runtime_id)


def is_official_runtime_id(runtime_id: object) -> bool:
    """Return whether runtime_id resolves to an official first-party runtime."""
    if not is_valid_runtime_id(runtime_id):
        return False
    return RUNTIME_ID_ALIASES.get(runtime_id, runtime_id) in OFFICIAL_RUNTIME_IDS


__all__ = [
    "OFFICIAL_RUNTIME_IDS",
    "OFFICIAL_RUNTIME_IDS_WITH_ALIASES",
    "RUNTIME_ID_ALIASES",
    "RUNTIME_ID_DISALLOWED_PATTERN",
    "RUNTIME_ID_MAX_LENGTH",
    "RUNTIME_ID_PATTERN",
    "RUNTIME_ID_SCHEMA",
    "is_official_runtime_id",
    "is_valid_runtime_id",
    "normalize_runtime_id",
]
`;
writeFileSync(resolve(repoRoot, "molecule_plugin/_runtime_ids.py"), python, "utf8");
writeFileSync(resolve(repoRoot, "gen/python/runtime_ids_gen.py"), python, "utf8");

const tsOfficial = official.map((id) => `  ${JSON.stringify(id)},`).join("\n");
const tsAliases = Object.entries(aliases)
  .map(([alias, target]) => `  ${JSON.stringify(alias)}: ${JSON.stringify(target)},`)
  .join("\n");
const typescript = `// ${header}

export const RUNTIME_ID_MAX_LENGTH = ${maxLength} as const;
export const RUNTIME_ID_PATTERN = ${JSON.stringify(pattern)} as const;
export const RUNTIME_ID_DISALLOWED_PATTERN = ${JSON.stringify(runtimeSchema.not.pattern)} as const;
const runtimeIdRe = new RegExp(RUNTIME_ID_PATTERN);
const runtimeIdDisallowedRe = new RegExp(RUNTIME_ID_DISALLOWED_PATTERN);

export const OFFICIAL_RUNTIME_IDS = [
${tsOfficial}
] as const;
export type OfficialRuntimeId = (typeof OFFICIAL_RUNTIME_IDS)[number];
export type RuntimeId = string;

export const RUNTIME_ID_ALIASES = {
${tsAliases}
} as const;
export type RuntimeIdAlias = keyof typeof RUNTIME_ID_ALIASES;

export function isValidRuntimeId(runtimeId: unknown): runtimeId is RuntimeId {
  if (typeof runtimeId !== "string" || runtimeId.length > RUNTIME_ID_MAX_LENGTH) {
    return false;
  }
  const match = runtimeIdRe.exec(runtimeId);
  return match !== null
    && match[0] === runtimeId
    && !runtimeIdDisallowedRe.test(runtimeId);
}

export function normalizeRuntimeId(runtimeId: string): RuntimeId {
  if (!isValidRuntimeId(runtimeId)) {
    throw new Error("invalid runtime id: " + JSON.stringify(runtimeId));
  }
  if (Object.prototype.hasOwnProperty.call(RUNTIME_ID_ALIASES, runtimeId)) {
    return (RUNTIME_ID_ALIASES as Record<string, OfficialRuntimeId>)[runtimeId];
  }
  return runtimeId;
}

export function isOfficialRuntimeId(runtimeId: unknown): boolean {
  if (!isValidRuntimeId(runtimeId)) return false;
  const normalized = normalizeRuntimeId(runtimeId);
  return (OFFICIAL_RUNTIME_IDS as readonly string[]).includes(normalized);
}
`;
writeFileSync(resolve(repoRoot, "gen/ts/runtime_ids.generated.ts"), typescript, "utf8");

const goOfficial = official.map((id) => `\t${JSON.stringify(id)},`).join("\n");
const goAliases = Object.entries(aliases)
  .map(([alias, target]) => `\t${JSON.stringify(alias)}: ${JSON.stringify(target)},`)
  .join("\n");
const go = `// Code generated from ${source} by tools/gen-runtimes.mjs. DO NOT EDIT.

package molcontracts

import "regexp"

const RuntimeIDMaxLength = ${maxLength}
const RuntimeIDPattern = ${JSON.stringify(pattern)}
const RuntimeIDDisallowedPattern = ${JSON.stringify(runtimeSchema.not.pattern)}

var runtimeIDRegexp = regexp.MustCompile(RuntimeIDPattern)
var runtimeIDDisallowedRegexp = regexp.MustCompile(RuntimeIDDisallowedPattern)

var OfficialRuntimeIDs = []string{
${goOfficial}
}

var RuntimeIDAliases = map[string]string{
${goAliases}
}

func IsValidRuntimeID(runtimeID string) bool {
\treturn len(runtimeID) <= RuntimeIDMaxLength &&
\t\truntimeIDRegexp.MatchString(runtimeID) &&
\t\t!runtimeIDDisallowedRegexp.MatchString(runtimeID)
}

func NormalizeRuntimeID(runtimeID string) (string, bool) {
\tif !IsValidRuntimeID(runtimeID) {
\t\treturn "", false
\t}
\tif canonical, ok := RuntimeIDAliases[runtimeID]; ok {
\t\treturn canonical, true
\t}
\treturn runtimeID, true
}

func IsOfficialRuntimeID(runtimeID string) bool {
\tnormalized, ok := NormalizeRuntimeID(runtimeID)
\tif !ok {
\t\treturn false
\t}
\tfor _, official := range OfficialRuntimeIDs {
\t\tif normalized == official {
\t\t\treturn true
\t\t}
\t}
\treturn false
}
`;
writeFileSync(resolve(repoRoot, "gen/go/molcontracts/runtime_ids_gen.go"), go, "utf8");

console.error(
  `gen-runtimes: synchronized open RuntimeId plus ${official.length} official runtimes`,
);
