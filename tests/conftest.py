# mypy: ignore-errors

"""Shared test fixtures — network-free, agent-comm stubs injected.

Because the sandbox may lack ``robotsix-agent-comm``, we inject minimal
stubs into ``sys.modules`` before any test imports so that the agent
module can import them without error.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Agent-comm stubs
# ---------------------------------------------------------------------------


@dataclass
class Request:
    """Minimal agent-comm Request stub."""

    body: Any = None
    sender: str = ""
    request_id: str = "req-0"


@dataclass
class Response:
    """Minimal agent-comm Response stub."""

    result: Any = None
    error: Any = None
    request_id: str = ""


@dataclass
class Error:
    """Minimal agent-comm Error stub with ``Error.to()`` classmethod."""

    code: str = ""
    message: str = ""

    @classmethod
    def to(cls, request: Request, *, code: str = "", message: str = "") -> Response:
        return Response(error={"code": code, "message": message})


class Agent:
    """Minimal agent-comm Agent stub.

    Captures the ``on_request`` handler for direct test invocation.
    """

    def __init__(
        self,
        agent_id: str = "",
        registry: Any = None,
        on_request: Any = None,
    ) -> None:
        self.agent_id = agent_id
        self.registry = registry
        self.on_request = on_request
        self._started = False

    async def start(self) -> None:
        self._started = True
        if self.registry is not None:
            self.registry.register(self)

    async def stop(self) -> None:
        self._started = False
        if self.registry is not None:
            self.registry.agents.pop(self.agent_id, None)


class Registry:
    """Minimal agent-comm Registry stub."""

    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self.agents[agent.agent_id] = agent


# Inject stubs into sys.modules.
_AGENT_COMM_MODULE = "robotsix_agent_comm"
if _AGENT_COMM_MODULE not in sys.modules:
    _mod = types.ModuleType(_AGENT_COMM_MODULE)
    _mod.Agent = Agent
    _mod.Registry = Registry
    _mod.Request = Request
    _mod.Response = Response
    _mod.Error = Error
    sys.modules[_AGENT_COMM_MODULE] = _mod


# ---------------------------------------------------------------------------
# Shared pytest fixtures
# ---------------------------------------------------------------------------

from robotsix_board_agent.config import BoardAgentSettings  # noqa: E402


@pytest.fixture
def settings() -> BoardAgentSettings:
    """Return a default settings instance pointing at a fake board."""
    return BoardAgentSettings(
        board_api_url="http://mock-board.test",
        board_api_token="test-token",
        board_repo_id="test-repo",
        enable_write_ops=True,
    )


@pytest.fixture
def registry() -> Registry:
    """Return a fresh agent-comm Registry stub."""
    return Registry()


@pytest.fixture
def mock_transport() -> httpx.MockTransport:
    """Return an httpx MockTransport that can be customised per-test.

    Tests should reassign ``transport.handler`` to control responses.
    """
    return httpx.MockTransport(lambda _: httpx.Response(200, json={}))


@pytest.fixture
async def client(settings: BoardAgentSettings, mock_transport: httpx.MockTransport) -> Any:
    """Return a BoardClient wired to the mock transport."""
    from robotsix_board_agent.client import BoardClient

    c = BoardClient(settings, transport=mock_transport)
    yield c
    await c.close()
