"""Prove-fail conformance gate for the idle-prompt digest contract (task #219).

The repo's `validate` CI job already checks that the POSITIVE
`contracts/idle-prompt/idle-prompt.contract.json` instance validates against
its sibling schema. This test adds the NEGATIVE half — the load-bearing
invariants a positive-only check can't prove — so a future loosening of the
schema reds here instead of silently accepting a bad payload:

  1. the canonical instance validates (positive, draft 2020-12), and the
     settled policy values are what the design SSOT ruled (300s idle-fire,
     post-on_included baselines, header excluded from emptiness);
  2. the shape-vs-engine ownership split is const-pinned — an instance
     claiming the assembler implementation lives anywhere but
     molecule_runtime is REJECTED;
  3. a contribution envelope without `age_band` is REJECTED — age_band is the
     ONLY permitted time-derived field, and it must always be declared (the
     goal cadence and sent-folder escalation ride this slot);
  4. a preview item smuggling a RAW time field (`age_seconds`) is REJECTED —
     raw ages change every tick and resurrect the steady-state nag loop the
     delta gate exists to kill;
  5. the delta baseline discipline is const-pinned — baselining at fire-time
     values (not post-on_included) double-fires every goal cadence, so an
     instance declaring any other baseline is REJECTED;
  6. `pinned` stays a reserved band value and the reservation target is
     const-pinned to identity-capabilities;
  7. a goal cadence below the idle-fire floor (300s) is REJECTED;
  8. a task row with a status outside the ruled enum is structurally
     representable (enum is advisory doc for codegen) but the top-level
     policy object rejects unknown keys — additionalProperties is false.

Hermetic: needs only jsonschema (run with `pytest --noconftest`).
"""

from __future__ import annotations

import copy
import glob
import json
import os

import pytest
from jsonschema import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
LAYER = os.path.join(HERE, "..", "contracts", "idle-prompt")


def _load(name: str) -> dict:
    with open(os.path.join(LAYER, name), encoding="utf-8") as fh:
        return json.load(fh)


def _schema() -> dict:
    return _load("idle-prompt.schema.json")


def _instance() -> dict:
    return _load("idle-prompt.contract.json")


def _errors(instance: dict) -> list:
    return list(Draft202012Validator(_schema()).iter_errors(instance))


def test_every_idle_prompt_instance_validates() -> None:
    instances = sorted(glob.glob(os.path.join(LAYER, "*.contract.json")))
    assert instances, "no idle-prompt contract instances found (fail-closed)"
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    for inst in instances:
        data = json.load(open(inst, encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(data))
        assert not errors, f"{os.path.basename(inst)}: {[e.message for e in errors]}"


def test_settled_policy_values_are_the_ruled_ones() -> None:
    """The canonical instance carries the operator-ruled settled values."""
    inst = _instance()
    assert inst["wake"]["idle_fire_after_seconds"] == 300
    assert inst["delta"]["baseline"] == "post-on-included-recompute-at-last-successful-fire"
    assert inst["empty"]["header_counts_toward_emptiness"] is False
    assert inst["trust"]["pinned_reserved_to"] == "identity-capabilities"
    assert inst["ownership"]["assembler_owner"] == "molecule_runtime"
    # The ratified canonical tuple is 7 fields — 'band' is excluded (derived
    # from provider_id + urgency, so it can neither change independently nor
    # mask a re-fire). Kept in lockstep with the design SSOT §2.1.
    assert inst["delta"]["hash_serialization"] == [
        "provider_id", "tier", "urgency", "count", "summary", "age_band", "item_ids",
    ]
    assert "band" not in inst["delta"]["hash_serialization"]
    # settled roster: task-queue is tier 1 and there is NO user-mail provider (D3)
    by_id = {p["provider_id"]: p for p in inst["providers"]}
    assert "user-mail" not in by_id, "user prompts are never digest contributions (D3)"
    assert by_id["task-queue"]["base_tier"] == 1
    assert by_id["goal-state"]["base_tier"] == 7
    assert by_id["identity-capabilities"]["band"] == "pinned"


def test_assembler_ownership_is_const_pinned() -> None:
    bad = copy.deepcopy(_instance())
    bad["ownership"]["assembler_owner"] = "molecule-ai-sdk"
    assert _errors(bad), "assembler_owner must be const-pinned to molecule_runtime"


def test_contribution_without_age_band_is_rejected() -> None:
    bad = copy.deepcopy(_instance())
    del bad["sample_contributions"][0]["age_band"]
    assert _errors(bad), "age_band is required on every contribution envelope"


def test_raw_time_field_in_preview_item_is_rejected() -> None:
    bad = copy.deepcopy(_instance())
    urgent = bad["sample_contributions"][1]
    assert urgent["preview_items"], "fixture drift: expected a preview item on the urgent envelope"
    urgent["preview_items"][0]["age_seconds"] = 420
    assert _errors(bad), "raw time fields are forbidden — age_band is the only time slot"


def test_raw_age_band_value_is_rejected() -> None:
    bad = copy.deepcopy(_instance())
    bad["sample_contributions"][1]["age_band"] = "3h12m"
    assert _errors(bad), "age_band must be one of the banded enum values, never a raw duration"


def test_fire_time_baseline_is_rejected() -> None:
    bad = copy.deepcopy(_instance())
    bad["delta"]["baseline"] = "hashes-at-fire-time"
    assert _errors(bad), "baseline is const-pinned to the post-on_included recompute"


def test_pinned_band_reservation_is_const_pinned() -> None:
    bad = copy.deepcopy(_instance())
    bad["trust"]["pinned_reserved_to"] = "task-queue"
    assert _errors(bad), "pinned_reserved_to must be const identity-capabilities"


def test_invalid_band_value_is_rejected() -> None:
    bad = copy.deepcopy(_instance())
    bad["sample_contributions"][0]["band"] = "header"
    assert _errors(bad), "band must be one of pinned/urgent/base"


def test_goal_cadence_below_idle_floor_is_rejected() -> None:
    bad = copy.deepcopy(_instance())
    bad["goal_state"]["sample_goal"]["cadence_seconds"] = 60
    assert _errors(bad), "goal cadence below 300s must be rejected (clamped floor)"


def test_header_emptiness_pin_cannot_be_loosened() -> None:
    bad = copy.deepcopy(_instance())
    bad["empty"]["header_counts_toward_emptiness"] = True
    assert _errors(bad), "header_counts_toward_emptiness is const-pinned false"


def test_unknown_top_level_key_is_rejected() -> None:
    bad = copy.deepcopy(_instance())
    bad["extension_bucket"] = {}
    assert _errors(bad), "top level is additionalProperties: false (no extension bucket — parent ruling)"


def test_negatives_are_not_vacuous() -> None:
    """The unmutated instance passes — proving each negative above bites on
    the mutation, not on a broken fixture."""
    assert not _errors(_instance())
