"""Tests for :mod:`robotsix_board_agent._lifecycle` — factory function."""

from __future__ import annotations

from robotsix_board_agent._lifecycle import _build_brokered_agent


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
