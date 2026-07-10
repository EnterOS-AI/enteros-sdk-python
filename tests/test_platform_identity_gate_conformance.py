"""Conformance gate: the platform-identity fail-closed ENFORCEMENT schema runs
against its golden decision-table cases.

``contracts/workspace-comms/enforcement/platform-identity-gate.schema.json`` is
the machine-checkable overlay that closes the base register/heartbeat schema's
vacuity (registry-contract.md divergence #5): the base schemas type
``mcp_server_present`` / ``loaded_mcp_tools`` as OPTIONAL (Go ``,omitempty``), so
a kind=platform payload omitting BOTH still validates and silently bypasses the
RCA #2970 / core#3082 fail-closed identity gate. The enforcement schema encodes
the EXACT four-branch Go decision table (not_platform / failed / degraded /
online) as draft-2020-12 conditionals keyed off a ``verdict`` discriminator.

A schema is only as good as the cases proving it. This gate loads the golden
case-set ``platform-identity-gate.cases.json`` and asserts, for the schema:

  * the schema is itself a valid draft-2020-12 schema;
  * the required-tool literal it composes matches the cross-repo SSOT
    (``mcp__molecule-platform__provision_workspace``);
  * EVERY ``pass`` case validates (after stripping the ``$case`` fixture label);
  * EVERY ``fail`` case does NOT validate — the anti-vacuous proof that the
    profile actually rejects the online-claim-without-proof bypass class.

Runs fully offline (both files live in this repo; the schema $refs only its own
``#/$defs``). Named ``.cases.json`` deliberately so the two-level
``contracts/*/*.contract.json`` validate glob does not pick it up — it is a
decision table, not a single canonical instance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
ENFORCE_DIR = REPO_ROOT / "contracts" / "workspace-comms" / "enforcement"
SCHEMA_PATH = ENFORCE_DIR / "platform-identity-gate.schema.json"
CASES_PATH = ENFORCE_DIR / "platform-identity-gate.cases.json"

REQUIRED_PROVISION_TOOL = "mcp__molecule-platform__provision_workspace"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def cases() -> dict:
    return json.loads(CASES_PATH.read_text())


def _strip_case_label(instance: dict) -> dict:
    """Remove the ``$case`` fixture-annotation key: the schema is
    additionalProperties:false at the top level, so ``$case`` is a label, not
    part of the instance under test."""
    return {k: v for k, v in instance.items() if k != "$case"}


# ---------------------------------------------------------------------------
# schema self-checks + cross-repo literal pin
# ---------------------------------------------------------------------------


def test_schema_is_valid_draft2020(schema: dict) -> None:
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_required_tool_literal_is_cross_repo_ssot(schema: dict) -> None:
    """The one tool id the core verified-ready gate matches literally. Pinned as
    a const so a rename of either the server name or the required verb reds this
    gate (and the mcp-plugin-delivery + adapter-registry gates)."""
    const = schema["$defs"]["requiredProvisionTool"]["const"]
    assert const == REQUIRED_PROVISION_TOOL, (
        f"platform-identity gate required tool literal is {const!r}, expected "
        f"{REQUIRED_PROVISION_TOOL!r} (mcp__<mcp_server_name>__<required_tool> "
        f"from mcp-plugin-delivery.contract.json)"
    )


def test_cases_file_has_both_arrays(cases: dict) -> None:
    assert cases.get("pass"), "golden case-set has no `pass` cases"
    assert cases.get("fail"), "golden case-set has no `fail` cases — the gate "
    "would be un-proven anti-vacuous"


# ---------------------------------------------------------------------------
# every PASS case validates
# ---------------------------------------------------------------------------


def test_pass_cases_validate(validator: Draft202012Validator, cases: dict) -> None:
    failures = []
    for case in cases["pass"]:
        label = case.get("$case", "<unlabeled>")
        instance = _strip_case_label(case)
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        if errors:
            rendered = "; ".join(
                f"at {list(e.path)}: {e.message}" for e in errors
            )
            failures.append(f"PASS case did NOT validate — {label}\n    {rendered}")
    assert not failures, (
        "one or more golden `pass` cases failed the enforcement schema:\n"
        + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# every FAIL case is rejected (anti-vacuous)
# ---------------------------------------------------------------------------


def test_fail_cases_are_rejected(validator: Draft202012Validator, cases: dict) -> None:
    leaks = []
    for case in cases["fail"]:
        label = case.get("$case", "<unlabeled>")
        instance = _strip_case_label(case)
        if validator.is_valid(instance):
            leaks.append(
                f"FAIL case was ACCEPTED (gate is vacuous for this branch) — {label}"
            )
    assert not leaks, (
        "one or more golden `fail` cases were accepted by the enforcement schema "
        "— the fail-closed identity gate is not actually enforcing:\n"
        + "\n".join(leaks)
    )


# ---------------------------------------------------------------------------
# spot-check the two load-bearing branches directly (readable regressions)
# ---------------------------------------------------------------------------


def test_online_requires_the_loaded_proof(validator: Draft202012Validator) -> None:
    """A kind=platform heartbeat claiming `online` without the required tool in
    loaded_mcp_tools must be rejected — the exact divergence #5 bypass."""
    bypass = {
        "kind": "heartbeat",
        "verdict": "online",
        "payload": {"kind": "platform", "mcp_server_present": True},
    }
    assert not validator.is_valid(bypass)

    proven = {
        "kind": "heartbeat",
        "verdict": "online",
        "payload": {
            "kind": "platform",
            "mcp_server_present": True,
            "loaded_mcp_tools": [REQUIRED_PROVISION_TOOL],
        },
    }
    assert validator.is_valid(proven)


def test_failed_requires_explicit_false(validator: Draft202012Validator) -> None:
    """`failed` is the fail-closed branch: only mcp_server_present==false reaches
    it (nil=allow, true=allow). A `failed` verdict with true is a contradiction."""
    contradiction = {
        "kind": "heartbeat",
        "verdict": "failed",
        "payload": {"kind": "platform", "mcp_server_present": True},
    }
    assert not validator.is_valid(contradiction)
