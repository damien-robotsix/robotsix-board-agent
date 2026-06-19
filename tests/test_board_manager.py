"""Tests for BoardManager — LLM-powered conversational board manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from robotsix_board_agent.board_manager import BoardManager
from robotsix_board_agent.config import BoardAgentSettings
from robotsix_board_agent.constants import BoardErrorCode


@pytest.fixture
def manager(settings: BoardAgentSettings, tmp_path: Path) -> BoardManager:
    """Return a BoardManager with a tmp_path-backed memory store."""
    return BoardManager(
        settings,
        broker_host="test-broker.robotsix.net",
        broker_token="test-broker-token",
        openrouter_key="test-openrouter-key",
        memory_path=tmp_path / "memory",
    )


# -- _handle_request ---------------------------------------------------------


class TestHandleRequest:
    """Test BoardManager._handle_request — mock _converse to isolate."""

    def test_missing_message_returns_error(self, manager: BoardManager) -> None:
        from tests.conftest import Request

        reply = manager._handle_request(Request(body={}))
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.BAD_REQUEST.value
        assert "message" in reply.error["message"]

    def test_empty_message_returns_error(self, manager: BoardManager) -> None:
        from tests.conftest import Request

        reply = manager._handle_request(Request(body={"message": "   "}))
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.BAD_REQUEST.value

    def test_body_not_dict_defaults_to_empty(self, manager: BoardManager) -> None:
        from tests.conftest import Request

        # When body is not a dict, _handle_request defaults to {}.
        with patch.object(manager, "_converse", return_value="test reply"):
            reply = manager._handle_request(Request(body="not a dict"))
        # Should treat as {} → missing message → error
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.BAD_REQUEST.value

    def test_valid_message_converses_and_returns_reply(self, manager: BoardManager) -> None:
        from tests.conftest import Request

        with patch.object(manager, "_converse", return_value="I did the thing."):
            reply = manager._handle_request(Request(body={"message": "do the thing"}))
        assert reply.error is None
        assert reply.result == {"reply": "I did the thing."}

    def test_question_key_also_accepted(self, manager: BoardManager) -> None:
        from tests.conftest import Request

        with patch.object(manager, "_converse", return_value="answer"):
            reply = manager._handle_request(Request(body={"question": "what is this?"}))
        assert reply.error is None
        assert reply.result == {"reply": "answer"}

    def test_message_preferred_over_question(self, manager: BoardManager) -> None:
        from tests.conftest import Request

        with patch.object(manager, "_converse", return_value="from message") as mock_conv:
            reply = manager._handle_request(
                Request(body={"message": "use this", "question": "not this"})
            )
        mock_conv.assert_called_once_with("use this", "agent")
        assert reply.result == {"reply": "from message"}

    def test_converse_result_appended_to_memory(self, manager: BoardManager) -> None:
        from tests.conftest import Request

        with patch.object(manager, "_converse", return_value="the answer"):
            manager._handle_request(Request(body={"message": "the question"}))

        entries = manager._memory.load()
        assert len(entries) == 1
        assert entries[0]["question"] == "the question"
        assert entries[0]["answer"] == "the answer"


# -- start / stop lifecycle --------------------------------------------------


class TestLifecycle:
    """Test BoardManager start() / stop() thread and event-loop management."""

    def test_start_creates_loop_and_thread(self, manager: BoardManager) -> None:
        assert manager._loop is None
        manager.start()
        try:
            assert manager._loop is not None
            assert manager._loop_thread is not None
            assert manager._loop_thread.is_alive()
            assert manager._loop_thread.daemon is True
        finally:
            manager.stop()

    def test_start_idempotent(self, manager: BoardManager) -> None:
        manager.start()
        try:
            loop1 = manager._loop
            manager.start()
            assert manager._loop is loop1
        finally:
            manager.stop()

    def test_stop_cleans_up(self, manager: BoardManager) -> None:
        manager.start()
        manager.stop()
        assert manager._loop is None
        assert manager._loop_thread is None

    def test_stop_before_start_safe(self, manager: BoardManager) -> None:
        manager.stop()
        assert manager._loop is None

    def test_full_cycle_repeatable(self, manager: BoardManager) -> None:
        for _ in range(2):
            manager.start()
            import asyncio

            fut = asyncio.run_coroutine_threadsafe(
                asyncio.sleep(0.01),
                manager._loop,  # type: ignore[arg-type]
            )
            fut.result(timeout=2.0)
            manager.stop()
            assert manager._loop is None
