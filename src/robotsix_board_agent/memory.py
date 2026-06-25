"""Bounded conversation memory for the board manager.

Stores only **question → answer** pairs (no internal tool steps / reasoning), so
the trace stays small and coherent. Capped at the most recent
:data:`MAX_CONVERSATIONS`; older entries are dropped. A low-tier LLM scans these
pairs for relevance to a new question (see :mod:`.board_manager`).

The maintained-memory note is guarded against transcript accumulation: Q&A
blocks (timestamp + ``Q:``/``A:`` lines) are stripped on every save so the note
never grows into a verbatim transcript.  When ``mark_done`` closes a ticket its
detailed entries are collapsed to a one-line summary.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Hard cap on retained conversations; the oldest beyond this are pruned.
MAX_CONVERSATIONS = 200

#: Cap on the agent-maintained memory note, so it stays coherent (not too long).
MAX_NOTES_CHARS = 2000

# -- transcript hygiene ------------------------------------------------------

#: Matches an ISO timestamp line (``[2026-06-25T21:42:39Z]`` or similar).
_ISO_TS_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\]]*\]$")

#: Matches a Q&A line from a verbatim transcript.
_QA_LINE_RE = re.compile(r"^[QA]:\s")

#: Matches a blank or whitespace-only line (boundary between transcript blocks).
_BLANK_RE = re.compile(r"^\s*$")


def _prune_transcripts(text: str) -> str:
    """Return *text* with verbatim Q&A transcript blocks collapsed.

    A transcript block is a sequence of lines where the first line looks like an
    ISO timestamp and is followed by ``Q:`` / ``A:`` lines.  Each such block is
    replaced with a single summary line so the note stays a note and never
    balloons into a full transcript.

    Non-transcript lines pass through unchanged.
    """
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect start of a transcript block: an ISO timestamp followed by a Q:
        # or A: on the next non-blank line.
        if _ISO_TS_RE.match(line):
            j = i + 1
            # Skip blank lines.
            while j < len(lines) and _BLANK_RE.match(lines[j]):
                j += 1
            if j < len(lines) and _QA_LINE_RE.match(lines[j]):
                # We have a transcript block — collect Q/A lines until a
                # non-Q/A, non-blank line or end.
                q_text = lines[j][2:].strip()[:80] if lines[j].startswith("Q:") else ""
                k = j + 1
                while k < len(lines):
                    if _BLANK_RE.match(lines[k]):
                        k += 1
                        continue
                    if _QA_LINE_RE.match(lines[k]):
                        k += 1
                        continue
                    break
                snippet = q_text[:60] + ("…" if len(q_text) > 60 else "")
                label = (
                    f"(transcript block collapsed: {snippet})"
                    if snippet
                    else "(transcript block collapsed)"
                )
                out.append(label)
                i = k
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _prune_ticket_lines(text: str, ticket_id: str) -> str:
    """Collapse lines in *text* that reference *ticket_id* to a single summary.

    Only lines containing the literal *ticket_id* are affected; all other lines
    pass through unchanged.  The collapsed line is inserted where the first
    affected line appeared (or at the end if none found).
    """
    lines = text.splitlines()
    kept: list[str] = []
    affected: list[str] = []
    for line in lines:
        if ticket_id in line:
            affected.append(line)
        else:
            kept.append(line)
    if not affected:
        return text
    # Build a single summary line from the first affected line, truncated.
    summary = affected[0].strip()
    if len(summary) > 120:
        summary = summary[:117] + "…"
    kept.append(f"Ticket {ticket_id}: closed (was: {summary})")
    return "\n".join(kept)


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
        """Replace the maintained memory note (truncated to ``max_notes_chars``).

        Verbose Q&A transcript blocks are stripped before saving so the note
        cannot grow into a full transcript — the agent's system prompt already
        instructs it to summarise, and this is a safety net.
        """
        cleaned = _prune_transcripts(text or "")
        if cleaned != (text or ""):
            logger.info("board-manager memory: stripped transcript blocks from note")
        self._notes_path.parent.mkdir(parents=True, exist_ok=True)
        self._notes_path.write_text(cleaned[: self._max_notes])

    def prune_closed_ticket(self, ticket_id: str) -> None:
        """Collapse maintained-memory entries for *ticket_id* to one summary line.

        Called automatically when a ticket is marked done so its detailed
        history doesn't persist in the note.
        """
        current = self.load_notes()
        if not current or ticket_id not in current:
            return
        pruned = _prune_ticket_lines(current, ticket_id)
        if pruned != current:
            logger.info("board-manager memory: pruned closed ticket %s from notes", ticket_id)
            self._notes_path.parent.mkdir(parents=True, exist_ok=True)
            self._notes_path.write_text(pruned[: self._max_notes])
