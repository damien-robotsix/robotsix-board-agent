"""Bounded conversation memory for the board manager.

Stores only **question → answer** pairs (no internal tool steps / reasoning), so
the trace stays small and coherent. Capped at the most recent
:data:`MAX_CONVERSATIONS`; older entries are dropped. A low-tier LLM scans these
pairs for relevance to a new question (see :mod:`.board_manager`).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Hard cap on retained conversations; the oldest beyond this are pruned.
MAX_CONVERSATIONS = 200

#: Cap on the agent-maintained memory note, so it stays coherent (not too long).
MAX_NOTES_CHARS = 2000


class BoardManagerMemory:
    """Persistence for the board manager's two memories.

    * the **conversation trace** — a JSON list of ``{timestamp, question,
      answer}`` (the recall source; capped at ``max_conversations``);
    * the **maintained memory** — a single free-form note the agent itself
      curates (board state, ongoing tasks, user preferences), capped at
      ``max_notes_chars`` and always shown back to the agent.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_conversations: int = MAX_CONVERSATIONS,
        max_notes_chars: int = MAX_NOTES_CHARS,
    ) -> None:
        """Initialise the memory store.

        *path* — filesystem path to the JSON conversation-trace file (a sibling
        ``_notes.md`` file is derived for the maintained memory note).
        *max_conversations* — maximum number of question/answer pairs to retain
        (oldest pruned first).  *max_notes_chars* — character cap on the
        agent-maintained memory note.
        """
        self._path = Path(path)
        self._max = max(1, max_conversations)
        self._notes_path = self._path.with_name(f"{self._path.stem}_notes.md")
        self._max_notes = max(0, max_notes_chars)

    def load(self) -> list[dict[str, str]]:
        """Return the stored conversations (oldest first); empty on any error."""
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text())
        except json.JSONDecodeError, OSError:
            logger.warning("could not read board-manager memory at %s", self._path)
            return []
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict) and "question" in e]

    def append(self, question: str, answer: str, *, timestamp: str | None = None) -> None:
        """Append a Q→A turn and prune to the most recent ``max_conversations``."""
        entries = self.load()
        entries.append(
            {
                "timestamp": timestamp or datetime.now(UTC).isoformat(),
                "question": question,
                "answer": answer,
            }
        )
        if len(entries) > self._max:
            entries = entries[-self._max :]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(entries, indent=2))

    def as_prompt(self) -> str:
        """Render the stored conversations as a compact Q/A block for an LLM."""
        entries = self.load()
        if not entries:
            return ""
        return "\n".join(
            f"[{e.get('timestamp', '?')}]\nQ: {e['question']}\nA: {e.get('answer', '')}"
            for e in entries
        )

    # -- maintained memory (the agent's own curated note) -----------------

    def load_notes(self) -> str:
        """Return the agent-maintained memory note ('' when none/unreadable)."""
        if not self._notes_path.exists():
            return ""
        try:
            return self._notes_path.read_text()
        except OSError:
            logger.warning("could not read board-manager notes at %s", self._notes_path)
            return ""

    def save_notes(self, text: str) -> None:
        """Replace the maintained memory note (truncated to ``max_notes_chars``)."""
        self._notes_path.parent.mkdir(parents=True, exist_ok=True)
        self._notes_path.write_text((text or "")[: self._max_notes])
