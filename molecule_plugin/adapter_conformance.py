"""SDK-owned adapter CONFORMANCE SUITE (ADR-004 §4).

This module is the executable half of ADR-004's decision #4 — *"Conformance CI
ships FROM the SDK; every adapter inherits it."* It is the single, SSOT test
battery that, given any runtime adapter class, asserts the adapter satisfies the
**contract socket** ADR-004 §Decision-1 declares: identity, lifecycle, the
MCP-config seam (native path/format/key + render / read / present-probe /
enumerate), persona, and **prompt application** — that the assembled
``config.system_prompt`` actually reaches the model turn (via the executor's
payload OR the materialized native identity file). The per-adapter battery is
``AdapterConformance`` (below): each template repo inherits it against its own
``Adapter``, so an adapter that does not conform fails **its own** CI.

The aggregate "official-registry" run — a single SDK-side job that drives THIS
battery across every runtime in ``contracts/adapter/official-runtimes.registry.json``
at once (claude-code / codex / hermes / openclaw) to prove first-party support
"e2e against the officially-supported ones" — is a STAGED / descriptive stage
per ``adapter-socket.contract.md`` §8, NOT a shipped symbol: the adapters are
vendored into their own template repos, so first-party proof today is the sum of
those per-repo ``AdapterConformance`` runs, not one collected SDK-side class.
(The registry-driven filename assertion in ``AdapterConformance`` — see
``test_native_persona_file_matches_registry`` — is the SDK-side slice of that
staged aggregate that CAN run offline against a passed-in adapter.)

WHY it lives in the SDK, not the runtime engine
-----------------------------------------------
ADR-004 supersedes ADR-003 §2: the per-runtime *shape* (renderers, readers,
present-probes) moves OUT of the shared engine (``molecule_runtime.mcp_render``
``_RUNTIME_SPECS`` / ``_RUNTIME_READERS`` / ``persona_render._RUNTIME_PERSONA``)
and INTO each adapter, and the *contract + conformance* move into the SDK. So
this suite replaces the engine-side guardrails ADR-004 names — G6
(``test_mcp_render_completeness_g6``: "every runtime has a concrete
``_RUNTIME_SPECS`` entry in the engine") and ``test_mcp_render_lockstep`` — with a
per-adapter, inherited check that asks the *adapter* (never the engine's dispatch
tables) whether it renders → reads → present-probes in lockstep and fails closed
when unmapped.

HOW an adapter opts in (~5 lines in the template repo — see the bottom of this
file for the copy-paste snippet)::

    # molecule-ai-workspace-template-<runtime>/tests/test_conformance.py
    from molecule_plugin.adapter_conformance import AdapterConformance
    from adapter import Adapter

    class TestAdapterConformance(AdapterConformance):
        adapter_class = Adapter

pytest collects every ``test_*`` method the base class defines against the
template's own ``Adapter``. No live ``npx`` / gateway / control-plane is required:
the MCP-spawn is stubbed at the shared probe seam, so the suite runs offline in
any template's unit-test job.

WHAT IS NOT TESTED HERE
-----------------------
This proves the adapter honours the *socket* (structure + the render/read/present/
enumerate/persona contract with a STUBBED spawn). It deliberately does NOT boot a
real runtime, spawn a real MCP server, or reach the control plane — those are the
template's own integration/e2e jobs. A green conformance run means "this adapter
plugs into the platform correctly", not "this runtime works end-to-end".
"""

from __future__ import annotations

import inspect
import json
import pathlib

import pytest

# The suite drives the adapter through the shared runtime engine's public seams
# (AdapterConfig, the platform-agent SSOT constants, and the boot-safe MCP probe).
# molecule-ai-workspace-runtime is a TEST-time dependency of every consumer that
# runs this suite (the SDK's own CI and each template's unit job both install it),
# so a hard import here is correct; if it is somehow absent we skip loudly rather
# than silently pass.
molecule_runtime = pytest.importorskip(
    "molecule_runtime",
    reason="adapter conformance requires molecule-ai-workspace-runtime (test dep)",
)

from molecule_runtime.adapter_base import AdapterConfig, BaseAdapter  # noqa: E402
from molecule_runtime import loaded_mcp_tools_probe as _probe  # noqa: E402
from molecule_runtime.platform_agent_identity import (  # noqa: E402
    MANAGEMENT_MCP_NAME,
    MANAGEMENT_PROVISION_TOOL_ID,
    REQUIRED_TOOL,
)

# The runtime-agnostic management-MCP descriptor a concierge declares. Byte-shape
# mirrors ``platform_agent_identity.MANAGEMENT_MCP_SPEC`` but uses the plugin-
# delivery ``npx @molecule-ai/mcp-server`` command form (what an ordinary
# de-baked concierge wires), so the render→read→present round-trip below is
# exercised on the exact spec shape the plugin ships.
_MANAGEMENT_SPEC = {
    "command": "npx",
    "args": ["-y", "@molecule-ai/mcp-server"],
    "env": {"MOLECULE_MCP_MODE": "management"},
}

# The critical socket methods every adapter MUST implement/override or inherit
# (ADR-004 §Decision-1). Identity + lifecycle are @abstractmethod on BaseAdapter
# (a non-implementing subclass can't even instantiate); the MCP-seam + persona
# methods have base defaults that DISPATCH — an adapter conforms by keeping the
# dispatching default OR overriding it, but must never delete the method.
_SOCKET_METHODS = (
    # identity
    "name",
    "display_name",
    "description",
    # lifecycle
    "setup",
    "create_executor",
    # MCP-config seam
    "mcp_settings_path",
    "register_mcp_server_hook",
    "management_mcp_present",
    "enumerate_loaded_mcp_tools",
    # persona
    "materialize_persona",
)

# The OFFICIAL runtime registry (ADR-004 §2) — SSOT for each first-party
# runtime's ``native_identity_file`` (the file its persona MUST materialize
# into). Runtime keys inside ``runtimes`` are the underscore dispatch spelling;
# each entry's ``name`` is the hyphenated id ``adapter.name()`` returns, which is
# what we key the lookup on. Loaded once, lazily, so a template repo that vendors
# this suite without the contracts tree present degrades to a clean skip rather
# than an import-time error.
_REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "contracts"
    / "adapter"
    / "official-runtimes.registry.json"
)


def _native_identity_file_by_runtime() -> "dict[str, str]":
    """Map ``adapter.name()`` (hyphenated runtime id) -> the BASENAME of that
    runtime's ``native_identity_file`` from the official-runtimes registry.

    Only the OFFICIAL ``runtimes`` block is authoritative here; third-party
    adapters are not part of first-party discovery. The registry value may be a
    ``~/``-prefixed absolute-ish path
    (hermes: ``~/.hermes/SOUL.md``) or a bare filename (``system-prompt.md``,
    ``AGENTS.md``, ``SOUL.md``) — we compare on ``basename`` so both shapes bind
    to the file the runtime actually reads its identity from. Returns ``{}`` if
    the registry isn't present (a bare-vendored suite), which the caller turns
    into a clean skip.
    """
    try:
        registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for entry in (registry.get("runtimes") or {}).values():
        name = entry.get("name")
        persona = entry.get("persona") or {}
        native = persona.get("native_identity_file")
        if isinstance(name, str) and isinstance(native, str) and native.strip():
            out[name] = pathlib.PurePosixPath(native).name
    return out


