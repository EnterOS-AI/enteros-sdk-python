"""TestSSOT gate: the prompt contract's canonical text is byte-identical to the
runtime producer.

``contracts/prompt/prompt-assembly-delivery.contract.json`` embeds two
load-bearing strings under ``canonical_text``:

  * ``base_platform_prompt.text``       — the platform identity frame prepended
    to EVERY workspace's system prompt (``molecule_runtime.prompt.BASE_PLATFORM_PROMPT``).
  * ``orchestrator_only_guardrail.text``— the concierge-only "you NEVER do the
    work yourself" gag, injected when ``mcp_server_present()``
    (``molecule_runtime.prompt.ORCHESTRATOR_ONLY_GUARDRAIL``).

The contract is only REAL if that embedded copy stays byte-identical to what the
runtime actually emits. A silent drift means the SDK advertises a base frame /
orchestrator gag the runtime no longer produces — exactly the class of failure
where a concierge on a stale template is left un-gagged and self-adopts work.

This gate mirrors the existing vendored-schema conformance pattern
(``test_workspace_comms_conformance.py``): the runtime constants are vendored
byte-for-byte under ``tests/fixtures/runtime_prompt/`` (see PROVENANCE.md) so the
core check runs fully offline in CI. Two legs:

  A. OFFLINE, always enforced — the CONTRACT's embedded text == the vendored
     bytes. Reds if either the contract or the vendored mirror is edited alone.
  B. CROSS-REPO, best-effort — when a runtime checkout is available, the LIVE
     ``prompt.py`` constants == the vendored bytes, so the mirror itself can't
     drift from the real producer unnoticed. Fails OPEN (skips) when no checkout
     is present; leg A still fully guards the contract.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = (
    REPO_ROOT / "contracts" / "prompt" / "prompt-assembly-delivery.contract.json"
)
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "runtime_prompt"

# contract canonical_text key  ->  (vendored fixture file, runtime constant name)
CANONICAL = {
    "base_platform_prompt": (
        "BASE_PLATFORM_PROMPT.txt",
        "BASE_PLATFORM_PROMPT",
    ),
    "orchestrator_only_guardrail": (
        "ORCHESTRATOR_ONLY_GUARDRAIL.txt",
        "ORCHESTRATOR_ONLY_GUARDRAIL",
    ),
}


def _contract_text(key: str) -> str:
    contract = json.loads(CONTRACT_PATH.read_text())
    return contract["canonical_text"][key]["text"]


def _vendored_text(fixture_name: str) -> str:
    return (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")


def _runtime_constants() -> dict[str, str] | None:
    """Extract BASE_PLATFORM_PROMPT / ORCHESTRATOR_ONLY_GUARDRAIL from a live
    runtime checkout by AST literal-eval (no import — the runtime pkg has heavy
    deps we don't want in the SDK test env). Returns None if no checkout found.
    """
    candidates = []
    env = os.environ.get("MOLECULE_RUNTIME_SRC")
    if env:
        candidates.append(Path(env))
    # sibling checkout next to this repo (the common local layout)
    candidates.append(REPO_ROOT.parent / "molecule-ai-workspace-runtime")

    for base in candidates:
        prompt_py = base / "molecule_runtime" / "prompt.py"
        if prompt_py.is_file():
            tree = ast.parse(prompt_py.read_text(encoding="utf-8"))
            out: dict[str, str] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if (
                            isinstance(t, ast.Name)
                            and t.id in ("BASE_PLATFORM_PROMPT", "ORCHESTRATOR_ONLY_GUARDRAIL")
                        ):
                            val = ast.literal_eval(node.value)
                            if isinstance(val, str):
                                out[t.id] = val
            if out:
                return out
    return None


# ---------------------------------------------------------------------------
# Leg A — OFFLINE, always enforced: contract embedded text == vendored mirror
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(CANONICAL))
def test_contract_text_matches_vendored_runtime_ssot(key: str) -> None:
    fixture_name, const_name = CANONICAL[key]
    contract_text = _contract_text(key)
    vendored_text = _vendored_text(fixture_name)
    assert contract_text == vendored_text, (
        f"prompt contract canonical_text.{key}.text has DRIFTED from the runtime "
        f"SSOT ({const_name}).\n"
        f"The contract's embedded copy MUST stay byte-identical to "
        f"molecule_runtime.prompt.{const_name} (mirrored in "
        f"tests/fixtures/runtime_prompt/{fixture_name}). If the runtime prompt "
        f"changed intentionally, re-vendor the fixture AND update the contract in "
        f"the same PR (see fixtures/runtime_prompt/PROVENANCE.md)."
    )


def test_contract_pins_the_runtime_symbol_names(key: str = "base_platform_prompt") -> None:
    """The contract names the runtime symbol it mirrors; a rename there must be
    reflected so the SSOT pointer stays honest."""
    contract = json.loads(CONTRACT_PATH.read_text())
    assert (
        contract["canonical_text"]["base_platform_prompt"]["symbol"]
        == "molecule_runtime.prompt.BASE_PLATFORM_PROMPT"
    )
    assert (
        contract["canonical_text"]["orchestrator_only_guardrail"]["symbol"]
        == "molecule_runtime.prompt.ORCHESTRATOR_ONLY_GUARDRAIL"
    )


# ---------------------------------------------------------------------------
# Leg B — CROSS-REPO, best-effort: live runtime constants == vendored mirror
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(CANONICAL))
def test_vendored_mirror_matches_live_runtime(key: str) -> None:
    consts = _runtime_constants()
    if consts is None:
        pytest.skip(
            "no runtime checkout found (set MOLECULE_RUNTIME_SRC or place "
            "../molecule-ai-workspace-runtime alongside this repo) — the offline "
            "contract-vs-vendored leg still fully guards the contract"
        )
    fixture_name, const_name = CANONICAL[key]
    assert const_name in consts, (
        f"runtime prompt.py no longer defines {const_name} — the vendored SSOT "
        f"mirror is orphaned"
    )
    assert consts[const_name] == _vendored_text(fixture_name), (
        f"the vendored SSOT mirror tests/fixtures/runtime_prompt/{fixture_name} "
        f"has DRIFTED from the LIVE runtime constant {const_name}. Re-vendor the "
        f"fixture from molecule_runtime/prompt.py and bump PROVENANCE.md, then "
        f"update the contract's canonical_text in the same PR."
    )
