"""Regression coverage for the SDK adapter-conformance PROMPT-APPLICATION check
(``AdapterConformance.test_executor_or_persona_carries_system_prompt``).

Context (review SHIP-WITH-NITS #1): the check USED TO be a free ``channel-A OR
channel-B`` disjunction, which is a FALSE-GREEN. The base
``BaseAdapter.materialize_persona`` writes the canonical persona into the DEFAULT
``system-prompt.md`` from ``config.prompt_files`` — and the suite's
``deliver_sentinel_persona`` seeds exactly that — so channel B is satisfiable for
ANY adapter, INCLUDING a channel-A runtime (hermes/codex/claude-code) whose
executor DROPS ``config.system_prompt`` before the model turn (the live hermes
persona-drop bug). The reviewer proved a ``DropAdapter`` that retains nothing +
inherits the base materializer passed GREEN when it should FAIL.

The fix PINS the channel per runtime: a channel-A runtime (executor consumes
``config.system_prompt``) MUST satisfy channel A; only a genuine native-file
runtime (executor takes no prompt AND the adapter OVERRIDES materialize_persona)
may satisfy via channel B.

These tests exercise that pinned check against synthetic adapters — no real
runtime, no live model, no spawn. They are the SDK-side regression that the
template repos' real-adapter conformance runs (claude-code/codex/hermes/openclaw)
cannot express (those only prove the POSITIVE case for their own runtime).
"""

import pytest

molecule_runtime = pytest.importorskip(
    "molecule_runtime",
    reason="adapter conformance requires molecule-ai-workspace-runtime (test dep)",
)

from molecule_runtime.adapter_base import AdapterConfig, BaseAdapter

from molecule_plugin.adapter_conformance import AdapterConformance


# ---------------------------------------------------------------------------
# Synthetic adapters modelling each persona channel + the drop bug.
# ---------------------------------------------------------------------------
class _RetainedConfigDropExecutor:
    """CHANNEL-A executor: it CONSUMES config (retains it + exposes a
    ``_build_initial_messages`` send-path) but its model-turn payload DROPS
    ``config.system_prompt`` — the faithful shape of the live hermes bug."""

    def __init__(self, config):
        self._config = config

    def _build_initial_messages(self, user_turn):
        # The persona-drop: outbound messages omit the {role:system} persona turn.
        return [{"role": "user", "content": user_turn}]


class _RetainsNothingExecutor:
    """An executor that exposes NO config-consuming surface at all (the exact
    'retains nothing' shape the reviewer used to prove the false-green)."""


class _ChannelBExecutor:
    """A native-file (channel-B) executor: built from workspace_id + heartbeat
    only, exposes no config-consuming surface (openclaw's OpenClawA2AExecutor)."""

    def __init__(self, workspace_id="", heartbeat=None):
        self.workspace_id = workspace_id
        self.heartbeat = heartbeat


def _base_adapter_boilerplate(cls_name, runtime_name):
    """Shared identity/lifecycle boilerplate so each fixture only differs in the
    executor + materialize_persona behaviour under test."""

    class _Base(BaseAdapter):
        @staticmethod
        def name() -> str:
            return runtime_name

        @staticmethod
        def display_name() -> str:
            return cls_name

        @staticmethod
        def description() -> str:
            return f"conformance fixture: {cls_name}"

        def mcp_settings_path(self, config: AdapterConfig) -> str:
            import os

            return os.path.join(config.config_path, ".fixture", "never-written.config")

        async def setup(self, config: AdapterConfig) -> None:  # pragma: no cover
            return None

    return _Base


class _ChannelADropAdapter(
    _base_adapter_boilerplate("Channel-A persona-drop", "drop-runtime-channel-a")
):
    """A CHANNEL-A runtime whose executor consumes config but DROPS the persona,
    and which inherits the base materialize_persona (the false-green vector)."""

    async def create_executor(self, config: AdapterConfig):
        return _RetainedConfigDropExecutor(config)

    # Inherits BaseAdapter.materialize_persona — the base false-green path.


class _RetainsNothingDropAdapter(
    _base_adapter_boilerplate("retains-nothing drop", "drop-runtime-bare")
):
    """The reviewer's exact repro: executor retains nothing + inherits base
    materialize_persona. Classifies channel-B by executor shape, but is NOT a
    genuine native-file runtime (no override), so channel B must not rescue it."""

    async def create_executor(self, config: AdapterConfig):
        return _RetainsNothingExecutor()

    # Inherits BaseAdapter.materialize_persona.


class _ChannelBNativeFileAdapter(
    _base_adapter_boilerplate("native-file channel-B", "native-file-runtime")
):
    """A GENUINE channel-B runtime (openclaw-class): executor takes no prompt AND
    the adapter OVERRIDES materialize_persona to write its OWN native identity
    file. This MUST pass — proving the fix does not over-reject the legit case."""

    async def create_executor(self, config: AdapterConfig):
        return _ChannelBExecutor(
            workspace_id=getattr(config, "workspace_id", "") or "",
            heartbeat=getattr(config, "heartbeat", None),
        )

    def materialize_persona(self, config: AdapterConfig):
        # Own native identity file (analogue of openclaw's SOUL.md). Reads the
        # canonical persona the same way the base does, then writes it to a
        # runtime-specific native file (NOT the default system-prompt.md).
        from pathlib import Path

        from molecule_runtime import persona_render

        persona = persona_render.read_canonical_persona(
            config.config_path, config.prompt_files
        )
        if not (persona or "").strip():
            return None
        target = Path(config.config_path) / "NATIVE_SOUL.md"
        target.write_text(persona, encoding="utf-8")
        return str(target)


def _suite() -> AdapterConformance:
    """A bare AdapterConformance instance to drive the prompt-application check
    directly against a fixture adapter (bypassing pytest collection of the base
    class, which requires ``adapter_class``)."""
    return AdapterConformance()


@pytest.mark.asyncio
async def test_channel_a_drop_adapter_fails(tmp_path):
    """A channel-A runtime that consumes config but DROPS the persona MUST fail —
    channel B must NOT rescue it (the core regression)."""
    with pytest.raises(AssertionError) as excinfo:
        await _suite().test_executor_or_persona_carries_system_prompt(
            _ChannelADropAdapter(), tmp_path
        )
    msg = str(excinfo.value)
    assert "persona-drop" in msg or "CHANNEL-A" in msg, (
        f"drop adapter must fail the pinned channel-A assertion; got: {msg!r}"
    )


@pytest.mark.asyncio
async def test_retains_nothing_drop_adapter_fails(tmp_path):
    """The reviewer's exact repro (executor retains nothing + inherits base
    materialize_persona) MUST fail — the base materializer's system-prompt.md
    false-green must not rescue a runtime with no genuine channel."""
    with pytest.raises(AssertionError) as excinfo:
        await _suite().test_executor_or_persona_carries_system_prompt(
            _RetainsNothingDropAdapter(), tmp_path
        )
    msg = str(excinfo.value)
    assert "does not override" in msg or "no channel" in msg.lower(), (
        f"retains-nothing adapter must fail as a non-genuine channel-B runtime; "
        f"got: {msg!r}"
    )


@pytest.mark.asyncio
async def test_genuine_channel_b_native_file_adapter_passes(tmp_path):
    """A GENUINE native-file (channel-B) runtime — executor takes no prompt AND
    the adapter overrides materialize_persona — MUST pass. Proves the fix pins the
    channel without over-rejecting the legitimate openclaw-class case."""
    # Must not raise.
    await _suite().test_executor_or_persona_carries_system_prompt(
        _ChannelBNativeFileAdapter(), tmp_path
    )
