"""Validator for a repository's ``repo-meta.yaml``.

``repo-meta.yaml`` is the per-repository manifest that declares **what a repo
is** (``layer``) and **what it can do** (``capabilities``). The meta-CI router
reads it to decide which CI capability-bundles to attach; org-enforcement reads
it to decide what a repo of a given layer is *required* to carry. See
``contracts/repo-meta/`` for the SSOT schema + doc.

This validator is the SDK-side authoring/CI helper. It:

1. **schema-validates** the manifest against ``contracts/repo-meta/
   repo-meta.schema.json`` (when ``jsonschema`` is installed — the ``[test]``
   extra; the SDK keeps ``jsonschema`` out of the *base* deps, so this leg is
   best-effort and degrades to the hand-rolled checks below when it is absent),
2. enforces the STRICT structural invariants directly (required fields, the
   closed ``layer`` enum, the kebab-case capability pattern, waiver shape) so
   the core checks hold even without ``jsonschema``, and
3. **WARNS — does not error** — on any capability outside the KNOWN vocabulary.
   An unknown capability is legal (forward-compat: a bundle may be declared
   before this schema learns its name) but attaches no CI bundle, so it is
   surfaced as a warning rather than a hard failure.

Warnings are returned distinctly from errors (``RepoMetaResult``) so CI can
treat them as non-fatal. Mirrors the ``ValidationError`` style of the sibling
``org``/``workspace`` validators; the only addition is the warn channel the
open-capability semantics require.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Reuse the canonical ValidationError dataclass (file, message) so a repo-meta
# problem is the same type the org/workspace validators emit — one error shape
# across the SDK's validators.
from .workspace import ValidationError

# SSOT schema location — resolved relative to this package, mirroring
# adapter_conformance._REGISTRY_PATH. Degrades to a clean skip of the
# jsonschema leg when the contracts tree is not vendored alongside the package.
_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "contracts"
    / "repo-meta"
    / "repo-meta.schema.json"
)

# The closed `layer` enum — kept in sync with contracts/repo-meta/
# repo-meta.schema.json $defs/layer.enum (asserted by the contract test).
LAYERS = frozenset(
    {"service", "runtime-template", "plugin", "org-template", "contract"}
)

# The KNOWN capability vocabulary — kept in sync with the schema's
# $defs/knownCapability.enum (asserted by the contract test). A capability
# OUTSIDE this set is legal but warned (attaches no bundle).
KNOWN_CAPABILITIES = frozenset(
    {
        "go-service",
        "python-package",
        "adapter",
        "mcp-server-bake",
        "skills",
        "settings-fragment",
        "env-mutator",
        "docker-image",
    }
)

# The kebab-case capability pattern — kept byte-identical to the schema's
# $defs/capability.pattern (asserted by the contract test). Lowercase
# kebab-case, optionally `x-`-prefixed for an experimental bundle.
CAPABILITY_RE = re.compile(r"^(x-)?[a-z0-9]+(-[a-z0-9]+)*$")

# A waiver reason should cite a tracking issue (audit trail). Detected as a
# `<word>#<number>` reference (e.g. `molecule-core#1234`, `#42`). Missing one is
# a WARNING, not an error — the schema requires a reason, this nudges toward an
# auditable one.
_ISSUE_REF_RE = re.compile(r"#\d+")


@dataclass
class RepoMetaResult:
    """Outcome of validating a repo-meta manifest.

    ``errors`` are fatal (manifest is invalid); ``warnings`` are advisory
    (valid manifest, but something a human/CI should notice — e.g. an unknown
    capability that attaches no bundle). ``ok`` is true iff there are no errors.
    """

    file: str
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_schema() -> dict[str, Any] | None:
    try:
        return json.loads(_SCHEMA_PATH.read_text())
    except (OSError, ValueError):
        return None


def _schema_errors(manifest: Any, file_ref: str) -> list[ValidationError]:
    """Best-effort jsonschema validation. Empty list if jsonschema or the
    vendored schema is unavailable (the hand-rolled checks still run)."""
    schema = _load_schema()
    if schema is None:
        return []
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        return []
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    out: list[ValidationError] = []
    for err in sorted(validator.iter_errors(manifest), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        out.append(ValidationError(file_ref, f"{loc}: {err.message}"))
    return out


def validate_repo_meta_data(manifest: Any, file_ref: str) -> RepoMetaResult:
    """Validate an already-parsed repo-meta mapping. Split out from the
    file-loading wrapper so tests can drive it with in-memory dicts."""
    result = RepoMetaResult(file=file_ref)

    if not isinstance(manifest, dict):
        result.errors.append(
            ValidationError(file_ref, "repo-meta.yaml must be a mapping/object")
        )
        return result

    # Schema leg first (authoritative when available). It catches
    # additionalProperties:false violations the hand-rolled checks below do not.
    result.errors.extend(_schema_errors(manifest, file_ref))

    # --- hand-rolled STRICT structural checks (hold without jsonschema) ------

    # schema_version — required, const 1.
    sv = manifest.get("schema_version")
    if "schema_version" not in manifest:
        result.errors.append(
            ValidationError(file_ref, "missing required field: schema_version")
        )
    elif sv != 1:
        result.errors.append(
            ValidationError(
                file_ref, f"schema_version must be the integer 1; got {sv!r}"
            )
        )

    # layer — required, closed enum.
    if "layer" not in manifest:
        result.errors.append(
            ValidationError(file_ref, "missing required field: layer")
        )
    else:
        layer = manifest["layer"]
        if layer not in LAYERS:
            result.errors.append(
                ValidationError(
                    file_ref,
                    f"layer={layer!r} — must be one of {sorted(LAYERS)}",
                )
            )

    # capabilities — optional, may be empty; open set + pattern; warn on unknown.
    caps = manifest.get("capabilities")
    if caps is not None:
        if not isinstance(caps, list):
            result.errors.append(
                ValidationError(file_ref, "capabilities must be a list")
            )
        else:
            seen: set[str] = set()
            for i, cap in enumerate(caps):
                if not isinstance(cap, str):
                    result.errors.append(
                        ValidationError(
                            file_ref, f"capabilities[{i}] must be a string; got {cap!r}"
                        )
                    )
                    continue
                if cap in seen:
                    result.errors.append(
                        ValidationError(
                            file_ref, f"capabilities[{i}]: duplicate capability {cap!r}"
                        )
                    )
                seen.add(cap)
                if not CAPABILITY_RE.match(cap):
                    # A pattern violation is a genuine ERROR (typo guard):
                    # `go_service`/`GoService`/trailing-space fail here.
                    result.errors.append(
                        ValidationError(
                            file_ref,
                            f"capabilities[{i}]={cap!r} — must be lowercase kebab-case "
                            f"(pattern {CAPABILITY_RE.pattern}); optionally 'x-'-prefixed",
                        )
                    )
                elif cap not in KNOWN_CAPABILITIES:
                    # Well-formed but unknown: legal, but attaches no bundle. WARN.
                    result.warnings.append(
                        ValidationError(
                            file_ref,
                            f"capabilities[{i}]={cap!r} is not a KNOWN capability "
                            f"{sorted(KNOWN_CAPABILITIES)} — it attaches no CI bundle "
                            "(forward-compat placeholder or a typo)",
                        )
                    )

    # waivers — optional; each {bundle, until(date), reason}; reason should cite an issue.
    waivers = manifest.get("waivers")
    if waivers is not None:
        if not isinstance(waivers, list):
            result.errors.append(
                ValidationError(file_ref, "waivers must be a list")
            )
        else:
            for i, w in enumerate(waivers):
                if not isinstance(w, dict):
                    result.errors.append(
                        ValidationError(file_ref, f"waivers[{i}] must be an object")
                    )
                    continue
                for req in ("bundle", "until", "reason"):
                    if not w.get(req):
                        result.errors.append(
                            ValidationError(
                                file_ref, f"waivers[{i}]: missing required field {req!r}"
                            )
                        )
                until = w.get("until")
                if isinstance(until, str) and not re.match(
                    r"^\d{4}-\d{2}-\d{2}$", until
                ):
                    result.errors.append(
                        ValidationError(
                            file_ref,
                            f"waivers[{i}].until={until!r} — must be a YYYY-MM-DD date",
                        )
                    )
                reason = w.get("reason")
                if isinstance(reason, str) and not _ISSUE_REF_RE.search(reason):
                    result.warnings.append(
                        ValidationError(
                            file_ref,
                            f"waivers[{i}].reason should name a tracking issue "
                            "(e.g. molecule-core#1234) for an auditable waiver",
                        )
                    )

    return result


def validate_repo_meta(path: Path) -> RepoMetaResult:
    """Validate a repo directory (or a repo-meta.yaml path directly).

    Accepts either a directory containing ``repo-meta.yaml`` or the manifest
    file itself. Returns a :class:`RepoMetaResult` (errors + warnings).
    """
    manifest_path = path / "repo-meta.yaml" if path.is_dir() else path
    file_ref = str(manifest_path)

    if not manifest_path.exists():
        return RepoMetaResult(
            file=file_ref,
            errors=[ValidationError(file_ref, "missing repo-meta.yaml")],
        )

    try:
        manifest = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError as exc:
        return RepoMetaResult(
            file=file_ref,
            errors=[ValidationError(file_ref, f"invalid YAML: {exc}")],
        )

    return validate_repo_meta_data(manifest, file_ref)


__all__ = [
    "CAPABILITY_RE",
    "KNOWN_CAPABILITIES",
    "LAYERS",
    "RepoMetaResult",
    "ValidationError",
    "validate_repo_meta",
    "validate_repo_meta_data",
]
