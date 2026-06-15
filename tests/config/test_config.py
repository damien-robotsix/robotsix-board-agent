# mypy: ignore-errors
"""Tests for BoardAgentSettings — defaults, required fields, and agent_id derivation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from robotsix_board_agent.config import BoardAgentSettings

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_enable_write_ops_defaults_to_true():
    """Default value of enable_write_ops is True."""
    settings = BoardAgentSettings(
        board_api_url="http://x",
        board_api_token="t",
        board_repo_id="r",
    )
    assert settings.enable_write_ops is True


def test_enable_write_ops_can_be_disabled():
    """enable_write_ops can be explicitly set to False."""
    settings = BoardAgentSettings(
        board_api_url="http://x",
        board_api_token="t",
        board_repo_id="r",
        enable_write_ops=False,
    )
    assert settings.enable_write_ops is False


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


def test_board_api_url_is_required():
    """Pydantic raises ValidationError when board_api_url is missing."""
    with pytest.raises(ValidationError) as exc:
        BoardAgentSettings(board_api_token="t", board_repo_id="r")
    assert "board_api_url" in str(exc.value)


def test_board_api_token_is_required():
    """Pydantic raises ValidationError when board_api_token is missing."""
    with pytest.raises(ValidationError) as exc:
        BoardAgentSettings(board_api_url="http://x", board_repo_id="r")
    assert "board_api_token" in str(exc.value)


def test_board_repo_id_is_required():
    """Pydantic raises ValidationError when board_repo_id is missing."""
    with pytest.raises(ValidationError) as exc:
        BoardAgentSettings(board_api_url="http://x", board_api_token="t")
    assert "board_repo_id" in str(exc.value)


def test_all_required_fields_missing_at_once():
    """Pydantic raises ValidationError with all missing fields reported."""
    with pytest.raises(ValidationError) as exc:
        BoardAgentSettings()
    msg = str(exc.value)
    assert "board_api_url" in msg
    assert "board_api_token" in msg
    assert "board_repo_id" in msg


# ---------------------------------------------------------------------------
# Agent ID derivation from board_repo_id
# ---------------------------------------------------------------------------


def test_agent_id_derived_from_board_repo_id():
    """Agent ID is derived as ``board-{board_repo_id}`` when no explicit ID."""
    from robotsix_agent_comm import Registry

    from robotsix_board_agent.agent import BoardAgent

    settings = BoardAgentSettings(
        board_api_url="http://x",
        board_api_token="t",
        board_repo_id="my-repo",
    )
    agent = BoardAgent(settings, Registry())
    assert agent.agent_id == "board-my-repo"
