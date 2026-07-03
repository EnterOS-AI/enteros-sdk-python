"""Conformance gate for the plugin-manifest `contributes.daemons` semantics.

The property is deliberately UNCONSTRAINED at manifest level: the workspace
runtime never rejects a manifest over `daemons` — malformed entries (or a
non-list value) are SKIPPED with a warning at spawn discovery
(molecule-ai-workspace-runtime plugin_daemons._entry_problem, runtime#216),
never a validation failure. Constraining it here would CHANGE runtime
semantics rather than capture them: the runtime's own
test_malformed_entries_skipped_valid_kept goes red against a strict-items
version of this property (a manifest with one bad + one good daemon entry
would be rejected wholesale, the good entry never spawned).

This test pins BOTH halves so neither can silently regress:

  1. tolerance — canonical instance AND malformed-daemons variants all
     validate against the full manifest schema (skip semantics preserved);
  2. canonical shape — `$defs/daemonContribution` stays a live, enforceable
     subschema: a well-formed entry passes it, malformed entries fail it
     (so emitters/gates that OPT IN to strictness still have a shape to
     validate against, and the def is never a dead orphan);
  3. prove-fail — a strict-items rewrite of the property (the exact shape
     this contract deliberately avoids) DOES reject the malformed manifest,
     demonstrating the tolerance in (1) is load-bearing, not vacuous.

Hermetic: needs only jsonschema (run with ``pytest --noconftest``).
"""

from __future__ import annotations

import copy
import json
import os

import pytest
from jsonschema import Draft202012Validator, ValidationError

HERE = os.path.dirname(__file__)
PM_DIR = os.path.join(HERE, "..", "contracts", "plugin-manifest")


def _load(name: str):
    with open(os.path.join(PM_DIR, name), "rb") as f:
        return json.load(f)


SCHEMA = _load("plugin-manifest.schema.json")
INSTANCE = _load("plugin-manifest.contract.json")

MALFORMED_DAEMONS_VARIANTS = {
    "junk-entries": [{"command": ""}, "not-a-mapping", {"name": "x", "command": "y", "args": [1]}],
    "non-list": "not-a-list",
    "null": None,
    "mixed-good-and-bad": [
        {"name": "good", "command": "bash", "args": ["run.sh"]},
        {"name": "  ", "command": "blank-name"},
    ],
}


def test_canonical_instance_validates():
    Draft202012Validator(SCHEMA).validate(INSTANCE)


@pytest.mark.parametrize("label", sorted(MALFORMED_DAEMONS_VARIANTS))
def test_malformed_daemons_tolerated_by_manifest_schema(label):
    # The load-bearing invariant: the runtime skips these at spawn discovery,
    # so manifest validation must tolerate them (a daemons typo must not brick
    # the plugin at the future fail-closed install gate).
    inst = copy.deepcopy(INSTANCE)
    inst["contributes"]["daemons"] = MALFORMED_DAEMONS_VARIANTS[label]
    Draft202012Validator(SCHEMA).validate(inst)


def _daemon_entry_subschema():
    return {"$ref": "#/$defs/daemonContribution", "$defs": SCHEMA["$defs"]}


def test_canonical_entry_shape_is_still_enforceable():
    # $defs/daemonContribution must remain a live, strict subschema for
    # emitters and opt-in gates — permissive at the manifest level does not
    # mean shapeless.
    Draft202012Validator(_daemon_entry_subschema()).validate(
        {"name": "lark-bridge", "command": "bash", "args": ["daemon-bootstrap.sh"]}
    )


@pytest.mark.parametrize(
    "bad_entry",
    [
        {"command": "no-name"},
        {"name": "no-command"},
        {"name": "   ", "command": "blank-name"},
        {"name": "x", "command": "y", "args": [1]},
        "not-a-mapping",
    ],
)
def test_canonical_entry_subschema_rejects_malformed(bad_entry):
    with pytest.raises(ValidationError):
        Draft202012Validator(_daemon_entry_subschema()).validate(bad_entry)


def test_prove_fail_strict_items_would_reject_the_tolerated_manifest():
    # Documents WHY the property is unconstrained: the strict shape this
    # contract deliberately avoids (type:array + items:$ref) rejects the
    # exact manifests the runtime tolerates. If someone re-tightens the
    # property, test_malformed_daemons_tolerated_by_manifest_schema reds;
    # this test shows the tolerance is doing real work.
    strict = copy.deepcopy(SCHEMA)
    strict["$defs"]["contributes"]["properties"]["daemons"] = {
        "type": "array",
        "items": {"$ref": "#/$defs/daemonContribution"},
    }
    inst = copy.deepcopy(INSTANCE)
    inst["contributes"]["daemons"] = MALFORMED_DAEMONS_VARIANTS["mixed-good-and-bad"]
    with pytest.raises(ValidationError):
        Draft202012Validator(strict).validate(inst)
