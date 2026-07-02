"""Prove-fail conformance gate for the marketplace-service catalog contracts.

The repo's `validate` CI job already checks that every
`contracts/catalog/*.contract.json` POSITIVE instance validates against its
sibling schema. This test adds the NEGATIVE half — the load-bearing invariants
a positive-only check can't prove — so a future loosening of the schema reds
here instead of silently accepting a bad payload:

  1. every catalog contract instance validates (positive, draft 2020-12);
  2. an UNPINNED `source` (`gitea://owner/repo` with no `#ref`) is REJECTED by
     every schema that uses the pinned `sourceRef` (`^gitea://[^#]+#[^#]+$`) —
     the immutable-ref invariant the contract prose promises;
  3. a non-`none` `attestation` with no `signature` is REJECTED by
     publish-request (no provenance-looking payload without provenance);
  4. an install-request missing the const-pinned `mode` is REJECTED (the
     `const: reconcile` pin only bites because `mode` is required).

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
CATALOG = os.path.join(HERE, "..", "contracts", "catalog")


def _load(name: str) -> dict:
    with open(os.path.join(CATALOG, name), encoding="utf-8") as fh:
        return json.load(fh)


def _schema(stem: str) -> dict:
    return _load(f"{stem}.schema.json")


def _instance(stem: str) -> dict:
    return _load(f"{stem}.contract.json")


def test_every_catalog_instance_validates() -> None:
    instances = sorted(glob.glob(os.path.join(CATALOG, "*.contract.json")))
    assert instances, "no catalog contract instances found (fail-closed)"
    for inst in instances:
        schema_path = inst[: -len(".contract.json")] + ".schema.json"
        schema = json.load(open(schema_path, encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        data = json.load(open(inst, encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(data))
        assert not errors, f"{os.path.basename(inst)}: {[e.message for e in errors]}"


@pytest.mark.parametrize("stem", ["catalog", "publish-request", "install-request", "entitlement"])
def test_unpinned_source_is_rejected(stem: str) -> None:
    """A source without a `#<ref>` is a mutable ref — must be rejected."""
    schema = _schema(stem)
    inst = copy.deepcopy(_instance(stem))
    if stem == "catalog":
        inst["entries"][0]["source"] = "gitea://molecule-ai/repo"
    else:
        inst["source"] = "gitea://molecule-ai/repo"
    errors = list(Draft202012Validator(schema).iter_errors(inst))
    assert errors, f"{stem}: unpinned source (no #ref) was accepted — sourceRef pattern too loose"


@pytest.mark.parametrize("stem", ["install-request", "entitlement"])
def test_install_boundary_source_rejects_mutable_ref(stem: str) -> None:
    """The install/authorization boundary MUST carry an immutable commit SHA —
    a branch/tag like `#main` or `#v1.2.0` is mutable and must be rejected."""
    schema = _schema(stem)
    for mutable in ("gitea://molecule-ai/repo#main", "gitea://molecule-ai/repo#v1.2.0", "gitea://molecule-ai/repo#3f2a1b9"):
        inst = copy.deepcopy(_instance(stem))
        inst["source"] = mutable
        errors = list(Draft202012Validator(schema).iter_errors(inst))
        assert errors, f"{stem}: mutable ref {mutable!r} accepted — install target could move / short-SHA ambiguous"


def test_publish_accepts_tag_ref() -> None:
    """Human-facing publish sources may carry a tag; the agent resolves it to a
    full commit SHA for the install/entitlement records (which are SHA-only)."""
    schema = _schema("publish-request")
    inst = copy.deepcopy(_instance("publish-request"))
    inst["source"] = "gitea://molecule-ai/repo#v1.2.0"
    assert not list(Draft202012Validator(schema).iter_errors(inst)), "publish-request: tag ref rejected"


def test_attestation_without_signature_is_rejected() -> None:
    schema = _schema("publish-request")
    inst = copy.deepcopy(_instance("publish-request"))
    inst["attestation"] = {
        "mode": "keyless",
        "digest": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }  # signer + signature missing
    errors = list(Draft202012Validator(schema).iter_errors(inst))
    assert errors, "keyless attestation without signature/signer was accepted (no-provenance payload)"


def test_attestation_none_needs_nothing() -> None:
    """mode:none is the unsigned escape hatch and must still validate."""
    schema = _schema("publish-request")
    inst = copy.deepcopy(_instance("publish-request"))
    inst["attestation"] = {"mode": "none"}
    assert not list(Draft202012Validator(schema).iter_errors(inst))


def test_install_request_requires_mode_and_idempotency_key() -> None:
    schema = _schema("install-request")
    for missing in ("mode", "idempotency_key"):
        inst = copy.deepcopy(_instance("install-request"))
        del inst[missing]
        errors = list(Draft202012Validator(schema).iter_errors(inst))
        assert errors, f"install-request without {missing!r} was accepted"


def test_paid_pricing_must_be_complete() -> None:
    """A paid pricing DECLARATION must carry amount+currency (+interval for
    subscription); `free` must not carry a nonzero amount or an interval."""
    schema = _schema("publish-request")
    base = copy.deepcopy(_instance("publish-request"))
    bad_pricings = [
        {"model": "one-time"},                                   # missing amount+currency
        {"model": "subscription", "amount_cents": 2000, "currency": "USD"},  # missing interval
        {"model": "subscription"},                               # missing everything
        {"model": "free", "amount_cents": 500},                  # free but nonzero
        {"model": "free", "interval": "month"},                  # free but has interval
    ]
    for pricing in bad_pricings:
        inst = copy.deepcopy(base)
        inst["pricing"] = pricing
        errors = list(Draft202012Validator(schema).iter_errors(inst))
        assert errors, f"incomplete/contradictory pricing accepted: {pricing}"
    # positive: a complete subscription and a bare free both validate
    for pricing in ({"model": "subscription", "amount_cents": 2000, "currency": "USD", "interval": "month"},
                    {"model": "free"}):
        inst = copy.deepcopy(base)
        inst["pricing"] = pricing
        assert not list(Draft202012Validator(schema).iter_errors(inst)), f"valid pricing rejected: {pricing}"


def test_catalog_entries_validate_against_catalog_entry_schema() -> None:
    """The catalog document only checks the envelope; the README promises every
    entry ALSO validates against catalog-entry.schema.json. Enforce that here
    (the cross-file invariant the self-contained schema can't express)."""
    entry_schema = _schema("catalog-entry")
    catalog = _instance("catalog")
    for i, entry in enumerate(catalog["entries"]):
        errors = list(Draft202012Validator(entry_schema).iter_errors(entry))
        assert not errors, f"catalog.entries[{i}] fails catalog-entry.schema.json: {[e.message for e in errors][:2]}"
    # Non-vacuous: catalog-entry.schema.json must REJECT a malformed entry (a
    # kind/spec mismatch that catalog.schema.json's open envelope would let pass).
    bad = copy.deepcopy(catalog["entries"][0])
    bad["kind"] = "not-a-real-kind"
    assert list(Draft202012Validator(entry_schema).iter_errors(bad)), \
        "catalog-entry.schema.json accepted an invalid kind — per-entry validation is vacuous"
