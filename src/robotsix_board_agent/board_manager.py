"""LLM board manager — natural-language management of the board over the broker.

Unlike :class:`~robotsix_board_agent.brokered.BrokeredBoardResponder` (a dumb
structured-op gateway), the manager is an llmio **level-3** agent that takes a
natural-language message, recalls relevant prior context via a cheap **level-1**
pass over its conversation memory, and acts directly on the board through the
real :class:`BoardClient` ops exposed as tools. It registers on the central
broker (pull/mailbox) so it can be reached from anywhere, NAT-safe.

Memory keeps only question→answer pairs (see :mod:`.memory`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from robotsix_agent_comm.protocol import Error, Message, Request, Response
from robotsix_agent_comm.sdk.agent import Agent
from robotsix_agent_comm.transport.brokered import create_transport_pair

from ._lifecycle import _ThreadedLoopMixin
from .client import BoardAPIError, BoardClient
from .config import BoardAgentSettings
from .constants import BoardErrorCode
from .memory import MAX_CONVERSATIONS, BoardManagerMemory

logger = logging.getLogger(__name__)

#: Cap a tool result handed back to the LLM (tickets lists can be large).
_RESULT_CAP = 12_000

#: llmio provider used for the manager's agents. The Claude-SDK provider also
#: works but its agents get host file/bash tools (unsafe for a board manager),
#: so we use the pydantic-ai OpenRouter provider — only our board tools.
_PROVIDER = "openrouter-deepseek"

#: Default level-3 model. The tier-3 default routes to the Claude SDK (``opus``),
#: which the OpenRouter provider can't serve, so the manager uses the strongest
#: llmio-known OpenRouter model by default (override via board_manager.model).
_DEFAULT_MANAGER_MODEL = "deepseek/deepseek-v4-pro"

_RECALL_SYSTEM = (
    "You retrieve relevant context for a board-management assistant. Given a NEW "
    "user question and a log of PRIOR question→answer exchanges, return only the "
    "prior exchanges that are genuinely relevant to the new question (decisions, "
    "tickets, or tasks it references or follows up on). Be terse — quote just the "
    "relevant bits. If nothing is relevant, reply exactly with 'none'."
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
    "Keep your final reply concise and tell the user exactly what you did "
    "(ids + outcomes) or answer their question.\n\n"
    "You keep a MAINTAINED MEMORY — a short, curated note of durable board state, "
    "ongoing/standing tasks, and user preferences (NOT a transcript). It is shown "
    "to you below each turn. When something worth remembering changes, call "
    "update_memory(memory) with the full revised note; keep it concise and "
    "coherent — rewrite/trim rather than letting it grow."
)


class BoardManager(_ThreadedLoopMixin):
    """Conversational, tool-using manager for a single board over the broker."""

    def __init__(
        self,
        settings: BoardAgentSettings,
        *,
        broker_host: str,
        broker_token: str,
        openrouter_key: str,
        memory_path: Path,
        broker_port: int = 443,
        broker_scheme: str = "https",
        agent_id: str | None = None,
        manager_model: str | None = None,
        recall_model: str | None = None,
        max_conversations: int = MAX_CONVERSATIONS,
        timeout: float = 120.0,
    ) -> None:
        self.settings = settings
        self.client = BoardClient(settings)
        self.agent_id = agent_id or f"board-manager-{settings.board_repo_id}"
        self._openrouter_key = openrouter_key
        self._manager_model = manager_model
        self._recall_model = recall_model
        self._memory = BoardManagerMemory(memory_path, max_conversations=max_conversations)
        registry, transport = create_transport_pair(
            "brokered",
            broker_host=broker_host,
            broker_port=broker_port,
            broker_scheme=broker_scheme,
            broker_token=broker_token,
        )
        self._agent = Agent(
            self.agent_id, registry, transport=transport, pull=True, timeout=timeout
        )
        self._agent.on_request(self._handle_request)
        self._loop = None
        self._loop_thread = None

    def _handle_request(self, request: Request) -> Message:
        body = request.body if isinstance(request.body, dict) else {}
        question = body.get("message") or body.get("question")
        if not isinstance(question, str) or not question.strip():
            return Error.to(
                request,
                code=BoardErrorCode.BAD_REQUEST.value,
                message="provide a 'message' (natural-language instruction)",
            )
        answer = self._converse(question)
        self._memory.append(question, answer)
        return Response.to(request, body={"reply": answer})

    # -- the LLM pipeline (level-1 recall -> level-3 act) ------------------

    def _converse(self, question: str) -> str:
        from robotsix_llmio.core.factory import get_provider
        from robotsix_llmio.core.run import run_agent

        provider = get_provider(provider=_PROVIDER, api_key=self._openrouter_key)

        # 1) Level-1 recall: scan prior Q→A for anything relevant.
        relevant = ""
        history = self._memory.as_prompt()
        if history:
            h1 = provider.build_agent(
                level=1,
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
        h3 = provider.build_agent(
            level=3,
            model=self._manager_model or _DEFAULT_MANAGER_MODEL,
            system_prompt=system,
            tools=self._build_tools(),
            output_type=str,
            name="board-manager",
        )
        return str(run_agent(h3, lambda: h3.run_sync(question).output, label="board-manager"))

    # -- board ops exposed as tools ---------------------------------------

    def _build_tools(self) -> list[Any]:
        client = self.client
        repo = self.settings.board_repo_id

        def _safe(coro: Any) -> str:
            try:
                return json.dumps(self._run(coro))[:_RESULT_CAP]
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

        def create_ticket(title: str, description: str) -> str:
            """Create a new ticket with a title and description."""
            return _safe(client.create_ticket(title=title, description=description, repo_id=repo))

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

        return [
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