# An identifier no adapter maps — used to prove fail-closed behaviour on an
# UNSUPPORTED runtime. After ADR-004 moves the per-runtime shape INTO the adapter,
# "unmapped" no longer means "a name the engine's dispatch tables don't key" — it
# means "an ADAPTER that hasn't implemented the MCP seam". So the fail-closed
# tests below drive an unmapped ADAPTER INSTANCE (``_UnmappedAdapter``) through the
# socket methods, NOT the engine's deleted-at-P4 by-name dispatch
# (``mcp_render.management_mcp_present_for`` / ``_probe.enumerate_loaded_mcp_tools_async``).
_UNMAPPED_RUNTIME = "totally-not-a-real-runtime-xyz"


class _UnmappedAdapter(BaseAdapter):
    """A throwaway adapter for an UNMAPPED/unimplemented runtime (ADR-004 §4).

    Models the fail-closed case the way ADR-004 reframes it: an adapter whose
    runtime the platform never registered and whose native MCP config therefore
    does not exist. It implements only the identity/lifecycle abstracts (so it can
    instantiate) and points ``mcp_settings_path`` at a native file that is NEVER
    written — so the INHERITED base seam (present-probe + enumerate) has no config
    to read and MUST fail closed: ``management_mcp_present`` → ``False`` (nothing
    wired), ``enumerate_loaded_mcp_tools`` → ``None`` (no servers declared).

    This asserts the ADAPTER's own fail-closed behaviour through the socket,
    P4-safe: it never calls the engine's by-name dispatch entrypoints
    (``mcp_render.management_mcp_present_for`` / ``_probe.enumerate_loaded_mcp_tools_async``)
    that P4 deletes — it drives ``adapter.management_mcp_present`` /
    ``adapter.enumerate_loaded_mcp_tools``, the same instance seams the rest of the
    suite already drives.
    """

    @staticmethod
    def name() -> str:
        return _UNMAPPED_RUNTIME

    @staticmethod
    def display_name() -> str:
        return "Unmapped Runtime (conformance fixture)"

    @staticmethod
    def description() -> str:
        return "A runtime with no implemented adapter seam — used to prove fail-closed."

    def mcp_settings_path(self, config: "AdapterConfig") -> str:
        # A native path guaranteed NEVER to exist under the test's tmp HOME, so the
        # present-probe/enumerate read an absent config and fail closed. Absolute +
        # runtime-specific (not claude's settings.json) so it never false-greens by
        # falling through to a seeded claude file (#3159).
        import os

        return os.path.join(
            config.config_path, ".unmapped-runtime", "never-written.config"
        )

    def management_mcp_present(self, config: "AdapterConfig") -> bool:
        # Fail-closed for an unimplemented seam: this adapter's native config
        # (mcp_settings_path) is never written, so nothing is wired. Read it
        # directly rather than dispatching on self.name() through the engine —
        # P4-safe (no mcp_render.management_mcp_present_for call). Absent native
        # config → the management MCP is not declared → False.
        native = _read_text(self.mcp_settings_path(config))
        return native is not None and MANAGEMENT_MCP_NAME in native

    async def enumerate_loaded_mcp_tools(
        self, config: "AdapterConfig"
    ) -> "list[str] | None":
        # No native config → no declared servers → the tri-state "never observed"
        # signal (None). Hand an EMPTY specs map to the shared, boot-safe engine
        # (enumerate_from_specs_async), which folds it to None — exercising the
        # adapter's own enumerate seam WITHOUT the deleted-at-P4 by-name dispatch
        # (_probe.enumerate_loaded_mcp_tools_async(name, config_path)).
        return await _probe.enumerate_from_specs_async({})

    async def setup(self, config: "AdapterConfig") -> None:  # pragma: no cover
        return None

    async def create_executor(self, config: "AdapterConfig"):  # pragma: no cover
        raise NotImplementedError(
            "the unmapped fixture is never booted — it only proves the MCP seam "
            "fails closed"
        )


# ---------------------------------------------------------------------------
# Spawn stub — lets the enumerate contract be exercised WITHOUT a live npx.
# ---------------------------------------------------------------------------
# Both the name-agnostic base-default enumerate (reads the generic JSON config via
# read_json_mcp_servers, then enumerate_from_specs_async) AND every official
# adapter's override (claude/codex/hermes/openclaw read their OWN native config and
# call enumerate_from_specs_async) funnel every declared server through
# ``_list_tools_from_mcp_server``. Patching THAT one
# seam is therefore adapter-shape-agnostic: it replaces the real stdio subprocess
# handshake with a deterministic in-memory tool list, so no runtime binary is
# spawned and the tri-state fold (None / [] / [ids]) is driven purely by what the
# stub returns per server.


def _install_spawn_stub(monkeypatch, *, tools_by_server):
    """Patch the shared MCP-spawn seam to return canned tool ids per server.

    ``tools_by_server``: ``{server_name: <list[str] tool names> | [] | None}``.
    The stub normalizes each bare tool name to ``mcp__<server>__<tool>`` exactly
    as the real handshake does (via ``_probe._normalize_tool_id``), returns ``[]``
    to model a connected-but-toolless server, and ``None`` to model a
    broken/unreachable server — so the caller's tri-state fold is exercised
    end-to-end with zero real I/O.
    """

    async def _fake_list_tools(server, spec):  # signature matches the real fn
        raw = tools_by_server.get(server, None)
        if raw is None:
            return None
        return [_probe._normalize_tool_id(server, name) for name in raw]

    monkeypatch.setattr(_probe, "_list_tools_from_mcp_server", _fake_list_tools)


