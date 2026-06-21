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


# -- _converse (LLM pipeline) ------------------------------------------------


class TestConverse:
    """Test BoardManager._converse — mock the provider to isolate."""

    @pytest.fixture
    def mock_provider(self) -> MagicMock:
        """Return a mock provider with build_agent returning fresh mocks."""
        provider = MagicMock()
        provider.build_agent.return_value = MagicMock()
        return provider

    @pytest.fixture
    def mock_get_provider(self, mock_provider: MagicMock) -> MagicMock:
        """Patch get_provider_for_identifier to return *mock_provider*.

        Patched in ``core.factory`` so the test stays hermetic — the concrete
        provider is never imported."""
        with patch(
            "robotsix_llmio.core.factory.get_provider_for_identifier",
            return_value=mock_provider,
        ) as gp:
            yield gp

    @pytest.fixture
    def mock_run_agent(self) -> MagicMock:
        """Patch run_agent to return canned output for each call."""
        with patch("robotsix_llmio.core.run.run_agent") as ra:
            yield ra

    # -- history absent -------------------------------------------------

    def test_no_history_skips_recall(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When memory is empty, no recall agent is built or run."""
        mock_run_agent.return_value = "final answer"

        result = manager._converse("some question")

        assert result == "final answer"
        # Only one build_agent call (the level-3 manager), not two.
        assert mock_provider.build_agent.call_count == 1
        call_kwargs = mock_provider.build_agent.call_args.kwargs
        assert call_kwargs["level"] == 3
        assert call_kwargs["name"] == "board-manager"

    def test_no_history_omits_relevant_from_system(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When memory is empty, the system prompt has no 'Relevant prior'."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "Relevant prior exchanges" not in system

    # -- history present -------------------------------------------------

    def test_history_present_builds_and_runs_recall(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When memory has entries, a level-1 recall agent is built and run."""
        manager._memory.append("prior Q", "prior A")
        # Return distinct values for recall and manager runs.
        mock_run_agent.side_effect = ["relevant context", "manager answer"]

        result = manager._converse("new question")

        assert result == "manager answer"
        assert mock_provider.build_agent.call_count == 2
        # First call: recall agent.
        recall_kwargs = mock_provider.build_agent.call_args_list[0].kwargs
        assert recall_kwargs["level"] == 1
        assert recall_kwargs["name"] == "board-manager-recall"
        assert recall_kwargs["model"] is None  # recall_model not set
        assert recall_kwargs["output_type"] is str
        # Second call: manager agent.
        mgr_kwargs = mock_provider.build_agent.call_args_list[1].kwargs
        assert mgr_kwargs["level"] == 3

    def test_recall_output_in_system_prompt(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The recall output text appears in the manager's system prompt."""
        manager._memory.append("q1", "a1")
        mock_run_agent.side_effect = ["remembered context", "final"]

        manager._converse("q2")

        system = mock_provider.build_agent.call_args_list[1].kwargs["system_prompt"]
        assert "remembered context" in system
        assert "Relevant prior exchanges:" in system

    def test_recall_none_output_omitted_from_system(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When recall returns 'none', 'Relevant prior' NOT in system prompt."""
        manager._memory.append("q", "a")
        mock_run_agent.side_effect = ["none", "ok"]

        manager._converse("q2")

        system = mock_provider.build_agent.call_args_list[1].kwargs["system_prompt"]
        assert "Relevant prior exchanges" not in system

    # -- notes present / absent ------------------------------------------

    def test_notes_present_in_system_prompt(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When load_notes() returns content, it appears in the system prompt."""
        manager._memory.save_notes("Task 1 is ongoing.")
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "Your maintained memory:" in system
        assert "Task 1 is ongoing." in system

    def test_notes_absent_omitted_from_system(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When load_notes() returns '', no memory section in system prompt."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "Your maintained memory:" not in system

    # -- recall_model ----------------------------------------------------

    def test_recall_model_override(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _recall_model is set, it is passed to build_agent for recall."""
        manager._recall_model = "custom-recall-model"
        manager._memory.append("q", "a")
        mock_run_agent.side_effect = ["ctx", "ans"]

        manager._converse("q2")

        recall_kwargs = mock_provider.build_agent.call_args_list[0].kwargs
        assert recall_kwargs["model"] == "custom-recall-model"

    def test_recall_model_unset_passes_none(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _recall_model is None, None is passed to build_agent."""
        manager._recall_model = None
        manager._memory.append("q", "a")
        mock_run_agent.side_effect = ["ctx", "ans"]

        manager._converse("q2")

        recall_kwargs = mock_provider.build_agent.call_args_list[0].kwargs
        assert recall_kwargs["model"] is None

    # -- system prompt structure -----------------------------------------

    def test_system_prompt_includes_repo_id(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The manager system prompt includes the board repo id."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "test-repo" in system

    def test_system_prompt_includes_requester(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The system prompt names the requester."""
        mock_run_agent.return_value = "ok"

        manager._converse("q", requester="alice")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "requester is 'alice'" in system

    # -- manager model ---------------------------------------------------

    def test_manager_model_uses_configured_value(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _manager_model is set, it is used for the level-3 agent."""
        manager._manager_model = "custom-manager-model"
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        mgr_kwargs = mock_provider.build_agent.call_args.kwargs
        assert mgr_kwargs["model"] == "custom-manager-model"

    def test_manager_model_defaults_when_unset(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _manager_model is None, the default model is used."""
        manager._manager_model = None
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        mgr_kwargs = mock_provider.build_agent.call_args.kwargs
        from robotsix_board_agent.board_manager import _DEFAULT_MANAGER_MODEL

        assert mgr_kwargs["model"] == _DEFAULT_MANAGER_MODEL

    # -- error path ------------------------------------------------------

    def test_provider_raises_propagates(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When the provider raises, the exception propagates (no catch in _converse)."""
        mock_run_agent.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError, match="provider down"):
            manager._converse("q")

    # -- tool assembly ---------------------------------------------------

    def test_tools_are_built_for_level3_agent(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The level-3 agent is built with tools from _build_tools."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        mgr_kwargs = mock_provider.build_agent.call_args.kwargs
        assert "tools" in mgr_kwargs
        assert mgr_kwargs["tools"] is not None

    def test_provider_constructed_without_api_key(
        self,
        manager: BoardManager,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The ClaudeSDK provider is constructed without an api_key (uses claude login)."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        mock_get_provider.assert_called_once()
        _, kwargs = mock_get_provider.call_args
        assert "api_key" not in kwargs

    # -- prompt id-handling guidance ---------------------------------------

    def test_system_prompt_includes_id_handling_guidance(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The system prompt contains explicit ticket id handling instructions."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "TICKET ID HANDLING" in system
        assert "opaque strings" in system
        assert "complete id" in system.lower() or "complete id" in system
        assert "verbatim" in system

    def test_system_prompt_warns_against_truncating_to_timestamp(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The system prompt warns never to truncate an id to its timestamp."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "never truncate" in system.lower()

    def test_system_prompt_includes_anti_duplicate_404_guard(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The system prompt includes the 404 anti-duplicate guard."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "ANTI-DUPLICATE GUARD" in system
        assert "do NOT re-create" in system
        assert "404" in system

    def test_system_prompt_example_id_is_not_truncated(
        self,
        manager: BoardManager,
        mock_provider: MagicMock,
        mock_get_provider: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The example id in the prompt is a full timestamp-slug-suffix string."""
        mock_run_agent.return_value = "ok"

        manager._converse("q")

        system = mock_provider.build_agent.call_args.kwargs["system_prompt"]
        assert "20260621T182023Z-add-automatic-conversation-restart-after-4cb7" in system


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
