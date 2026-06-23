"""Tests for BoardManager — LLM-powered conversational board manager."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from robotsix_board_agent.board_manager import BoardManager
from robotsix_board_agent.client import BoardAPIError
from robotsix_board_agent.config import BoardAgentSettings
from robotsix_board_agent.constants import BoardErrorCode


@pytest.fixture
def manager(settings: BoardAgentSettings, tmp_path: Path) -> BoardManager:
    """Return a BoardManager with a tmp_path-backed memory store."""
    return BoardManager(
        settings,
        broker_host="test-broker.robotsix.net",
        broker_token="test-broker-token",
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

    def test_message_key_accepted(self, manager: BoardManager) -> None:
        from tests.conftest import Request

        with patch.object(manager, "_converse", return_value="from message") as mock_conv:
            reply = manager._handle_request(Request(body={"message": "use this"}))
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

    def test_converse_failure_returns_error_reply(self, manager: BoardManager) -> None:
        """When _converse raises, _handle_request returns a clear error reply
        (with error=True) instead of letting the broker emit an opaque
        'internal handler error'."""
        from tests.conftest import Request

        with patch.object(
            manager,
            "_converse",
            side_effect=RuntimeError("model may not exist"),
        ):
            reply = manager._handle_request(Request(body={"message": "do the thing"}))

        # conftest's Response.to maps body=... into result.
        assert reply.error is None
        assert reply.result is not None
        assert reply.result["error"] is True
        assert "could not complete your request" in reply.result["reply"]
        # The error class + message are surfaced for diagnosis.
        assert "RuntimeError" in reply.result["reply"]
        assert "model may not exist" in reply.result["reply"]

    def test_converse_failure_not_appended_to_memory(self, manager: BoardManager) -> None:
        """A failed turn is not written to conversation memory."""
        from tests.conftest import Request

        with patch.object(manager, "_converse", side_effect=RuntimeError("boom")):
            manager._handle_request(Request(body={"message": "the question"}))

        assert manager._memory.load() == []


# -- _converse (LLM pipeline) ------------------------------------------------


class TestConverse:
    """Test BoardManager._converse — mock build_agent_for_level to isolate.

    The recall pass and the manager pass each resolve their OWN provider via
    llmio's per-level defaults (``build_agent_for_level``): recall is level-1
    (DeepSeek), manager is level-3 (Claude).  Patching the single entry point
    keeps the test hermetic — no concrete provider/transport is constructed.
    """

    @pytest.fixture
    def mock_build_agent(self) -> MagicMock:
        """Patch build_agent_for_level to return fresh agent mocks per call.

        Patched at the source (``robotsix_llmio``) since ``_converse`` does a
        ``from robotsix_llmio import build_agent_for_level`` *inside* the function
        (so there is no module-level name to patch on ``board_manager``).
        """
        with patch(
            "robotsix_llmio.build_agent_for_level",
            side_effect=lambda *a, **k: MagicMock(),
        ) as ba:
            yield ba

    @pytest.fixture
    def mock_run_agent(self) -> MagicMock:
        """Patch run_agent to return canned output for each call."""
        with patch("robotsix_llmio.core.run.run_agent") as ra:
            yield ra

    # -- history absent -------------------------------------------------

    def test_no_history_skips_recall(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When memory is empty, no recall agent is built or run."""
        mock_run_agent.return_value = "final answer"

        result = manager._converse("some question")

        assert result == "final answer"
        # Only one build_agent_for_level call (the level-3 manager), not two.
        assert mock_build_agent.call_count == 1
        call = mock_build_agent.call_args
        assert call.args[0] == 3  # manager is level-3
        assert call.kwargs["name"] == "board-manager"

    def test_no_history_omits_relevant_from_system(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When memory is empty, the system prompt has no 'Relevant prior'."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "Relevant prior exchanges" not in system

    # -- history present -------------------------------------------------

    def test_history_present_builds_and_runs_recall(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When memory has entries, a level-1 recall agent is built and run.

        Recall and manager are built on DISTINCT levels (1 vs 3) — each carries
        its own provider via llmio's per-level defaults.
        """
        manager._memory.append("prior Q", "prior A")
        # Return distinct values for recall and manager runs.
        mock_run_agent.side_effect = ["relevant context", "manager answer"]

        result = manager._converse("new question")

        assert result == "manager answer"
        assert mock_build_agent.call_count == 2
        # First call: recall agent (level-1).
        recall_call = mock_build_agent.call_args_list[0]
        assert recall_call.args[0] == 1
        assert recall_call.kwargs["name"] == "board-manager-recall"
        assert recall_call.kwargs["model"] is None  # recall_model not set
        assert recall_call.kwargs["output_type"] is str
        # Second call: manager agent (level-3).
        mgr_call = mock_build_agent.call_args_list[1]
        assert mgr_call.args[0] == 3
        assert mgr_call.kwargs["name"] == "board-manager"
        # Recall and manager are distinct levels (distinct providers).
        assert recall_call.args[0] != mgr_call.args[0]

    def test_recall_output_in_system_prompt(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The recall output text appears in the manager's system prompt."""
        manager._memory.append("q1", "a1")
        mock_run_agent.side_effect = ["remembered context", "final"]

        manager._converse("q2")

        system = mock_build_agent.call_args_list[1].kwargs["system_prompt"]
        assert "remembered context" in system
        assert "Relevant prior exchanges:" in system

    def test_recall_none_output_omitted_from_system(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When recall returns 'none', 'Relevant prior' NOT in system prompt."""
        manager._memory.append("q", "a")
        mock_run_agent.side_effect = ["none", "ok"]

        manager._converse("q2")

        system = mock_build_agent.call_args_list[1].kwargs["system_prompt"]
        assert "Relevant prior exchanges" not in system

    # -- notes present / absent ------------------------------------------

    def test_notes_present_in_system_prompt(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When load_notes() returns content, it appears in the system prompt."""
        manager._memory.save_notes("Task 1 is ongoing.")
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "Your maintained memory:" in system
        assert "Task 1 is ongoing." in system

    def test_notes_absent_omitted_from_system(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When load_notes() returns '', no memory section in system prompt."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "Your maintained memory:" not in system

    # -- recall_model ----------------------------------------------------

    def test_recall_model_override(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _recall_model is set, it is passed to the level-1 recall build."""
        manager._recall_model = "custom-recall-model"
        manager._memory.append("q", "a")
        mock_run_agent.side_effect = ["ctx", "ans"]

        manager._converse("q2")

        recall_call = mock_build_agent.call_args_list[0]
        assert recall_call.args[0] == 1
        assert recall_call.kwargs["model"] == "custom-recall-model"

    def test_recall_model_unset_passes_none(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _recall_model is None, model=None is passed (level-1 default kept)."""
        manager._recall_model = None
        manager._memory.append("q", "a")
        mock_run_agent.side_effect = ["ctx", "ans"]

        manager._converse("q2")

        recall_call = mock_build_agent.call_args_list[0]
        assert recall_call.args[0] == 1
        assert recall_call.kwargs["model"] is None

    # -- system prompt structure -----------------------------------------

    def test_system_prompt_includes_repo_id(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The manager system prompt includes the board repo id."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "test-repo" in system

    def test_system_prompt_includes_requester(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The system prompt names the requester."""
        mock_run_agent.return_value = "ok"

        manager._converse("q", requester="alice")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "requester is 'alice'" in system

    # -- manager model ---------------------------------------------------

    def test_manager_model_uses_configured_value(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _manager_model is set, it is used for the level-3 agent."""
        manager._manager_model = "custom-manager-model"
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        mgr_call = mock_build_agent.call_args
        assert mgr_call.args[0] == 3
        assert mgr_call.kwargs["model"] == "custom-manager-model"

    def test_manager_model_defaults_when_unset(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _manager_model is None, model=None is passed (level-3 default kept).

        The level-3 default (Claude opus) is resolved inside llmio, not here.
        """
        manager._manager_model = None
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        mgr_call = mock_build_agent.call_args
        assert mgr_call.args[0] == 3
        assert mgr_call.kwargs["model"] is None

    # -- error path ------------------------------------------------------

    def test_provider_raises_propagates(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When the run raises, the exception propagates out of _converse (no catch).

        The catch lives one layer up in _handle_request (see TestHandleRequest).
        """
        mock_run_agent.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError, match="provider down"):
            manager._converse("q")

    # -- tool assembly ---------------------------------------------------

    def test_tools_are_built_for_level3_agent(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The level-3 agent is built with tools from _build_tools."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        mgr_call = mock_build_agent.call_args
        assert mgr_call.args[0] == 3
        assert "tools" in mgr_call.kwargs
        assert mgr_call.kwargs["tools"] is not None

    # -- prompt id-handling guidance ---------------------------------------

    def test_system_prompt_includes_id_handling_guidance(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The system prompt contains explicit ticket id handling instructions."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "TICKET ID HANDLING" in system
        assert "opaque strings" in system
        assert "complete id" in system.lower() or "complete id" in system
        assert "verbatim" in system

    def test_system_prompt_warns_against_truncating_to_timestamp(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The system prompt warns never to truncate an id to its timestamp."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "never truncate" in system.lower()

    def test_system_prompt_includes_anti_duplicate_404_guard(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The system prompt includes the 404 anti-duplicate guard."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "ANTI-DUPLICATE GUARD" in system
        assert "do NOT re-create" in system
        assert "404" in system

    def test_system_prompt_example_id_is_not_truncated(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The example id in the prompt is a full timestamp-slug-suffix string."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "20260621T182023Z-add-automatic-conversation-restart-after-4cb7" in system

    # -- enable_write_ops system prompt notice ---------------------------

    @pytest.fixture
    def read_only_manager(self, tmp_path: Path) -> BoardManager:
        """Return a BoardManager with enable_write_ops=False."""
        settings = BoardAgentSettings(
            board_api_url="http://mock-board.test",
            board_api_token="test-token",
            board_repo_id="test-repo",
            enable_write_ops=False,
        )
        return BoardManager(
            settings,
            broker_host="test-broker.robotsix.net",
            broker_token="test-broker-token",
            memory_path=tmp_path / "memory",
        )

    def test_read_only_notice_in_system_prompt(
        self,
        read_only_manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When enable_write_ops=False, system prompt contains read-only notice."""
        mock_run_agent.return_value = "ok"

        read_only_manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "Write operations are disabled" in system

    def test_read_write_no_notice_in_system_prompt(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When enable_write_ops=True (default), no read-only notice."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_build_agent.call_args.kwargs["system_prompt"]
        assert "Write operations are disabled" not in system


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


# -- _build_tools ------------------------------------------------------------


class TestBuildTools:
    """Direct unit tests for BoardManager._build_tools()."""

    # -- tool count & names --------------------------------------------------

    def test_returns_exactly_16_callables(self, manager: BoardManager) -> None:
        tools = manager._build_tools("test-requester")
        assert len(tools) == 16
        assert all(callable(t) for t in tools)

    def test_tool_names_match_expected(self, manager: BoardManager) -> None:
        tools = manager._build_tools("test-requester")
        expected = [
            "list_tickets",
            "get_ticket",
            "board_cards",
            "ticket_history",
            "merge_status",
            "ticket_description",
            "create_ticket",
            "comment",
            "transition",
            "approve",
            "mark_done",
            "merge_now",
            "migrate",
            "resume_blocked",
            "set_priority",
            "update_memory",
        ]
        assert [t.__name__ for t in tools] == expected

    # -- create_ticket -------------------------------------------------------

    def test_create_ticket_defaults_source_to_requester(self, manager: BoardManager) -> None:
        manager._run = MagicMock(return_value={"id": "ticket-1"})
        manager.client.create_ticket = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        create_ticket = next(t for t in tools if t.__name__ == "create_ticket")

        create_ticket(title="x", description="y")

        manager.client.create_ticket.assert_called_once_with(
            title="x",
            description="y",
            source="test-requester",
            repo_id=manager.settings.board_repo_id,
        )

    def test_create_ticket_respects_explicit_source(self, manager: BoardManager) -> None:
        manager._run = MagicMock(return_value={"id": "ticket-2"})
        manager.client.create_ticket = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        create_ticket = next(t for t in tools if t.__name__ == "create_ticket")

        create_ticket(title="x", description="y", source="custom-source")

        manager.client.create_ticket.assert_called_once_with(
            title="x",
            description="y",
            source="custom-source",
            repo_id=manager.settings.board_repo_id,
        )

    # -- update_memory -------------------------------------------------------

    def test_update_memory_delegates_to_save_notes(self, manager: BoardManager) -> None:
        manager._memory.save_notes = MagicMock()

        tools = manager._build_tools("test-requester")
        update_memory = next(t for t in tools if t.__name__ == "update_memory")

        result = update_memory("new notes")

        manager._memory.save_notes.assert_called_once_with("new notes")
        assert result == "maintained memory updated"

    # -- _safe error wrapping ------------------------------------------------

    def test_safe_propagates_board_api_error_as_string(self, manager: BoardManager) -> None:
        error = BoardAPIError(422, "validation failed")
        manager._run = MagicMock(side_effect=error)
        manager.client.list_tickets = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        list_tickets = next(t for t in tools if t.__name__ == "list_tickets")

        result = list_tickets(state="open")

        # _safe must convert BoardAPIError to a string, never let it propagate.
        assert isinstance(result, str)
        assert "board API error 422" in result
        assert "validation failed" in result

    # -- _safe truncation id-safety ----------------------------------------

    def test_safe_truncation_drops_trailing_list_elements(self, manager: BoardManager) -> None:
        """When a list result exceeds _RESULT_CAP, whole trailing elements
        are dropped and an omission marker is appended, never mangling ids."""
        from robotsix_board_agent.board_manager import _RESULT_CAP

        # Build a list large enough that its JSON exceeds _RESULT_CAP.
        # Each dict ~150 chars → ~80 items needed.
        items: list[dict[str, object]] = [
            {
                "id": f"ticket-{i:04d}-a-long-suffix-to-fill-json-payload-space",
                "title": f"issue number {i}",
                "data": "x" * 80,
            }
            for i in range(200)
        ]
        assert len(json.dumps(items)) > _RESULT_CAP

        manager._run = MagicMock(return_value=items.copy())
        manager.client.list_tickets = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        list_tickets_fn = next(t for t in tools if t.__name__ == "list_tickets")

        result = list_tickets_fn()

        # Must be valid JSON.
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        # Fewer items returned than originally.
        assert len(parsed) < len(items)
        # Every ticket id in the result is a full, unmangled id from the input.
        input_ids = {item["id"] for item in items}
        for entry in parsed:
            if "_truncated" in entry:
                continue
            assert entry["id"] in input_ids, f"id {entry['id']!r} not in input ids"
        # An omission marker is present.
        markers = [e for e in parsed if "_truncated" in e]
        assert len(markers) == 1
        assert "omitted" in markers[0]["_truncated"]

    def test_safe_truncation_marker_is_last_element(self, manager: BoardManager) -> None:
        """The _truncated marker is the last element of the list."""
        from robotsix_board_agent.board_manager import _RESULT_CAP

        items = [
            {
                "id": f"ticket-{i:04d}-padding-padding-padding-padding-padding",
                "x": "y" * 100,
            }
            for i in range(200)
        ]
        assert len(json.dumps(items)) > _RESULT_CAP

        manager._run = MagicMock(return_value=items.copy())
        manager.client.list_tickets = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        list_tickets_fn = next(t for t in tools if t.__name__ == "list_tickets")

        result = list_tickets_fn()
        parsed = json.loads(result)
        assert "_truncated" in parsed[-1]

    def test_safe_does_not_truncate_single_dict(self, manager: BoardManager) -> None:
        """A single dict result (e.g. get_ticket) is returned whole — never
        sliced mid-field even if it exceeds _RESULT_CAP (though single tickets
        are far under 12 KB in practice)."""
        ticket = {
            "id": "20260621T182023Z-my-ticket-a1b2",
            "title": "test",
            "description": "x" * 15000,  # push past _RESULT_CAP
        }

        manager._run = MagicMock(return_value=ticket)
        manager.client.get_ticket = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        get_ticket_fn = next(t for t in tools if t.__name__ == "get_ticket")

        result = get_ticket_fn(ticket_id=ticket["id"])

        parsed = json.loads(result)
        # The full id is present and unmangled.
        assert parsed["id"] == ticket["id"]
        # The description is complete (no slicing).
        assert parsed["description"] == ticket["description"]

    def test_safe_small_list_not_truncated(self, manager: BoardManager) -> None:
        """A small list under _RESULT_CAP is returned as-is with no marker."""
        items = [
            {"id": "ticket-0001-short", "title": "small"},
            {"id": "ticket-0002-short", "title": "list"},
        ]
        assert len(json.dumps(items)) < 12_000  # well under _RESULT_CAP

        manager._run = MagicMock(return_value=items.copy())
        manager.client.list_tickets = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        list_tickets_fn = next(t for t in tools if t.__name__ == "list_tickets")

        result = list_tickets_fn()
        parsed = json.loads(result)
        assert parsed == items
        assert not any("_truncated" in e for e in parsed)

    # -- enable_write_ops gating ------------------------------------------

    @pytest.fixture
    def read_only_manager(self, tmp_path: Path) -> BoardManager:
        """Return a BoardManager with enable_write_ops=False."""
        settings = BoardAgentSettings(
            board_api_url="http://mock-board.test",
            board_api_token="test-token",
            board_repo_id="test-repo",
            enable_write_ops=False,
        )
        return BoardManager(
            settings,
            broker_host="test-broker.robotsix.net",
            broker_token="test-broker-token",
            memory_path=tmp_path / "memory",
        )

    def test_read_only_returns_7_tools(self, read_only_manager: BoardManager) -> None:
        tools = read_only_manager._build_tools("test-requester")
        assert len(tools) == 7
        assert all(callable(t) for t in tools)

    def test_read_only_tool_names_are_read_only(self, read_only_manager: BoardManager) -> None:
        tools = read_only_manager._build_tools("test-requester")
        names = {t.__name__ for t in tools}
        expected = {
            "list_tickets",
            "get_ticket",
            "board_cards",
            "ticket_history",
            "merge_status",
            "ticket_description",
            "update_memory",
        }
        assert names == expected

    def test_read_only_excludes_all_write_ops(self, read_only_manager: BoardManager) -> None:
        from robotsix_board_agent.ops import WRITE_OPS

        tools = read_only_manager._build_tools("test-requester")
        names = {t.__name__ for t in tools}
        assert names.isdisjoint(WRITE_OPS)

    def test_read_write_returns_full_16(self, manager: BoardManager) -> None:
        """When enable_write_ops=True (default fixture), still 16 tools."""
        tools = manager._build_tools("test-requester")
        assert len(tools) == 16

    # -- _truncate_result fallback pop ------------------------------------

    def test_truncate_result_fallback_pop_drops_last_element(self) -> None:
        """When a single element + the omission marker still exceed
        _RESULT_CAP, the last element is also dropped (secondary fallback pop)."""
        from robotsix_board_agent.board_manager import _RESULT_CAP, _truncate_result

        # Build a large element whose JSON is just under _RESULT_CAP so that
        # after truncation [element, marker] overflows the cap.
        pad_len = _RESULT_CAP - 20
        big = {"data": "x" * pad_len}
        big_json = json.dumps(big)
        assert len(big_json) < _RESULT_CAP

        # Sanity-check: [big, marker] really does overflow.
        marker = {"_truncated": "1 item(s) omitted (result cap)"}
        assert len(json.dumps([big, marker])) > _RESULT_CAP

        # The list [big, small] exceeds _RESULT_CAP (big alone is just under,
        # so the list is over).  After popping small, the remaining [big]
        # + marker would still overflow → fallback pop fires.
        small = {"id": "ticket-0001"}
        result = _truncate_result([big, small])
        parsed = json.loads(result)

        # Both elements should be dropped; only the marker remains.
        assert len(parsed) == 1
        assert "_truncated" in parsed[0]
        assert "2 item(s) omitted" in parsed[0]["_truncated"]
