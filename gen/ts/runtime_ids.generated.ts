// Generated from contracts/adapter/runtime-id.schema.json and official-runtimes.registry.json by tools/gen-runtimes.mjs. DO NOT EDIT.

export const RUNTIME_ID_MAX_LENGTH = 64 as const;
export const RUNTIME_ID_PATTERN = "^[a-z0-9]+([-_][a-z0-9]+)*$" as const;
export const RUNTIME_ID_DISALLOWED_PATTERN = "[^a-z0-9_-]" as const;
const runtimeIdRe = new RegExp(RUNTIME_ID_PATTERN);
const runtimeIdDisallowedRe = new RegExp(RUNTIME_ID_DISALLOWED_PATTERN);

export const OFFICIAL_RUNTIME_IDS = [
  "claude-code",
  "codex",
  "hermes",
  "openclaw",
] as const;
export type OfficialRuntimeId = (typeof OFFICIAL_RUNTIME_IDS)[number];
export type RuntimeId = string;

export const RUNTIME_ID_ALIASES = {
  "claude_code": "claude-code",
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
