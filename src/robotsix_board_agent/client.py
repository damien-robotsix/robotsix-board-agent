"""Typed REST client for the mill board API.

Network-free in tests — pass ``transport=`` to inject a mock transport.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import BoardAgentSettings

logger = logging.getLogger(__name__)


class BoardAPIError(Exception):
    """Raised when the board API returns a non-2xx status code."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Board API error {status_code}: {detail}")


class BoardClient:
    """Typed HTTP client for the mill board REST API.

    Each public method maps 1:1 to an existing board endpoint.
    """

    def __init__(
        self,
        settings: BoardAgentSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url: str = settings.board_api_url.rstrip("/")
        self._token: str = settings.board_api_token
        self._repo_id: str = settings.board_repo_id
        self._transport: httpx.AsyncBaseTransport | None = transport
        self._http: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create or return the shared ``AsyncClient``."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._token}"},
                transport=self._transport,
            )
        return self._http

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # -- helpers -----------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request and return parsed JSON, or raise ``BoardAPIError``."""
        client = await self._get_client()
        logger.debug("HTTP %s %s", method, path)
        resp = await client.request(method, path, params=params, json=json_body)
        if resp.is_error:
            logger.warning(
                "Non-2xx response: %s %s -> %d %s",
                method,
                path,
                resp.status_code,
                resp.reason_phrase,
            )
            detail = ""
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise BoardAPIError(resp.status_code, detail)
        return resp.json()

    # -- read operations ---------------------------------------------------

    async def list_tickets(
        self,
        state: str | None = None,
        repo_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tickets, optionally filtered by state and/or repo."""
        params: dict[str, str] = {}
        if state is not None:
            params["state"] = state
        if repo_id is not None:
            params["repo_id"] = repo_id
        return await self._request("GET", "/tickets", params=params)  # type: ignore[no-any-return]

    async def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        """Get a single ticket by id."""
        return await self._request("GET", f"/tickets/{ticket_id}")  # type: ignore[no-any-return]

    async def board_cards(
        self,
        repo_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get board cards, optionally filtered by repo."""
        params: dict[str, str] = {}
        if repo_id is not None:
            params["repo_id"] = repo_id
        return await self._request("GET", "/board/cards", params=params)  # type: ignore[no-any-return]

    async def history(self, ticket_id: str) -> list[dict[str, Any]]:
        """Get the history log for a ticket."""
        return await self._request("GET", f"/tickets/{ticket_id}/history")  # type: ignore[no-any-return]

    async def merge_status(self, ticket_id: str) -> dict[str, Any]:
        """Get merge status for a ticket."""
        return await self._request("GET", f"/tickets/{ticket_id}/merge-status")  # type: ignore[no-any-return]

    async def description(self, ticket_id: str) -> dict[str, Any]:
        """Get the description of a ticket."""
        return await self._request("GET", f"/tickets/{ticket_id}/description")  # type: ignore[no-any-return]

    # -- write operations --------------------------------------------------

    async def create_ticket(
        self,
        title: str,
        description: str,
        source: str = "agent",
        kind: str = "task",
        repo_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new ticket."""
        body: dict[str, Any] = {
            "title": title,
            "description": description,
            "source": source,
            "kind": kind,
            "repo_id": repo_id or self._repo_id,
            **kwargs,
        }
        return await self._request("POST", "/tickets", json_body=body)  # type: ignore[no-any-return]

    async def add_comment(
        self,
        ticket_id: str,
        body: str,
        author: str = "board-agent",
    ) -> dict[str, Any]:
        """Add a comment to a ticket."""
        return await self._request(  # type: ignore[no-any-return]
            "POST",
            f"/tickets/{ticket_id}/comments",
            json_body={"body": body, "author": author},
        )

    async def transition(
        self,
        ticket_id: str,
        state: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Transition a ticket to a new state."""
        return await self._request(  # type: ignore[no-any-return]
            "POST",
            f"/tickets/{ticket_id}/transition",
            json_body={"state": state, "note": note},
        )

    async def approve(self, ticket_id: str) -> dict[str, Any]:
        """Approve a ticket."""
        return await self._request("POST", f"/tickets/{ticket_id}/approve")  # type: ignore[no-any-return]

    async def mark_done(
        self,
        ticket_id: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Mark a ticket as done."""
        return await self._request(  # type: ignore[no-any-return]
            "POST",
            f"/tickets/{ticket_id}/mark-done",
            json_body={"note": note},
        )

    async def merge_now(self, ticket_id: str) -> dict[str, Any]:
        """Trigger an immediate merge for a ticket."""
        return await self._request("POST", f"/tickets/{ticket_id}/merge-now")  # type: ignore[no-any-return]

    async def resume_blocked(self, ticket_id: str) -> dict[str, Any]:
        """Resume a blocked ticket."""
        return await self._request(  # type: ignore[no-any-return]
            "POST", f"/tickets/{ticket_id}/resume-blocked"
        )

    async def migrate(
        self,
        ticket_id: str,
        target_repo_id: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Migrate a ticket to another repo."""
        return await self._request(  # type: ignore[no-any-return]
            "POST",
            f"/tickets/{ticket_id}/migrate",
            json_body={"target_repo_id": target_repo_id, "note": note},
        )

    async def set_priority(
        self,
        ticket_id: str,
        priority: bool,
    ) -> dict[str, Any]:
        """Set or clear the priority flag on a ticket."""
        return await self._request(  # type: ignore[no-any-return]
            "POST",
            f"/tickets/{ticket_id}/priority",
            json_body={"priority": priority},
        )
