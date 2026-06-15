# mypy: ignore-errors
"""Tests for BoardClient — one test per REST method, all network-free."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from robotsix_board_agent.client import BoardAPIError, BoardClient
from robotsix_board_agent.config import BoardAgentSettings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def json_response(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


async def test_auth_header_sent():
    """Every request sends ``Authorization: Bearer <token>``."""
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_headers
        captured_headers = dict(request.headers)
        return json_response({"ok": True})

    transport = httpx.MockTransport(handler)
    settings = BoardAgentSettings(
        board_api_url="http://x",
        board_api_token="secret-123",
        board_repo_id="r",
    )
    client = BoardClient(settings, transport=transport)
    await client.get_ticket("t1")
    assert captured_headers.get("authorization") == "Bearer secret-123"
    await client.close()


# ---------------------------------------------------------------------------
# list_tickets
# ---------------------------------------------------------------------------


async def test_list_tickets_no_filters(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert str(req.url).endswith("/tickets") or "/tickets?" not in str(req.url)
        return json_response([{"id": "t1"}])

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.list_tickets()
    assert result == [{"id": "t1"}]


async def test_list_tickets_with_filters(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert "state=open" in str(req.url)
        assert "repo_id=myrepo" in str(req.url)
        return json_response([])

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.list_tickets(state="open", repo_id="myrepo")
    assert result == []


# ---------------------------------------------------------------------------
# get_ticket
# ---------------------------------------------------------------------------


async def test_get_ticket(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert "/tickets/T-42" in str(req.url)
        return json_response({"id": "T-42", "title": "Test"})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.get_ticket("T-42")
    assert result["id"] == "T-42"


# ---------------------------------------------------------------------------
# board_cards
# ---------------------------------------------------------------------------


async def test_board_cards(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert "/board/cards" in str(req.url)
        return json_response([{"id": "card1"}])

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.board_cards()
    assert result == [{"id": "card1"}]


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


async def test_history(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert "/tickets/T-1/history" in str(req.url)
        return json_response([{"event": "created"}])

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.history("T-1")
    assert result == [{"event": "created"}]


# ---------------------------------------------------------------------------
# merge_status
# ---------------------------------------------------------------------------


async def test_merge_status(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert "/tickets/T-1/merge-status" in str(req.url)
        return json_response({"mergeable": True})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.merge_status("T-1")
    assert result == {"mergeable": True}


# ---------------------------------------------------------------------------
# description
# ---------------------------------------------------------------------------


async def test_description(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert "/tickets/T-1/description" in str(req.url)
        return json_response({"body": "desc"})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.description("T-1")
    assert result == {"body": "desc"}


# ---------------------------------------------------------------------------
# create_ticket (write)
# ---------------------------------------------------------------------------


async def test_create_ticket(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets" in str(req.url) and "/tickets/" not in str(req.url).replace(
            "//tickets", "/tickets"
        )
        return json_response({"id": "new-1", "title": "Hello"}, status=201)

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.create_ticket(title="Hello", description="World")
    assert result["id"] == "new-1"


# ---------------------------------------------------------------------------
# add_comment (write)
# ---------------------------------------------------------------------------


async def test_add_comment(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets/T-1/comments" in str(req.url)
        return json_response({"id": "c1"}, status=201)

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.add_comment("T-1", "Nice!")
    assert result["id"] == "c1"


# ---------------------------------------------------------------------------
# transition (write)
# ---------------------------------------------------------------------------


async def test_transition(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets/T-1/transition" in str(req.url)
        return json_response({"state": "approved"})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.transition("T-1", "approved")
    assert result["state"] == "approved"


# ---------------------------------------------------------------------------
# approve (write)
# ---------------------------------------------------------------------------


async def test_approve(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets/T-1/approve" in str(req.url)
        return json_response({"approved": True})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.approve("T-1")
    assert result["approved"] is True


# ---------------------------------------------------------------------------
# mark_done (write)
# ---------------------------------------------------------------------------


async def test_mark_done(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets/T-1/mark-done" in str(req.url)
        return json_response({"state": "done"})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.mark_done("T-1")
    assert result["state"] == "done"


# ---------------------------------------------------------------------------
# merge_now (write)
# ---------------------------------------------------------------------------


async def test_merge_now(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets/T-1/merge-now" in str(req.url)
        return json_response({"merged": True})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.merge_now("T-1")
    assert result["merged"] is True


# ---------------------------------------------------------------------------
# resume_blocked (write)
# ---------------------------------------------------------------------------


async def test_resume_blocked(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets/T-1/resume-blocked" in str(req.url)
        return json_response({"state": "open"})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.resume_blocked("T-1")
    assert result["state"] == "open"


# ---------------------------------------------------------------------------
# migrate (write)
# ---------------------------------------------------------------------------


async def test_migrate(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets/T-1/migrate" in str(req.url)
        return json_response({"target": "other-repo"})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.migrate("T-1", "other-repo")
    assert result["target"] == "other-repo"


# ---------------------------------------------------------------------------
# set_priority (write)
# ---------------------------------------------------------------------------


async def test_set_priority(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert "/tickets/T-1/priority" in str(req.url)
        return json_response({"priority": True})

    mock_transport.handler = handler  # type: ignore[attr-defined]
    result = await client.set_priority("T-1", True)
    assert result["priority"] is True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_board_api_error_4xx(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        return json_response({"detail": "Not found"}, status=404)

    mock_transport.handler = handler  # type: ignore[attr-defined]
    with pytest.raises(BoardAPIError) as exc:
        await client.get_ticket("nonexistent")
    assert exc.value.status_code == 404
    assert "Not found" in str(exc.value)


async def test_board_api_error_5xx(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        return json_response({"detail": "Boom"}, status=500)

    mock_transport.handler = handler  # type: ignore[attr-defined]
    with pytest.raises(BoardAPIError) as exc:
        await client.list_tickets()
    assert exc.value.status_code == 500


async def test_board_api_error_no_detail(client: BoardClient, mock_transport: httpx.MockTransport):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    mock_transport.handler = handler  # type: ignore[attr-defined]
    with pytest.raises(BoardAPIError) as exc:
        await client.list_tickets()
    assert exc.value.status_code == 500
