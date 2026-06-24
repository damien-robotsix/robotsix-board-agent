"""LLM board manager — natural-language management of the board over the broker.

Unlike :class:`~robotsix_board_agent.brokered.BrokeredBoardResponder` (a dumb
structured-op gateway), the manager is an llmio **level-3** agent that takes a
natural-language message, recalls relevant prior context via a cheap **level-1**
pass over its conversation memory, and acts directly on the board through the
real :class:`BoardClient` ops exposed as tools. It registers on the central
broker (pull/mailbox) so it can be reached from anywhere, NAT-safe.

The two passes run on their OWN provider via llmio's per-level defaults
(``build_agent_for_level``): the **recall** pass is level-1 (DeepSeek-flash over
OpenRouter — cheap), and the **manager** pass is level-3 (Claude opus over the
Claude-SDK — strongest reasoning). Each level resolves its own transport, so the
recall model is never forced through the Claude transport (which would 400 with
"model may not exist"). An optional ``model=`` override changes only the bare
model name; the level's provider stays fixed.

Memory keeps only question→answer pairs (see :mod:`.memory`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from robotsix_agent_comm.protocol import Error, Message, Request, Response

from ._imports import _setup_langfuse_tracing
from ._lifecycle import _build_brokered_agent, _ThreadedLoopMixin
from .client import BoardAPIError, BoardClient
from .config import BoardAgentSettings
from .constants import DEFAULT_TICKET_SOURCE, BoardErrorCode
from .memory import MAX_CONVERSATIONS, BoardManagerMemory
from .ops import WRITE_OPS

_setup_langfuse_tracing()

logger = logging.getLogger(__name__)

#: Cap a tool result handed back to the LLM (tickets lists can be large).
_RESULT_CAP = 12_000


def _truncate_list(items: list[Any], cap: int) -> tuple[list[Any], int]:
    """Return a truncated copy of *items* that fits under *cap* (JSON-serialised)
    together with the count of dropped elements.

    The input list is **not** mutated — the caller receives a new list.
    """
    result = list(items)
    original_len = len(result)

    # Drop trailing elements until the serialised payload fits.
    while result and len(json.dumps(result)) > cap:
        result.pop()

    omitted = original_len - len(result)
    if omitted == 0:
        return result, 0

    # Make room for the omission marker.  When even a single element plus the
    # marker still overflows the cap the last element is also dropped (the
    # fallback pop) and the omission count is updated accordingly.
    marker: dict[str, str] = {"_truncated": f"{omitted} item(s) omitted (result cap)"}
    if result and len(json.dumps([*result, marker])) > cap:
        result.pop()
        omitted = original_len - len(result)

    return result, omitted


def _truncate_result(result: Any) -> str:
    """Serialize *result* to JSON, truncating lists that exceed :data:`_RESULT_CAP`.

    Trailing elements are dropped whole (never sliced mid-field) and an
    ``{"_truncated": "…"}`` omission marker is appended.  When even a single
    element plus the marker still overflows the cap the last element is also
    dropped (the fallback pop) and the marker's count is updated accordingly.

    Returns the (possibly truncated) JSON string.
    """
    serialised = json.dumps(result)
    if len(serialised) <= _RESULT_CAP or not isinstance(result, list):
        return serialised

    truncated, omitted = _truncate_list(result, _RESULT_CAP)
    if omitted > 0:
        marker: dict[str, str] = {"_truncated": f"{omitted} item(s) omitted (result cap)"}
        truncated.append(marker)
    return json.dumps(truncated)


_RECALL_SYSTEM = (
    "You retrieve relevant context for a board-management assistant. Given a NEW "
    "user question and a log of PRIOR question→answer exchanges, produce 2-3 "
    "terse factual outcome summaries of the prior exchanges that are genuinely "
    "relevant to the new question (decisions made, tickets created/modified, "
    "results delivered). Summarise — do NOT quote verbatim transcripts. "
    "If nothing is relevant, reply with the single word NONE and nothing else."
)

_MANAGER_SYSTEM = (
    "You are the manager of the kanban board for the repository {repo}. You act "
    "on the user's natural-language instructions by reading and modifying the "
    "board through your tools (list/get tickets, board cards, create, comment, "
    "transition, approve, mark done, merge, migrate, resume, set priority). Act directly "
    "— the user has authorized you to make changes. Prefer reading first when a "
    "request is ambiguous about which ticket(s) it targets. When you transition "
    "a ticket, use a valid board state.\n\n"
    "DEDUPLICATE before creating: whenever you are about to create a ticket, first "
    "list the existing tickets and check whether an open one already covers the "
    "same issue. If a near-duplicate exists, do NOT create another — add a comment "
    "to (or update) the existing ticket instead, and tell the user which one. Only "
    "create a new ticket when none matches.\n\n"
    "TICKET ID HANDLING: Ticket ids are opaque strings of the form "
    "<timestamp>-<slug>-<suffix> (e.g. "
    "'20260621T182023Z-add-automatic-conversation-restart-after-4cb7'). ALWAYS "
    "use the complete id string exactly as it appeared in a tool result — never "
    "truncate an id to its leading timestamp, never reconstruct or derive an id "
    "from a timestamp, and never shorten it. When acting on a ticket from "
    "board_cards or list_tickets, copy its 'id' field verbatim. After "
    "create_ticket, use the 'id' field from the returned record verbatim for any "
    "follow-up operation.\n\n"
    "MISSING/INCOMPLETE ID FALLBACK: when a user provides only a partial ticket id "
    '(a bare slug suffix like "-dc29" or a bare timestamp) and get_ticket '
    "returns 404, do NOT scan the whole board with board_cards to find it — "
    "board_cards is expensive and its output may be truncated. Instead, use "
    "list_tickets with a state filter when you can narrow the search, or tell the "
    "user you need the full id and ask them to provide it.\n\n"
    "ANTI-DUPLICATE GUARD: if a single-ticket operation (get_ticket, transition, "
    "migrate, comment, mark_done) returns a 404 ('board API error 404') right "
    "after you created a ticket, do NOT re-create the ticket — a 404 there "
    "means an id was passed incorrectly, not that the ticket is missing. Re-read "
    "the create response and retry with the full id. Do NOT call board_cards to "
    "find the ticket — board_cards returns the entire board and wastes tokens.\n\n"
    "REPORT FORMAT: Keep your final reply concise and tell the user exactly "
    "what you did (ids + outcomes) or answer their question. When summarising "
    "code changes or analysis findings, use descriptive paragraph summaries "
    "naming files and functions — do NOT include exhaustive file:line "
    "references (e.g. 'core/states.py lines 54/89/258/276') unless the user "
    "explicitly asked for them. Omit line numbers by default; describe what "
    "changed and where at the file/function level.\n\n"
    "You keep a MAINTAINED MEMORY — a bare-bones, current-state note of active "
    "board status, open decisions, and user preferences (NOT a transcript or "
    "log). It is shown to you below each turn. Strip stale or resolved items "
    "aggressively; when calling update_memory, pass only what is still relevant "
    "right now — rewrite/trim rather than letting it grow."
)

_CLASSIFY_SYSTEM = (
    "You classify incoming user requests for a board-management assistant. "
    "Reply with a single token — SIMPLE or COMPLEX — and nothing else.\n\n"
    "SIMPLE: the request is a straightforward read-only board status query or "
    "summary. It asks for current board state, ticket listings, ticket details, "
    "or a concise summary of what is on the board. It needs NO board modification "
    "and NO multi-step reasoning.\n\n"
    "COMPLEX: the request involves any board modification (create, transition, "
    "comment, approve, mark done, migrate, merge, set priority, resume), requires "
    "multi-step reasoning, or is ambiguous about intent.\n\n"
    "When in doubt, reply COMPLEX."
)


class BoardManager(_ThreadedLoopMixin):
    """Conversational, tool-using manager for a single board over the broker."""

    def __init__(
        self,
        settings: BoardAgentSettings,
        *,
        broker_host: str,
        broker_token: str,
        memory_path: Path,
        broker_port: int = 443,
        broker_scheme: str = "https",
        agent_id: str | None = None,
        manager_model: str | None = None,
        recall_model: str | None = None,
        simple_read_model: str = "sonnet",
        classify_model: str | None = None,
        max_conversations: int = MAX_CONVERSATIONS,
        timeout: float = 120.0,
    ) -> None:
        """Initialise the board manager.

        *settings* — the board configuration (repo id, board URL, auth token,
        and ``enable_write_ops`` which gates whether board-mutating tools are
        exposed).
        *broker_host*/*broker_port*/*broker_scheme*/*broker_token* — broker
        connection details for the agent-comm layer.  *memory_path* — filesystem path for persisting
        conversation traces and the maintained memory note.  *agent_id* — custom
        broker agent id (defaults to ``board-manager-{repo_id}``).
        *manager_model*/*recall_model* — optional model overrides for the primary
        manager LLM and the lower-tier recall scanner.
        *simple_read_model* — bare Claude alias (``"sonnet"``, ``"haiku"``) used
        for requests the complexity classifier deems SIMPLE; default ``"sonnet"``.
        *classify_model* — optional bare model override for the level-1
        classifier (defaults to level-1's DeepSeek-flash).  *max_conversations* —
        cap on stored conversation pairs.  *timeout* — broker operation timeout
        in seconds.
        """
        self.settings = settings
        self.client = BoardClient(settings)
        self.agent_id = agent_id or f"board-manager-{settings.board_repo_id}"
        self._manager_model = manager_model
        self._recall_model = recall_model
        self._simple_read_model = simple_read_model
        self._classify_model = classify_model
        self._memory = BoardManagerMemory(memory_path, max_conversations=max_conversations)
        self._agent = _build_brokered_agent(
            self.agent_id,
            broker_host=broker_host,
            broker_port=broker_port,
            broker_scheme=broker_scheme,
            broker_token=broker_token,
            timeout=timeout,
            on_request=self._handle_request,
        )
        self._loop = None
        self._loop_thread = None

    def _handle_request(self, request: Request) -> Message:
        body = request.body if isinstance(request.body, dict) else {}
        question = body.get("message")
        if not isinstance(question, str) or not question.strip():
            return Error.to(
                request,
                code=BoardErrorCode.BAD_REQUEST.value,
                message="provide a 'message' (natural-language instruction)",
            )
        # Real agent-comm carries the sender on request.metadata.sender; the
        # test stubs put it on request.sender — accept either.
        meta = getattr(request, "metadata", None)
        requester = (
            getattr(meta, "sender", None)
            or getattr(request, "sender", None)
            or DEFAULT_TICKET_SOURCE
        )
        try:
            answer = self._converse(question, requester)
        except Exception as exc:
            logger.exception("board-manager: _converse failed for requester %s", requester)
            return Response.to(
                request,
                body={
                    "reply": (
                        "⚠️ The board-manager could not complete your request — its "
                        f"LLM call failed: {type(exc).__name__}: {exc}"
                    ),
                    "error": True,
                },
            )
        self._memory.append(question, answer)
        return Response.to(request, body={"reply": answer})

    # -- complexity classification ------------------------------------------

    def _select_manager_model(self, question: str) -> str | None:
        """Classify *question* and return the model override for the manager pass.

        If the operator explicitly set ``_manager_model``, return it verbatim
        (operator override wins — no down-tier).  Otherwise, run a cheap
        **level-1** classifier agent (DeepSeek provider) that replies with a
        single token: ``SIMPLE`` → return ``_simple_read_model`` (default
        ``"sonnet"``); anything else → return ``None`` (level-3 default =
        Opus).

        Any failure inside the classifier is logged and swallowed —
        ``None`` is returned so the request falls back to Opus.
        """
        if self._manager_model is not None:
            return self._manager_model

        try:
            from robotsix_llmio import build_agent_for_level
            from robotsix_llmio.core.run import run_agent

            h1 = build_agent_for_level(
                1,
                model=self._classify_model or None,
                system_prompt=_CLASSIFY_SYSTEM,
                output_type=str,
                name="board-manager-classify",
            )
            verdict = str(
                run_agent(
                    h1,
                    lambda: h1.run_sync(question).output,
                    label="board-manager-classify",
                )
            )
        except Exception:
            logger.warning("board-manager: classifier failed, falling back to Opus", exc_info=True)
            return None

        if verdict.strip().upper() == "SIMPLE":
            return self._simple_read_model
        return None

    # -- the LLM pipeline (level-1 recall -> classify -> level-3 act) -------

    def _converse(self, question: str, requester: str = DEFAULT_TICKET_SOURCE) -> str:
        from robotsix_llmio import build_agent_for_level
        from robotsix_llmio.core.run import run_agent

        # 1) Level-1 recall: scan prior Q→A for anything relevant.  Level-1's own
        #    default provider/model (DeepSeek-flash over OpenRouter) is used; a
        #    model override changes only the bare model name, not the transport.
        relevant = ""
        history = self._memory.as_prompt()
        if history:
            h1 = build_agent_for_level(
                1,
                model=self._recall_model or None,
                system_prompt=_RECALL_SYSTEM,
                output_type=str,
                name="board-manager-recall",
            )
            recall_prompt = f"NEW question:\n{question}\n\nPRIOR exchanges:\n{history}"
            relevant = run_agent(
                h1,
                lambda: h1.run_sync(recall_prompt).output,
                label="board-manager-recall",
            )

        # 2) Level-3 manager: act on the board via tools, with both its curated
        #    maintained memory and the recalled prior context in view.
        system = _MANAGER_SYSTEM.format(repo=self.settings.board_repo_id)
        notes = self._memory.load_notes()
        if notes.strip():
            system += f"\n\nYour maintained memory:\n{notes.strip()}"
        if relevant and relevant.strip().lower() != "none":
            system += f"\n\nRelevant prior exchanges:\n{relevant.strip()}"
        system += (
            f"\n\nThis turn's requester is '{requester}'. Any ticket you create is "
            f"sourced to it automatically, but you may pass an explicit source."
        )
        if not self.settings.enable_write_ops:
            system += (
                "\n\nWrite operations are disabled — you may only read the board and "
                "answer questions. Explain this to the user rather than attempting "
                "any board mutations."
            )
        # Level-3's own default provider/model (Claude opus over the Claude-SDK)
        # is used; a model override changes only the bare model name.
        # The override is chosen by _select_manager_model — a classifier may
        # down-tier simple read-only requests to a cheaper Claude alias.
        h3 = build_agent_for_level(
            3,
            model=self._select_manager_model(question),
            system_prompt=system,
            tools=self._build_tools(requester),
            output_type=str,
            name="board-manager",
        )
        return str(run_agent(h3, lambda: h3.run_sync(question).output, label="board-manager"))

    # -- board ops exposed as tools ---------------------------------------

    def _build_tools(self, requester: str = DEFAULT_TICKET_SOURCE) -> list[Any]:
        client = self.client
        repo = self.settings.board_repo_id

        def _safe(coro: Any) -> str:
            try:
                result = self._run(coro)
                return _truncate_result(result)
            except BoardAPIError as exc:
                return f"board API error {exc.status_code}: {exc.detail}"

        def list_tickets(state: str | None = None) -> str:
            """List board tickets, optionally filtered by a board state."""
            return _safe(client.list_tickets(state=state, repo_id=repo))

        def get_ticket(ticket_id: str) -> str:
            """Get one ticket's full record by id."""
            return _safe(client.get_ticket(ticket_id=ticket_id))

        def board_cards() -> str:
            """Get the board's cards grouped by column/state."""
            return _safe(client.board_cards(repo_id=repo))

        def ticket_history(ticket_id: str) -> str:
            """Get a ticket's history/event log."""
            return _safe(client.history(ticket_id=ticket_id))

        def merge_status(ticket_id: str) -> str:
            """Get a ticket's merge status."""
            return _safe(client.merge_status(ticket_id=ticket_id))

        def ticket_description(ticket_id: str) -> str:
            """Get a ticket's full description."""
            return _safe(client.description(ticket_id=ticket_id))

        def create_ticket(title: str, description: str, source: str = "") -> str:
            """Create a new ticket. `source` records the origin; leave blank to
            default to the requester so we always know where it came from."""
            return _safe(
                client.create_ticket(
                    title=title,
                    description=description,
                    source=source or requester,
                    repo_id=repo,
                )
            )

        def comment(ticket_id: str, body: str) -> str:
            """Add a comment to a ticket."""
            return _safe(client.add_comment(ticket_id=ticket_id, body=body))

        def transition(ticket_id: str, state: str, note: str = "") -> str:
            """Transition a ticket to a new board state (optionally with a note)."""
            return _safe(client.transition(ticket_id=ticket_id, state=state, note=note))

        def approve(ticket_id: str) -> str:
            """Approve a ticket."""
            return _safe(client.approve(ticket_id=ticket_id))

        def mark_done(ticket_id: str, note: str = "") -> str:
            """Mark a ticket as done (optionally with a closing note)."""
            return _safe(client.mark_done(ticket_id=ticket_id, note=note))

        def merge_now(ticket_id: str) -> str:
            """Trigger an immediate merge for a ticket."""
            return _safe(client.merge_now(ticket_id=ticket_id))

        def migrate(ticket_id: str, target_repo_id: str) -> str:
            """Migrate a ticket to another repository."""
            return _safe(client.migrate(ticket_id=ticket_id, target_repo_id=target_repo_id))

        def resume_blocked(ticket_id: str) -> str:
            """Resume a blocked ticket."""
            return _safe(client.resume_blocked(ticket_id=ticket_id))

        def set_priority(ticket_id: str, priority: bool) -> str:
            """Set or clear a ticket's priority flag."""
            return _safe(client.set_priority(ticket_id=ticket_id, priority=priority))

        def update_memory(memory: str) -> str:
            """Replace your maintained memory with `memory` — a concise, coherent
            note of durable board state, ongoing tasks, and user preferences to
            remember across conversations. Pass the full revised note."""
            self._memory.save_notes(memory)
            return "maintained memory updated"

        tools = [
            list_tickets,
            get_ticket,
            board_cards,
            ticket_history,
            merge_status,
            ticket_description,
            create_ticket,
            comment,
            transition,
            approve,
            mark_done,
            merge_now,
            migrate,
            resume_blocked,
            set_priority,
            update_memory,
        ]
        if not self.settings.enable_write_ops:
            tools = [t for t in tools if t.__name__ not in WRITE_OPS]
        return tools
