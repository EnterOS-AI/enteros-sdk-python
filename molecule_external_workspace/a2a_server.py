"""A2A server for inbound agent calls.

Bundled alongside :class:`molecule_external_workspace.client.RemoteAgentClient` to
enable remote agents to receive A2A calls from the platform without
requiring the agent author to provision their own HTTP endpoint.

Phase 30.8b contract — the server exposes ``POST /a2a/inbound`` which
the platform's ingress proxy calls when it needs to push work to a
registered remote agent.

Usage::

    from molecule_external_workspace import RemoteAgentClient, A2AServer

    client = RemoteAgentClient(workspace_id="...", platform_url="...")
    server = A2AServer(
        agent_id=client.workspace_id,
        inbound_url="https://my-agent.example.com/a2a/inbound",
        message_handler=my_handler,
    )

    # Start server in background thread, then register with platform.
    server.start_in_background()
    client.reported_url = server.inbound_url  # platform reaches this URL
    token = client.register()

    # Heartbeat loop now reports a real URL instead of "remote://no-inbound".
    client.run_heartbeat_loop()

    # Shutdown the server when the agent exits.
    server.stop()

The ``message_handler`` signature is::

    async def my_handler(request: dict) -> dict:
        '''Return an A2A-formatted response dict.'''
        ...

Handlers are invoked on the server's internal thread pool.
"""
from __future__ import annotations

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Awaitable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Module-level HTTPServer instance so the handler can access server state.
_server: HTTPServer | None = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class _A2AHandler(BaseHTTPRequestHandler):
    """Handles ``POST /a2a/inbound`` requests.

    The request body is a JSON A2A task dispatch dict::

        {
            "task_id": "...",
            "sender": "...",
            "message": "...",
            "idempotency_key": "...",
        }

    The ``message_handler`` ( supplied at construction) is called with the
    parsed dict and its return value is written as a JSON response::

        200 {"status": "ok", "result": <handler-result>}
        400 {"error": "bad request: ..."}
        500 {"error": "internal error: ..."}
    """

    protocol_version = "HTTP/1.1"

    # Shared inbound-auth secret (the platform_inbound_secret). Class attribute
    # mirroring ``_message_handler`` — set by the owning A2AServer in
    # start_in_background() / set_inbound_secret(). ``None`` means "no secret
    # configured yet" (legacy unauthenticated passthrough, with a loud warning);
    # a non-empty value means the inbound endpoint is FAIL-CLOSED and every
    # request must present ``Authorization: Bearer <secret>``.
    _inbound_secret: str | None = None
    # One-shot guard so the "serving inbound WITHOUT auth" warning is logged
    # once per process rather than on every request.
    _warned_no_secret: bool = False

    def _inbound_authorized(self) -> bool:
        """Return True iff this inbound request is allowed to reach the handler.

        Mirrors molecule_runtime.platform_inbound_auth.inbound_authorized — the
        in-platform consumer of the SAME contract — exactly:

        * No secret configured (``_inbound_secret`` falsy) → legacy
          unauthenticated passthrough. The platform delivers the
          platform_inbound_secret on register + every heartbeat, so once the
          owning RemoteAgentClient has registered this is wired and the branch
          below (fail-closed) takes over. Until then we allow + warn loudly.
        * Secret configured → strict, constant-time equality against
          ``Bearer <secret>``. Absent or mismatched Authorization → reject.
        """
        expected = _A2AHandler._inbound_secret
        if not expected:
            if not _A2AHandler._warned_no_secret:
                logger.warning(
                    "A2AServer is serving POST /a2a/inbound WITHOUT inbound auth "
                    "(no platform_inbound_secret configured). This is an OPEN RPC "
                    "endpoint if reachable. Wire the secret via "
                    "RemoteAgentClient (register/heartbeat persists it) + "
                    "A2AServer(inbound_secret=...) / set_inbound_secret() to "
                    "fail closed."
                )
                _A2AHandler._warned_no_secret = True
            return True
        auth_header = self.headers.get("Authorization", "")
        # hmac.compare_digest is the stdlib constant-time compare; it avoids
        # leaking the secret one byte at a time via timing analysis on a
        # network-reachable endpoint. Length mismatch short-circuits safely.
        return hmac.compare_digest(auth_header, f"Bearer {expected}")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr noise; use structured logging instead."""
        logger.debug("%s %s — %s", self.command, self.path, format % args)

    def log_error(self, format: str, *args: Any) -> None:
        logger.warning("%s %s — %s", self.command, self.path, format % args)

    def _send_json(self, status: int, body: dict) -> None:
        body_bytes = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body_bytes)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/a2a/inbound":
            self._send_json(404, {"error": "not found"})
            return

        # Verify the platform_inbound_secret BEFORE reading the body, so an
        # unauthenticated caller can neither reach the handler nor make us
        # buffer an arbitrary-sized payload. Fail-closed when a secret is
        # configured; reject absent or mismatched bearers with 401.
        if not self._inbound_authorized():
            logger.warning("rejected unauthenticated inbound A2A call (401)")
            # We reject BEFORE reading the request body so an unauthenticated
            # caller can't make us buffer an arbitrary-sized payload. That
            # leaves an undrained body on the socket, so close the (HTTP/1.1
            # keep-alive) connection rather than risk desyncing the next
            # request on it.
            self.close_connection = True
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                raise ValueError("empty body")
            body = self.rfile.read(content_length)
            payload = json.loads(body)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"bad request: {exc}"})
            return

        try:
            result = _A2AHandler._message_handler(payload)
            if isinstance(result, Awaitable):
                # If the handler is async, run it synchronously in the server thread.
                # Agents that want full async semantics should use an explicit ASGI app;
                # this path covers the common case of a simple sync handler.
                import asyncio
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(result)
                finally:
                    loop.close()
            self._send_json(200, {"status": "ok", "result": result})
        except Exception as exc:
            logger.exception("message_handler raised: %s", exc)
            self._send_json(500, {"error": f"internal error: {exc}"})


# ---------------------------------------------------------------------------
# A2AServer
# ---------------------------------------------------------------------------

class A2AServer:
    """HTTP server that receives inbound A2A calls and dispatches them to a
    handler running alongside :class:`~molecule_external_workspace.client.RemoteAgentClient`.

    Args:
        agent_id: The workspace / agent identifier. Used in log messages.
        inbound_url: The URL the platform's ingress proxy uses to reach this
            server. Must be a reachable host:port (or a publicly accessible
            URL if a tunnel is in front). The value is typically assigned to
            ``RemoteAgentClient.reported_url`` before registration so the
            platform knows where to deliver inbound calls.
        message_handler: Callable that receives a parsed A2A task dict and
            returns a dict response. May be ``async def`` or regular ``def``.
        host: Address to bind the HTTP server to. Defaults to ``"0.0.0.0"``
            (all interfaces); bind to ``"127.0.0.1"`` if behind a reverse
            proxy or tunnel.
        port: TCP port to listen on. ``0`` picks an available ephemeral port
            (useful when the real public URL is managed by a proxy/tunnel).
        inbound_secret: The shared ``platform_inbound_secret`` the platform
            signs proxied inbound A2A calls with (``Authorization: Bearer
            <secret>``). Additive + optional. When set, the server is
            FAIL-CLOSED — every inbound request must present the matching
            bearer or it is rejected with 401. When ``None`` the server keeps
            the legacy unauthenticated behavior (and logs a loud warning). The
            secret is normally not known at construction time (the platform
            delivers it on the register/heartbeat response), so the common
            flow is to leave this ``None`` and let it be wired after
            registration via :py:meth:`set_inbound_secret` — which
            :class:`~molecule_external_workspace.inbound.PushDelivery` does
            automatically from the owning ``RemoteAgentClient``. Pass it
            explicitly only when you already hold a persisted secret (e.g. on
            a restart) and want fail-closed from the first request.
    """

    def __init__(
        self,
        agent_id: str,
        inbound_url: str,
        message_handler: Callable[[dict], dict | Awaitable[dict]],
        host: str = "0.0.0.0",
        port: int = 0,
        inbound_secret: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.inbound_url = inbound_url
        self.host = host
        self.port = port
        self._handler = message_handler
        self._inbound_secret = inbound_secret or None
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def set_inbound_secret(self, secret: str | None) -> None:
        """Set / update the inbound-auth secret after construction.

        Called once the owning :class:`RemoteAgentClient` has captured the
        ``platform_inbound_secret`` from a register/heartbeat response (the
        platform re-delivers it on most heartbeats). Idempotent — feeding the
        same value is a no-op. Updating to a non-empty value flips the server
        to fail-closed from the next request; passing ``None``/empty is
        ignored (we never downgrade an already-configured secret to no-auth).
        Safe to call from another thread: the assignment of a single object
        reference is atomic under CPython, and the request handler reads the
        class attribute fresh on every call.
        """
        if not secret:
            return
        self._inbound_secret = secret
        # Push to the class attribute the running handler reads, but only when
        # this instance owns the live server (its handler is wired). Avoids one
        # A2AServer clobbering another's secret when several are constructed.
        if self._server is not None:
            _A2AHandler._inbound_secret = secret

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def start_in_background(self) -> None:
        """Start the HTTP server in a daemon thread and return immediately.

        Call :py:meth:`stop` to shut it down cleanly.
        """
        global _server
        with _lock:
            self._server = HTTPServer((self.host, self.port), _A2AHandler)
            _server = self._server
            _A2AHandler._server = self  # type: ignore[attr-defined]
            _A2AHandler._message_handler = self._handler  # type: ignore[attr-defined]
            # Wire the inbound-auth secret for this server. None = legacy
            # unauthenticated passthrough (a loud warning fires on first call);
            # non-empty = fail-closed bearer check.
            _A2AHandler._inbound_secret = self._inbound_secret

        actual = self._server.server_address
        logger.info(
            "A2AServer for %s listening on %s:%s (inbound_url=%s)",
            self.agent_id, actual[0], actual[1], self.inbound_url,
        )

        self._thread = threading.Thread(target=self._serve_forever, daemon=True)
        self._thread.start()

    def _serve_forever(self) -> None:
        assert self._server is not None
        while not self._stop_event.is_set():
            try:
                self._server.timeout = 0.5
                self._server.handle_request()
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.warning("A2AServer handle_request raised: %s", exc)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the HTTP server and join the background thread.

        Idempotent — safe to call multiple times.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self._server is not None:
            try:
                self._server.server_close()
            except Exception as exc:
                logger.warning("A2AServer server_close raised: %s", exc)
            self._server = None
        global _server
        with _lock:
            _server = None


__all__ = ["A2AServer"]
