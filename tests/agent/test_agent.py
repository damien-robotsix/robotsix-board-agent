# mypy: ignore-errors
"""Tests for BoardAgent — handler round-trip, write gate, error paths.

All network-free — uses agent-comm stubs from conftest.py.
"""

from __future__ import annotations

import httpx
import pytest

# Import stubs from conftest (injected into sys.modules).
from robotsix_agent_comm import Registry, Request

from robotsix_board_agent.agent import BoardAgent
from robotsix_board_agent.config import BoardAgentSettings
from robotsix_board_agent.ops import WRITE_OPS

# ---------------------------------------------------------------------------
# Fixtures (settings and registry are provided by tests/conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def transport_handler():
    """Returns a mutable dict so tests can set ``handler["fn"]``."""
    return {"fn": lambda req: httpx.Response(200, json={})}


@pytest.fixture
def agent(settings: BoardAgentSettings, registry: Registry, transport_handler) -> BoardAgent:
    """Return a BoardAgent whose internal client uses a mock transport."""
    agent = BoardAgent(settings, registry)

    # Replace the internal client with one that uses a mock transport.
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return transport_handler["fn"](request)

    agent.client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler),
        base_url=settings.board_api_url,
    )
    return agent


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_agent_registers_with_registry(agent: BoardAgent, registry: Registry):
    await agent.start()
    assert agent.agent_id in registry.agents
    assert registry.agents[agent.agent_id].agent_id == agent.agent_id
    assert registry.agents[agent.agent_id].on_request is not None
    await agent.stop()


# ---------------------------------------------------------------------------
# Read op dispatch
# ---------------------------------------------------------------------------


async def test_read_op_returns_response(
    agent: BoardAgent, registry: Registry, transport_handler: dict
):
    transport_handler["fn"] = lambda req: httpx.Response(200, json={"id": "T-1", "title": "Hello"})
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body={"op": "get_ticket", "args": {"ticket_id": "T-1"}})
    resp = await handler(req)

    assert resp.result == {"id": "T-1", "title": "Hello"}
    assert resp.error is None
    await agent.stop()


# ---------------------------------------------------------------------------
# Write op succeeds when enabled
# ---------------------------------------------------------------------------


async def test_write_op_succeeds_when_enabled(
    agent: BoardAgent, registry: Registry, transport_handler: dict
):
    transport_handler["fn"] = lambda req: httpx.Response(201, json={"id": "new-1", "title": "Test"})
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body={"op": "create_ticket", "args": {"title": "Test", "description": "Desc"}})
    resp = await handler(req)

    assert resp.result == {"id": "new-1", "title": "Test"}
    assert resp.error is None
    await agent.stop()


# ---------------------------------------------------------------------------
# Write gate: enable_write_ops=False rejects write ops
# ---------------------------------------------------------------------------


async def test_write_op_rejected_when_disabled(registry: Registry, transport_handler: dict):
    settings = BoardAgentSettings(
        board_api_url="http://mock-board.test",
        board_api_token="t",
        board_repo_id="r",
        enable_write_ops=False,
    )
    agent = BoardAgent(settings, registry)
    agent.client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        base_url=settings.board_api_url,
    )
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body={"op": "create_ticket", "args": {"title": "T", "description": "D"}})
    resp = await handler(req)

    assert resp.result is None
    assert resp.error is not None
    assert resp.error["code"] == "WRITE_OPS_DISABLED"
    assert "enable_write_ops" in resp.error["message"]
    await agent.stop()


async def test_read_op_still_works_when_writes_disabled(
    registry: Registry, transport_handler: dict
):
    settings = BoardAgentSettings(
        board_api_url="http://mock-board.test",
        board_api_token="t",
        board_repo_id="r",
        enable_write_ops=False,
    )
    agent = BoardAgent(settings, registry)
    transport_handler["fn"] = lambda req: httpx.Response(200, json={"id": "T-1", "title": "Test"})
    agent.client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(transport_handler["fn"]),
        base_url=settings.board_api_url,
    )
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body={"op": "get_ticket", "args": {"ticket_id": "T-1"}})
    resp = await handler(req)

    assert resp.result == {"id": "T-1", "title": "Test"}
    assert resp.error is None
    await agent.stop()


