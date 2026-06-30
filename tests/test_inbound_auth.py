"""Tests for the inbound A2A auth gap fix + platform_inbound_secret persistence.

Covers:
* :class:`A2AServer` verifying the ``platform_inbound_secret`` on
  ``POST /a2a/inbound`` (fail-closed when a secret is configured; backward-
  compatible passthrough when it is not).
* :class:`RemoteAgentClient` capturing + persisting the secret from the
  register / heartbeat responses (0600, alongside the auth token).
* :class:`PushDelivery` feeding the captured secret to the A2AServer.

The auth mechanism mirrors the in-platform consumer of the same contract,
``molecule_runtime.platform_inbound_auth`` — the platform signs proxied
inbound calls with ``Authorization: Bearer <platform_inbound_secret>`` and the
receiver does a constant-time compare.
"""
from __future__ import annotations

import json
import stat
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from molecule_external_workspace import RemoteAgentClient
from molecule_external_workspace.a2a_server import A2AServer
from molecule_external_workspace.inbound import PushDelivery


SECRET = "pis_8a1c3e5f70b9d2a463f9c1b7a2e4d605"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int = 200, json_body=None):
        self.status_code = status_code
        self._json = json_body

    def json(self):
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def tmp_token_dir(tmp_path: Path) -> Path:
    return tmp_path / "molecule-token-cache"


@pytest.fixture
def client(tmp_token_dir: Path) -> RemoteAgentClient:
    return RemoteAgentClient(
        workspace_id="ws-test-123",
        platform_url="http://platform.test",
        agent_card={"name": "test-agent"},
        token_dir=tmp_token_dir,
        session=MagicMock(),
    )


def _post(host: str, port: int, payload: dict, headers: dict | None = None) -> tuple[int, dict]:
    conn = HTTPConnection(host, port, timeout=5)
    body = json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    conn.request("POST", "/a2a/inbound", body=body, headers=hdrs)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


# ---------------------------------------------------------------------------
# A2AServer inbound-auth enforcement
# ---------------------------------------------------------------------------


def test_inbound_with_secret_rejects_missing_auth() -> None:
    """A secret-configured server 401s a request with no Authorization."""
    handler = MagicMock(return_value={"ok": True})
    server = A2AServer(
        agent_id="a",
        inbound_url="https://x/a2a/inbound",
        message_handler=handler,
        inbound_secret=SECRET,
    )
    server.start_in_background()
    try:
        host, port = server._server.server_address  # type: ignore[union-attr]
        status, body = _post(host, port, {"task_id": "t1"})
        assert status == 401
        assert body["error"] == "unauthorized"
        handler.assert_not_called()
    finally:
        server.stop()


def test_inbound_with_secret_rejects_wrong_bearer() -> None:
    """A wrong / mismatched bearer is rejected without reaching the handler."""
    handler = MagicMock(return_value={"ok": True})
    server = A2AServer(
        agent_id="a",
        inbound_url="https://x/a2a/inbound",
        message_handler=handler,
        inbound_secret=SECRET,
    )
    server.start_in_background()
    try:
        host, port = server._server.server_address  # type: ignore[union-attr]
        status, body = _post(host, port, {"task_id": "t1"}, {"Authorization": "Bearer nope"})
        assert status == 401
        handler.assert_not_called()
        # A bare secret without the "Bearer " prefix is also rejected.
        status2, _ = _post(host, port, {"task_id": "t1"}, {"Authorization": SECRET})
        assert status2 == 401
    finally:
        server.stop()


def test_inbound_with_secret_accepts_correct_bearer() -> None:
    """The legitimate caller (platform holds the secret) is served normally."""
    handler = MagicMock(return_value={"reply": "pong"})
    server = A2AServer(
        agent_id="a",
        inbound_url="https://x/a2a/inbound",
        message_handler=handler,
        inbound_secret=SECRET,
    )
    server.start_in_background()
    try:
        host, port = server._server.server_address  # type: ignore[union-attr]
        status, body = _post(host, port, {"task_id": "t1"}, {"Authorization": f"Bearer {SECRET}"})
        assert status == 200
        assert body["status"] == "ok"
        assert body["result"] == {"reply": "pong"}
        handler.assert_called_once_with({"task_id": "t1"})
    finally:
        server.stop()


def test_inbound_without_secret_is_backward_compatible() -> None:
    """No secret configured → legacy unauthenticated passthrough (no 401).

    Closing the gap is opt-in via the secret the platform always delivers;
    we must not break existing direct A2AServer users who never set one.
    """
    handler = MagicMock(return_value={"ok": True})
    server = A2AServer(
        agent_id="a",
        inbound_url="https://x/a2a/inbound",
        message_handler=handler,
    )
    server.start_in_background()
    try:
        host, port = server._server.server_address  # type: ignore[union-attr]
        status, _ = _post(host, port, {"task_id": "t1"})
        assert status == 200
        handler.assert_called_once()
    finally:
        server.stop()


