"""Tests for BrokeredBoardResponder — structured op gateway over the broker."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from robotsix_board_agent.brokered import BrokeredBoardResponder
from robotsix_board_agent.client import BoardAPIError
from robotsix_board_agent.config import BoardAgentSettings
from robotsix_board_agent.constants import BoardErrorCode


@pytest.fixture
def responder(settings: BoardAgentSettings) -> BrokeredBoardResponder:
    """Return a BrokeredBoardResponder with default settings."""
    return BrokeredBoardResponder(
        settings,
        broker_host="test-broker.robotsix.net",
        broker_token="test-broker-token",
    )


# -- helpers ----------------------------------------------------------------

_WRITE_OP_BODY = {
    "op": "create_ticket",
    "args": {"title": "x", "description": "y"},
}


def _req(body: Any) -> Any:
    from tests.conftest import Request

    return Request(body=body)


# -- _handle_request: error paths (no loop needed) ---------------------------


class TestHandleRequestErrors:
    """Test _handle_request error paths — these don't touch the event loop."""

    def test_body_not_dict_or_string_returns_bad_request(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        reply = responder._handle_request(_req(42))
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.BAD_REQUEST.value
        assert "JSON object" in reply.error["message"]

    def test_body_string_not_valid_json_returns_bad_request(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        reply = responder._handle_request(_req("not json"))
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.BAD_REQUEST.value
        assert "valid JSON" in reply.error["message"]

    def test_body_not_valid_boardop_returns_bad_request(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        reply = responder._handle_request(_req({"not": "an op"}))
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.BAD_REQUEST.value
        assert "Invalid operation" in reply.error["message"]

    def test_unknown_op_returns_unknown_op_error(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        reply = responder._handle_request(
            _req({"op": "nonexistent_op", "args": {}}),
        )
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.UNKNOWN_OP.value
        assert "Unknown op" in reply.error["message"]

    def test_write_op_disabled_returns_error(
        self,
        settings: BoardAgentSettings,
    ) -> None:
        settings.enable_write_ops = False
        r = BrokeredBoardResponder(
            settings,
            broker_host="test-broker.robotsix.net",
            broker_token="test-broker-token",
        )
        reply = r._handle_request(_req(_WRITE_OP_BODY))
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.WRITE_OPS_DISABLED.value
        assert "enable_write_ops" in reply.error["message"]

    def test_read_op_still_allowed_when_write_disabled(
        self,
        settings: BoardAgentSettings,
    ) -> None:
        settings.enable_write_ops = False
        r = BrokeredBoardResponder(
            settings,
            broker_host="test-broker.robotsix.net",
            broker_token="test-broker-token",
        )
        # Mock _run to avoid needing a real event loop.
        with patch.object(r, "_run", return_value={"tickets": []}):
            reply = r._handle_request(
                _req({"op": "list_tickets", "args": {}}),
            )
        assert reply.error is None
        assert reply.result == {"tickets": []}


# -- _handle_request: successful dispatch ------------------------------------


class TestHandleRequestDispatch:
    """Test _handle_request when dispatch is called — mock _run."""

    def test_valid_read_op_dispatches_and_returns_result(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        with patch.object(
            responder,
            "_run",
            return_value={"tickets": [{"id": "1"}]},
        ):
            reply = responder._handle_request(
                _req({"op": "list_tickets", "args": {"state": "open"}}),
            )
        assert reply.error is None
        assert reply.result == {"tickets": [{"id": "1"}]}

    def test_valid_write_op_dispatches_and_returns_result(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        body = {
            "op": "create_ticket",
            "args": {"title": "hello", "description": "world"},
        }
        with patch.object(
            responder,
            "_run",
            return_value={"id": "new-ticket", "title": "hello"},
        ):
            reply = responder._handle_request(_req(body))
        assert reply.error is None
        assert reply.result == {"id": "new-ticket", "title": "hello"}

    def test_board_api_error_converts_to_error_response(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        with patch.object(
            responder,
            "_run",
            side_effect=BoardAPIError(422, "duplicate title"),
        ):
            reply = responder._handle_request(
                _req(
                    {
                        "op": "create_ticket",
                        "args": {"title": "dup", "description": "x"},
                    },
                ),
            )
        assert reply.error is not None
        assert reply.error["code"] == BoardErrorCode.BOARD_API_ERROR.value
        assert "422" in reply.error["message"]
        assert "duplicate title" in reply.error["message"]

    def test_body_dict_without_string_parse_works(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        # body is already a dict — should be used directly.
        with patch.object(responder, "_run", return_value={"cards": []}):
            reply = responder._handle_request(
                _req({"op": "board_cards", "args": {}}),
            )
        assert reply.error is None
        assert reply.result == {"cards": []}

    def test_json_string_body_parsed(
        self,
        responder: BrokeredBoardResponder,
    ) -> None:
        import json

        body_str = json.dumps(
            {"op": "get_ticket", "args": {"ticket_id": "abc"}},
        )
        with patch.object(
            responder,
            "_run",
            return_value={"id": "abc", "title": "test"},
        ):
            reply = responder._handle_request(_req(body_str))
        assert reply.error is None
        assert reply.result == {"id": "abc", "title": "test"}


# -- start / stop lifecycle --------------------------------------------------


class TestLifecycle:
    """Test start() / stop() thread and event-loop management."""

    def test_start_creates_loop_and_thread(self, responder: BrokeredBoardResponder) -> None:
        assert responder._loop is None
        assert responder._loop_thread is None
        responder.start()
        try:
            assert responder._loop is not None
            assert responder._loop_thread is not None
            assert responder._loop_thread.is_alive()
            assert responder._loop_thread.daemon is True
        finally:
            responder.stop()

    def test_start_is_idempotent(self, responder: BrokeredBoardResponder) -> None:
        responder.start()
        try:
            loop1 = responder._loop
            responder.start()  # second call should no-op
            assert responder._loop is loop1
        finally:
            responder.stop()

    def test_stop_shuts_down_loop_and_thread(self, responder: BrokeredBoardResponder) -> None:
        responder.start()
        responder.stop()
        # After stop, the loop should be closed and thread should be None.
        assert responder._loop is None
        assert responder._loop_thread is None

    def test_stop_before_start_is_safe(self, responder: BrokeredBoardResponder) -> None:
        # Should not raise.
        responder.stop()
        assert responder._loop is None

    def test_stop_waits_for_thread(self, responder: BrokeredBoardResponder) -> None:
        responder.start()
        thread = responder._loop_thread
        assert thread is not None
        responder.stop()
        # Thread should have been joined (not alive anymore).
        # Give a short grace period for the thread to actually exit.
        thread.join(timeout=1.0)
        assert not thread.is_alive()

    def test_full_cycle_repeatable(self, responder: BrokeredBoardResponder) -> None:
        for _ in range(2):
            responder.start()
            # Verify we can run a coroutine on the loop.
            import asyncio

            fut = asyncio.run_coroutine_threadsafe(
                asyncio.sleep(0.01),
                responder._loop,  # type: ignore[arg-type]
            )
            fut.result(timeout=2.0)
            responder.stop()
            assert responder._loop is None
            assert responder._loop_thread is None
