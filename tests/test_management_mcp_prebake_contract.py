"""Contract test: the `management_mcp_server` pre-bake block.

The block in ``contracts/mcp/mcp-plugin-delivery.contract.json`` is the SSOT for
the concierge management-MCP npm package (``@molecule-ai/mcp-server``) and its
BUILD-TIME pre-bake — the launch-side of RCA #2970. This test pins the block's
shape + schema-validity so the base-runtime prebake helper and every template's
Guard-D lockstep have one stable governed source (ADR-004: SDK contract -> base
runtime default -> per-adapter override-if-needed).
"""
import json
import re
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "mcp" / "mcp-plugin-delivery.contract.json"
SCHEMA_PATH = ROOT / "contracts" / "mcp" / "mcp-plugin-delivery.schema.json"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text())


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def test_delivery_contract_validates_against_schema():
    # The block is `required` + additionalProperties:false, so this fails if the
    # block is missing, mistyped, or carries an unknown key.
    jsonschema.validate(_contract(), _schema())


def test_management_mcp_server_block_shape():
    mms = _contract()["management_mcp_server"]
    assert mms["npm_package"] == "@molecule-ai/mcp-server"
    assert mms["registry_scope"] == "@molecule-ai"
    assert mms["registry"].startswith("https://"), mms["registry"]
    # pinned_version is a concrete semver SSOT (the deterministic bake target).
    assert re.fullmatch(r"\d+\.\d+\.\d+", mms["pinned_version"]), mms["pinned_version"]
    # compatible_range is the semver RANGE the launch resolves against.
    rng = mms["compatible_range"]
    assert re.fullmatch(r"\^\d+\.\d+\.\d+", rng), rng
    # The launch resolves the RANGE, not the exact pin, so any in-range baked
    # version launches offline — the semver-range model that kills the
    # bump-ahead-of-rebuild fail-close window.
    assert mms["npm_package"] in mms["launch"]
    assert "<compatible_range>" in mms["launch"]
    assert "<pinned_version>" not in mms["launch"]


def test_pinned_version_satisfies_compatible_range():
    """Guard-D drift-tolerant invariant: the concrete bake target MUST fall
    inside the launch range (else a fresh image would bake something the
    launch range rejects)."""
    mms = _contract()["management_mcp_server"]
    base = mms["compatible_range"].lstrip("^")
    p = tuple(int(x) for x in mms["pinned_version"].split("."))
    b = tuple(int(x) for x in base.split("."))
    assert p[0] == b[0], f"pinned {mms['pinned_version']} outside range major {base}"
    assert p >= b, f"pinned {mms['pinned_version']} below range floor {base}"


def test_prebake_required_and_conformance_names_the_gate_tool():
    c = _contract()
    pb = c["management_mcp_server"]["prebake"]
    assert pb["required"] is True
    # The offline self-check must assert the SAME degrade-gate tool the concierge
    # requires (`required_tool` == provision_workspace), so a bake that resolves
    # the wrong/empty surface fails the build.
    assert c["required_tool"] in pb["conformance"]
    assert "offline" in pb["conformance"].lower()
    # The cache the bake warms is the agent HOME the gosu-dropped runtime reads.
    assert pb["cache_home"] == "/home/agent"
    # Ownership is the base runtime (a per-template fork is the anti-pattern this
    # block exists to retire) — the word "base runtime" must appear.
    assert "base runtime" in pb["owner"].lower()


def test_prebake_home_independence_is_governed():
    # The runtime spawns the mgmt-MCP under a launch HOME that may NOT be the
    # agent home (observed /root in the local docker provisioner); a HOME-local
    # ${HOME}/.npmrc would ETARGET on the private @molecule-ai scope even when the
    # version is correctly baked (#1027 fail-close). The contract mandates GLOBAL
    # (HOME-independent) registry+cache config and a FOREIGN-HOME self-check so
    # this launch-side regression can never ship.
    pb = _contract()["management_mcp_server"]["prebake"]
    hi = pb["home_independent"].lower()
    assert "global" in hi, "home_independent must mandate GLOBAL npm config"
    assert "home" in hi
    assert "foreign home" in pb["conformance"].lower(), "conformance must require the foreign-HOME check"
