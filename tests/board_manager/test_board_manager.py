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

    An autouse fixture patches ``_select_manager_model`` to return ``None`` so
    the existing tests' call-count and ordering assertions remain valid without
    the new classifier step interfering.  Classification behaviour is tested
    separately in ``TestSelectManagerModel``.
    """

    @pytest.fixture(autouse=True)
    def _patch_select_model(self, manager: BoardManager) -> None:
        """Patch _select_manager_model to return None — keep existing assertions valid."""
        with patch.object(manager, "_select_manager_model", return_value=None):
            yield

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
        """When _manager_model is set, _select_manager_model returns it and the
        manager build receives that model (operator override)."""
        manager._manager_model = "custom-manager-model"
        mock_run_agent.return_value = "ok"

        # Override the autouse patch: simulate the real _select_manager_model
        # returning the configured manager_model.
        with patch.object(manager, "_select_manager_model", return_value="custom-manager-model"):
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


# -- _select_manager_model (complexity classifier) ---------------------------


class TestSelectManagerModel:
    """Test BoardManager._select_manager_model and its integration in _converse.

    These tests do NOT patch ``_select_manager_model`` — they exercise the
    real method and verify that the classifier routes requests to the correct
    model (or falls back to Opus on failure/override).
    """

    @pytest.fixture
    def mock_build_agent(self) -> MagicMock:
        """Patch build_agent_for_level to return fresh agent mocks per call."""
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

    # -- SIMPLE -> sonnet --------------------------------------------------

    def test_simple_classification_routes_to_sonnet(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When the classifier returns SIMPLE, the manager build gets model='sonnet'."""
        mock_run_agent.side_effect = ["SIMPLE", "manager answer"]

        result = manager._converse("what is on the board?")

        assert result == "manager answer"
        # Two build_agent_for_level calls: classifier (level-1) + manager (level-3).
        assert mock_build_agent.call_count == 2

        # Classifier call.
        classify_call = mock_build_agent.call_args_list[0]
        assert classify_call.args[0] == 1
        assert classify_call.kwargs["name"] == "board-manager-classify"
        assert classify_call.kwargs["output_type"] is str

        # Manager call — must receive model="sonnet", not None/Opus.
        mgr_call = mock_build_agent.call_args_list[1]
        assert mgr_call.args[0] == 3
        assert mgr_call.kwargs["name"] == "board-manager"
        assert mgr_call.kwargs["model"] == "sonnet"

    # -- COMPLEX -> None (Opus) --------------------------------------------

    def test_complex_classification_routes_to_opus(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When the classifier returns COMPLEX, the manager build gets model=None (Opus)."""
        mock_run_agent.side_effect = ["COMPLEX", "manager answer"]

        result = manager._converse("create a ticket for the login bug")

        assert result == "manager answer"
        assert mock_build_agent.call_count == 2

        mgr_call = mock_build_agent.call_args_list[1]
        assert mgr_call.args[0] == 3
        assert mgr_call.kwargs["model"] is None

    # -- unrecognized / empty -> None (Opus) -------------------------------

    def test_unrecognized_classifier_output_routes_to_opus(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When the classifier returns something unrecognized, fall back to Opus."""
        mock_run_agent.side_effect = ["something weird", "manager answer"]

        result = manager._converse("vague request")

        assert result == "manager answer"
        mgr_call = mock_build_agent.call_args_list[1]
        assert mgr_call.kwargs["model"] is None

    def test_empty_classifier_output_routes_to_opus(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When the classifier returns an empty string, fall back to Opus."""
        mock_run_agent.side_effect = ["", "manager answer"]

        result = manager._converse("what's up")

        assert result == "manager answer"
        mgr_call = mock_build_agent.call_args_list[1]
        assert mgr_call.kwargs["model"] is None

    # -- operator override wins (no classifier call) -----------------------

    def test_operator_override_skips_classifier(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _manager_model is explicitly set, the classifier is NOT called
        and the override is passed verbatim to the manager build."""
        manager._manager_model = "custom-manager-model"
        mock_run_agent.return_value = "manager answer"

        result = manager._converse("do something complex")

        assert result == "manager answer"
        # Only one build_agent_for_level call: the manager (no classifier).
        assert mock_build_agent.call_count == 1
        mgr_call = mock_build_agent.call_args_list[0]
        assert mgr_call.args[0] == 3
        assert mgr_call.kwargs["model"] == "custom-manager-model"

    # -- classifier built at level-1 with correct name ---------------------

    def test_classifier_built_at_level1_with_correct_name(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """The classifier agent is built at level-1 with name='board-manager-classify'."""
        mock_run_agent.side_effect = ["SIMPLE", "ok"]

        manager._converse("board status")

        classify_call = mock_build_agent.call_args_list[0]
        assert classify_call.args[0] == 1
        assert classify_call.kwargs["name"] == "board-manager-classify"
        assert classify_call.kwargs["output_type"] is str
        # Level-1 means the cheap (non-Claude) provider is used.
        # model is None → level-1 default (DeepSeek-flash).
        assert classify_call.kwargs["model"] is None

    # -- classifier exception falls back to Opus ---------------------------

    def test_classifier_exception_falls_back_to_opus(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When the classifier raises, _converse still completes and the manager
        gets model=None (Opus)."""
        # Side effect: first run_agent call (classifier) raises; second
        # (manager) succeeds.
        mock_run_agent.side_effect = [
            RuntimeError("classification failed"),
            "manager answer",
        ]

        result = manager._converse("some request")

        assert result == "manager answer"
        # Classifier built but its run_agent raised → manager still built.
        assert mock_build_agent.call_count == 2
        mgr_call = mock_build_agent.call_args_list[1]
        assert mgr_call.args[0] == 3
        assert mgr_call.kwargs["model"] is None

    # -- classify_model override -------------------------------------------

    def test_classify_model_passed_to_classifier(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _classify_model is set, it is passed to the classifier build."""
        manager._classify_model = "custom-classify-model"
        mock_run_agent.side_effect = ["SIMPLE", "ok"]

        manager._converse("board status")

        classify_call = mock_build_agent.call_args_list[0]
        assert classify_call.kwargs["model"] == "custom-classify-model"

    def test_classify_model_unset_passes_none(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When _classify_model is None, model=None is passed (level-1 default)."""
        manager._classify_model = None
        mock_run_agent.side_effect = ["SIMPLE", "ok"]

        manager._converse("board status")

        classify_call = mock_build_agent.call_args_list[0]
        assert classify_call.kwargs["model"] is None

    # -- simple_read_model override ----------------------------------------

    def test_simple_read_model_default_is_sonnet(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """Default _simple_read_model is 'sonnet'."""
        assert manager._simple_read_model == "sonnet"

    def test_simple_read_model_override_haiku(
        self,
        tmp_path: Path,
        settings: BoardAgentSettings,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When simple_read_model='haiku' is passed, SIMPLE requests use it."""
        mgr = BoardManager(
            settings,
            broker_host="test-broker.robotsix.net",
            broker_token="test-broker-token",
            memory_path=tmp_path / "memory",
            simple_read_model="haiku",
        )
        mock_run_agent.side_effect = ["SIMPLE", "ok"]

        mgr._converse("board status")

        mgr_call = mock_build_agent.call_args_list[1]
        assert mgr_call.kwargs["model"] == "haiku"

    # -- SIMPLE with whitespace is still recognized ------------------------

    def test_simple_with_whitespace_still_recognized(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """Classifier output '  SIMPLE  ' (with surrounding whitespace) routes to sonnet."""
        mock_run_agent.side_effect = ["  SIMPLE  ", "ok"]

        manager._converse("what tickets are open?")

        mgr_call = mock_build_agent.call_args_list[1]
        assert mgr_call.kwargs["model"] == "sonnet"

    # -- SIMPLE with history present (recall, classify, manager all run) ---

    def test_simple_with_history_all_three_passes(
        self,
        manager: BoardManager,
        mock_build_agent: MagicMock,
        mock_run_agent: MagicMock,
    ) -> None:
        """When history is present and classifier says SIMPLE, all three passes
        run: recall (level-1), classifier (level-1), manager (level-3) with sonnet."""
        manager._memory.append("prior Q", "prior A")
        # Side effect order: recall, classifier, manager.
        mock_run_agent.side_effect = ["relevant ctx", "SIMPLE", "manager answer"]

        result = manager._converse("what is on the board?")

        assert result == "manager answer"
        assert mock_build_agent.call_count == 3

        # Recall.
        recall_call = mock_build_agent.call_args_list[0]
        assert recall_call.args[0] == 1
        assert recall_call.kwargs["name"] == "board-manager-recall"

        # Classifier.
        classify_call = mock_build_agent.call_args_list[1]
        assert classify_call.args[0] == 1
        assert classify_call.kwargs["name"] == "board-manager-classify"

        # Manager (with sonnet).
        mgr_call = mock_build_agent.call_args_list[2]
        assert mgr_call.args[0] == 3
        assert mgr_call.kwargs["name"] == "board-manager"
        assert mgr_call.kwargs["model"] == "sonnet"


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

    def test_returns_exactly_17_callables(self, manager: BoardManager) -> None:
        tools = manager._build_tools("test-requester")
        assert len(tools) == 17
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
            "lookup_reference",
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
        manager._memory.save_notes = MagicMock(return_value="maintained memory updated")

        tools = manager._build_tools("test-requester")
        update_memory = next(t for t in tools if t.__name__ == "update_memory")

        result = update_memory("new notes")

        manager._memory.save_notes.assert_called_once_with("new notes")
        assert result == "maintained memory updated"

    def test_update_memory_reports_truncation(self, manager: BoardManager) -> None:
        """When save_notes truncates, update_memory returns the truncation notice."""
        manager._memory.save_notes = MagicMock(
            return_value="maintained memory updated (truncated to 2000 chars — trim stale entries)"
        )

        tools = manager._build_tools("test-requester")
        update_memory = next(t for t in tools if t.__name__ == "update_memory")

        result = update_memory("x" * 5000)

        assert "truncated" in result
        assert "2000" in result

    # -- lookup_reference ---------------------------------------------------

    def test_lookup_reference_delegates_to_search_reference(self, manager: BoardManager) -> None:
        manager._memory.search_reference = MagicMock(
            return_value="## State Machine\n- open → in_progress → review → done"
        )

        tools = manager._build_tools("test-requester")
        lookup_ref = next(t for t in tools if t.__name__ == "lookup_reference")

        result = lookup_ref("state machine transitions")

        manager._memory.search_reference.assert_called_once_with("state machine transitions")
        assert "## State Machine" in result

    def test_lookup_reference_no_match_returns_notice(self, manager: BoardManager) -> None:
        manager._memory.search_reference = MagicMock(
            return_value="(no reference material matches query: 'nonexistent')"
        )

        tools = manager._build_tools("test-requester")
        lookup_ref = next(t for t in tools if t.__name__ == "lookup_reference")

        result = lookup_ref("nonexistent")
        assert "no reference material" in result.lower()

    # -- mark_done triggers prune -------------------------------------------

    def test_mark_done_prunes_closed_ticket_from_notes(self, manager: BoardManager) -> None:
        """When mark_done succeeds, the closed ticket's memory entries are pruned."""
        manager._run = MagicMock(return_value={"ok": True})
        manager._memory.prune_closed_ticket = MagicMock()
        manager.client.mark_done = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        mark_done = next(t for t in tools if t.__name__ == "mark_done")

        result = mark_done("20260625T214218Z-prune-memory-a505")

        manager._memory.prune_closed_ticket.assert_called_once_with(
            "20260625T214218Z-prune-memory-a505"
        )
        # The tool still returns the API result.
        assert "ok" in result

    def test_mark_done_prunes_even_on_api_error(self, manager: BoardManager) -> None:
        """mark_done prunes the ticket from notes even if the API call fails."""
        error = BoardAPIError(404, "ticket not found")
        manager._run = MagicMock(side_effect=error)
        manager._memory.prune_closed_ticket = MagicMock()
        manager.client.mark_done = MagicMock(return_value=MagicMock())

        tools = manager._build_tools("test-requester")
        mark_done = next(t for t in tools if t.__name__ == "mark_done")

        result = mark_done("non-existent-id")

        # prune happens regardless of API outcome
        manager._memory.prune_closed_ticket.assert_called_once_with("non-existent-id")
        assert "board API error 404" in result

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

    def test_read_only_returns_8_tools(self, read_only_manager: BoardManager) -> None:
        tools = read_only_manager._build_tools("test-requester")
        assert len(tools) == 8
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
            "lookup_reference",
        }
        assert names == expected

    def test_read_only_excludes_all_write_ops(self, read_only_manager: BoardManager) -> None:
        from robotsix_board_agent.ops import WRITE_OPS

        tools = read_only_manager._build_tools("test-requester")
        names = {t.__name__ for t in tools}
        assert names.isdisjoint(WRITE_OPS)

    def test_read_write_returns_full_17(self, manager: BoardManager) -> None:
        """When enable_write_ops=True (default fixture), still 17 tools."""
        tools = manager._build_tools("test-requester")
        assert len(tools) == 17

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

    def test_truncate_result_returns_non_list_unchanged(self) -> None:
        """A non-list result (e.g. a plain string) is returned as-is with no
        truncation, even when longer than _RESULT_CAP."""
        from robotsix_board_agent.board_manager import _RESULT_CAP, _truncate_result

        long_string = "x" * (_RESULT_CAP + 100)
        result = _truncate_result(long_string)

        # Non-list results bypass truncation — full string returned unchanged.
        assert result == json.dumps(long_string)
        assert len(result) > _RESULT_CAP


# -- _truncate_list -----------------------------------------------------------


class TestTruncateList:
    """Direct unit tests for _truncate_list()."""

    def test_empty_list_returns_empty_and_zero(self) -> None:
        from robotsix_board_agent.board_manager import _truncate_list

        result, omitted = _truncate_list([], 1000)
        assert result == []
        assert omitted == 0

    def test_list_under_cap_returned_whole(self) -> None:
        from robotsix_board_agent.board_manager import _truncate_list

        items = [{"id": "a"}, {"id": "b"}]
        result, omitted = _truncate_list(items, 10000)
        assert result == items
        assert omitted == 0

    def test_list_over_cap_drops_trailing_and_counts_omitted(self) -> None:
        from robotsix_board_agent.board_manager import _truncate_list

        items = [{"data": "x" * 100} for _ in range(50)]
        cap = 500
        assert len(json.dumps(items)) > cap, "precondition: list must exceed cap"

        result, omitted = _truncate_list(items, cap)
        assert len(result) < len(items)
        assert omitted == len(items) - len(result)
        assert len(json.dumps(result)) <= cap

    def test_fallback_pop_when_marker_overflows_cap(self) -> None:
        from robotsix_board_agent.board_manager import _truncate_list

        # After the while loop one element remains, but element + omission
        # marker still exceeds cap → fallback pop drops the last element.
        cap = 100
        big = {"data": "x" * 80}  # ~92 bytes, fits alone
        small = {"y": "z"}  # ~10 bytes
        items = [big, small]
        assert len(json.dumps(items)) > cap, "precondition: full list exceeds cap"

        result, omitted = _truncate_list(items, cap)
        # Both elements dropped: small popped in while loop,
        # big popped in fallback.
        assert result == []
        assert omitted == 2

    def test_exactly_at_cap_no_truncation(self) -> None:
        from robotsix_board_agent.board_manager import _truncate_list

        items = [{"id": "a"}, {"id": "b"}]
        cap = len(json.dumps(items))
        result, omitted = _truncate_list(items, cap)
        assert result == items
        assert omitted == 0

    def test_marker_accounts_for_all_omitted(self) -> None:
        from robotsix_board_agent.board_manager import _truncate_list

        items = [{"data": "x" * 100} for _ in range(20)]
        cap = 400
        assert len(json.dumps(items)) > cap, "precondition: list must exceed cap"

        result, omitted = _truncate_list(items, cap)
        # Omitted count matches the actual number of dropped elements.
        assert omitted == len(items) - len(result)
        assert omitted > 0
        assert len(json.dumps(result)) <= cap


# -- fast read path tests ----------------------------------------------------


class TestFastReadTicket:
    """Tests for BoardManager._fast_read_ticket — serving ticket status
    directly from the board API without an LLM hop."""

    TICKET_ID = "20260621T182023Z-my-ticket-a1b2"

    @staticmethod
    def _ticket_data(**overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            "state": "in_progress",
            "branch": "feat/cool",
            "pr_url": "https://github.com/org/repo/pull/42",
            "pending_question": None,
            "errors": None,
        }
        data.update(overrides)  # type: ignore[arg-type]
        return data

    # -- fast path accepted --------------------------------------------------

    def test_simple_read_returns_structured_status(self, manager: BoardManager) -> None:
        """A simple "read ticket X" query returns structured status without LLM."""
        data = self._ticket_data()
        manager._run = MagicMock(return_value=data)

        result = manager._fast_read_ticket(f"Read the live state of ticket {self.TICKET_ID}")

        assert result is not None
        assert self.TICKET_ID in result
        assert "state: in_progress" in result
        assert "branch: feat/cool" in result
        assert "pr_url: https://github.com/org/repo/pull/42" in result
        # Not from cache on first call.
        assert "(served from cache)" not in result
        # _run was called exactly once with the get_ticket coroutine.
        manager._run.assert_called_once()

    def test_simple_read_omits_none_fields(self, manager: BoardManager) -> None:
        """Optional None fields are omitted from the status summary."""
        data = {"state": "open", "branch": None, "pr_url": None}
        manager._run = MagicMock(return_value=data)

        result = manager._fast_read_ticket(f"status of {self.TICKET_ID}")

        assert result is not None
        assert "branch:" not in result
        assert "pr_url:" not in result

    def test_read_with_pending_question_and_errors(self, manager: BoardManager) -> None:
        """pending_question and errors are included when present."""
        data = self._ticket_data(
            pending_question="approve this?",
            errors=[{"code": "lint-fail", "message": "flake8"}],
        )
        manager._run = MagicMock(return_value=data)

        result = manager._fast_read_ticket(f"what's up with {self.TICKET_ID}")

        assert result is not None
        assert "pending_question: approve this?" in result
        assert "errors:" in result

    # -- cache ---------------------------------------------------------------

    def test_cache_hit_avoids_api_call(self, manager: BoardManager) -> None:
        """Second identical read is served from cache, no API call."""
        data = self._ticket_data()
        manager._run = MagicMock(return_value=data)

        # First call — hits the API.
        r1 = manager._fast_read_ticket(f"status of {self.TICKET_ID}")
        assert r1 is not None
        assert "(served from cache)" not in r1
        assert manager._run.call_count == 1

        # Second call — cache hit, no additional API call.
        r2 = manager._fast_read_ticket(f"status of {self.TICKET_ID}")
        assert r2 is not None
        assert "(served from cache)" in r2
        assert manager._run.call_count == 1  # still only one

    def test_cache_hit_different_wording(self, manager: BoardManager) -> None:
        """Cache key is the ticket id, not the question phrasing."""
        data = self._ticket_data()
        manager._run = MagicMock(return_value=data)

        manager._fast_read_ticket(f"read {self.TICKET_ID}")
        assert manager._run.call_count == 1

        # Different wording, same ticket id → cache hit.
        r2 = manager._fast_read_ticket(f"get status for {self.TICKET_ID} please")
        assert r2 is not None
        assert "(served from cache)" in r2
        assert manager._run.call_count == 1

    def test_cache_expiry_re_fetches(self, manager: BoardManager) -> None:
        """After TTL, cache misses and the API is called again."""
        from robotsix_board_agent.board_manager import _TicketCache

        # Replace cache with a zero-TTL instance.
        manager._ticket_cache = _TicketCache(ttl=0.0)

        data1 = self._ticket_data(state="open")
        data2 = self._ticket_data(state="done")
        manager._run = MagicMock(side_effect=[data1, data2])

        r1 = manager._fast_read_ticket(f"read {self.TICKET_ID}")
        assert "state: open" in (r1 or "")
        assert manager._run.call_count == 1

        # TTL is 0, so this re-fetches.
        r2 = manager._fast_read_ticket(f"read {self.TICKET_ID}")
        assert "state: done" in (r2 or "")
        assert manager._run.call_count == 2

    # -- fast path skipped ---------------------------------------------------

    def test_write_intent_skips_fast_path(self, manager: BoardManager) -> None:
        """A question with write-intent keywords returns None (fall through to LLM)."""
        manager._run = MagicMock()

        result = manager._fast_read_ticket(f"please transition {self.TICKET_ID} to done")
        assert result is None
        manager._run.assert_not_called()

    def test_no_ticket_id_skips_fast_path(self, manager: BoardManager) -> None:
        """A question without a ticket id returns None."""
        manager._run = MagicMock()

        result = manager._fast_read_ticket("what tickets are open?")
        assert result is None
        manager._run.assert_not_called()

    def test_multiple_ticket_ids_skips_fast_path(self, manager: BoardManager) -> None:
        """A question mentioning multiple ticket ids returns None."""
        manager._run = MagicMock()

        result = manager._fast_read_ticket(
            f"compare {self.TICKET_ID} and 20260621T182023Z-other-one-b3c4"
        )
        assert result is None
        manager._run.assert_not_called()

    # -- API error fallback --------------------------------------------------

    def test_api_error_falls_back_to_llm(self, manager: BoardManager) -> None:
        """When the board API returns an error, the fast path returns None."""
        manager._run = MagicMock(side_effect=BoardAPIError(404, "not found"))

        result = manager._fast_read_ticket(f"read {self.TICKET_ID}")
        assert result is None
        manager._run.assert_called_once()

    # -- integration with _handle_request ------------------------------------

    def test_handle_request_uses_fast_path(self, manager: BoardManager) -> None:
        """_handle_request returns the fast-path result without calling _converse."""
        from tests.conftest import Request

        data = self._ticket_data()
        manager._run = MagicMock(return_value=data)

        with patch.object(manager, "_converse") as mock_conv:
            reply = manager._handle_request(Request(body={"message": f"read {self.TICKET_ID}"}))

        mock_conv.assert_not_called()
        assert reply.error is None
        assert reply.result is not None
        assert self.TICKET_ID in reply.result["reply"]
        assert "state: in_progress" in reply.result["reply"]

    def test_handle_request_falls_back_to_converse(self, manager: BoardManager) -> None:
        """When fast path returns None, _handle_request calls _converse."""
        from tests.conftest import Request

        with patch.object(manager, "_converse", return_value="LLM response") as mock_conv:
            reply = manager._handle_request(
                Request(body={"message": "create a ticket for the login bug"})
            )

        mock_conv.assert_called_once()
        assert reply.result == {"reply": "LLM response"}
