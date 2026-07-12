# Generated from contracts/adapter/runtime-id.schema.json and official-runtimes.registry.json by tools/gen-runtimes.mjs. DO NOT EDIT.

import re

RUNTIME_ID_MAX_LENGTH = 64
RUNTIME_ID_PATTERN = "^[a-z0-9]+([-_][a-z0-9]+)*$"
RUNTIME_ID_DISALLOWED_PATTERN = "[^a-z0-9_-]"
RUNTIME_ID_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 64,
    "pattern": "^[a-z0-9]+([-_][a-z0-9]+)*$",
    "not": {
        "pattern": "[^a-z0-9_-]"
    },
    "description": "Open, bounded, path-safe runtime identifier. Official first-party support is discovered separately; known aliases normalize without restricting third-party IDs."
}
_RUNTIME_ID_RE = re.compile(RUNTIME_ID_PATTERN)
_RUNTIME_ID_DISALLOWED_RE = re.compile(RUNTIME_ID_DISALLOWED_PATTERN)

OFFICIAL_RUNTIME_IDS = (
    "claude-code",
    "codex",
    "hermes",
    "openclaw",
)
RUNTIME_ID_ALIASES = {
    "claude_code": "claude-code",
}
OFFICIAL_RUNTIME_IDS_WITH_ALIASES = frozenset((*OFFICIAL_RUNTIME_IDS, *RUNTIME_ID_ALIASES))


def is_valid_runtime_id(runtime_id: object) -> bool:
    """Return whether runtime_id is a bounded, path-safe RuntimeId."""
    return (
        isinstance(runtime_id, str)
        and len(runtime_id) <= RUNTIME_ID_MAX_LENGTH
        and _RUNTIME_ID_RE.fullmatch(runtime_id) is not None
        and _RUNTIME_ID_DISALLOWED_RE.search(runtime_id) is None
    )


def normalize_runtime_id(runtime_id: str) -> str:
    """Normalize a known alias and preserve every other valid RuntimeId."""
    if not isinstance(runtime_id, str):
        raise TypeError("runtime id must be a string")
    if not is_valid_runtime_id(runtime_id):
        raise ValueError(f"invalid runtime id: {runtime_id!r}")
    return RUNTIME_ID_ALIASES.get(runtime_id, runtime_id)


def is_official_runtime_id(runtime_id: object) -> bool:
    """Return whether runtime_id resolves to an official first-party runtime."""
    if not is_valid_runtime_id(runtime_id):
        return False
    return RUNTIME_ID_ALIASES.get(runtime_id, runtime_id) in OFFICIAL_RUNTIME_IDS


__all__ = [
    "OFFICIAL_RUNTIME_IDS",
    "OFFICIAL_RUNTIME_IDS_WITH_ALIASES",
    "RUNTIME_ID_ALIASES",
    "RUNTIME_ID_DISALLOWED_PATTERN",
    "RUNTIME_ID_MAX_LENGTH",
    "RUNTIME_ID_PATTERN",
    "RUNTIME_ID_SCHEMA",
    "is_official_runtime_id",
    "is_valid_runtime_id",
    "normalize_runtime_id",
]
