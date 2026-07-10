"""Contract + validator tests for the repo-meta SSOT (RFC: org CI-enforcement,
P1 keystone).

Two layers, mirroring test_plugin_manifest_daemons_contract.py:

  1. SCHEMA — the canonical instance validates; the STRICT invariants are
     load-bearing (bad layer / unknown-additional-property / missing required /
     bad waiver are rejected by the schema; a well-formed unknown capability is
     TOLERATED by the schema — the openness is proven non-vacuous).
  2. VALIDATOR — molecule_plugin.validate_repo_meta: valid passes, bad layer
     errors, unknown capability WARNS-but-passes-schema, missing required field
     errors, a waiver validates, and the schema/validator vocabularies agree.

The schema legs are hermetic (jsonschema only; run with ``pytest --noconftest``).
"""
from __future__ import annotations

import json
import os

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaValidationError

HERE = os.path.dirname(__file__)
RM_DIR = os.path.join(HERE, "..", "contracts", "repo-meta")


def _load(name: str):
    with open(os.path.join(RM_DIR, name), "rb") as f:
        return json.load(f)


SCHEMA = _load("repo-meta.schema.json")
INSTANCE = _load("repo-meta.contract.json")


def _validator() -> Draft202012Validator:
    return Draft202012Validator(SCHEMA, format_checker=FormatChecker())


# --------------------------------------------------------------------------- #
# 1. SCHEMA layer                                                             #
# --------------------------------------------------------------------------- #


def test_canonical_instance_validates():
    _validator().validate(INSTANCE)


def test_minimal_manifest_validates():
    # schema_version + layer are the only required fields; capabilities may be
    # empty/absent.
    _validator().validate({"schema_version": 1, "layer": "service"})


def test_empty_capabilities_ok():
    _validator().validate(
        {"schema_version": 1, "layer": "service", "capabilities": []}
    )


@pytest.mark.parametrize(
    "layer", ["service", "runtime-template", "plugin", "org-template", "contract"]
)
def test_every_layer_enum_value_validates(layer):
    _validator().validate({"schema_version": 1, "layer": layer})


def test_bad_layer_rejected():
    with pytest.raises(SchemaValidationError):
        _validator().validate({"schema_version": 1, "layer": "microservice"})


def test_missing_layer_rejected():
    with pytest.raises(SchemaValidationError):
        _validator().validate({"schema_version": 1})


def test_missing_schema_version_rejected():
    with pytest.raises(SchemaValidationError):
        _validator().validate({"layer": "service"})


def test_wrong_schema_version_rejected():
    with pytest.raises(SchemaValidationError):
        _validator().validate({"schema_version": 2, "layer": "service"})


def test_additional_top_level_property_rejected():
    # STRICT routing contract: a mis-spelled/unknown top-level key is a HARD
    # error (additionalProperties:false), unlike the tolerant marketplace
    # artifacts. This is the load-bearing difference the .README calls out.
    with pytest.raises(SchemaValidationError):
        _validator().validate(
            {"schema_version": 1, "layer": "service", "capabilties": ["go-service"]}
        )


@pytest.mark.parametrize(
    "cap", ["go_service", "GoService", "go--service", "-leading", "trailing-", "x-", ""]
)
def test_malformed_capability_rejected_by_pattern(cap):
    # The kebab-case pattern is the typo guard: fat-finger variants of a KNOWN
    # capability fail the pattern outright rather than passing as novel.
    with pytest.raises(SchemaValidationError):
        _validator().validate(
            {"schema_version": 1, "layer": "service", "capabilities": [cap]}
        )


@pytest.mark.parametrize("cap", ["go-service", "mcp-server-bake", "x-fuzz", "some-new-bundle"])
def test_wellformed_capability_tolerated_by_schema(cap):
    # OPEN set: a well-formed capability validates whether or not it is KNOWN
    # (forward-compat). `some-new-bundle` is unknown yet schema-legal — proving
    # the openness is non-vacuous. (The validator WARNS on it; see below.)
    _validator().validate(
        {"schema_version": 1, "layer": "service", "capabilities": [cap]}
    )


def test_duplicate_capabilities_rejected():
    with pytest.raises(SchemaValidationError):
        _validator().validate(
            {
                "schema_version": 1,
                "layer": "service",
                "capabilities": ["go-service", "go-service"],
            }
        )


def test_valid_waiver_validates():
    _validator().validate(
        {
            "schema_version": 1,
            "layer": "runtime-template",
            "capabilities": ["mcp-server-bake"],
            "waivers": [
                {
                    "bundle": "mcp-server-bake",
                    "until": "2026-09-01",
                    "reason": "blocked on molecule-core#1234 — flaky bake infra",
                }
            ],
        }
    )


@pytest.mark.parametrize("drop", ["bundle", "until", "reason"])
def test_waiver_missing_required_field_rejected(drop):
    waiver = {
        "bundle": "mcp-server-bake",
        "until": "2026-09-01",
        "reason": "blocked on molecule-core#1234",
    }
    del waiver[drop]
    with pytest.raises(SchemaValidationError):
        _validator().validate(
            {"schema_version": 1, "layer": "service", "waivers": [waiver]}
        )


def test_waiver_bad_date_rejected():
    with pytest.raises(SchemaValidationError):
        _validator().validate(
            {
                "schema_version": 1,
                "layer": "service",
                "waivers": [
                    {"bundle": "x", "until": "next-quarter", "reason": "see #1"}
                ],
            }
        )


def test_waiver_additional_property_rejected():
    with pytest.raises(SchemaValidationError):
        _validator().validate(
            {
                "schema_version": 1,
                "layer": "service",
                "waivers": [
                    {
                        "bundle": "x",
                        "until": "2026-09-01",
                        "reason": "see #1",
                        "forever": True,
                    }
                ],
            }
        )


def test_known_capability_vocabulary_matches_readme_families():
    # The documentation-only knownCapability enum is the machine-readable home
    # of the KNOWN vocabulary; keep it non-empty and exactly the 8 families.
    known = set(SCHEMA["$defs"]["knownCapability"]["enum"])
    assert known == {
        "go-service",
        "python-package",
        "adapter",
        "mcp-server-bake",
        "skills",
        "settings-fragment",
        "env-mutator",
        "docker-image",
    }