def test_set_inbound_secret_flips_to_fail_closed() -> None:
    """set_inbound_secret() after start enforces auth from the next request."""
    handler = MagicMock(return_value={"ok": True})
    server = A2AServer(
        agent_id="a",
        inbound_url="https://x/a2a/inbound",
        message_handler=handler,
    )
    server.start_in_background()
    try:
        host, port = server._server.server_address  # type: ignore[union-attr]
        # Before: unauthenticated allowed.
        assert _post(host, port, {"task_id": "t1"})[0] == 200
        # Wire the secret -> now fail-closed.
        server.set_inbound_secret(SECRET)
        assert _post(host, port, {"task_id": "t2"})[0] == 401
        assert _post(host, port, {"task_id": "t3"}, {"Authorization": f"Bearer {SECRET}"})[0] == 200
        # Passing empty never downgrades an already-configured secret.
        server.set_inbound_secret("")
        assert _post(host, port, {"task_id": "t4"})[0] == 401
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# RemoteAgentClient secret persistence
# ---------------------------------------------------------------------------


def test_register_captures_and_persists_secret(client: RemoteAgentClient) -> None:
    client._session.post.return_value = FakeResponse(
        200, {"status": "registered", "auth_token": "tok-1", "platform_inbound_secret": SECRET}
    )
    client.register()
    # Persisted 0600 alongside the auth token.
    assert client.platform_inbound_secret_file.exists()
    mode = stat.S_IMODE(client.platform_inbound_secret_file.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got 0o{mode:o}"
    assert client.platform_inbound_secret == SECRET
    assert client.platform_inbound_secret_file.read_text() == SECRET


def test_heartbeat_captures_secret(client: RemoteAgentClient) -> None:
    client._session.post.return_value = FakeResponse(
        200, {"status": "ok", "platform_inbound_secret": SECRET}
    )
    client.heartbeat()
    assert client.platform_inbound_secret == SECRET


def test_secret_roundtrip_and_empty_ignored(client: RemoteAgentClient) -> None:
    client.save_platform_inbound_secret(SECRET)
    assert client.load_platform_inbound_secret() == SECRET
    # Empty / whitespace never clobbers a good secret (fail-open heartbeat).
    client.save_platform_inbound_secret("")
    client.save_platform_inbound_secret("   ")
    assert client.load_platform_inbound_secret() == SECRET


def test_register_without_secret_writes_no_file(client: RemoteAgentClient) -> None:
    client._session.post.return_value = FakeResponse(
        200, {"status": "registered", "auth_token": "tok-1"}
    )
    client.register()
    assert not client.platform_inbound_secret_file.exists()
    assert client.platform_inbound_secret is None


def test_load_secret_none_when_absent(client: RemoteAgentClient) -> None:
    assert client.load_platform_inbound_secret() is None


# ---------------------------------------------------------------------------
# PushDelivery wiring: client secret -> A2AServer
# ---------------------------------------------------------------------------


def test_pushdelivery_feeds_secret_to_server(client: RemoteAgentClient) -> None:
    """PushDelivery wires the server so a captured secret reaches inbound-auth."""
    server = A2AServer(
        agent_id=client.workspace_id,
        inbound_url="https://x/a2a/inbound",
        message_handler=MagicMock(return_value={}),
    )
    delivery = PushDelivery(client, server)

    # Simulate the platform delivering the secret on a heartbeat.
    client._session.post.return_value = FakeResponse(
        200, {"status": "ok", "platform_inbound_secret": SECRET}
    )
    client.heartbeat()
    # The attached server received the secret (fed on capture).
    assert server._inbound_secret == SECRET

    # run_once re-syncs (covers lazy-heal / rotation) without raising.
    assert delivery.run_once(MagicMock()) == 0
    assert server._inbound_secret == SECRET


def test_attach_inbound_server_feeds_persisted_secret(client: RemoteAgentClient) -> None:
    """On restart (secret already on disk) attaching wires fail-closed at once."""
    client.save_platform_inbound_secret(SECRET)
    server = A2AServer(
        agent_id=client.workspace_id,
        inbound_url="https://x/a2a/inbound",
        message_handler=MagicMock(return_value={}),
    )
    PushDelivery(client, server)  # attach happens in __init__
    assert server._inbound_secret == SECRET
