"""RuntimeId shape and official-runtime registry conformance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_SCHEMA_PATHS = (
    "contracts/plugin-manifest/plugin-manifest.schema.json",
    "contracts/workspace-template/workspace-template.schema.json",
    "contracts/org-template/org-template.schema.json",
    "contracts/catalog/catalog.schema.json",
    "contracts/catalog/catalog-entry.schema.json",
    "contracts/catalog/publish-request.schema.json",
)

VALID_RUNTIME_IDS = (
    "claude-code",
    "codex",
    "hermes",
    "openclaw",
    "claude_code",
    "acme-agent",
    "acme_agent",
    "constructor",
    "a",
    "a" * 64,
)

INVALID_RUNTIME_IDS = (
    "",
    "Acme-Agent",
    "../acme",
    "acme/agent",
    "acme\\agent",
    "acme agent",
    "acme\nagent",
    "acme\n",
    "acme\r",
    "acme\u2028",
    "acme\u2029",
    "-acme",
    "acme-",
    "acme--agent",
    "a" * 65,
)


@pytest.mark.parametrize("relative_path", RUNTIME_SCHEMA_PATHS)
def test_runtime_id_schema_is_open_and_path_safe(relative_path: str) -> None:
    schema = json.loads((REPO_ROOT / relative_path).read_text())
    assert schema["$id"].startswith(
        "https://git.moleculesai.app/molecule-ai/molecule-ai-sdk/"
    )
    runtime_id = Draft202012Validator(schema["$defs"]["runtimeId"])

    for value in VALID_RUNTIME_IDS:
        assert runtime_id.is_valid(value), f"{relative_path} rejected {value!r}"
    for value in INVALID_RUNTIME_IDS:
        assert not runtime_id.is_valid(value), f"{relative_path} accepted {value!r}"


def test_official_registry_contains_exactly_the_four_first_party_runtimes() -> None:
    registry = json.loads(
        (REPO_ROOT / "contracts/adapter/official-runtimes.registry.json").read_text()
    )

    assert set(registry["runtimes"]) == {
        "claude_code",
        "codex",
        "hermes",
        "openclaw",
    }
    assert "not_yet_official" not in registry


def test_python_runtime_normalizer_preserves_safe_custom_ids() -> None:
    from molecule_plugin import normalize_runtime_id

    assert normalize_runtime_id("claude_code") == "claude-code"
    assert normalize_runtime_id("acme-agent") == "acme-agent"

    for value in INVALID_RUNTIME_IDS:
        with pytest.raises((TypeError, ValueError)):
            normalize_runtime_id(value)


def test_sdk_and_published_python_runtime_bindings_are_identical() -> None:
    assert (REPO_ROOT / "molecule_plugin/_runtime_ids.py").read_bytes() == (
        REPO_ROOT / "gen/python/runtime_ids_gen.py"
    ).read_bytes()


def test_org_defaults_runtime_uses_runtime_id_contract() -> None:
    schema = json.loads(
        (REPO_ROOT / "contracts/org-template/org-template.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)

    assert validator.is_valid(
        {"name": "custom", "defaults": {"runtime": "acme-agent"}}
    )
    assert not validator.is_valid(
        {"name": "unsafe", "defaults": {"runtime": "../../adapter"}}
    )


def test_catalog_org_defaults_runtime_uses_runtime_id_contract() -> None:
    schema = json.loads(
        (REPO_ROOT / "contracts/catalog/catalog-entry.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)
    entry = {
        "id": "org-custom",
        "kind": "org-template",
        "name": "Custom Org",
        "version": "1.0.0",
        "source": "gitea://molecule-ai/custom-org#v1.0.0",
        "spec": {"defaults": {"runtime": "acme-agent"}},
    }

    assert validator.is_valid(entry)
    entry["spec"]["defaults"]["runtime"] = "../../adapter"
    assert not validator.is_valid(entry)


def test_exported_plugin_schema_uses_complete_runtime_id_contract() -> None:
    from molecule_plugin import PLUGIN_YAML_SCHEMA

    validator = Draft202012Validator(PLUGIN_YAML_SCHEMA)
    assert validator.is_valid({"name": "custom", "runtimes": ["acme-agent"]})
    assert not validator.is_valid({"name": "unsafe", "runtimes": ["acme\n"]})
