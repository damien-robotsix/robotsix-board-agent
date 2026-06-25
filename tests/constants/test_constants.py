# mypy: ignore-errors
"""Tests for default constants and BoardErrorCode enum."""

from __future__ import annotations

from robotsix_board_agent.constants import (
    DEFAULT_COMMENT_AUTHOR,
    DEFAULT_NOTE,
    DEFAULT_TICKET_KIND,
    DEFAULT_TICKET_SOURCE,
    BoardErrorCode,
)

# ---------------------------------------------------------------------------
# Default constant values
# ---------------------------------------------------------------------------


def test_default_ticket_source_is_agent():
    """DEFAULT_TICKET_SOURCE equals "agent"."""
    assert DEFAULT_TICKET_SOURCE == "agent"


def test_default_ticket_kind_is_task():
    """DEFAULT_TICKET_KIND equals "task"."""
    assert DEFAULT_TICKET_KIND == "task"


def test_default_comment_author_is_board_agent():
    """DEFAULT_COMMENT_AUTHOR equals "board-agent"."""
    assert DEFAULT_COMMENT_AUTHOR == "board-agent"


def test_default_note_is_empty_string():
    """DEFAULT_NOTE equals empty string."""
    assert DEFAULT_NOTE == ""


# ---------------------------------------------------------------------------
# BoardErrorCode enum completeness
# ---------------------------------------------------------------------------


def test_board_error_code_all_members_present():
    """BoardErrorCode has exactly 4 members with correct values."""
    members = {m.name: m.value for m in BoardErrorCode}
    assert members == {
        "BAD_REQUEST": "BAD_REQUEST",
        "UNKNOWN_OP": "UNKNOWN_OP",
        "WRITE_OPS_DISABLED": "WRITE_OPS_DISABLED",
        "BOARD_API_ERROR": "BOARD_API_ERROR",
    }


def test_board_error_code_count():
    """BoardErrorCode has exactly 4 members."""
    assert len(BoardErrorCode) == 4


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------


def test_all_public_symbols_importable():
    """All 5 public symbols import successfully from constants module."""
    names = [
        "DEFAULT_TICKET_SOURCE",
        "DEFAULT_TICKET_KIND",
        "DEFAULT_COMMENT_AUTHOR",
        "DEFAULT_NOTE",
        "BoardErrorCode",
    ]
    for name in names:
        assert name in globals(), f"Module-level symbol {name!r} missing"
