"""LLM board manager — natural-language management of the board over the broker.

Unlike :class:`~robotsix_board_agent.brokered.BrokeredBoardResponder` (a dumb
structured-op gateway), the manager is an llmio **level-3** agent that takes a
natural-language message, recalls relevant prior context via a cheap **level-1**
pass over its conversation memory, and acts directly on the board through the
real :class:`BoardClient` ops exposed as tools. It registers on the central
broker (pull/mailbox) so it can be reached from anywhere, NAT-safe.

The two passes run on their OWN provider via llmio's per-level defaults
(``build_agent_for_level``): the **recall** pass is level-1 (DeepSeek-flash over
OpenRouter — cheap), and the **manager** pass is level-3 (Claude-SDK — strongest
reasoning). The manager pass uses a three-tier complexity classifier: trivial
reads route to Haiku (default), straightforward CRUD/dedup routes to Sonnet
(default), and only genuinely ambiguous multi-step planning routes to Opus. Each
level resolves its own transport, so the recall model is never forced through
the Claude transport (which would 400 with "model may not exist"). An optional
``model=`` override changes only the bare model name; the level's provider stays
fixed.

Memory keeps only question→answer pairs (see :mod:`.memory`).
"""

from __future__ import annotations

import json
import logging
import re
import time
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


# -- fast read path: ticket status without an LLM hop ---------------------

#: Regex that matches a board ticket id (e.g. 20260621T182023Z-slug-a1b2).
_TICKET_ID_RE = re.compile(r"\b\d{8}T\d{6}Z-[a-z0-9-]+-[a-f0-9]{4}\b")

#: Words that signal a write/mutation intent — used to skip the fast read path.
_WRITE_INTENT_WORDS: frozenset[str] = frozenset(
    {
        "create",
        "new ticket",
        "add",
        "comment",
        "transition",
        "approve",
        "mark done",
        "mark_done",
        "merge",
        "migrate",
        "resume",
        "priority",
        "close",
        "delete",
        "change",
        "modify",
        "set",
        "move",
        "update",
        "assign",
        "reopen",
    }
)

#: Default TTL for the ticket-status cache (seconds).
_DEFAULT_CACHE_TTL: float = 300.0


class _TicketCache:
    """A simple time-TTL cache for ticket read results.

    Not thread-safe — the caller (BoardManager) serialises access through
    its own event loop, so no lock is needed.
    """

    def __init__(self, ttl: float = _DEFAULT_CACHE_TTL) -> None:
        self._ttl = ttl
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        """Return the cached ticket dict, or ``None`` if absent or expired."""
        entry = self._store.get(ticket_id)
        if entry is None:
            return None
        inserted_at, data = entry
        if time.monotonic() - inserted_at > self._ttl:
            del self._store[ticket_id]
            return None
        return data

    def set(self, ticket_id: str, data: dict[str, Any]) -> None:
        """Store *data* for *ticket_id*, resetting its TTL."""
        self._store[ticket_id] = (time.monotonic(), data)

    def clear(self) -> None:
        """Drop all cached entries.

        Called after any LLM/ops turn that may have mutated ticket state
        (transitions, approvals, …) so a subsequent fast read does not serve
        a stale status within the TTL.
        """
        self._store.clear()


def _has_write_intent(question: str) -> bool:
    """Return ``True`` if *question* contains any write-intent keyword."""
    lower = question.lower()
    return any(word in lower for word in _WRITE_INTENT_WORDS)


def _extract_ticket_ids(question: str) -> list[str]:
    """Return all unique ticket ids found in *question*."""
    return list(dict.fromkeys(_TICKET_ID_RE.findall(question)))


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
    "transition, approve, mark done, merge_now, migrate, resume_blocked, set priority)"
    ". Act directly "
    "— the user has authorized you to make changes. Prefer reading first when a "
    "request is ambiguous about which ticket(s) it targets. When you transition "
    "a ticket, use a valid board state.\n\n"
    "SILENCE BETWEEN TOOLS: Do NOT narrate your actions between tool calls. "
    "Never emit preambles like 'Let me…', 'Now I'll…', 'I'll start by…', "
    "or 'First, let me check…'. Call tools silently and directly — the user "
    "only sees your final reply, not your step-by-step thoughts.\n\n"
    "DEDUPLICATE before creating: whenever you are about to create a ticket, first "
    "list the existing tickets and check whether an open one already covers the "
    "same issue. If a near-duplicate exists, do NOT create another — add a comment "
    "to (or update) the existing ticket instead, and tell the user which one. Only "
    "create a new ticket when none matches.\n\n"
    "BATCH FETCH: when you need details (titles, descriptions, status) for several "
    "tickets at once — e.g. after list_tickets or board_cards returns many ids — "
    "use get_multiple_ticket_descriptions with all the ticket ids in one call "
    "instead of calling get_ticket or ticket_description for each one individually. "
    "One batch call replaces many round-trips, saving substantial tokens and time. "
    "Fetch all the descriptions you need in a single pass before acting on them.\n\n"
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
    "REPORT FORMAT: Your final reply must be EXTREMELY terse — output only ids "
    "+ outcomes as short fragments, one per line. Example: 'Created "
    "#abc-def-1234 (Fix timeout). Transitioned #xyz-7890 to in_progress.' "
    "Do NOT restate the user's question, add markdown headers, write bullet "
    "essays, or include explanatory paragraphs. If the user explicitly asks "
    "for a detailed report you may expand — otherwise default to the shortest "
    "possible answer that conveys the outcome. For code-changes or analysis, "
    "summarise at the file/function level — do NOT include exhaustive "
    "file:line references unless the user explicitly asked for them.\n\n"
    "REFERENCE LOOKUP: you have a lookup_reference tool for rarely-needed "
    "canonical reference material (board state-machine catalog, repo registry, "
    "epic genealogy, approval inventories). Call it ONLY when a request "
    "genuinely needs that information — it is NOT injected every turn so you "
    "must fetch it yourself. Pass a short keyword query (e.g. 'state machine "
    "transitions' or 'repo registry frontend').\n\n"
    "You keep a MAINTAINED MEMORY — a bare-bones, current-state note of active "
    "board status, open decisions, and user preferences (NOT a transcript or "
    "log). It is shown to you below each turn. Strip stale or resolved items "
    "aggressively; when calling update_memory, pass only what is still relevant "
    "right now — rewrite/trim rather than letting it grow. The memory is "
    "capped at a few hundred words; keep reference material out of it (use "
    "lookup_reference instead)."
)

