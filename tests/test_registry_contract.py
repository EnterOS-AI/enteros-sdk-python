"""Schema + invariant conformance gate for the container-registry SSOT.

Python-side twin of the Node generator (tools/gen-registry.mjs) and its drift
workflow. Loads the SSOT data (contracts/registry.yaml, via real pyyaml) and its
JSON Schema (contracts/registry.schema.json, draft 2020-12), then:

  1. asserts the schema itself is a valid draft-2020-12 schema,
  2. asserts the schema ``$id`` is the canonical molecule-ai-sdk URL (tripwire so
     a forked/relocated copy is caught rather than silently validating),
  3. validates the YAML instance against the schema,
  4. asserts the load-bearing SEMANTIC invariant the JSON Schema cannot express:
     ``prefix == host + "/" + owner`` (the whole point of the SSOT — one prefix
     every ref derives from), and
  5. asserts the generated env fragment (gen/registry/registry.env) carries the
     SAME prefix on BOTH derivation seams (env var + CI var), so the "one config
     -> all refs derive" contract is machine-checked, not just documented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"
YAML_PATH = CONTRACTS_DIR / "registry.yaml"
SCHEMA_PATH = CONTRACTS_DIR / "registry.schema.json"
ENV_PATH = REPO_ROOT / "gen" / "registry" / "registry.env"

CANONICAL_ID = (
    "https://git.moleculesai.app/molecule-ai/molecule-ai-sdk/contracts/"
    "registry.schema.json"
)


def _load_yaml() -> dict:
    with YAML_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_schema() -> dict:
    import json

    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_schema_is_valid_draft2020():
    Draft202012Validator.check_schema(_load_schema())


def test_schema_id_is_canonical():
    assert _load_schema().get("$id") == CANONICAL_ID


def test_instance_validates_against_schema():
    Draft202012Validator(_load_schema()).validate(_load_yaml())


def test_prefix_equals_host_slash_owner():
    reg = _load_yaml()["registry"]
    assert reg["prefix"] == f"{reg['host']}/{reg['owner']}", (
        "registry.prefix MUST equal host/owner — it is the one value every image "
        "ref derives from"
    )


def test_retention_cap_is_positive():
    assert _load_yaml()["retention"]["keep_max_versions"] >= 1


def _parse_env(text: str) -> dict:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def test_generated_env_in_sync_and_both_seams_agree():
    """gen/registry/registry.env must exist and carry the SAME prefix on the
    runtime env var AND the CI var (the SSOT's whole promise)."""
    assert ENV_PATH.exists(), (
        "gen/registry/registry.env missing — run `node tools/gen-registry.mjs`"
    )
    data = _load_yaml()
    prefix = data["registry"]["prefix"]
    env = _parse_env(ENV_PATH.read_text(encoding="utf-8"))
    assert env.get(data["env_var"]) == prefix
    assert env.get(data["ci_var"]) == prefix
    assert env.get("MOLECULE_REGISTRY_PREFIX") == prefix
    assert env.get("MOLECULE_REGISTRY_KEEP_MAX_VERSIONS") == str(
        data["retention"]["keep_max_versions"]
    )
