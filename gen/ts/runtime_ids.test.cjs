const assert = require("node:assert/strict");
const runtime = require("./dist/runtime_ids.generated.js");

for (const value of [
  "claude-code",
  "claude_code",
  "acme-agent",
  "acme_agent",
  "constructor",
  "a",
]) {
  assert.equal(runtime.isValidRuntimeId(value), true, value);
}
for (const value of [
  "",
  "../acme",
  "acme/agent",
  "acme\\agent",
  "acme agent",
  "acme\nagent",
  "acme\n",
  "acme\r",
  "acme\u2028",
  "acme\u2029",
  "Acme",
  "acme--agent",
  "a".repeat(runtime.RUNTIME_ID_MAX_LENGTH + 1),
]) {
  assert.equal(runtime.isValidRuntimeId(value), false, value);
}

assert.equal(runtime.normalizeRuntimeId("claude_code"), "claude-code");
assert.equal(runtime.normalizeRuntimeId("acme-agent"), "acme-agent");
assert.equal(runtime.normalizeRuntimeId("constructor"), "constructor");
assert.equal(runtime.isOfficialRuntimeId("acme-agent"), false);
assert.deepEqual(
  [...runtime.OFFICIAL_RUNTIME_IDS].sort(),
  ["claude-code", "codex", "hermes", "openclaw"].sort(),
);