_CLASSIFY_SYSTEM = (
    "You classify incoming user requests for a board-management assistant. "
    "Reply with a single token — SIMPLE_READ, MODERATE, or COMPLEX — and "
    "nothing else.\n\n"
    "SIMPLE_READ: the request is a trivial, pure read-only board status query "
    "or listing with zero ambiguity. It asks only for current board state, "
    "ticket listings, ticket details, or a simple summary of what is on the "
    "board. No board modification, no multi-step reasoning, no deduplication "
    "check, no organisation/classification work.\n\n"
    "MODERATE: the request needs board tools but is straightforward CRUD, "
    "deduplication, ticket organisation/classification, or a simple single-step "
    "mutation (create, transition, comment, migrate, approve, mark done, "
    "merge_now, set priority, resume_blocked) with no complex multi-step "
    "planning or ambiguity.\n\n"
    "COMPLEX: the request is genuinely ambiguous, requires deep multi-step "
    "reasoning or planning across several coordinated board operations, or "
    "involves nuanced judgement where the cheapest models would likely make "
    "mistakes.\n\n"
    "When in doubt between SIMPLE_READ and MODERATE, reply MODERATE. "
    "When in doubt between MODERATE and COMPLEX, reply MODERATE."
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
        simple_read_model: str = "haiku",
        moderate_model: str = "sonnet",
        classify_model: str | None = None,
        max_conversations: int = MAX_CONVERSATIONS,
        max_recall_conversations: int = 50,
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
        *simple_read_model* — bare Claude alias (``"haiku"``, ``"sonnet"``) used
        for requests the complexity classifier deems SIMPLE_READ; default ``"haiku"``.
        *moderate_model* — bare Claude alias (``"sonnet"``) used for requests
        the complexity classifier deems MODERATE (straightforward CRUD/dedup/
        organisation); default ``"sonnet"``.
        *classify_model* — optional bare model override for the level-1
        classifier (defaults to level-1's DeepSeek-flash).  *max_conversations* —
        cap on stored conversation pairs.  *max_recall_conversations* — how many
        recent conversations to feed into the recall scan (default 50); stored
        pairs beyond this are pruned from the recall prompt but kept on disk for
        traceability.  *timeout* — broker operation timeout in seconds.
        """
        self.settings = settings
        self.client = BoardClient(settings)
        self.agent_id = agent_id or f"board-manager-{settings.board_repo_id}"
        self._manager_model = manager_model
        self._recall_model = recall_model
        self._simple_read_model = simple_read_model
        self._moderate_model = moderate_model
        self._classify_model = classify_model
        self._max_recall_conversations = max_recall_conversations
        self._memory = BoardManagerMemory(memory_path, max_conversations=max_conversations)
        self._ticket_cache = _TicketCache()
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
            fast_answer = self._fast_read_ticket(question)
            if fast_answer is not None:
                answer = fast_answer
            else:
                # The full pipeline may mutate ticket state (transitions,
                # approvals, …). Invalidate the read cache afterwards so a
                # subsequent fast read reflects the change rather than a
                # stale cached status. Unconditional because the write-intent
                # gate is keyword-based and can miss a write.
                answer = self._converse(question, requester)
                self._ticket_cache.clear()
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

    # -- fast read path: ticket status without an LLM hop -------------------

    def _fast_read_ticket(self, question: str) -> str | None:
        """Serve a read-only ticket-status query directly from the board API.

        Returns a structured summary string when *question* is a simple
        read request that mentions exactly one ticket id and contains no
        write-intent language.  Returns ``None`` when the fast path cannot
        handle the request — the caller falls back to the full LLM pipeline.
        """
        if _has_write_intent(question):
            return None
        ticket_ids = _extract_ticket_ids(question)
        if len(ticket_ids) != 1:
            return None

        ticket_id = ticket_ids[0]

        # Check the cache first.
        cached = self._ticket_cache.get(ticket_id)
        if cached is not None:
            logger.debug("board-manager: serving ticket %s from cache", ticket_id)
            return self._format_ticket_status(ticket_id, cached, cached=True)

        # Fetch from the board API.
        try:
            data: dict[str, Any] = self._run(self.client.get_ticket(ticket_id=ticket_id))
        except BoardAPIError as exc:
            logger.debug(
                "board-manager: fast-read ticket %s failed (%s), falling back to LLM",
                ticket_id,
                exc,
            )
            return None

        self._ticket_cache.set(ticket_id, data)
        return self._format_ticket_status(ticket_id, data, cached=False)

    @staticmethod
    def _format_ticket_status(ticket_id: str, data: dict[str, Any], *, cached: bool = False) -> str:
        """Format a ticket dict into a concise structured status summary.

        Extracts the key fields: state, branch, pr_url, pending_question, errors.
        """
        state = data.get("state", "unknown")
        branch = data.get("branch")
        pr_url = data.get("pr_url")
        pending_question = data.get("pending_question")
        errors = data.get("errors")

        parts: list[str] = [
            f"Ticket {ticket_id}:",
            f"  state: {state}",
        ]
        if branch:
            parts.append(f"  branch: {branch}")
        if pr_url:
            parts.append(f"  pr_url: {pr_url}")
        if pending_question:
            parts.append(f"  pending_question: {pending_question}")
        if errors:
            parts.append(f"  errors: {errors}")
        if cached:
            parts.append("  (served from cache)")

        return "\n".join(parts)

    # -- complexity classification ------------------------------------------

    def _select_manager_model(self, question: str) -> str | None:
        """Classify *question* and return the model override for the manager pass.

        If the operator explicitly set ``_manager_model``, return it verbatim
        (operator override wins — no down-tier).  Otherwise, run a cheap
        **level-1** classifier agent (DeepSeek provider) that replies with a
        single token: ``SIMPLE_READ`` → return ``_simple_read_model`` (default
        ``"haiku"``); ``MODERATE`` → return ``_moderate_model`` (default
        ``"sonnet"``); anything else (including ``COMPLEX``) → return ``None``
        (level-3 default = Opus).

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

        v = verdict.strip().upper()
        if v == "SIMPLE_READ":
            return self._simple_read_model
        if v == "MODERATE":
            return self._moderate_model
        return None

    # -- the LLM pipeline (level-1 recall -> classify -> level-3 act) -------

    def _converse(self, question: str, requester: str = DEFAULT_TICKET_SOURCE) -> str:
        from robotsix_llmio import build_agent_for_level
        from robotsix_llmio.core.run import run_agent

        # 1) Level-1 recall: scan prior Q→A for anything relevant.  Level-1's own
        #    default provider/model (DeepSeek-flash over OpenRouter) is used; a
        #    model override changes only the bare model name, not the transport.
        relevant = ""
        history = self._memory.as_prompt(max_entries=self._max_recall_conversations)
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
        answer = str(run_agent(h3, lambda: h3.run_sync(question).output, label="board-manager"))
        cap = self.settings.max_output_chars
        if cap > 0 and len(answer) > cap:
            answer = answer[:cap] + "\n\n[truncated — reply exceeded output cap]"
        return answer

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

        def get_multiple_ticket_descriptions(ticket_ids: list[str]) -> str:
            """Get descriptions for multiple tickets in one batch call. Use this
            instead of calling get_ticket or ticket_description one-by-one when
            you need details on several tickets — it replaces N round-trips with
            one, saving substantial tokens and time."""
            return _safe(client.get_multiple_ticket_descriptions(ticket_ids=ticket_ids))

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
            result = _safe(client.mark_done(ticket_id=ticket_id, note=note))
            self._memory.prune_closed_ticket(ticket_id)
            return result

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
            remember across conversations. Pass the full revised note. The note
            is capped — if truncated you will be told so you can trim further."""
            return self._memory.save_notes(memory)

        def lookup_reference(query: str) -> str:
            """Search the canonical reference material for paragraphs matching
            `query`. Use for rarely-needed board reference data: state-machine
            catalog, repo registry, epic genealogy, approval inventories.
            Pass a short keyword query (e.g. 'state transitions' or
            'repo registry'). Only call when a request genuinely needs it —
            this material is NOT injected every turn."""
            return self._memory.search_reference(query)

        tools = [
            list_tickets,
            get_ticket,
            board_cards,
            ticket_history,
            merge_status,
            ticket_description,
            get_multiple_ticket_descriptions,
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
            lookup_reference,
        ]
        if not self.settings.enable_write_ops:
            tools = [t for t in tools if t.__name__ not in WRITE_OPS]
        return tools
