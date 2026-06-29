"""Tests for manager_cli.main — CLI entry point for the board manager."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

from robotsix_board_agent.manager_cli import main

# -- helper: build an Agent stub that will receive send_request calls --------


def _build_target_agent(
    registry: Any, response_body: dict[str, Any] | str | None = None, error: bool = False
) -> Any:
    """Register a target agent in *registry* that returns a given reply."""
    from tests.conftest import Agent, Request

    target = Agent(agent_id="board-manager-test-repo", registry=registry)
    if error:
        from tests.conftest import Error

        def handler(req: Request) -> Any:
            return Error(code="INTERNAL", message="something broke")
    else:
        body = response_body or {"reply": "hello from manager"}

        def handler(req: Request) -> Any:
            from tests.conftest import Response

            return Response.to(req, body=body)

    # on_request is a _OnRequest wrapper; set the underlying handler.
    target.on_request._handler = handler
    registry.register(target)
    return target


def _default_target_agent(registry: Any) -> Any:
    """Register a target at the default id used when BOARD_MANAGER_TARGET is unset."""
    from tests.conftest import Agent, Response

    target = Agent(agent_id="board-manager-robotsix-mill", registry=registry)
    target.on_request._handler = lambda req: Response.to(req, body={"reply": "default target"})
    registry.register(target)
    return target


# -- tests -------------------------------------------------------------------


def _brokered_using(registry: Any) -> Any:
    """A ``BrokeredAgent`` replacement binding the CLI agent to *registry* so it
    shares the target agent's in-memory registry."""
    from tests.conftest import Agent

    def _factory(agent_id: str, **_kwargs: Any) -> Agent:
        return Agent(agent_id, registry=registry)

    return _factory


class TestMainErrors:
    """Test main() error paths."""

    def test_no_args_prints_usage_and_exits_2(self, capsys: Any) -> None:
        with patch.dict(os.environ, {"BOARD_MANAGER_CLI_TOKEN": "tok"}):
            rc = main(argv=[])
        assert rc == 2
        captured = capsys.readouterr()
        assert "usage:" in captured.err

    def test_missing_token_exits_2(self, capsys: Any) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # Ensure no BOARD_MANAGER_CLI_TOKEN in env.
            rc = main(argv=["do something"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "BOARD_MANAGER_CLI_TOKEN" in captured.err


class TestMainSuccess:
    """Test main() successful paths — patch create_transport_pair to share registry."""

    def test_valid_args_and_token_returns_0_and_prints_reply(
        self, capsys: Any, registry: Any
    ) -> None:
        _build_target_agent(registry, response_body={"reply": "done!"})
        env = {
            "BOARD_MANAGER_CLI_TOKEN": "tok",
            "BOARD_MANAGER_TARGET": "board-manager-test-repo",
        }
        with (
            patch.dict(os.environ, env),
            patch(
                "robotsix_board_agent.manager_cli.BrokeredAgent",
                new=_brokered_using(registry),
            ),
        ):
            rc = main(argv=["list all tickets"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "done!" in captured.out

    def test_multi_word_message_joined_correctly(self, capsys: Any, registry: Any) -> None:
        _build_target_agent(registry)
        env = {
            "BOARD_MANAGER_CLI_TOKEN": "tok",
            "BOARD_MANAGER_TARGET": "board-manager-test-repo",
        }
        with (
            patch.dict(os.environ, env),
            patch(
                "robotsix_board_agent.manager_cli.BrokeredAgent",
                new=_brokered_using(registry),
            ),
        ):
            rc = main(argv=["close", "all", "stale", "drafts"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "hello from manager" in captured.out

    def test_error_response_returns_1(self, capsys: Any, registry: Any) -> None:
        _build_target_agent(registry, error=True)
        env = {
            "BOARD_MANAGER_CLI_TOKEN": "tok",
            "BOARD_MANAGER_TARGET": "board-manager-test-repo",
        }
        with (
            patch.dict(os.environ, env),
            patch(
                "robotsix_board_agent.manager_cli.BrokeredAgent",
                new=_brokered_using(registry),
            ),
        ):
            rc = main(argv=["do something"])
        assert rc == 1

    def test_non_dict_body_printed_directly(self, capsys: Any, registry: Any) -> None:
        _build_target_agent(registry, response_body="plain text response")
        env = {
            "BOARD_MANAGER_CLI_TOKEN": "tok",
            "BOARD_MANAGER_TARGET": "board-manager-test-repo",
        }
        with (
            patch.dict(os.environ, env),
            patch(
                "robotsix_board_agent.manager_cli.BrokeredAgent",
                new=_brokered_using(registry),
            ),
        ):
            rc = main(argv=["hi"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "plain text response" in captured.out

    def test_default_env_vars_used_when_not_set(self, capsys: Any, registry: Any) -> None:
        # When BOARD_MANAGER_TARGET is not set, main() defaults to
        # "board-manager-robotsix-mill".
        _default_target_agent(registry)

        env = {"BOARD_MANAGER_CLI_TOKEN": "tok"}
        with (
            patch.dict(os.environ, env),
            patch(
                "robotsix_board_agent.manager_cli.BrokeredAgent",
                new=_brokered_using(registry),
            ),
        ):
            rc = main(argv=["hello"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "default target" in captured.out
