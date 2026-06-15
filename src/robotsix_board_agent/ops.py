"""Operation dispatch table and argument models.

Maps structured ``{"op": "...", "args": {...}}`` requests to
``BoardClient`` method calls.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .client import BoardClient

logger = logging.getLogger(__name__)


class UnknownOpError(Exception):
    """Raised when the requested operation name is not in the op table."""

    def __init__(self, op: str) -> None:
        self.op = op
        super().__init__(f"Unknown operation: {op}")


# -- operation argument models ---------------------------------------------


class ListTicketsArgs(BaseModel):
    """Arguments for the ``list_tickets`` operation — optional state and repo filters."""
    state: str | None = None
    repo_id: str | None = None


class GetTicketArgs(BaseModel):
    """Arguments for the ``get_ticket`` operation — identifies a single ticket by id."""
    ticket_id: str


class BoardCardsArgs(BaseModel):
    """Arguments for the ``board_cards`` operation — optional repo filter."""
    repo_id: str | None = None


class HistoryArgs(BaseModel):
    """Arguments for the ``history`` operation — identifies a ticket by id."""
    ticket_id: str


class MergeStatusArgs(BaseModel):
    """Arguments for the ``merge_status`` operation — identifies a ticket by id."""
    ticket_id: str


class DescriptionArgs(BaseModel):
    """Arguments for the ``get_description`` operation — identifies a ticket by id."""
    ticket_id: str


class CreateTicketArgs(BaseModel):
    """Arguments for the ``create_ticket`` operation — title, description, and optional metadata."""
    title: str
    description: str
    source: str = "agent"
    kind: str = "task"
    repo_id: str | None = None


class AddCommentArgs(BaseModel):
    """Arguments for the ``add_comment`` operation — ticket id, body, and optional author."""
    ticket_id: str
    body: str
    author: str = "board-agent"


class TransitionArgs(BaseModel):
    """Arguments for the ``transition`` operation — ticket id, target state, and optional note."""
    ticket_id: str
    state: str
    note: str = ""


class ApproveArgs(BaseModel):
    """Arguments for the ``approve`` operation — identifies a ticket by id."""
    ticket_id: str


class MarkDoneArgs(BaseModel):
    """Arguments for the ``mark_done`` operation — ticket id and optional closing note."""
    ticket_id: str
    note: str = ""


class MergeNowArgs(BaseModel):
    """Arguments for the ``merge_now`` operation — identifies a ticket by id."""
    ticket_id: str


class ResumeBlockedArgs(BaseModel):
    """Arguments for the ``resume_blocked`` operation — identifies a ticket by id."""
    ticket_id: str


class MigrateArgs(BaseModel):
    """Arguments for the ``migrate`` operation — ticket id, target repo, and optional note."""
    ticket_id: str
    target_repo_id: str
    note: str = ""


class SetPriorityArgs(BaseModel):
    """Arguments for the ``set_priority`` operation — ticket id and priority flag."""
    ticket_id: str
    priority: bool


# -- op dispatch table -----------------------------------------------------


async def _list_tickets(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = ListTicketsArgs.model_validate(args)
    result = await client.list_tickets(state=a.state, repo_id=a.repo_id)
    return {"tickets": result}


async def _get_ticket(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = GetTicketArgs.model_validate(args)
    return await client.get_ticket(ticket_id=a.ticket_id)


async def _board_cards(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = BoardCardsArgs.model_validate(args)
    result = await client.board_cards(repo_id=a.repo_id)
    return {"cards": result}


async def _history(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = HistoryArgs.model_validate(args)
    result = await client.history(ticket_id=a.ticket_id)
    return {"history": result}


async def _merge_status(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = MergeStatusArgs.model_validate(args)
    return await client.merge_status(ticket_id=a.ticket_id)


async def _description(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = DescriptionArgs.model_validate(args)
    return await client.description(ticket_id=a.ticket_id)


async def _create_ticket(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = CreateTicketArgs.model_validate(args)
    return await client.create_ticket(
        title=a.title,
        description=a.description,
        source=a.source,
        kind=a.kind,
        repo_id=a.repo_id,
    )


async def _add_comment(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = AddCommentArgs.model_validate(args)
    return await client.add_comment(
        ticket_id=a.ticket_id,
        body=a.body,
        author=a.author,
    )


async def _transition(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = TransitionArgs.model_validate(args)
    return await client.transition(
        ticket_id=a.ticket_id,
        state=a.state,
        note=a.note,
    )


async def _approve(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = ApproveArgs.model_validate(args)
    return await client.approve(ticket_id=a.ticket_id)


async def _mark_done(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = MarkDoneArgs.model_validate(args)
    return await client.mark_done(ticket_id=a.ticket_id, note=a.note)


async def _merge_now(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = MergeNowArgs.model_validate(args)
    return await client.merge_now(ticket_id=a.ticket_id)


async def _resume_blocked(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = ResumeBlockedArgs.model_validate(args)
    return await client.resume_blocked(ticket_id=a.ticket_id)


async def _migrate(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = MigrateArgs.model_validate(args)
    return await client.migrate(
        ticket_id=a.ticket_id,
        target_repo_id=a.target_repo_id,
        note=a.note,
    )


async def _set_priority(client: BoardClient, args: dict[str, Any]) -> dict[str, Any]:
    a = SetPriorityArgs.model_validate(args)
    return await client.set_priority(ticket_id=a.ticket_id, priority=a.priority)


OP_TABLE: dict[str, Callable[[BoardClient, dict[str, Any]], Any]] = {
    # read ops
    "list_tickets": _list_tickets,
    "get_ticket": _get_ticket,
    "board_cards": _board_cards,
    "history": _history,
    "merge_status": _merge_status,
    "description": _description,
    # write ops
    "create_ticket": _create_ticket,
    "comment": _add_comment,
    "transition": _transition,
    "approve": _approve,
    "mark_done": _mark_done,
    "merge_now": _merge_now,
    "resume_blocked": _resume_blocked,
    "migrate": _migrate,
    "set_priority": _set_priority,
}

WRITE_OPS: frozenset[str] = frozenset(
    {
        "create_ticket",
        "comment",
        "transition",
        "approve",
        "mark_done",
        "merge_now",
        "resume_blocked",
        "migrate",
        "set_priority",
    }
)


# -- dispatch --------------------------------------------------------------


class BoardOp(BaseModel):
    """A structured operation request: ``{"op": "...", "args": {...}}``."""

    op: str
    args: dict[str, Any] = {}


async def dispatch(client: BoardClient, op: BoardOp) -> dict[str, Any]:
    """Look up *op* in ``OP_TABLE``, validate args, and execute.

    Raises:
        UnknownOpError: if *op* is not in the table.
    """
    handler = OP_TABLE.get(op.op)
    if handler is None:
        logger.error("Dispatch failed: unknown op=%s", op.op)
        raise UnknownOpError(op.op)
    logger.info("Dispatching op=%s", op.op)
    result = await handler(client, op.args)
    logger.info("Dispatch succeeded: op=%s", op.op)
    return result  # type: ignore[no-any-return]
