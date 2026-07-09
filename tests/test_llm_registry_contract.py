"""Schema + invariant conformance gate for the LLM-registry SSOT.

Python-side twin of the Node generator (tools/gen-llm-registry.mjs) and its drift
workflow. Loads the SSOT data (contracts/llm-registry/llm-registry.yaml, via real
pyyaml) and its JSON Schema (contracts/llm-registry/llm-registry.schema.json,
draft 2020-12), then:

  1. asserts the schema itself is a valid draft-2020-12 schema,
  2. asserts the schema ``$id`` is the canonical molecule-ai-sdk URL (tripwire so
     a forked/relocated copy is caught rather than silently validating),
  3. validates the YAML instance against the schema,
  4. asserts the load-bearing SEMANTIC invariants the JSON Schema cannot express —
     the same closed-loop checks molecule-core's providers.parseManifest enforces
     at boot, so a malformed SSOT fails HERE (in the SDK's own CI) rather than
     only in the consumer:
       * provider names are unique,
       * every ``model_prefix_match`` is a compilable regex,
       * every ``runtimes[].providers[].name`` resolves to a real provider
         (RFC #340 — no over-offer that the proxy can't route), and
       * every runtime declares at least one native provider.
  5. asserts the generated Go embed copy (gen/go/llmregistry/llm-registry.yaml) is
     byte-identical to the contracts source, so the "one edit moves it everywhere"
     contract is machine-checked, not just documented.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = REPO_ROOT / "contracts" / "llm-registry"
YAML_PATH = CONTRACTS_DIR / "llm-registry.yaml"
SCHEMA_PATH = CONTRACTS_DIR / "llm-registry.schema.json"
GEN_EMBED_PATH = REPO_ROOT / "gen" / "go" / "llmregistry" / "llm-registry.yaml"

CANONICAL_ID = (
    "https://git.moleculesai.app/molecule-ai/molecule-ai-sdk/contracts/"
    "llm-registry/llm-registry.schema.json"
)


def _load_yaml() -> dict:
    with YAML_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_schema() -> dict:
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_schema_is_valid_draft2020():
    Draft202012Validator.check_schema(_load_schema())


def test_schema_id_is_canonical():
    assert _load_schema()["$id"] == CANONICAL_ID


def test_instance_validates_against_schema():
    validator = Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(_load_yaml()), key=lambda e: e.path)
    assert not errors, "\n".join(
        f"{list(e.path)}: {e.message}" for e in errors
    )


def test_schema_version_is_one():
    assert _load_yaml()["schema_version"] == 1


def test_provider_names_unique():
    names = [p["name"] for p in _load_yaml()["providers"]]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"duplicate provider names: {dupes}"


def test_model_prefix_match_regexes_compile():
    bad = []
    for p in _load_yaml()["providers"]:
        pat = p.get("model_prefix_match")
        if not pat:
            continue
        try:
            re.compile(pat)
        except re.error as exc:
            bad.append(f"{p['name']}: {pat!r} -> {exc}")
    assert not bad, "uncompilable model_prefix_match:\n" + "\n".join(bad)


def test_runtime_provider_refs_resolve():
    """RFC #340: every runtime's native provider set references real catalog
    entries — no over-offer the proxy could never route."""
    data = _load_yaml()
    catalog = {p["name"] for p in data["providers"]}
    unresolved = []
    for rt, native in data["runtimes"].items():
        provs = native.get("providers") or []
        assert provs, f"runtime {rt!r} declares no native providers"
        for ref in provs:
            if ref["name"] not in catalog:
                unresolved.append(f"{rt} -> {ref['name']}")
    assert not unresolved, "runtime native refs not in catalog: " + ", ".join(unresolved)


def test_gen_embed_is_byte_identical_to_source():
    """The Go embed copy must equal the contracts source verbatim — the drift
    gate re-runs the generator, but this pins it hermetically in the test suite
    too (catches a stale embed even offline)."""
    assert GEN_EMBED_PATH.exists(), (
        f"{GEN_EMBED_PATH} missing — run 'node tools/gen-llm-registry.mjs'"
    )
    src = YAML_PATH.read_bytes()
    embedded = GEN_EMBED_PATH.read_bytes()
    assert embedded == src, (
        "gen/go/llmregistry/llm-registry.yaml is stale vs the contracts SSOT — "
        "run 'node tools/gen-llm-registry.mjs' and commit."
    )