# ---------------------------------------------------------------------------
# Unknown op
# ---------------------------------------------------------------------------


async def test_unknown_op_returns_error(agent: BoardAgent, registry: Registry):
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body={"op": "nonexistent", "args": {}})
    resp = await handler(req)

    assert resp.result is None
    assert resp.error is not None
    assert resp.error["code"] == "UNKNOWN_OP"
    assert "nonexistent" in resp.error["message"]
    await agent.stop()


# ---------------------------------------------------------------------------
# Board API error
# ---------------------------------------------------------------------------


async def test_board_api_error_returns_error(
    agent: BoardAgent, registry: Registry, transport_handler: dict
):
    transport_handler["fn"] = lambda req: httpx.Response(500, json={"detail": "Internal explosion"})
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body={"op": "list_tickets", "args": {}})
    resp = await handler(req)

    assert resp.result is None
    assert resp.error is not None
    assert resp.error["code"] == "BOARD_API_ERROR"
    assert "Internal explosion" in resp.error["message"]
    assert "500" in resp.error["message"]
    await agent.stop()


# ---------------------------------------------------------------------------
# Bad request body
# ---------------------------------------------------------------------------


async def test_non_dict_body_returns_error(agent: BoardAgent, registry: Registry):
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body="not a dict")
    resp = await handler(req)

    assert resp.error is not None
    assert resp.error["code"] == "BAD_REQUEST"
    await agent.stop()


async def test_invalid_json_body_returns_error(agent: BoardAgent, registry: Registry):
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body="not json")
    resp = await handler(req)

    assert resp.error is not None
    assert resp.error["code"] == "BAD_REQUEST"
    await agent.stop()


async def test_missing_op_field_returns_error(agent: BoardAgent, registry: Registry):
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    req = Request(body={"args": {}})
    resp = await handler(req)

    assert resp.error is not None
    assert resp.error["code"] == "BAD_REQUEST"
    await agent.stop()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


async def test_agent_id_defaults_to_board_repo_id(settings: BoardAgentSettings, registry: Registry):
    agent = BoardAgent(settings, registry)
    assert agent.agent_id == "board-test-repo"


async def test_agent_id_custom(settings: BoardAgentSettings, registry: Registry):
    agent = BoardAgent(settings, registry, agent_id="my-agent")
    assert agent.agent_id == "my-agent"


async def test_start_stop_lifecycle(agent: BoardAgent):
    await agent.start()
    assert agent._agent._started is True
    await agent.stop()
    assert agent._agent._started is False


# ---------------------------------------------------------------------------
# All write ops are rejected when writes disabled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op_name", sorted(WRITE_OPS))
async def test_every_write_op_rejected_when_disabled(
    op_name: str, registry: Registry, transport_handler: dict
):
    settings = BoardAgentSettings(
        board_api_url="http://mock-board.test",
        board_api_token="t",
        board_repo_id="r",
        enable_write_ops=False,
    )
    agent = BoardAgent(settings, registry)
    agent.client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        base_url=settings.board_api_url,
    )
    await agent.start()
    handler = registry.agents[agent.agent_id].on_request

    # Build minimal valid args per op so we hit the write gate, not arg validation.
    args: dict[str, str] = {}
    if "ticket_id" in op_name or op_name not in ("create_ticket", "board_cards"):
        args["ticket_id"] = "T-1"
    if op_name == "create_ticket":
        args = {"title": "T", "description": "D"}
    if op_name == "transition":
        args["state"] = "open"
    if op_name == "migrate":
        args["target_repo_id"] = "other"
    if op_name == "set_priority":
        args["priority"] = True  # type: ignore[assignment]
    if op_name == "comment":
        args["body"] = "hi"

    req = Request(body={"op": op_name, "args": args})
    resp = await handler(req)

    assert resp.error is not None, f"Expected error for write op {op_name}"
    assert resp.error["code"] == "WRITE_OPS_DISABLED", (
        f"Wrong error code for {op_name}: {resp.error}"
    )
    await agent.stop()
