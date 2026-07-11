"""Regression coverage for the SDK adapter-conformance TOOL-TRACE check
(``AdapterConformance.test_executor_emits_tool_call_activity``).

Context (ADR-004 — shared tool-call emit): the workspace canvas renders a
tool-call ONLY from an ``agent_log`` activity row POSTed via the shared engine
primitive ``molecule_runtime.tool_trace.emit_tool_call``. core turns each row
into BOTH the live MyChat progress line AND the persistent ``ToolTraceChip`` it
reconstructs server-side (core#2636). Before ADR-004 ONLY the claude-code
template emitted these rows; hermes/codex/openclaw ran tools but emitted nothing
renderable. The fix makes the emit SDK-owned, and this conformance check gates
every adapter so none can silently skip it.

These tests exercise that gate against SYNTHETIC executors — no real runtime, no
live model, no spawn, no platform POST. They are the SDK-side proof the check is
well-formed: an EMITTING executor passes, a NON-emitting one FAILS, and an
executor with no drivable offline tool seam SKIPS with a pointer to override
``drive_one_tool``. The template repos' real-adapter conformance runs
(claude-code/codex/hermes/openclaw) can only express the POSITIVE case for their
own runtime; this file proves the negative + skip legs.
"""

import pytest

molecule_runtime = pytest.importorskip(
    "molecule_runtime",
    reason="adapter conformance requires molecule-ai-workspace-runtime (test dep)",
)

from molecule_runtime.adapter_base import AdapterConfig, BaseAdapter

from molecule_plugin.adapter_conformance import AdapterConformance


# ---------------------------------------------------------------------------
# Synthetic executors modelling the emit / no-emit / no-seam cases.
# ---------------------------------------------------------------------------
class _EmittingExecutor:
    """An executor that DOES emit at its tool site: its per-tool hook calls the
    shared ``molecule_runtime.tool_trace.emit_tool_call`` — the correct
    post-ADR-004 shape every adapter must have.

    ``_report_tool_use`` is the conventional tool-observation hook name (the
    claude-code reference the shared primitive generalizes); the default
    ``drive_one_tool`` finds + drives it. It imports the emitter through the
    module so the test's monkeypatch of ``tool_trace.emit_tool_call`` is the
    seam it resolves through (exactly how a real adapter's tool site binds)."""

    def __init__(self, config):
        self._config = config

    async def _report_tool_use(self, name):
        from molecule_runtime import tool_trace

        await tool_trace.emit_tool_call(name=name, summary=None, status="ok")


class _NonEmittingExecutor:
    """An executor that runs a tool but emits NOTHING renderable — the
    pre-ADR-004 hermes/codex/openclaw shape. It exposes the same conventional
    tool-observation hook (so the default ``drive_one_tool`` drives it) but the
    hook does real per-tool work WITHOUT calling ``emit_tool_call``. This MUST
    fail the gate."""

    def __init__(self, config):
        self._config = config

    async def _report_tool_use(self, name):
        # Observes the tool (e.g. would append to a local trace list / log) but
        # never emits the agent_log activity row → canvas can't render a chip.
        _ = str(name)


class _NoToolSeamExecutor:
    """An executor exposing NONE of the conventional tool-observation hooks the
    default ``drive_one_tool`` probes — the default cannot drive a tool, so the
    check SKIPS with a loud pointer to override ``drive_one_tool``. Models a
    template whose tool site is shaped differently and hasn't overridden the
    hook yet."""

    def __init__(self, config):
        self._config = config


def _base_adapter_boilerplate(cls_name, runtime_name):
    """Shared identity/lifecycle boilerplate so each fixture only differs in the
    executor it builds (mirrors the persona-regression file's helper)."""

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


class _EmittingAdapter(
    _base_adapter_boilerplate("emits tool-call", "emit-runtime")
):
    async def create_executor(self, config: AdapterConfig):
        return _EmittingExecutor(config)


class _NonEmittingAdapter(
    _base_adapter_boilerplate("no tool-call emit", "no-emit-runtime")
):
    async def create_executor(self, config: AdapterConfig):
        return _NonEmittingExecutor(config)


class _NoToolSeamAdapter(
    _base_adapter_boilerplate("no drivable tool seam", "no-seam-runtime")
):
    async def create_executor(self, config: AdapterConfig):
        return _NoToolSeamExecutor(config)


def _suite() -> AdapterConformance:
    """A bare AdapterConformance instance to drive the tool-trace check directly
    against a fixture adapter (bypassing pytest collection of the base class,
    which requires ``adapter_class``). ``make_config`` + ``drive_one_tool`` are
    the base defaults."""
    return AdapterConformance()


@pytest.fixture
def _no_op_monkeypatch(monkeypatch):
    """The check takes a ``monkeypatch`` arg — pass the real fixture through so
    the setattr is auto-undone after each test."""
    return monkeypatch


@pytest.mark.asyncio
async def test_emitting_executor_passes(tmp_path, _no_op_monkeypatch):
    """An executor whose tool site calls the shared ``emit_tool_call`` MUST pass —
    the correct post-ADR-004 shape."""
    # Must not raise / skip.
    await _suite().test_executor_emits_tool_call_activity(
        _EmittingAdapter(), tmp_path, _no_op_monkeypatch
    )


@pytest.mark.asyncio
async def test_non_emitting_executor_fails(tmp_path, _no_op_monkeypatch):
    """An executor that runs a tool but never emits an agent_log tool-call row
    MUST fail — the pre-ADR-004 hermes/codex/openclaw state the gate exists to
    catch."""
    with pytest.raises(AssertionError) as excinfo:
        await _suite().test_executor_emits_tool_call_activity(
            _NonEmittingAdapter(), tmp_path, _no_op_monkeypatch
        )
    msg = str(excinfo.value)
    assert "emit_tool_call" in msg and "ToolTraceChip" in msg, (
        f"non-emitting adapter must fail citing the missing emit; got: {msg!r}"
    )


@pytest.mark.asyncio
async def test_no_tool_seam_executor_skips(tmp_path, _no_op_monkeypatch):
    """An executor exposing no conventional tool-observation hook makes the
    default ``drive_one_tool`` return None → the check SKIPS with a pointer to
    override the hook (rather than silently pass or spuriously fail)."""
    with pytest.raises(pytest.skip.Exception) as excinfo:
        await _suite().test_executor_emits_tool_call_activity(
            _NoToolSeamAdapter(), tmp_path, _no_op_monkeypatch
        )
    assert "drive_one_tool" in str(excinfo.value), (
        f"no-seam adapter must skip with a pointer to override drive_one_tool; "
        f"got: {excinfo.value!r}"
    )