class AdapterConformance:
    """Inheritable conformance battery for a runtime adapter (ADR-004 §4).

    A template repo opts in with a ~5-line subclass that sets ``adapter_class``
    to its ``Adapter``. pytest then collects every ``test_*`` below against that
    adapter. Override ``make_config`` only if the adapter needs bespoke config to
    reach its render/probe seam (the default is sufficient for every official
    adapter, all of which read ``config.config_path``).

    The suite is engine-agnostic across the two enumerate shapes ADR-004 allows:
    the base-default probe (claude-code / codex / openclaw) and an adapter that
    reads its own native config (hermes) — both are driven through the same
    stubbed spawn seam, so a subclass needs no per-runtime special-casing.
    """

    #: REQUIRED — set by the subclass to the adapter class under test.
    adapter_class: type[BaseAdapter] = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Fixtures / helpers a subclass may override.
    # ------------------------------------------------------------------
    @pytest.fixture
    def adapter(self):
        """The adapter INSTANCE under test. Adapters are constructed with no
        args (BaseAdapter defines no ``__init__`` params; official adapters that
        do define ``__init__`` — e.g. openclaw — take none)."""
        cls = self._require_adapter_class()
        return cls()

    def make_config(self, tmp_path) -> AdapterConfig:
        """Build the AdapterConfig used to drive the MCP-seam round-trip.

        ``config_path`` points at a temp dir so render/read/present operate on a
        throwaway native config. Runtimes whose native file resolves from ``$HOME``
        (codex / openclaw / hermes) are handled by the tests' own ``HOME``
        monkeypatch, so this single config works for every official adapter.
        Override only if an adapter needs extra fields to reach its seam.
        """
        return AdapterConfig(
            model="anthropic:claude-sonnet-4-6",
            config_path=str(tmp_path),
            workspace_id="conformance-ws",
        )

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    def _require_adapter_class(self) -> type[BaseAdapter]:
        cls = type(self).adapter_class
        if cls is None:
            raise pytest.fail.Exception(
                f"{type(self).__name__} must set `adapter_class = <YourAdapter>` "
                "to run the ADR-004 conformance suite."
            )
        return cls

    @pytest.fixture(autouse=True)
    def _home_at_tmp(self, tmp_path, monkeypatch):
        """Point $HOME at the test's tmp dir.

        codex / openclaw / hermes resolve their native MCP-config file from
        ``$HOME`` (``~/.codex/config.toml`` etc.), IGNORING ``config.config_path``.
        Anchoring HOME to tmp_path makes render/read/present operate on a
        throwaway file for THOSE runtimes too, so the same round-trip test body
        works uniformly across every official adapter without per-runtime
        branching. claude-code (which uses ``config.config_path``) is unaffected.
        """
        monkeypatch.setenv("HOME", str(tmp_path))

    # ==================================================================
    # 1. SOCKET — the adapter implements the contract.
    # ==================================================================
    def test_is_base_adapter_subclass(self):
        """The adapter MUST extend the SDK-declared socket base
        (``molecule_runtime.adapter_base.BaseAdapter``)."""
        cls = self._require_adapter_class()
        assert issubclass(cls, BaseAdapter), (
            f"{cls.__name__} must subclass BaseAdapter (the adapter socket)."
        )

    def test_implements_every_socket_method(self):
        """Every critical socket method (ADR-004 §Decision-1) is present + callable.

        Identity/lifecycle are @abstractmethod, so a non-implementing subclass is
        un-instantiable; the MCP-seam + persona methods inherit a dispatching
        default. Either way the attribute must exist and be callable."""
        cls = self._require_adapter_class()
        for meth in _SOCKET_METHODS:
            attr = getattr(cls, meth, None)
            assert attr is not None, f"{cls.__name__} is missing socket method {meth!r}"
            assert callable(attr), f"{cls.__name__}.{meth} is not callable"

    def test_is_instantiable_and_identity_is_stable(self):
        """The adapter constructs with no args and reports non-empty, stable
        identity strings; ``name()`` is the runtime id the platform dispatches on."""
        cls = self._require_adapter_class()
        inst = cls()
        name = cls.name()
        assert isinstance(name, str) and name.strip(), "name() must be a non-empty str"
        assert cls.name() == name, "name() must be stable"
        assert isinstance(cls.display_name(), str) and cls.display_name().strip()
        assert isinstance(cls.description(), str) and cls.description().strip()
        # name() is a @staticmethod on the socket — reachable off the instance too.
        assert inst.name() == name

    def test_lifecycle_methods_are_coroutines(self):
        """``setup`` and ``create_executor`` are async (the A2A boot path awaits
        them). enumerate + materialize likewise sit on async/await seams."""
        cls = self._require_adapter_class()
        assert inspect.iscoroutinefunction(cls.setup)
        assert inspect.iscoroutinefunction(cls.create_executor)
        assert inspect.iscoroutinefunction(cls.enumerate_loaded_mcp_tools)

    # ==================================================================
    # 2. MCP-CONFIG SEAM — render → read/present round-trip, byte-stable.
    # ==================================================================
    def test_native_mcp_path_is_runtime_specific(self, adapter, tmp_path):
        """The native MCP-config path the adapter resolves is a concrete, absolute
        file — and, unless this IS claude-code, is NOT claude's
        ``.claude/settings.json`` (the #3159 cross-runtime mis-attribution)."""
        cfg = self.make_config(tmp_path)
        path = str(adapter.mcp_settings_path(cfg))
        assert path, "mcp_settings_path returned empty"
        if adapter.name() != "claude-code":
            assert not path.endswith("/.claude/settings.json"), (
                f"{adapter.name()!r} resolves to claude's settings.json — an "
                "unmapped/fallthrough render target (the #3159 bug)."
            )

    @pytest.mark.asyncio
    async def test_render_present_roundtrip(self, adapter, tmp_path):
        """Drive the render → present-probe round-trip on a temp native config.

        Before wiring, the management MCP is ABSENT (fail-closed). After the
        adapter's ``register_mcp_server_hook`` renders the descriptor into ITS
        native config, ``management_mcp_present`` reports True — proving renderer
        and present-probe are in lockstep on the SAME file (ADR-004's replacement
        for the engine-side ``test_mcp_render_lockstep``)."""
        cfg = self.make_config(tmp_path)

        assert adapter.management_mcp_present(cfg) is False, (
            "management MCP must read ABSENT on a fresh config (fail-closed)."
        )

        adapter.register_mcp_server_hook(cfg, MANAGEMENT_MCP_NAME, dict(_MANAGEMENT_SPEC))

        assert adapter.management_mcp_present(cfg) is True, (
            f"after rendering {MANAGEMENT_MCP_NAME!r} into {adapter.name()!r}'s "
            "native config, the present-probe must see it (render/present lockstep)."
        )

    @pytest.mark.asyncio
    async def test_render_is_byte_stable_and_idempotent(self, adapter, tmp_path):
        """Re-rendering the SAME descriptor is byte-idempotent.

        The native config file after two identical ``register_mcp_server_hook``
        calls is byte-for-byte identical to after one — an install re-run never
        churns the file (ADR-004's "byte-stable native-config output" property,
        the golden-parity invariant the migration must preserve)."""
        cfg = self.make_config(tmp_path)
        native = adapter.mcp_settings_path(cfg)

        adapter.register_mcp_server_hook(cfg, MANAGEMENT_MCP_NAME, dict(_MANAGEMENT_SPEC))
        first = _read_bytes(native)
        assert first is not None, (
            f"{adapter.name()!r} render wrote nothing to its native path {native}"
        )

        adapter.register_mcp_server_hook(cfg, MANAGEMENT_MCP_NAME, dict(_MANAGEMENT_SPEC))
        second = _read_bytes(native)
        assert second == first, (
            f"{adapter.name()!r} render is not byte-stable — re-installing the same "
            "descriptor changed the native config (non-idempotent render)."
        )

    @pytest.mark.asyncio
    async def test_render_is_additive(self, adapter, tmp_path):
        """Rendering the management MCP does not evict a pre-existing server.

        Wire an unrelated server first, then the management MCP; both must be
        present afterwards (the renderer merges additively, never clobbers)."""
        cfg = self.make_config(tmp_path)
        other = "conformance-other-server"

        adapter.register_mcp_server_hook(cfg, other, {"command": "true"})
        adapter.register_mcp_server_hook(cfg, MANAGEMENT_MCP_NAME, dict(_MANAGEMENT_SPEC))

        assert adapter.management_mcp_present(cfg) is True
        # The present-probe only checks the management name; assert the other
        # server survived by re-reading the raw native file for its name.
        native_text = _read_text(adapter.mcp_settings_path(cfg)) or ""
        assert other in native_text, (
            f"{adapter.name()!r} render evicted the pre-existing {other!r} server "
            "(non-additive merge)."
        )

    # ==================================================================
    # 3. ENUMERATE — loaded-tool inventory + the load-bearing tri-state.
    # (spawn stubbed — NO live npx.)
    # ==================================================================
    @pytest.mark.asyncio
    async def test_enumerate_returns_list_including_required_tool(
        self, adapter, tmp_path, monkeypatch
    ):
        """With the management MCP wired and its stub advertising the required
        verb, ``enumerate_loaded_mcp_tools`` returns a LIST that includes the
        gate id ``mcp__molecule-platform__provision_workspace``.

        This is the signal the online/degraded gate reads (core#3082 / runtime#181).
        The spawn is stubbed, so no ``npx`` is required — the stub reports that the
        ``molecule-platform`` server advertised the ``provision_workspace`` tool."""
        cfg = self.make_config(tmp_path)
        adapter.register_mcp_server_hook(cfg, MANAGEMENT_MCP_NAME, dict(_MANAGEMENT_SPEC))
        _install_spawn_stub(
            monkeypatch,
            tools_by_server={MANAGEMENT_MCP_NAME: [REQUIRED_TOOL, "other_tool"]},
        )

        observed = await adapter.enumerate_loaded_mcp_tools(cfg)

        assert isinstance(observed, list), (
            "enumerate must return a list when a server connected and advertised "
            f"tools (got {observed!r})."
        )
        assert MANAGEMENT_PROVISION_TOOL_ID in observed, (
            f"enumerate must include the required gate id {MANAGEMENT_PROVISION_TOOL_ID!r}; "
            f"got {observed!r}."
        )

    @pytest.mark.asyncio
    async def test_enumerate_none_when_no_servers_declared(
        self, adapter, tmp_path, monkeypatch
    ):
        """TRI-STATE ``None``: nothing declared → nothing observed.

        With NO management MCP wired (an ordinary, non-concierge config), enumerate
        returns ``None`` — the "never observed" signal that leaves the heartbeat
        field unset so core's grace window applies. Never ``[]`` (which would falsely
        assert a connected-but-toolless server), never a guessed list."""
        cfg = self.make_config(tmp_path)
        # Stub present but empty: even if a server were spawned it advertises
        # nothing — but here none is declared, so the stub is never consulted.
        _install_spawn_stub(monkeypatch, tools_by_server={})

        observed = await adapter.enumerate_loaded_mcp_tools(cfg)

        assert observed is None, (
            "enumerate must return None (not [] or a list) when no MCP server is "
            f"declared; got {observed!r}."
        )

    @pytest.mark.asyncio
    async def test_enumerate_empty_list_when_server_connects_toolless(
        self, adapter, tmp_path, monkeypatch
    ):
        """TRI-STATE ``[]``: a server genuinely connected but advertised ZERO tools.

        Distinct from ``None`` ("never observed"): the management MCP is wired and
        the stub reports it connected with an empty tool list, so enumerate returns
        ``[]`` — a meaningful "connected-but-toolless" observation."""
        cfg = self.make_config(tmp_path)
        adapter.register_mcp_server_hook(cfg, MANAGEMENT_MCP_NAME, dict(_MANAGEMENT_SPEC))
        _install_spawn_stub(monkeypatch, tools_by_server={MANAGEMENT_MCP_NAME: []})

        observed = await adapter.enumerate_loaded_mcp_tools(cfg)

        assert observed == [], (
            "enumerate must return [] (connected-but-toolless), distinct from None, "
            f"when a declared server advertises zero tools; got {observed!r}."
        )

    @pytest.mark.asyncio
    async def test_enumerate_none_when_server_unreachable(
        self, adapter, tmp_path, monkeypatch
    ):
        """TRI-STATE ``None`` on failure: the ONLY declared server is broken/
        unreachable (stub returns None), so nothing could be observed → ``None``,
        never ``[]``. Proves the adapter degrades safely rather than false-empty."""
        cfg = self.make_config(tmp_path)
        adapter.register_mcp_server_hook(cfg, MANAGEMENT_MCP_NAME, dict(_MANAGEMENT_SPEC))
        _install_spawn_stub(monkeypatch, tools_by_server={MANAGEMENT_MCP_NAME: None})

        observed = await adapter.enumerate_loaded_mcp_tools(cfg)

        assert observed is None, (
            "enumerate must return None (not []) when the only declared server "
            f"could not be enumerated; got {observed!r}."
        )

    @pytest.mark.asyncio
    async def test_enumerate_never_raises(self, adapter, tmp_path, monkeypatch):
        """BOOT-SAFETY: enumerate maps every internal failure to the tri-state and
        NEVER raises into the boot path — even if the spawn seam itself explodes."""

        async def _boom(server, spec):
            raise RuntimeError("simulated spawn explosion")

        cfg = self.make_config(tmp_path)
        adapter.register_mcp_server_hook(cfg, MANAGEMENT_MCP_NAME, dict(_MANAGEMENT_SPEC))
        monkeypatch.setattr(_probe, "_list_tools_from_mcp_server", _boom)

        observed = await adapter.enumerate_loaded_mcp_tools(cfg)
        assert observed is None, (
            "a spawn explosion must be absorbed to None, never raised into boot; "
            f"got {observed!r}."
        )

    # ==================================================================
    # 4. FAIL-CLOSED — an unmapped/unsupported runtime never false-greens.
    # ==================================================================
    def test_unmapped_runtime_present_is_false(self, tmp_path, monkeypatch):
        """An UNMAPPED adapter must fail CLOSED at the present-probe.

        ADR-004 reframes "unmapped": after the per-runtime shape moves INTO the
        adapter, "unmapped" is not "a name the engine's dispatch tables don't key"
        — it is *an adapter whose MCP seam is unimplemented / whose native config
        was never written*. Such an adapter's present-probe MUST read ABSENT and
        report False (fail-closed) — never false-green by falling through to
        claude's ``.claude/settings.json`` (#3159).

        Drives the ADAPTER INSTANCE (``_UnmappedAdapter.management_mcp_present``),
        NOT the engine's deleted-at-P4 ``mcp_render.management_mcp_present_for``. A
        claude settings.json is seeded declaring the MCP to prove the unmapped
        adapter does NOT attribute it to itself."""
        monkeypatch.setenv("HOME", str(tmp_path))

        # Seed claude's settings.json declaring the MCP — the file the #3159 bug
        # would wrongly attribute an unmapped runtime to.
        claude_settings = tmp_path / ".claude" / "settings.json"
        claude_settings.parent.mkdir(parents=True, exist_ok=True)
        claude_settings.write_text(
            '{"mcpServers": {"%s": {"command": "npx"}}}' % MANAGEMENT_MCP_NAME
        )

        adapter = _UnmappedAdapter()
        cfg = self.make_config(tmp_path)
        present = adapter.management_mcp_present(cfg)
        assert present is False, (
            f"unmapped adapter {adapter.name()!r} must fail closed (present=False) "
            "instead of falling through to claude's settings.json (#3159)."
        )

    @pytest.mark.asyncio
    async def test_unmapped_runtime_enumerate_is_none(self, tmp_path, monkeypatch):
        """An UNMAPPED adapter enumerates to ``None`` (fail-closed), never a
        guessed list — an unimplemented seam has no native config to read, so no
        servers are declared and the tri-state "never observed" (``None``) applies.

        Drives the ADAPTER INSTANCE (``_UnmappedAdapter.enumerate_loaded_mcp_tools``),
        NOT the engine's deleted-at-P4
        ``_probe.enumerate_loaded_mcp_tools_async(name, config_path)`` by-name
        dispatch."""
        monkeypatch.setenv("HOME", str(tmp_path))
        # Seed a claude file too — an unmapped adapter must NOT attribute it.
        claude_settings = tmp_path / ".claude" / "settings.json"
        claude_settings.parent.mkdir(parents=True, exist_ok=True)
        claude_settings.write_text(
            '{"mcpServers": {"%s": {"command": "npx"}}}' % MANAGEMENT_MCP_NAME
        )

        adapter = _UnmappedAdapter()
        cfg = self.make_config(tmp_path)
        observed = await adapter.enumerate_loaded_mcp_tools(cfg)
        assert observed is None, (
            f"unmapped adapter {adapter.name()!r} must enumerate to None, not a "
            f"fallback list; got {observed!r}."
        )

    # ==================================================================
    # 5. PROMPT APPLICATION — the assembled persona reaches the model turn.
    # (no live model — assert against the payload/native-file the adapter
    #  would carry to the LLM.)
    # ==================================================================
    #
    # WHY this section exists
    # -----------------------
    # Sections 1-4 prove the *adapter* honours the socket (structure + the
    # MCP/persona seams). They do NOT prove the *executor* actually carries
    # ``config.system_prompt`` to the model. A runtime that builds the prompt
    # correctly (``_common_setup`` -> ``build_system_prompt`` publishes it onto
    # ``config.system_prompt``) but whose executor DROPS it before the model turn
    # passes 1-4 green — which is exactly the live hermes persona-drop bug and the
    # ``create_executor`` mandate at
    # ``contracts/adapter/adapter-socket.contract.md:145-146`` that §8 never
    # enforced. This section closes that gap.
    #
    # THE INVARIANT IS A PINNED CHANNEL, NOT A FREE DISJUNCTION
    # --------------------------------------------------------
    # There are two DISJOINT persona-delivery channels and each official runtime
    # uses EXACTLY ONE (adapter-socket.contract.md §2/§4: "exactly one channel
    # carries the persona per runtime"):
    #   (A) executor-consumes-config.system_prompt — hermes (system message),
    #       codex (developerInstructions), claude-code (SDK system_prompt=).
    #       The executor is BUILT FROM config and surfaces config.system_prompt
    #       into its model-turn payload.
    #   (B) native-identity-file — openclaw's executor is built with only
    #       workspace_id + heartbeat and NEVER reads config.system_prompt; the
    #       persona reaches the model via the materialized native SOUL.md
    #       (materialize_persona / §4 persona seam), which the adapter OVERRIDES
    #       to own its native file.
    #
    # A FREE disjunction ("channel A OR channel B") is a FALSE-GREEN and must NOT
    # be used. The base ``materialize_persona`` (adapter_base.py) writes the
    # canonical persona into the DEFAULT ``system-prompt.md`` from
    # ``config.prompt_files`` — and ``deliver_sentinel_persona`` below seeds
    # exactly that. So channel B is satisfiable for ANY adapter that merely
    # inherits the base materializer, INCLUDING a channel-A runtime whose executor
    # DROPS config.system_prompt (the live hermes persona-drop bug). A free
    # disjunction would let that drop pass via channel B — defeating the whole
    # point of this section. (Proven: a DropAdapter whose executor retains nothing
    # and inherits the base materializer passed green under the old free
    # disjunction; see ``test_channel_a_drop_adapter_fails`` for the regression.)
    #
    # SO WE PIN THE CHANNEL PER RUNTIME:
    #   1. Classify the runtime by whether its BUILT executor consumes
    #      config.system_prompt (``_executor_consumes_config_prompt`` — the
    #      executor exposes a config-consuming surface: a retained AdapterConfig,
    #      a ``system_prompt`` attribute, or ``_build_initial_messages``).
    #   2. A CHANNEL-A runtime (executor consumes config.system_prompt) MUST
    #      satisfy channel A — the sentinel MUST appear in the executor's
    #      model-turn payload. Channel B does NOT rescue it: an executor that
    #      consumes the prompt but drops the sentinel is the hermes-class bug and
    #      MUST fail.
    #   3. Only a NATIVE-FILE-channel runtime (channel-B: executor takes no
    #      prompt AND the adapter OVERRIDES materialize_persona to own a native
    #      identity file — openclaw-class) may satisfy via channel B. Requiring
    #      the override closes the base-materializer false-green: an adapter that
    #      merely inherits the base default is NOT a genuine channel-B runtime and
    #      cannot claim channel B.
    #
    # OFFLINE — no live model, no spawn
    # ---------------------------------
    # We never boot a runtime or call an LLM. Channel A is probed by asking the
    # adapter, via the ``prompt_application_probe`` hook below, for the persona
    # text its executor would send (default: build create_executor()'s executor
    # with the sentinel already on config, then read it back through the
    # executor's own construction — see the hook's default). Channel B is probed
    # by calling ``materialize_persona`` and reading the native file it writes.
    # Both are pure/offline.

    def deliver_sentinel_persona(self, config, tmp_path, sentinel):
        """Seed ``sentinel`` as the workspace persona on ``config`` for BOTH
        channels, the way the real boot path delivers it.

        - Channel A reads ``config.system_prompt`` (published by ``_common_setup``
          in production; set directly here to keep the test offline).
        - Channel B (``materialize_persona``) reads the CANONICAL persona from
          ``config.prompt_files`` / the ``system-prompt.md`` fallback under
          ``config.config_path`` (NOT ``config.system_prompt`` — see
          ``adapter_base.materialize_persona`` -> ``read_canonical_persona``). So
          we also drop the sentinel into a delivered ``system-prompt.md`` and
          declare it in ``prompt_files``.

        A subclass may override if its adapter delivers the persona differently.
        """
        from pathlib import Path

        config.system_prompt = sentinel
        persona_file = Path(config.config_path) / "system-prompt.md"
        persona_file.write_text(sentinel, encoding="utf-8")
        # Declare it as the canonical persona source (relative to config_path),
        # matching how a workspace ships prompt_files.
        config.prompt_files = ["system-prompt.md"]

    async def prompt_application_probe(self, adapter, config):
        """CHANNEL A probe — return the persona text the executor would carry to
        the model turn, or ``None`` if this adapter uses the native-file channel.

        Default (works offline for every executor that RETAINS the config it was
        built with — hermes/codex/claude-code): construct the executor via
        ``create_executor`` and surface whatever ``config.system_prompt`` the
        executor holds, checking the two shapes the official executors expose:

          * ``executor._config.system_prompt`` — hermes / codex store the whole
            AdapterConfig and read ``.system_prompt`` at turn-build time
            (hermes ``_build_initial_messages`` -> system message; codex
            ``params['developerInstructions']``).
          * ``executor.system_prompt`` — claude-code's ``ClaudeSDKExecutor`` copies
            it into ``self.system_prompt`` (-> SDK ``system_prompt=`` param).

        Additionally, when the executor exposes hermes' ``_build_initial_messages``
        (a clean, offline message builder), drive it and return the concatenated
        system content — the STRONGEST channel-A signal (asserts the sentinel in
        the actual outbound payload, not merely retained on the config).

        Returns the persona string if found via channel A, else ``None``. A
        ``None`` here means the executor surfaced NO config.system_prompt text —
        which is EITHER a genuine channel-B runtime (executor takes no prompt) OR
        a channel-A runtime that DROPPED the prompt; the two are told apart by
        ``_executor_consumes_config_prompt``, not by this text alone. A template
        whose executor's send-path differs (no retained config, no
        ``_build_initial_messages``) OVERRIDES this to return the text its
        executor would emit — keeping the check offline and adapter-specific.
        """
        executor = await adapter.create_executor(config)

        # STRONGEST + AUTHORITATIVE signal: a real, offline message-builder
        # (hermes). When present and it returns a message list, THAT list IS the
        # outbound model-turn payload — so its system content is authoritative and
        # we do NOT fall back to the retained config. This is load-bearing: an
        # executor that retains config.system_prompt on ``_config`` but whose
        # ``_build_initial_messages`` omits the {role:system} turn has DROPPED the
        # persona (the live hermes bug); falling back to the retained ``_config``
        # here would mask that drop and re-introduce the false-green.
        build = getattr(executor, "_build_initial_messages", None)
        if callable(build):
            try:
                messages = build("conformance-user-turn")
            except TypeError:
                messages = None
            if isinstance(messages, list):
                sys_text = "\n".join(
                    str(m.get("content", ""))
                    for m in messages
                    if isinstance(m, dict) and m.get("role") == "system"
                )
                # Authoritative: return the built system text (possibly "" — a
                # drop), NOT the retained config. Empty => persona not carried.
                return sys_text or None

        # Retained-config shapes for executors WITHOUT a message-builder
        # send-path (codex: executor._config; claude: executor.system_prompt).
        inner_cfg = getattr(executor, "_config", None)
        if inner_cfg is not None:
            sp = getattr(inner_cfg, "system_prompt", None)
            if sp:
                return sp
        sp = getattr(executor, "system_prompt", None)
        if sp:
            return sp

        return None

    async def _executor_consumes_config_prompt(self, adapter, config) -> bool:
        """CLASSIFY the runtime's persona channel by inspecting its BUILT executor.

        Returns ``True`` when the executor CONSUMES ``config.system_prompt`` — a
        CHANNEL-A runtime (hermes / codex / claude-code) that MUST carry the
        persona in its model-turn payload. Returns ``False`` when the executor
        takes NO prompt — a NATIVE-FILE (channel-B) runtime (openclaw), which
        instead carries the persona via ``materialize_persona``.

        This is the pin that turns the old free ``A OR B`` disjunction into
        "satisfy THE channel this runtime uses". It is deliberately independent of
        whether the sentinel is PRESENT — a channel-A runtime that consumes the
        prompt but DROPS the sentinel still classifies channel-A (so it is judged
        against channel A and fails), which is exactly the hermes persona-drop bug
        this section exists to catch.

        Detection is by the config-consuming SURFACE the executor exposes, the
        same three shapes ``prompt_application_probe`` reads:
          * ``_build_initial_messages`` — hermes' offline message builder that
            emits the ``{role:system}`` turn from the retained config.
          * a retained ``_config`` that carries a ``system_prompt`` attribute —
            codex (``params.developerInstructions``) / hermes.
          * a ``system_prompt`` attribute — claude-code's ``ClaudeSDKExecutor``.
        openclaw's ``OpenClawA2AExecutor`` (built from workspace_id + heartbeat
        only) exposes none of these → channel-B.

        A template whose channel-A executor uses a different send-surface (no
        retained config / no ``_build_initial_messages`` / no ``system_prompt``)
        MUST override ``prompt_application_probe`` to return its payload text — and
        because that override then returns non-None for a channel-A runtime, this
        classifier need not be overridden in the common case; override it too only
        if the executor deliberately exposes none of the surfaces above yet is
        still channel-A.
        """
        executor = await adapter.create_executor(config)
        if callable(getattr(executor, "_build_initial_messages", None)):
            return True
        inner_cfg = getattr(executor, "_config", None)
        if inner_cfg is not None and hasattr(inner_cfg, "system_prompt"):
            return True
        if hasattr(executor, "system_prompt"):
            return True
        return False

    def _overrides_materialize_persona(self, adapter) -> bool:
        """True iff the adapter OVERRIDES ``materialize_persona`` (does not merely
        inherit the ``BaseAdapter`` default).

        The base default writes the canonical persona into the DEFAULT
        ``system-prompt.md`` from ``config.prompt_files`` — which
        ``deliver_sentinel_persona`` seeds — so it satisfies the channel-B probe
        for ANY adapter, INCLUDING a channel-A runtime that dropped its prompt.
        A GENUINE channel-B (native-file) runtime owns its native identity file by
        OVERRIDING this method (openclaw → SOUL.md). Requiring the override is what
        stops the base false-green from rescuing a channel-A drop."""
        return (
            type(adapter).materialize_persona
            is not BaseAdapter.materialize_persona
        )

    @pytest.mark.asyncio
    async def test_executor_or_persona_carries_system_prompt(
        self, adapter, tmp_path
    ):
        """The assembled persona MUST reach the model turn via THE channel this
        runtime uses (socket §2 ``create_executor`` mandate + §4 persona seam).

        NOT a free ``A OR B`` disjunction — that is a false-green (the base
        ``materialize_persona`` satisfies channel B for ANY adapter, so a
        channel-A runtime that drops the prompt would pass via B). Instead we PIN
        the channel per runtime (adapter-socket.contract.md §2/§4 "exactly one
        channel carries the persona per runtime"):

          * CHANNEL-A runtime (its executor CONSUMES config.system_prompt —
            hermes/codex/claude-code): the sentinel MUST appear in the executor's
            model-turn payload. Channel B does NOT rescue it. An executor that
            consumes the prompt but drops the sentinel is the live hermes
            persona-drop bug and MUST fail here.
          * NATIVE-FILE runtime (channel-B — executor takes no prompt AND the
            adapter OVERRIDES materialize_persona to own its native identity file,
            openclaw's SOUL.md): the sentinel MUST appear in that native file.

        Offline: no model is spawned. The executor payload is read through the
        adapter's ``prompt_application_probe`` hook; the native file through
        ``materialize_persona``; the classification through
        ``_executor_consumes_config_prompt`` / ``_overrides_materialize_persona``."""
        sentinel = "CONFORMANCE-PERSONA-SENTINEL-7f3a9e21-do-not-drop"
        cfg = self.make_config(tmp_path)
        self.deliver_sentinel_persona(cfg, tmp_path, sentinel)

        # Classify WHICH channel this runtime uses (independent of the sentinel).
        consumes_config_prompt = await self._executor_consumes_config_prompt(
            adapter, cfg
        )

        if consumes_config_prompt:
            # CHANNEL-A runtime: the executor consumes config.system_prompt, so it
            # MUST surface the sentinel into its model-turn payload. Channel B is
            # NOT allowed to rescue a channel-A drop.
            via_executor = await self.prompt_application_probe(adapter, cfg)
            carried_by_executor = bool(via_executor) and sentinel in via_executor
            assert carried_by_executor, (
                f"{adapter.name()!r} is a CHANNEL-A runtime (its executor consumes "
                "config.system_prompt) but the assembled persona did NOT reach its "
                f"model-turn payload (prompt_application_probe → {via_executor!r} — "
                "sentinel absent). An executor built from config.system_prompt that "
                "drops it before the turn is the live hermes persona-drop bug "
                "(socket contract create_executor MUST, §2). The native-file "
                "channel (materialize_persona) does NOT rescue a channel-A runtime "
                "— that would be the false-green this check exists to catch."
            )
            return

        # NATIVE-FILE (channel-B) runtime: the executor takes no prompt. It is a
        # GENUINE channel-B runtime ONLY if it OVERRIDES materialize_persona to own
        # its native identity file — merely inheriting the base default (which
        # writes system-prompt.md from prompt_files) is the false-green vector and
        # does NOT make a channel-A drop legitimate.
        assert self._overrides_materialize_persona(adapter), (
            f"{adapter.name()!r}: its executor carries NO config.system_prompt "
            "(so it cannot satisfy channel A) AND it does not override "
            "materialize_persona (so it is not a genuine native-file/channel-B "
            "runtime either — it would only pass via the BASE materializer's "
            "system-prompt.md false-green). config.system_prompt has no channel to "
            "reach the model turn: either surface it in the executor payload "
            "(channel A) or override materialize_persona to write the runtime's "
            "native identity file (channel B)."
        )
        written = adapter.materialize_persona(cfg)
        native = _read_text(written) if written is not None else None
        carried_by_native_file = native is not None and sentinel in native
        assert carried_by_native_file, (
            f"{adapter.name()!r} is a NATIVE-FILE (channel-B) runtime (its executor "
            "takes no prompt) but materialize_persona did NOT write the persona "
            f"into its native identity file (→ {written!r}; sentinel absent). The "
            "native identity file is this runtime's ONLY channel to the model turn "
            "(socket §4 persona seam)."
        )

    # ==================================================================
    # 2b. TOOL-TRACE — the executor emits an agent_log tool-call row per
    #     tool invocation, so the canvas can render a ToolTraceChip
    #     (adapter-socket.contract.md §2 tool-trace MUST + §8; core#2636).
    # ==================================================================
    # WHY this exists
    # ---------------
    # The workspace canvas renders a tool-call ONLY from an ``agent_log`` activity
    # row POSTed to ``{PLATFORM_URL}/workspaces/{WORKSPACE_ID}/activity`` via the
    # shared engine primitive ``molecule_runtime.tool_trace.emit_tool_call`` — core
    # turns each row into BOTH the live MyChat progress line AND the persistent
    # ``ToolTraceChip`` it reconstructs server-side (core#2636). Before ADR-004 ONLY
    # claude-code emitted these rows (its ``_report_tool_use``); hermes/codex/openclaw
    # ran tools but emitted NOTHING renderable, so their canvas showed a bare spinner.
    # The fix makes the emit SDK-owned (one engine primitive every adapter calls at
    # its tool site); this check is the gate that stops any adapter from silently
    # skipping it.
    #
    # OFFLINE — no live model / npx / platform
    # ----------------------------------------
    # We NEVER boot a runtime, spawn a tool, or POST to a platform. We monkeypatch
    # ``tool_trace.emit_tool_call`` with an async RECORDER (mirroring the
    # ``_install_spawn_stub`` seam-patching idiom), build the executor offline, drive
    # exactly ONE tool through the executor's own tool-observation seam via the
    # overridable ``drive_one_tool`` hook, and assert the recorder captured at least
    # one emit whose ``method`` is that tool's name. An adapter that runs a tool but
    # never calls ``emit_tool_call`` records ZERO and FAILS.

    #: The tool name the default ``drive_one_tool`` drives through the executor. A
    #: template may reference it when overriding the hook.
    TOOL_TRACE_SENTINEL_TOOL = "ConformanceSentinelTool"

    async def drive_one_tool(self, adapter, executor, cfg):
        """Drive EXACTLY ONE tool through ``executor``'s own tool-observation seam
        so its ``emit_tool_call`` at the tool site fires — return the tool NAME the
        executor should have emitted (``method``), or ``None`` if this adapter's
        executor exposes no drivable offline tool seam (then the test SKIPS with a
        loud pointer to override this hook).

        The tool-dispatch seam DIFFERS per runtime and each executor lives in its
        OWN template repo, so this default cannot know every shape. It drives the
        common convention: an executor that centralizes its per-tool emit in a
        single hook method (the point where it observes a tool invocation and is
        expected to call ``emit_tool_call``). We probe, in order, the conventional
        names such a hook uses and invoke the first one found with the sentinel tool
        name, awaiting it if it is a coroutine:

          * ``_report_tool_use`` — claude-code's ClaudeSDKExecutor tool-observation
            hook (the battle-tested reference the shared primitive generalizes).
          * ``_emit_tool_call`` / ``_on_tool_start`` / ``on_tool_call`` — the
            conventional per-tool hook names an a2a-executor turn loop dispatches to
            at ``on_tool_start`` (see the runtime a2a_executor SSE tool-start block).

        Each is called as ``hook(name)`` first, then ``hook(name=name)``, so a hook
        whose signature carries extra keyword-only params (``context_id=`` etc.)
        with defaults is still driven. The hook is what MUST call
        ``emit_tool_call`` — if the adapter wired the emit there, the recorder
        captures it; if it did not, the recorder stays empty and the test fails.

        A template whose executor centralizes its emit somewhere this default does
        not reach OVERRIDES this hook to call its own tool site directly and return
        the tool name (keeping the check offline + adapter-specific), exactly like
        ``prompt_application_probe`` is overridable for the persona channel.
        Returning ``None`` means "no drivable offline tool seam here" — a template
        SHOULD override rather than leave the check skipped.
        """
        tool_name = self.TOOL_TRACE_SENTINEL_TOOL
        for hook_name in (
            "_report_tool_use",
            "_emit_tool_call",
            "_on_tool_start",
            "on_tool_call",
        ):
            hook = getattr(executor, hook_name, None)
            if not callable(hook):
                continue
            called = False
            for invoke in (
                lambda h=hook: h(tool_name),
                lambda h=hook: h(name=tool_name),
                lambda h=hook: h(tool_name=tool_name),
            ):
                try:
                    result = invoke()
                except TypeError:
                    # Signature mismatch — try the next calling convention.
                    continue
                called = True
                if inspect.isawaitable(result):
                    await result
                break
            if called:
                return tool_name
        # No conventional tool-observation hook on this executor — the template must
        # override drive_one_tool to point the check at its own tool site.
        return None

    @pytest.mark.asyncio
    async def test_executor_emits_tool_call_activity(
        self, adapter, tmp_path, monkeypatch
    ):
        """The executor MUST emit an ``agent_log`` tool-call activity row for each
        tool it invokes, via ``molecule_runtime.tool_trace.emit_tool_call`` — so the
        canvas can render a ToolTraceChip (adapter-socket.contract.md §2 tool-trace
        MUST + §8; core#2636).

        Fully OFFLINE: no model, no npx, no platform POST. We stub
        ``tool_trace.emit_tool_call`` with an async recorder, build the executor,
        drive ONE tool through it via ``drive_one_tool``, and require the recorder
        captured >= 1 emit whose ``method`` is that tool's name. An adapter that runs
        a tool but never calls ``emit_tool_call`` records ZERO and FAILS — the
        pre-ADR-004 state where only claude-code emitted.
        """
        from molecule_runtime import tool_trace

        captured: list[dict] = []

        async def _recording_emit(name, summary=None, status="ok"):
            # Mirror emit_tool_call's own signature so an adapter's call site binds
            # identically to the real primitive (positional name, keyword
            # summary/status). Record the tool name under ``method`` — the key the
            # real payload carries + the field core reconstructs the chip from.
            captured.append(
                {"method": name, "summary": summary, "status": status}
            )

        # Patch the seam the adapters IMPORT + call. Adapters reference the emitter
        # as ``molecule_runtime.tool_trace.emit_tool_call`` (a module attribute, not
        # a bound method), so patching the attribute on the module is the seam every
        # adapter's tool site resolves through — mirroring the ``_install_spawn_stub``
        # ``monkeypatch.setattr(_probe, "_list_tools_from_mcp_server", ...)`` idiom.
        monkeypatch.setattr(tool_trace, "emit_tool_call", _recording_emit)

        cfg = self.make_config(tmp_path)
        executor = await adapter.create_executor(cfg)

        driven_tool = await self.drive_one_tool(adapter, executor, cfg)
        if driven_tool is None:
            pytest.skip(
                f"{adapter.name()!r}: no drivable offline tool seam found on its "
                "executor by the default drive_one_tool (it probes the conventional "
                "per-tool hook names). This template MUST override "
                "AdapterConformance.drive_one_tool to call its executor's own tool "
                "site with a sentinel tool and return the tool name — otherwise the "
                "tool-trace MUST (adapter-socket.contract.md §2) is unverified here."
            )

        emitted_methods = [c["method"] for c in captured]
        assert driven_tool in emitted_methods, (
            f"{adapter.name()!r}: its executor ran a tool "
            f"({driven_tool!r}) but emitted NO agent_log tool-call row via "
            "molecule_runtime.tool_trace.emit_tool_call — the canvas cannot render a "
            "ToolTraceChip for it (core#2636). Every adapter that dispatches tools "
            "MUST emit_tool_call at its tool site (adapter-socket.contract.md §2 "
            "tool-trace MUST). Only claude-code did this before ADR-004; "
            f"hermes/codex/openclaw emitted nothing renderable. Captured emits: "
            f"{emitted_methods!r}."
        )

    def test_native_persona_file_matches_registry(self, adapter, tmp_path):
        """``materialize_persona`` MUST write the runtime's REGISTRY-PINNED native
        identity file — bound to ``official-runtimes.registry.json`` (C3).

        The check above proves the persona reaches the model turn, but for a
        channel-A runtime (codex / hermes / claude-code) it ``return``s WITHOUT
        ever calling ``materialize_persona`` or checking the filename — so a
        regression that materializes into the WRONG file (or stops writing at all)
        ships green. That is not academic for hermes: SOUL.md is hermes's SOLE
        persona channel on the a2a-platform transport
        (``MOLECULE_A2A_PLATFORM_ENABLED=true`` forwards to hermes-agent WITHOUT
        ``config.system_prompt``), so a ``materialize_persona`` drop there is a
        live persona-loss bug the channel-A path cannot see.

        So — DECOUPLED from the channel-A/B classification, for EVERY official
        runtime — assert the BASENAME of the file ``materialize_persona(config)``
        writes EQUALS this runtime's ``native_identity_file`` in the registry
        (``~/.hermes/SOUL.md`` → ``SOUL.md``; ``system-prompt.md``; ``AGENTS.md``).
        Parametrized over the registry via ``adapter.name()``: an adapter whose
        runtime is NOT in the official registry (a third-party adapter, or a bare
        suite vendored without the contracts tree) is skipped with a reason —
        the registry only pins FIRST-PARTY identity files."""
        native_by_runtime = _native_identity_file_by_runtime()
        if not native_by_runtime:
            pytest.skip(
                "official-runtimes.registry.json not resolvable from this suite's "
                f"location ({_REGISTRY_PATH}); cannot bind persona filename to the "
                "registry (bare-vendored suite — the template repo's own contracts "
                "tree carries the SSOT)."
            )
        runtime = adapter.name()
        expected = native_by_runtime.get(runtime)
        if expected is None:
            pytest.skip(
                f"{runtime!r} is not an OFFICIAL runtime in "
                "official-runtimes.registry.json — the registry only pins "
                "first-party native identity files, so third-party adapters have "
                "no registry-mandated persona filename to assert."
            )

        sentinel = "CONFORMANCE-PERSONA-FILENAME-SENTINEL-9c1d-do-not-drop"
        cfg = self.make_config(tmp_path)
        self.deliver_sentinel_persona(cfg, tmp_path, sentinel)

        written = adapter.materialize_persona(cfg)
        assert written is not None, (
            f"{runtime!r}: materialize_persona wrote NO file, but the registry pins "
            f"its native identity file to {expected!r}. Every official runtime MUST "
            "materialize its persona into that native file (socket §4 persona seam) "
            "— a hermes-class drop (SOUL.md is hermes's ONLY persona channel on the "
            "a2a-platform transport) is exactly this failure."
        )
        actual = pathlib.PurePath(str(written)).name
        assert actual == expected, (
            f"{runtime!r}: materialize_persona wrote {str(written)!r} (basename "
            f"{actual!r}), but official-runtimes.registry.json pins this runtime's "
            f"native_identity_file to {expected!r}. The persona MUST land in the "
            "file the runtime actually reads its identity from — a mismatch means "
            "the assembled persona never reaches the model turn on transports that "
            "rely on the native file (e.g. hermes SOUL.md on a2a-platform)."
        )
        native = _read_text(str(written))
        assert native is not None and sentinel in native, (
            f"{runtime!r}: materialize_persona wrote its registry-pinned file "
            f"{expected!r} but the assembled persona (sentinel) is NOT in it — the "
            "native identity file exists but does not carry the persona."
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _read_bytes(path):
    from pathlib import Path

    p = Path(path)
    try:
        return p.read_bytes()
    except OSError:
        return None


def _read_text(path):
    b = _read_bytes(path)
    return b.decode("utf-8", "replace") if b is not None else None
