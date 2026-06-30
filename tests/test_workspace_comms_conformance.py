"""Schema-conformance gate for the workspace-comms wire contract.

This REPLACES the old cross-repo AST drift-checker
(``molecule-ai-workspace-runtime/scripts/check_platform_comm_contract.py``).
Instead of statically pattern-matching code structure, it captures the ACTUAL
register + A2A-envelope payloads :class:`RemoteAgentClient` puts on the wire and
validates each against the SSOT JSON-Schema (draft 2020-12) promoted into
``molecule-contracts/workspace-comms``. That is strictly stronger than the AST
guard: it checks the real produced bytes, not a code shape a refactor could
satisfy while still emitting a non-conformant body.

The schemas are vendored under ``tests/fixtures/workspace_comms/`` (byte-for-byte
copies of the contracts SSOT — see PROVENANCE.md) so the gate runs fully offline
in CI with no cross-repo clone, no token, and no network.

Each contract instance models BOTH directions (``request`` + ``response``); the
client is the REQUEST producer, so we validate the captured bodies against the
schema's ``#/properties/request`` sub-schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from molecule_external_workspace import RemoteAgentClient

SCHEMA_DIR = Path(__file__).parent / "fixtures" / "workspace_comms"

# Canonical SSOT $id prefix — a tripwire so a silently-edited / forked vendored
# copy is caught rather than validating against a drifted schema.
CANONICAL_ID_PREFIX = (
    "https://git.moleculesai.app/molecule-ai/molecule-contracts/workspace-comms/"
)


def _request_validator(schema_name: str) -> Draft202012Validator:
    """Build a draft-2020-12 validator for a schema's ``#/properties/request``.

    The request sub-schema ``$ref``s ``#/$defs/agentCard`` at the document root,
    so we register the WHOLE schema as a resource (under its ``$id``) and point
    the validator at the request sub-schema by ref — the internal ``$defs``
    pointers then resolve against the full document.
    """
    schema = json.loads((SCHEMA_DIR / f"{schema_name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["$id"].startswith(CANONICAL_ID_PREFIX), (
        f"vendored {schema_name}.schema.json $id {schema['$id']!r} is not the "
        f"canonical contracts URL — the vendored copy has drifted from SSOT"
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    resource = Resource(contents=schema, specification=DRAFT202012)
    registry = Registry().with_resource(uri=schema["$id"], resource=resource)
    return Draft202012Validator(
        {"$ref": schema["$id"] + "#/properties/request"}, registry=registry
    )


def _assert_valid(validator: Draft202012Validator, payload: dict[str, Any]) -> None:
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        rendered = "\n".join(
            f"  - at {list(e.path)}: {e.message}" for e in errors
        )
        raise AssertionError(
            "payload does not conform to the workspace-comms contract:\n"
            f"{rendered}\npayload={json.dumps(payload, indent=2)}"
        )


class _FakeResponse:
    def __init__(self, json_body: Any) -> None:
        self._json = json_body
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.text = ""

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        return None


class _CapturingSession:
    """A requests.Session-shaped stub that records every POST body.

    Lets us assert on the REAL wire payload the client builds without standing
    up a platform — this is the exact JSON ``RemoteAgentClient`` hands to
    ``requests``.
    """

    def __init__(self, json_body: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._json_body = json_body or {}

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, "json": kwargs.get("json")})
        return _FakeResponse(self._json_body)

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:  # pragma: no cover
        return _FakeResponse(self._json_body)

    @property
    def last_body(self) -> dict[str, Any]:
        assert self.calls, "no POST was captured"
        body = self.calls[-1]["json"]
        assert isinstance(body, dict), f"captured body is not a dict: {body!r}"
        return body


def _client(session: _CapturingSession, tmp_path: Path, **overrides: Any) -> RemoteAgentClient:
    kwargs: dict[str, Any] = dict(
        workspace_id="0b8f2c4a-1d3e-4f56-9a7b-2c8d4e6f1a90",
        platform_url="http://platform.test",
        agent_card={"name": "Remote Agent", "description": "an external agent"},
        reported_url="https://remote.example/a2a",
        token_dir=tmp_path / "token-cache",
        session=session,
    )
    kwargs.update(overrides)
    return RemoteAgentClient(**kwargs)


# ---------------------------------------------------------------------------
# Positive: the real builders emit contract-conformant payloads
# ---------------------------------------------------------------------------


def test_register_payload_conforms(tmp_path: Path) -> None:
    session = _CapturingSession(
        {"status": "registered", "delivery_mode": "push", "auth_token": ""}
    )
    client = _client(session, tmp_path)
    client.register()
    body = session.last_body
    assert "/registry/register" in session.calls[-1]["url"]
    _assert_valid(_request_validator("register"), body)


def test_call_peer_envelope_conforms(tmp_path: Path) -> None:
    session = _CapturingSession({"status": "queued", "delivery_mode": "push-async"})
    client = _client(session, tmp_path)
    # prefer_direct=False routes straight through the platform proxy, so the
    # captured body is the full JSON-RPC A2A envelope the client constructs.
    client.call_peer("peer-workspace-id", "hello peer", prefer_direct=False)
    body = session.last_body
    assert "/a2a" in session.calls[-1]["url"]
    _assert_valid(_request_validator("a2a-envelope"), body)


def test_register_agent_card_default_conforms(tmp_path: Path) -> None:
    # The constructor synthesizes a default agent_card ({"name": ...}) when none
    # is supplied; the contract requires a non-empty card name, so prove the
    # default path is conformant too.
    session = _CapturingSession(
        {"status": "registered", "delivery_mode": "push", "auth_token": ""}
    )
    client = _client(session, tmp_path, agent_card=None)
    client.register()
    _assert_valid(_request_validator("register"), session.last_body)


# ---------------------------------------------------------------------------
# Negative: the gate MUST reject a divergent payload (anti-vacuous proof)
# ---------------------------------------------------------------------------


def test_gate_catches_type_keyed_part() -> None:
    """A2A v0.3 parts are discriminated by ``kind``; a ``type``-keyed part is
    silently dropped by the receiver's validator (#2345). The gate must catch
    a regression that ships ``type`` instead of ``kind``."""
    validator = _request_validator("a2a-envelope")
    bad_envelope = {
        "jsonrpc": "2.0",
        "id": "abc",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": "abc",
                "parts": [{"type": "text", "text": "dropped by v0.3 validator"}],
            }
        },
    }
    assert list(validator.iter_errors(bad_envelope)), (
        "gate FAILED to reject a type-keyed (non-kind) A2A part — it would not "
        "catch the #2345 regression class"
    )


def test_gate_catches_missing_register_id() -> None:
    validator = _request_validator("register")
    bad = {"url": "https://x", "agent_card": {"name": "n"}}  # missing required id
    assert list(validator.iter_errors(bad))


def test_gate_catches_bad_delivery_mode() -> None:
    validator = _request_validator("register")
    bad = {"id": "x", "agent_card": {"name": "n"}, "delivery_mode": "carrier-pigeon"}
    assert list(validator.iter_errors(bad))


@pytest.mark.parametrize("schema_name", ["register", "heartbeat", "a2a-envelope"])
def test_vendored_schema_is_canonical(schema_name: str) -> None:
    """Tripwire: the vendored schema is the SSOT mirror, not a fork."""
    _request_validator(schema_name)  # raises if $id/$schema drifted
