"""Tests for the molecule_plugin.validate_repo_meta validator.

Covers the RFC-required cases: a valid manifest passes; a bad layer fails; an
unknown capability WARNS but does not fail schema; a missing required field
fails; a waiver validates. Plus: the validator's LAYERS / KNOWN_CAPABILITIES /
CAPABILITY_RE stay in sync with the SSOT schema (so a schema edit that is not
mirrored in the validator reds here).
"""
from __future__ import annotations

import json
import os

from molecule_plugin.validate_repo_meta import (
    CAPABILITY_RE,
    KNOWN_CAPABILITIES,
    LAYERS,
    validate_repo_meta,
    validate_repo_meta_data,
)

HERE = os.path.dirname(__file__)
RM_DIR = os.path.join(HERE, "..", "contracts", "repo-meta")


def _schema():
    with open(os.path.join(RM_DIR, "repo-meta.schema.json"), "rb") as f:
        return json.load(f)


# --- valid manifests pass --------------------------------------------------- #


def test_valid_manifest_passes():
    r = validate_repo_meta_data(
        {"schema_version": 1, "layer": "service", "capabilities": ["go-service"]},
        "mem",
    )
    assert r.ok, r.errors
    assert not r.warnings


def test_canonical_instance_file_passes():
    # The .contract.json canonical instance loaded from disk (as a repo-meta.yaml
    # would be) passes — it uses only KNOWN capabilities, so no warnings either.
    import yaml

    inst = json.load(open(os.path.join(RM_DIR, "repo-meta.contract.json")))
    r = validate_repo_meta_data(yaml.safe_load(json.dumps(inst)), "canonical")
    assert r.ok, r.errors
    assert not r.warnings, r.warnings


def test_empty_capabilities_passes():
    r = validate_repo_meta_data(
        {"schema_version": 1, "layer": "contract", "capabilities": []}, "mem"
    )
    assert r.ok, r.errors


# --- bad layer fails -------------------------------------------------------- #


def test_bad_layer_fails():
    r = validate_repo_meta_data({"schema_version": 1, "layer": "nope"}, "mem")
    assert not r.ok
    assert any("layer" in e.message for e in r.errors)


# --- unknown capability WARNS but passes schema ----------------------------- #


def test_unknown_capability_warns_but_passes():
    r = validate_repo_meta_data(
        {"schema_version": 1, "layer": "service", "capabilities": ["some-new-bundle"]},
        "mem",
    )
    # Well-formed unknown capability: legal (no error), but WARNED (no bundle).
    assert r.ok, r.errors
    assert any("some-new-bundle" in w.message for w in r.warnings)


def test_experimental_x_prefixed_capability_warns_but_passes():
    r = validate_repo_meta_data(
        {"schema_version": 1, "layer": "service", "capabilities": ["x-fuzz"]}, "mem"
    )
    assert r.ok, r.errors
    assert any("x-fuzz" in w.message for w in r.warnings)


def test_typo_on_known_capability_is_an_error_not_a_warning():
    # `go_service` violates the kebab pattern -> hard error (typo guard), NOT a
    # tolerated-unknown warning.
    r = validate_repo_meta_data(
        {"schema_version": 1, "layer": "service", "capabilities": ["go_service"]},
        "mem",
    )
    assert not r.ok
    assert any("go_service" in e.message for e in r.errors)


# --- missing required field fails ------------------------------------------- #


def test_missing_layer_fails():
    r = validate_repo_meta_data({"schema_version": 1}, "mem")
    assert not r.ok
    assert any("layer" in e.message for e in r.errors)


def test_missing_schema_version_fails():
    r = validate_repo_meta_data({"layer": "service"}, "mem")
    assert not r.ok
    assert any("schema_version" in e.message for e in r.errors)


def test_non_mapping_fails():
    r = validate_repo_meta_data(["not", "a", "map"], "mem")
    assert not r.ok


# --- a waiver validates ----------------------------------------------------- #


def test_valid_waiver_passes():
    r = validate_repo_meta_data(
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
        },
        "mem",
    )
    assert r.ok, r.errors
    assert not r.warnings, r.warnings


def test_waiver_missing_field_fails():
    r = validate_repo_meta_data(
        {
            "schema_version": 1,
            "layer": "service",
            "waivers": [{"bundle": "x", "until": "2026-09-01"}],
        },
        "mem",
    )
    assert not r.ok
    assert any("reason" in e.message for e in r.errors)


def test_waiver_without_issue_reference_warns():
    r = validate_repo_meta_data(
        {
            "schema_version": 1,
            "layer": "service",
            "waivers": [
                {"bundle": "go-service", "until": "2026-09-01", "reason": "later"}
            ],
        },
        "mem",
    )
    # Schema-valid (reason present) but not auditable -> warning, not error.
    assert r.ok, r.errors
    assert any("tracking issue" in w.message for w in r.warnings)


# --- file-path entrypoint --------------------------------------------------- #


def test_missing_file_reports_error(tmp_path):
    r = validate_repo_meta(tmp_path)  # a dir with no repo-meta.yaml
    assert not r.ok
    assert any("missing repo-meta.yaml" in e.message for e in r.errors)


def test_reads_repo_meta_yaml_from_dir(tmp_path):
    (tmp_path / "repo-meta.yaml").write_text(
        "schema_version: 1\nlayer: plugin\ncapabilities: [skills, env-mutator]\n"
    )
    r = validate_repo_meta(tmp_path)
    assert r.ok, r.errors


# --- validator vocab stays in sync with the SSOT schema --------------------- #


def test_layers_match_schema_enum():
    schema = _schema()
    assert LAYERS == set(schema["$defs"]["layer"]["enum"])


def test_known_capabilities_match_schema_enum():
    schema = _schema()
    assert KNOWN_CAPABILITIES == set(schema["$defs"]["knownCapability"]["enum"])


def test_capability_pattern_matches_schema():
    schema = _schema()
    assert CAPABILITY_RE.pattern == schema["$defs"]["capability"]["pattern"]
