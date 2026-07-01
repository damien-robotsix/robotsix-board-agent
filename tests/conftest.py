# mypy: ignore-errors

"""Shared test fixtures — network-free, agent-comm stubs injected.

Because the sandbox may lack ``robotsix-agent-comm``, we inject minimal
stubs into ``sys.modules`` before any test imports so that the agent
module can import them without error.

Stub classes live in ``tests.agent_comm_stubs`` — import them from there
instead of from this module.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

# Trigger sys.modules injection before any test code imports agent-comm.
import tests.agent_comm_stubs  # noqa: F401
from robotsix_board_agent.config import BoardAgentSettings

# Re-export Registry for the registry fixture (and backward compat).
from tests.agent_comm_stubs import Registry


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
