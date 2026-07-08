# idle-prompt — consolidated idle digest contract

JSON-Schema (draft 2020-12) IDL for the **consolidated idle-prompt digest**
(a.k.a. the email/inbox kernel, task #219): one `idle-prompt.schema.json` (the
shape) plus one `idle-prompt.contract.json` (the canonical settled-policy
instance). Design SSOT: `consolidated-idle-prompt-design.html` v2 (2026-07-07,
operator-reviewed) and the three phase-1 provider design docs
(identity-capabilities, task-queue, goal-state).

## What it pins

| Block | Load-bearing pins |
|---|---|
| `ownership` | shape owner = this repo; **assembler implementation owner = `molecule_runtime`** (no reimplement-per-runtime) |
| `wake` | idle-fire 300s is a **second** lease consumer — `stall_lease_is_separate` guards against retuning `MOLECULE_TURN_LEASE_TTL_SECONDS`; atomic-fire recheck precondition |
| `sort` | D1/D2: pinned band → urgent band above ALL base tiers → base tiers ascending |
| `delta` | assembler-computed SHA-256 over the canonical tuple; provider hashes advisory; **baselines recomputed post-`on_included`** (prevents the cadence double-fire); `age_band` is the only time field |
| `empty` | sleep; the pinned header never counts toward emptiness; event-driven re-arm + the single scheduler sleep-until exception |
| `limits` / `failure` / `trust` | size caps + deterministic truncation; skip-and-degrade with hash exclusion; reserved ids, pinned reserved to identity-capabilities, third-party caps, state-folder jailing |
| `header` | operator ruling 2026-07-07: second person — you_are / responsibility / priorities / native_tools grouped by origin (platform MCP = platform agents only) |
| `task_queue` | row shape + status/origin enums (D3 user-pivot rows and §5.2 lifecycle resume rows live here); runtime-owned store; kernel-gated writes |
| `goal_state` | cadence band rides `age_band` (just-included/due); `.migrated` marker + source-rank overwrite rule |
| `correlation` | introduced by this contract — minted on send-with-expects-reply, echoed on reply, fallback matchers for mixed fleets, carried by bounce |

User prompts are **never** digest contributions (D3) — they are synchronous
top-priority input; the interrupted task stays durable in the task queue.

## Derivation & validation

Schemas validate **offline** — local `#/$defs` refs only, no cross-file `$ref`.
CI: the `validate` job in `.gitea/workflows/contracts-codegen-drift.yml`
auto-covers this pair via the `contracts/*/*.contract.json` glob;
`tests/test_idle_prompt_contract.py` carries the prove-fail negatives.

## Generated bindings

`tools/gen-{go,ts,python}.mjs` emit `gen/go/molcontracts/idle_prompt_gen.go`,
`gen/ts/idle_prompt_gen.ts`, `gen/python/idle_prompt_gen.py` from this layer
(walker: `tools/lib/comms-schema.mjs`). Regenerate with
`node tools/gen-go.mjs && node tools/gen-ts.mjs && node tools/gen-python.mjs`.
If you change the contract, update both files (schema + instance), bump the
`$comment` contract-version, and regenerate `gen/`.

## Status

Phase 1 (identity-capabilities · task-queue · goal-state) builds against this
layer; sent-folder / inbound-a2a / delegation-results / scheduler are phase 2.
The platform-side lane (a2a_queue `correlation_id`, user-origin marker on
proxied user messages, requests read API) is sequenced with this contract in
molecule-core.
