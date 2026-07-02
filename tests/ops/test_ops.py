# mypy: ignore-errors
"""Tests for the op dispatch table — one test per op, all network-free."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pydantic
import pytest

from robotsix_board_agent.client import BoardClient
from robotsix_board_agent.ops import (
    OP_TABLE,
    WRITE_OPS,
    BoardOp,
    UnknownOpError,
    dispatch,
)


def _client_with_mock(method_name: str, return_value: Any = None) -> tuple[BoardClient, AsyncMock]:
    """Create a BoardClient with a mocked method returning *return_value*."""
    if return_value is None:
        return_value = {}
    client = BoardClient.__new__(BoardClient)
    mock = AsyncMock(return_value=return_value)
    setattr(client, method_name, mock)
    return client, mock


# ---------------------------------------------------------------------------
# All read ops route correctly
# ---------------------------------------------------------------------------

READ_OP_TESTS = [
    (
        "list_tickets",
        "list_tickets",
        {"state": "open"},
        [{"id": "t1"}],
        {"tickets": [{"id": "t1"}]},
    ),
    (
        "get_ticket",
        "get_ticket",
        {"ticket_id": "T-1"},
        {"id": "T-1"},
        {"id": "T-1"},
    ),
    (
        "board_cards",
        "board_cards",
        {"repo_id": "r"},
        [{"id": "c1"}],
        {"cards": [{"id": "c1"}]},
    ),
    (
        "history",
        "history",
        {"ticket_id": "T-1"},
        [{"event": "x"}],
        {"history": [{"event": "x"}]},
    ),
    (
        "merge_status",
        "merge_status",
        {"ticket_id": "T-1"},
        {"mergeable": True},
        {"mergeable": True},
    ),
    (
        "description",
        "description",
        {"ticket_id": "T-1"},
        {"body": "desc"},
        {"body": "desc"},
    ),
    (
        "get_multiple_ticket_descriptions",
        "get_multiple_ticket_descriptions",
        {"ticket_ids": ["T-1", "T-2"]},
        [{"body": "d1"}, {"body": "d2"}],
        {"descriptions": [{"body": "d1"}, {"body": "d2"}]},
    ),
]


@pytest.mark.parametrize(
    ("op_name", "method_name", "args", "return_value", "expected"), READ_OP_TESTS
)
async def test_read_op_routes_correctly(
    op_name: str,
    method_name: str,
    args: dict[str, Any],
    return_value: Any,
    expected: Any,
):
    client, mock = _client_with_mock(method_name, return_value)
    result = await dispatch(client, BoardOp(op=op_name, args=args))
    mock.assert_awaited_once()
    assert result == expected


# ---------------------------------------------------------------------------
# All write ops route correctly
# ---------------------------------------------------------------------------

WRITE_OP_TESTS = [
    ("create_ticket", "create_ticket", {"title": "Hi", "description": "there"}, {"id": "new"}),
    ("comment", "add_comment", {"ticket_id": "T-1", "body": "nice"}, {"id": "c1"}),
    ("transition", "transition", {"ticket_id": "T-1", "state": "done"}, {"state": "done"}),
    ("approve", "approve", {"ticket_id": "T-1"}, {"approved": True}),
    ("mark_done", "mark_done", {"ticket_id": "T-1", "note": "x"}, {"state": "done"}),
    ("merge_now", "merge_now", {"ticket_id": "T-1"}, {"merged": True}),
    ("resume_blocked", "resume_blocked", {"ticket_id": "T-1"}, {"state": "open"}),
    ("migrate", "migrate", {"ticket_id": "T-1", "target_repo_id": "other"}, {"target": "other"}),
    ("set_priority", "set_priority", {"ticket_id": "T-1", "priority": True}, {"priority": True}),
]


@pytest.mark.parametrize(("op_name", "method_name", "args", "return_value"), WRITE_OP_TESTS)
async def test_write_op_routes_correctly(
    op_name: str,
    method_name: str,
    args: dict[str, Any],
    return_value: Any,
):
    client, mock = _client_with_mock(method_name, return_value)
    result = await dispatch(client, BoardOp(op=op_name, args=args))
    mock.assert_awaited_once()
    assert result == return_value


# ---------------------------------------------------------------------------
# Unknown op
# ---------------------------------------------------------------------------


async def test_unknown_op_raises():
    client = BoardClient.__new__(BoardClient)
    with pytest.raises(UnknownOpError, match="Unknown operation"):
        await dispatch(client, BoardOp(op="nonexistent", args={}))


# ---------------------------------------------------------------------------
# Write ops are in WRITE_OPS and OP_TABLE covers all
# ---------------------------------------------------------------------------


def test_op_table_covers_all_known_ops():
    """Every key in OP_TABLE should be either a known read or a known write."""
    all_ops = set(OP_TABLE.keys())
    assert WRITE_OPS.issubset(all_ops)
    # All 16 ops are present.
    assert len(all_ops) == 16


def test_write_ops_set_content():
    """WRITE_OPS should contain exactly the 9 write op names."""
    assert {
        "create_ticket",
        "comment",
        "transition",
        "approve",
        "mark_done",
        "merge_now",
        "resume_blocked",
        "migrate",
        "set_priority",
    } == WRITE_OPS


# ---------------------------------------------------------------------------
# Arg-model validation: missing required fields
# ---------------------------------------------------------------------------


MISSING_REQUIRED_TESTS = [
    ("get_ticket", {}, "ticket_id"),
    ("history", {}, "ticket_id"),
    ("merge_status", {}, "ticket_id"),
    ("description", {}, "ticket_id"),
    ("get_multiple_ticket_descriptions", {}, "ticket_ids"),
    ("create_ticket", {}, "title"),
    ("comment", {}, "ticket_id"),
    ("transition", {}, "ticket_id"),
    ("approve", {}, "ticket_id"),
    ("mark_done", {}, "ticket_id"),
    ("merge_now", {}, "ticket_id"),
    ("resume_blocked", {}, "ticket_id"),
    ("migrate", {}, "ticket_id"),
    ("set_priority", {}, "ticket_id"),
]


@pytest.mark.parametrize(("op_name", "args", "missing_field"), MISSING_REQUIRED_TESTS)
async def test_op_rejects_missing_required_fields(
    op_name: str,
    args: dict[str, Any],
    missing_field: str,
):
    """Each op with required fields should raise ValidationError on empty args."""
    client = BoardClient.__new__(BoardClient)
    with pytest.raises(pydantic.ValidationError, match=missing_field):
        await dispatch(client, BoardOp(op=op_name, args=args))


# ---------------------------------------------------------------------------
# Arg-model validation: type errors
# ---------------------------------------------------------------------------


TYPE_ERROR_TESTS = [
    # read ops
    ("list_tickets", {"state": 42}),
    ("get_ticket", {"ticket_id": 42}),
    ("board_cards", {"repo_id": 42}),
    ("history", {"ticket_id": 42}),
    ("merge_status", {"ticket_id": 42}),
    ("description", {"ticket_id": 42}),
    ("get_multiple_ticket_descriptions", {"ticket_ids": "not-a-list"}),
    # write ops
    ("create_ticket", {"title": 42, "description": "ok"}),
    ("comment", {"ticket_id": 42, "body": "ok"}),
    ("transition", {"ticket_id": 42, "state": "ok"}),
    ("approve", {"ticket_id": 42}),
    ("mark_done", {"ticket_id": 42, "note": "ok"}),
    ("merge_now", {"ticket_id": 42}),
    ("resume_blocked", {"ticket_id": 42}),
    ("migrate", {"ticket_id": 42, "target_repo_id": "ok"}),
    ("set_priority", {"ticket_id": "T-1", "priority": "not-a-bool"}),
]


@pytest.mark.parametrize(("op_name", "args"), TYPE_ERROR_TESTS)
async def test_op_rejects_type_errors(
    op_name: str,
    args: dict[str, Any],
):
    """Each op should raise ValidationError when given args of the wrong type."""
    client = BoardClient.__new__(BoardClient)
    with pytest.raises(pydantic.ValidationError):
        await dispatch(client, BoardOp(op=op_name, args=args))
