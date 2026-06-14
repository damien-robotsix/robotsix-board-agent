"""Board agent configuration model."""

from pydantic import BaseModel


class BoardAgentSettings(BaseModel):
    """Settings for the BoardAgent.

    All values are passed explicitly by the caller — this is NOT a
    pydantic BaseSettings model that reads from environment variables.
    """

    board_api_url: str
    """Base URL of the board REST API (e.g. ``http://localhost:8000``)."""

    board_api_token: str
    """Bearer token sent as ``Authorization: Bearer <token>``."""

    board_repo_id: str
    """The ``repo_id`` / board ID to scope operations to."""

    enable_write_ops: bool = True
    """When ``False``, all write ops return an Error."""
