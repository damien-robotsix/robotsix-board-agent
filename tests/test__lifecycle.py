"""Tests for :mod:`robotsix_board_agent._lifecycle` — factory function and mixin."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from robotsix_board_agent._lifecycle import _build_brokered_agent, _ThreadedLoopMixin

# ---------------------------------------------------------------------------
# _build_brokered_agent
# ---------------------------------------------------------------------------


def _dummy_handler(request: object) -> dict[str, str]:
    return {"reply": "ok"}


class TestBuildBrokeredAgent:
    """Unit tests for :func:`_build_brokered_agent`."""

    def test_constructs_brokered_agent_with_expected_attributes(self) -> None:
        """The returned BrokeredAgent has the agent_id and timeout we passed."""
        agent = _build_brokered_agent(
            "my-agent",
            broker_host="broker.example.com",
            broker_port=8443,
            broker_scheme="https",
            broker_token="secret",
            timeout=45.0,
            on_request=_dummy_handler,
        )
        assert agent.agent_id == "my-agent"
        assert agent._agent.timeout == 45.0
        assert agent._agent.broker_host == "broker.example.com"
        assert agent._agent.broker_port == 8443
        assert agent._agent.broker_scheme == "https"
        assert agent._agent.broker_token == "secret"  # noqa: S105

    def test_on_request_handler_is_registered(self) -> None:
        """The on_request callable is bound to the agent's handler."""
        agent = _build_brokered_agent(
            "agent-2",
            broker_host="h",
            broker_port=1,
            broker_scheme="http",
            broker_token="t",
            timeout=10.0,
            on_request=_dummy_handler,
        )
        # The stub BrokeredAgent stores the handler on the inner Agent's
        # _OnRequest wrapper, accessible via agent._agent.on_request._handler.
        assert agent._agent.on_request._handler is _dummy_handler


# ---------------------------------------------------------------------------
# _ThreadedLoopMixin
# ---------------------------------------------------------------------------


class _ConcreteLoop(_ThreadedLoopMixin):
    """Minimal concrete subclass for testing the mixin."""

    def __init__(self, agent_id: str = "test-agent") -> None:
        self.agent_id = agent_id
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: Any = None
        self._agent = _FakeAgent()
        self.client = _FakeClient()

    # Expose for assertions.
    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    @property
    def loop_thread(self) -> Any:
        return self._loop_thread


class _FakeAgent:
    """Tracks start/stop calls."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class _FakeClient:
    """Tracks close calls; can be told to raise."""

    def __init__(self) -> None:
        self.closed = False
        self._raise_on_close: Exception | None = None

    async def close(self) -> None:
        self.closed = True
        if self._raise_on_close is not None:
            raise self._raise_on_close


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    def test_creates_loop_and_thread(self) -> None:
        obj = _ConcreteLoop()
        obj.start()

        assert obj.loop is not None
        assert obj.loop.is_running()
        assert obj.loop_thread is not None
        assert obj.loop_thread.is_alive()
        assert obj._agent.started

    def test_idempotent_second_call(self) -> None:
        obj = _ConcreteLoop()
        obj.start()
        loop = obj.loop
        thread = obj.loop_thread

        obj._agent.started = False
        obj.start()  # second call — should be no-op

        assert obj.loop is loop  # same loop object
        assert obj.loop_thread is thread  # same thread
        assert not obj._agent.started  # not called again


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    def test_safe_to_call_before_start(self) -> None:
        obj = _ConcreteLoop()
        obj.stop()  # should not raise
        assert obj._agent.stopped

    def test_cleans_up_after_start(self) -> None:
        obj = _ConcreteLoop()
        obj.start()
        loop = obj.loop
        thread = obj.loop_thread

        obj.stop()

        assert obj._agent.stopped
        assert obj.loop is None
        assert obj.loop_thread is None
        assert obj.client.closed
        assert loop is not None
        assert loop.is_closed()
        thread.join(timeout=0.5)  # should already be done

    def test_handles_close_failure_gracefully(self, caplog: pytest.LogCaptureFixture) -> None:
        obj = _ConcreteLoop()
        obj.client._raise_on_close = RuntimeError("boom")
        obj.start()
        loop = obj.loop
        thread = obj.loop_thread

        parent = logging.getLogger("robotsix_board_agent")
        parent.propagate = True
        try:
            with caplog.at_level(logging.WARNING):
                obj.stop()
        finally:
            parent.propagate = False

        assert obj._agent.stopped
        assert obj.loop is None
        assert obj.loop_thread is None
        assert "board client close failed during stop" in caplog.text
        # Loop and thread should still be cleaned up despite close failure.
        assert loop is not None
        assert loop.is_closed()
        thread.join(timeout=0.5)


# ---------------------------------------------------------------------------
# _run()
# ---------------------------------------------------------------------------


class TestRun:
    def test_schedules_and_completes_coroutine(self) -> None:
        obj = _ConcreteLoop()
        obj.start()

        async def add(a: int, b: int) -> int:
            return a + b

        result = obj._run(add(1, 2))
        assert result == 3

    def test_raises_assertion_error_when_not_started(self) -> None:
        obj = _ConcreteLoop()
        with pytest.raises(AssertionError):
            obj._run(asyncio.sleep(0))
