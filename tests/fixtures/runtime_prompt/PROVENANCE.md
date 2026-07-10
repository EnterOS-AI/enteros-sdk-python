# Vendored runtime prompt canonical text (SSOT mirror)

These `*.txt` files are **byte-for-byte copies** of the two prompt-assembly
canonical-text constants that live in the runtime engine:

    molecule-ai-workspace-runtime/molecule_runtime/prompt.py
      - BASE_PLATFORM_PROMPT          -> BASE_PLATFORM_PROMPT.txt
      - ORCHESTRATOR_ONLY_GUARDRAIL   -> ORCHESTRATOR_ONLY_GUARDRAIL.txt

Source commit: `04b305718e0ed23caa0ec62428cb2231bc9cdc6a`
Source repo:   https://git.moleculesai.app/molecule-ai/molecule-ai-workspace-runtime

Each file holds the constant's Python string value VERBATIM (no added trailing
newline, no re-wrapping) — written by `ast.literal_eval` on the source, so the
bytes are exactly what the runtime prepends to every workspace's system prompt.

SHA-256 (over the UTF-8 bytes):

    BASE_PLATFORM_PROMPT.txt         73f720144f6dc98cabfc8531ae192a78a63b9c4513d2ef871d24c3de2c9bf496
    ORCHESTRATOR_ONLY_GUARDRAIL.txt  88f70c8de6056c4c267fdb791efe4d94929a2d7cd32149154305e1e2ed1f46e5

## Why vendored (and what the gate checks)

`contracts/prompt/prompt-assembly-delivery.contract.json` embeds these exact
strings under `canonical_text.base_platform_prompt.text` and
`canonical_text.orchestrator_only_guardrail.text`. That embedded copy is the
SDK's SSOT-mirror of the runtime producer — the prompt contract is only "REAL"
(machine-enforced) if that mirror stays byte-identical to what the runtime
actually emits. A drift means the SDK claims a base frame / orchestrator gag the
runtime no longer produces (or vice-versa), silently un-gagging a concierge or
changing the platform identity frame.

`tests/test_prompt_canonical_text_contract.py` is the TestSSOT gate:

  1. It asserts the CONTRACT's embedded `canonical_text.*.text` equals these
     vendored bytes — this runs fully offline in CI, no runtime clone, no token.
  2. When a runtime checkout is present (env `MOLECULE_RUNTIME_SRC`, or a sibling
     `../molecule-ai-workspace-runtime`), it ALSO asserts the LIVE runtime
     constants equal these vendored bytes — so the vendored mirror can't silently
     drift from the real producer. Absent a checkout it fails OPEN on that leg
     only (the offline contract-vs-vendored leg is always enforced).

To update after an intentional runtime prompt change: re-copy both constants
from `prompt.py` at the new commit (the test prints a ready-to-run snippet on
failure), bump the commit + SHAs above, and update the contract's embedded text
in the same PR so all three move together.
