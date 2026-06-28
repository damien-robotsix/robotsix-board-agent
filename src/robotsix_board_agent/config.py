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

    max_output_chars: int = 2_000
    """Maximum characters in the LLM's final reply before truncation.

    The board-manager's final answer is truncated at this boundary (with a
    truncation marker appended) to guard against verbose narration burning
    subscription quota.  Replies under this limit are returned unchanged.
    Set to ``0`` to disable truncation entirely.
    """
