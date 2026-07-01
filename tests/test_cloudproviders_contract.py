"""Schema + invariant conformance gate for the cloud-provider SSOT.

Mirrors tests/test_workspace_comms_conformance.py: it loads the SSOT data
(contracts/cloudproviders.yaml, via real pyyaml) and its JSON Schema
(contracts/cloudproviders.schema.json, draft 2020-12), then:

  1. asserts the schema itself is a valid draft-2020-12 schema
     (Draft202012Validator.check_schema),
  2. asserts the schema ``$id`` is the canonical molecule-ai-sdk URL (a tripwire
     so a forked/relocated copy is caught rather than silently validating),
  3. validates the YAML instance against the schema, and
  4. asserts the SEMANTIC invariants the JSON Schema cannot express — the "no
     duplicate id" gate (unique ids, unique non-colliding aliases, exactly one
     is_local, default_id resolves, backend_key == persist) AND the load-bearing
     migration-056 equality: {every provider.persist} ∪ {""} equals the
     organizations.provider CHECK set exactly.

This is the Python-side twin of the Node generators' own invariant checks
(tools/lib/cloudproviders.mjs) and the moved-verbatim Go behavior oracle
(gen/go/cloudprovider/cloudprovider_test.go): three independent guards over the
same SSOT, so a bad edit reds at least one no matter which toolchain runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"
YAML_PATH = CONTRACTS_DIR / "cloudproviders.yaml"
SCHEMA_PATH = CONTRACTS_DIR / "cloudproviders.schema.json"

# Canonical SSOT $id — a tripwire so a silently forked/relocated copy is caught.
CANONICAL_ID = (
    "https://git.moleculesai.app/molecule-ai/molecule-ai-sdk/contracts/"
    "cloudproviders.schema.json"
)

# The organizations.provider values migration 056 makes DB-legal:
#   molecule-controlplane/migrations/056_org_provider_local.up.sql
#   CHECK (provider IN ('', 'aws', 'hetzner', 'gcp', 'local'))
MIGRATION_056_CHECK_SET = {"", "aws", "hetzner", "gcp", "local"}


def _load_schema() -> dict:
    import json

    return json.loads(SCHEMA_PATH.read_text())


def _load_data() -> dict:
    return yaml.safe_load(YAML_PATH.read_text())


def test_schema_is_valid_draft202012() -> None:
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_schema_id_is_canonical() -> None:
    """Tripwire: the schema $id is the canonical molecule-ai-sdk URL."""
    assert _load_schema()["$id"] == CANONICAL_ID, (
        "cloudproviders.schema.json $id is not the canonical molecule-ai-sdk URL "
        "— the SSOT schema has been forked/relocated"
    )


def test_yaml_conforms_to_schema() -> None:
    validator = Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(_load_data()), key=lambda e: list(e.path))
    assert not errors, "cloudproviders.yaml violates its schema:\n" + "\n".join(
        f"  - at {list(e.path)}: {e.message}" for e in errors
    )


def test_ids_unique() -> None:
    ids = [p["id"] for p in _load_data()["providers"]]
    assert len(ids) == len(set(ids)), f"duplicate provider id(s) in {ids}"


def test_aliases_unique_and_non_colliding() -> None:
    data = _load_data()
    ids = {p["id"] for p in data["providers"]}
    seen: set[str] = set()
    for p in data["providers"]:
        for a in p.get("aliases", []) or []:
            assert a not in ids, f"alias {a!r} on {p['id']} collides with a provider id"
            assert a not in seen, f"alias {a!r} is defined more than once"
            seen.add(a)


def test_exactly_one_is_local() -> None:
    locals_ = [p["id"] for p in _load_data()["providers"] if p["is_local"]]
    assert len(locals_) == 1, f"expected exactly one is_local provider, got {locals_}"


def test_default_id_resolves() -> None:
    data = _load_data()
    ids = {p["id"] for p in data["providers"]}
    assert data["default_id"] in ids, f"default_id {data['default_id']!r} is not a real id"
    if "empty_normalizes_to" in data:
        assert data["empty_normalizes_to"] == data["default_id"], (
            "empty_normalizes_to must equal default_id"
        )


def test_backend_key_equals_persist_for_every_row() -> None:
    for p in _load_data()["providers"]:
        assert p["backend_key"] == p["persist"], (
            f"provider {p['id']!r}: backend_key ({p['backend_key']}) must equal "
            f"persist ({p['persist']}) for every current row"
        )


def test_persist_set_equals_migration_056_check_set() -> None:
    persist = {p["persist"] for p in _load_data()["providers"]} | {""}
    assert persist == MIGRATION_056_CHECK_SET, (
        f"{{persist}} ∪ {{''}} = {sorted(persist)} must equal the migration-056 "
        f"CHECK set {sorted(MIGRATION_056_CHECK_SET)}"
    )


# ---------------------------------------------------------------------------
# Negative: the gate MUST reject a malformed instance (anti-vacuous proof)
# ---------------------------------------------------------------------------


def test_gate_rejects_bad_backend_key() -> None:
    schema = _load_schema()
    bad = _load_data()
    bad["providers"][0]["backend_key"] = "azure"  # not in the enum
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(bad)), (
        "schema failed to reject an out-of-enum backend_key"
    )


def test_gate_rejects_missing_required_field() -> None:
    schema = _load_schema()
    bad = _load_data()
    del bad["providers"][0]["display"]  # required
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(bad)), (
        "schema failed to reject a provider missing a required field"
    )


@pytest.mark.parametrize("value", ["Azure", "AWS", "a b", "-x", "1x"])
def test_gate_rejects_bad_id_pattern(value: str) -> None:
    schema = _load_schema()
    bad = _load_data()
    bad["providers"][0]["id"] = value
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(bad)), (
        f"schema failed to reject an id violating the pattern: {value!r}"
    )
