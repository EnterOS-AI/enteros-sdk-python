"""Conformance + drift gate for the adapter-socket OFFICIAL runtime registry.

Makes ``contracts/adapter/official-runtimes.registry.json`` (ADR-004 §2 SSOT for
the set of natively-supported runtimes and their adapter-socket metadata) a
MACHINE-ENFORCED companion of ``contracts/mcp/mcp-plugin-delivery.contract.json``
rather than a prose promise that they "are RECONCILED".

The registry's own ``$comment`` states the invariant:

    the per-runtime ``mcp`` block below is RECONCILED with that contract's
    ``runtimes`` block (same runtimes, same native path/format/server-map
    location) — that delivery contract remains SSOT for the MCP-server
    descriptor + gate tool; THIS file is the SSOT for which runtimes are
    officially supported and their adapter identity/persona/enumerate metadata.

Left unenforced, that reconciliation drifts the instant someone edits one file
(add a runtime, rename ``mcpServers`` → ``mcp_servers``, move the openclaw
``key_path``) without the other. This gate turns every clause of that sentence
into an assertion:

  1. The registry validates as well-formed JSON with the fields ADR-004 pins.
  2. The OFFICIAL runtime set (``runtimes`` keys) is EXACTLY the delivery
     contract's ``runtimes`` set — no official runtime is missing from either
     side, none is extra.
  3. Per runtime, the native surface is byte-identical across the two files:
     ``settings_path``/``native_path_pattern``, ``format``, and the
     server-map location (``key`` / ``table`` / ``key_path``).
  4. The cross-repo SSOT literals (``management_mcp_name`` == the delivery
     contract's ``mcp_server_name``; ``required_tool``; the tool/present
     field names) match between the two files AND match the values the
     platform-identity gate composes its required tool id from.

Kept in ``tests/`` (not the two-level ``contracts/*/*.contract.json`` validate
glob) because it is a CROSS-file reconciliation, not a single-instance schema
check. Wired into ``.gitea/workflows/contracts-codegen-drift.yml`` alongside the
other contract-conformance gates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "contracts" / "adapter" / "official-runtimes.registry.json"
DELIVERY_PATH = REPO_ROOT / "contracts" / "mcp" / "mcp-plugin-delivery.contract.json"


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text())


@pytest.fixture(scope="module")
def delivery() -> dict:
    return json.loads(DELIVERY_PATH.read_text())


# ---------------------------------------------------------------------------
# 1. registry is well-formed and pins the ADR-004 fields
# ---------------------------------------------------------------------------


def test_registry_shape(registry: dict) -> None:
    assert registry["contract"] == "adapter-socket"
    for key in (
        "management_mcp_name",
        "required_tool",
        "loaded_mcp_tools_field",
        "runtime_present_field",
        "default_runtime",
        "runtimes",
    ):
        assert key in registry, f"registry missing required field {key!r}"
    assert isinstance(registry["runtimes"], dict) and registry["runtimes"], (
        "registry.runtimes must be a non-empty object"
    )
    # The delivery contract this reconciles with is named in-file; a rename must
    # not silently orphan the reconciliation.
    assert registry["delivery_contract_ref"] == "../mcp/mcp-plugin-delivery.contract.json"


def test_default_runtime_is_official(registry: dict) -> None:
    assert registry["default_runtime"] in registry["runtimes"], (
        f"default_runtime {registry['default_runtime']!r} is not in the official set"
    )


# ---------------------------------------------------------------------------
# 2. the OFFICIAL runtime set matches the delivery contract EXACTLY
# ---------------------------------------------------------------------------


def test_official_runtime_set_matches_delivery(registry: dict, delivery: dict) -> None:
    reg_runtimes = set(registry["runtimes"])
    del_runtimes = set(delivery["runtimes"])
    assert reg_runtimes == del_runtimes, (
        "official-runtimes.registry.json and mcp-plugin-delivery.contract.json "
        "disagree on the runtime set (they MUST be the same runtimes — ADR-004 §2 "
        f"reconciliation):\n  only in registry: {sorted(reg_runtimes - del_runtimes)}\n"
        f"  only in delivery: {sorted(del_runtimes - reg_runtimes)}"
    )


# ---------------------------------------------------------------------------
# 3. per-runtime native surface is byte-identical across the two files
# ---------------------------------------------------------------------------


def _server_map_location(block: dict) -> tuple[str, str]:
    """Return (kind, value) for the runtime's MCP server-map location.

    Exactly one of key / table / key_path locates the server map; the two files
    must agree on both which one and its value.
    """
    for kind in ("key", "table", "key_path"):
        if kind in block:
            return kind, block[kind]
    raise AssertionError(f"no server-map location (key/table/key_path) in {block!r}")


@pytest.mark.parametrize(
    "runtime",
    # parametrize over the delivery contract's runtimes; test #2 already proved the
    # sets are equal, so this covers every official runtime by construction.
    sorted(json.loads(DELIVERY_PATH.read_text())["runtimes"]),
)
def test_native_surface_reconciles(runtime: str, registry: dict, delivery: dict) -> None:
    reg_mcp = registry["runtimes"][runtime]["mcp"]
    del_mcp = delivery["runtimes"][runtime]

    # native config path: registry calls it native_path_pattern, delivery settings_path
    assert reg_mcp["native_path_pattern"] == del_mcp["settings_path"], (
        f"[{runtime}] native config path differs — registry "
        f"{reg_mcp['native_path_pattern']!r} vs delivery {del_mcp['settings_path']!r}"
    )
    assert reg_mcp["format"] == del_mcp["format"], (
        f"[{runtime}] format differs — registry {reg_mcp['format']!r} "
        f"vs delivery {del_mcp['format']!r}"
    )

    reg_loc = _server_map_location(reg_mcp)
    del_loc = _server_map_location(del_mcp)
    assert reg_loc == del_loc, (
        f"[{runtime}] server-map location differs — registry {reg_loc} "
        f"vs delivery {del_loc} (same runtime must read the same native key)"
    )

    # the renderer symbol the delivery contract names must match the registry's
    assert reg_mcp["renderer"] == del_mcp["renderer"], (
        f"[{runtime}] renderer symbol differs — registry {reg_mcp['renderer']!r} "
        f"vs delivery {del_mcp['renderer']!r}"
    )


# ---------------------------------------------------------------------------
# 4. cross-repo SSOT literals agree (server name / required tool / field names)
# ---------------------------------------------------------------------------


def test_ssot_literals_agree(registry: dict, delivery: dict) -> None:
    # The management MCP server name is the SAME literal in both files (the
    # registry calls it management_mcp_name; the delivery contract mcp_server_name).
    assert registry["management_mcp_name"] == delivery["mcp_server_name"], (
        "management MCP server-name literal drifted between registry "
        f"({registry['management_mcp_name']!r}) and delivery "
        f"({delivery['mcp_server_name']!r})"
    )
    for field in ("required_tool", "loaded_mcp_tools_field", "runtime_present_field"):
        assert registry[field] == delivery[field], (
            f"{field!r} literal drifted between registry ({registry[field]!r}) "
            f"and delivery ({delivery[field]!r})"
        )


def test_required_tool_id_composes_to_the_gate_literal(registry: dict) -> None:
    """The registry's server-name + required-tool compose to the exact tool id
    the platform-identity gate (and core's verified-ready loop) match literally.

    This binds THREE SSOTs to one string:
      registry.management_mcp_name + registry.required_tool
        == mcp__molecule-platform__provision_workspace
        == platform-identity-gate.schema.json#/$defs/requiredProvisionTool.const
    A rename in the registry reds this gate AND the identity-gate conformance test.
    """
    composed = f"mcp__{registry['management_mcp_name']}__{registry['required_tool']}"

    gate_schema = json.loads(
        (
            REPO_ROOT
            / "contracts"
            / "workspace-comms"
            / "enforcement"
            / "platform-identity-gate.schema.json"
        ).read_text()
    )
    gate_literal = gate_schema["$defs"]["requiredProvisionTool"]["const"]
    assert composed == gate_literal, (
        f"registry composes {composed!r} but the identity gate matches "
        f"{gate_literal!r} — the required management tool id drifted across SSOTs"
    )


# ---------------------------------------------------------------------------
# anti-vacuous: the reconciliation gate actually rejects drift
# ---------------------------------------------------------------------------


def test_gate_catches_native_key_drift(registry: dict, delivery: dict) -> None:
    """Simulate a rename of claude_code's mcpServers key in ONLY the delivery
    contract; the reconciliation MUST catch it."""
    import copy

    drifted = copy.deepcopy(delivery)
    drifted["runtimes"]["claude_code"]["key"] = "mcp_servers_RENAMED"

    reg_loc = _server_map_location(registry["runtimes"]["claude_code"]["mcp"])
    del_loc = _server_map_location(drifted["runtimes"]["claude_code"])
    assert reg_loc != del_loc, (
        "the reconciliation gate would NOT have caught a one-sided native-key "
        "rename — it is vacuous"
    )
