"""Unit tests for :func:`_parse_and_validate`."""

from __future__ import annotations

import pytest
from robotsix_agent_comm.protocol import Request

from robotsix_board_agent._request_handler import _parse_and_validate
from robotsix_board_agent.config import BoardAgentSettings
from robotsix_board_agent.constants import BoardErrorCode
from robotsix_board_agent.ops import BoardOp


@pytest.fixture
def settings_write_enabled() -> BoardAgentSettings:
    return BoardAgentSettings(
        board_api_url="http://mock-board.test",
        board_api_token="test-token",
        board_repo_id="test-repo",
        enable_write_ops=True,
    )


@pytest.fixture
def settings_write_disabled() -> BoardAgentSettings:
    return BoardAgentSettings(
        board_api_url="http://mock-board.test",
        board_api_token="test-token",
        board_repo_id="test-repo",
        enable_write_ops=False,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestValidOp:
    def test_returns_op_and_none(self, settings_write_enabled: BoardAgentSettings) -> None:
        req = Request(body={"op": "list_tickets", "args": {}})
        op, err = _parse_and_validate(req, settings_write_enabled)

        assert isinstance(op, BoardOp)
        assert op.op == "list_tickets"
        assert op.args == {}
        assert err is None


# ---------------------------------------------------------------------------
# Invalid JSON body
# ---------------------------------------------------------------------------


class TestInvalidJSON:
    def test_returns_bad_request_error(self, settings_write_enabled: BoardAgentSettings) -> None:
        req = Request(body="not valid json {")
        op, err = _parse_and_validate(req, settings_write_enabled)

        assert op is None
        assert err is not None
        assert err.error["code"] == BoardErrorCode.BAD_REQUEST.value
        assert "valid JSON" in err.error["message"]


# ---------------------------------------------------------------------------
# Non-dict body
# ---------------------------------------------------------------------------


class TestNonDictBody:
    def test_returns_bad_request_error(self, settings_write_enabled: BoardAgentSettings) -> None:
        req = Request(body=42)
        op, err = _parse_and_validate(req, settings_write_enabled)

        assert op is None
        assert err is not None
        assert err.error["code"] == BoardErrorCode.BAD_REQUEST.value
        assert "JSON object" in err.error["message"]

    def test_list_body_rejected(self, settings_write_enabled: BoardAgentSettings) -> None:
        req = Request(body=[1, 2, 3])
        op, err = _parse_and_validate(req, settings_write_enabled)

        assert op is None
        assert err is not None
        assert err.error["code"] == BoardErrorCode.BAD_REQUEST.value


# ---------------------------------------------------------------------------
# Unknown op name
# ---------------------------------------------------------------------------


class TestUnknownOp:
    def test_returns_unknown_op_error(self, settings_write_enabled: BoardAgentSettings) -> None:
        req = Request(body={"op": "nonexistent_operation", "args": {}})
        op, err = _parse_and_validate(req, settings_write_enabled)

        assert op is None
        assert err is not None
        assert err.error["code"] == BoardErrorCode.UNKNOWN_OP.value
        assert "Unknown op" in err.error["message"]


# ---------------------------------------------------------------------------
# Write gate (enable_write_ops=False)
# ---------------------------------------------------------------------------


class TestWriteGate:
    def test_write_op_blocked_when_disabled(
        self, settings_write_disabled: BoardAgentSettings
    ) -> None:
        req = Request(body={"op": "create_ticket", "args": {"title": "test"}})
        op, err = _parse_and_validate(req, settings_write_disabled)

        assert op is None
        assert err is not None
        assert err.error["code"] == BoardErrorCode.WRITE_OPS_DISABLED.value
        assert "Write operation" in err.error["message"]

    def test_read_op_allowed_when_write_disabled(
        self, settings_write_disabled: BoardAgentSettings
    ) -> None:
        req = Request(body={"op": "list_tickets", "args": {}})
        op, err = _parse_and_validate(req, settings_write_disabled)

        assert isinstance(op, BoardOp)
        assert op.op == "list_tickets"
        assert err is None
