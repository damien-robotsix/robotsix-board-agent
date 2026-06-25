"""Tests for the board manager's bounded conversation memory."""

from __future__ import annotations

from pathlib import Path

from robotsix_board_agent.memory import (
    BoardManagerMemory,
    _prune_ticket_lines,
    _prune_transcripts,
)


def test_append_and_load(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.append("what is open?", "3 tickets are open", timestamp="2026-01-01T00:00:00Z")
    mem.append("close T-1", "closed T-1", timestamp="2026-01-01T00:01:00Z")
    entries = mem.load()
    assert [e["question"] for e in entries] == ["what is open?", "close T-1"]
    assert entries[0]["answer"] == "3 tickets are open"
    # Only question/answer/timestamp are kept — no internal steps.
    assert set(entries[0]) == {"timestamp", "question", "answer"}


def test_prunes_to_cap(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json", max_conversations=200)
    for i in range(250):
        mem.append(f"q{i}", f"a{i}", timestamp=f"t{i}")
    entries = mem.load()
    assert len(entries) == 200
    # The oldest 50 were dropped; the most recent are kept.
    assert entries[0]["question"] == "q50"
    assert entries[-1]["question"] == "q249"


def test_as_prompt_empty_and_nonempty(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    assert mem.as_prompt() == ""
    mem.append("hi", "hello", timestamp="t0")
    rendered = mem.as_prompt()
    assert "Q: hi" in rendered and "A: hello" in rendered


def test_maintained_notes_roundtrip(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    assert mem.load_notes() == ""
    mem.save_notes("auth epic split into 3 sub-tickets; user prefers terse replies")
    assert mem.load_notes() == "auth epic split into 3 sub-tickets; user prefers terse replies"
    # Stored separately from the conversation trace.
    assert (tmp_path / "mem_notes.md").exists()


def test_maintained_notes_capped(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json", max_notes_chars=10)
    mem.save_notes("x" * 50)
    assert mem.load_notes() == "x" * 10


def test_notes_independent_of_conversations(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.append("q", "a", timestamp="t0")
    mem.save_notes("a durable note")
    assert len(mem.load()) == 1
    assert mem.load_notes() == "a durable note"


def test_corrupt_file_is_ignored(tmp_path: Path) -> None:
    p = tmp_path / "mem.json"
    p.write_text("{ not json")
    mem = BoardManagerMemory(p)
    assert mem.load() == []
    # A subsequent append recovers cleanly.
    mem.append("q", "a", timestamp="t")
    assert len(mem.load()) == 1


# -- transcript pruning -----------------------------------------------------


def test_prune_transcripts_strips_qa_blocks() -> None:
    text = """## Active tasks
- Ticket T-1: in progress

[2026-06-25T21:42:39Z]
Q: what is the status of ticket T-1?
A: T-1 is in the review column

[2026-06-25T21:45:00Z]
Q: close ticket T-1
A: closing T-1 now

## Preferences
- user likes terse replies"""
    result = _prune_transcripts(text)
    assert "Q: what is the status" not in result
    assert "A: T-1 is in the review column" not in result
    assert "Q: close ticket T-1" not in result
    assert "A: closing T-1 now" not in result
    assert "transcript block collapsed" in result
    assert "## Active tasks" in result
    assert "## Preferences" in result


def test_prune_transcripts_preserves_non_transcript_lines() -> None:
    text = "Just a normal note.\nNo transcript here.\nStill good."
    assert _prune_transcripts(text) == text


def test_prune_transcripts_handles_empty() -> None:
    assert _prune_transcripts("") == ""


def test_prune_transcripts_preserves_timestamp_without_qa() -> None:
    """A bare ISO timestamp line not followed by Q:/A: is kept."""
    text = "The event happened at [2026-06-25T21:42:39Z] and was handled."
    result = _prune_transcripts(text)
    assert "[2026-06-25T21:42:39Z]" in result


def test_prune_transcripts_collapses_multiple_blocks() -> None:
    text = (
        "[2026-06-25T21:42:00Z]\n"
        "Q: first question\n"
        "A: first answer\n"
        "\n"
        "Some middle text.\n"
        "\n"
        "[2026-06-25T21:43:00Z]\n"
        "Q: second question that is long but fits within the line limit ok\n"
        "A: second answer"
    )
    result = _prune_transcripts(text)
    assert result.count("transcript block collapsed") == 2
    assert "Some middle text" in result
    assert "Q: first question" not in result
    assert "Q: second question" not in result


# -- ticket-id pruning ------------------------------------------------------


def test_prune_ticket_lines_collapses_affected_lines(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.save_notes(
        "Active:\n"
        "- 20260625T214218Z-prune-memory-a505: structural changes\n"
        "Other text here.\n"
        "20260625T214218Z-prune-memory-a505: needs more work\n"
        "Done: ticket-123 is closed"
    )
    mem.prune_closed_ticket("20260625T214218Z-prune-memory-a505")
    result = mem.load_notes()
    # Affected lines are removed; a summary line is appended.
    assert "needs more work" not in result  # second affected line dropped
    assert "Ticket 20260625T214218Z-prune-memory-a505: closed" in result
    assert "Other text here" in result  # unaffected line preserved


def test_prune_ticket_lines_no_match_is_noop(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    original = "Active:\n- ticket-1: in progress\n- ticket-2: review"
    mem.save_notes(original)
    mem.prune_closed_ticket("non-existent-id")
    assert mem.load_notes() == original


def test_prune_ticket_lines_empty_notes(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.prune_closed_ticket("any-id")
    assert mem.load_notes() == ""


# -- save_notes transcript guard --------------------------------------------


def test_save_notes_strips_transcripts(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json", max_notes_chars=2000)
    text_with_transcript = (
        "## Active\n"
        "- ticket-1: open\n"
        "[2026-06-25T21:42:39Z]\n"
        "Q: what is open?\n"
        "A: ticket-1 is open\n"
    )
    mem.save_notes(text_with_transcript)
    saved = mem.load_notes()
    assert "Q: what is open?" not in saved
    assert "A: ticket-1 is open" not in saved
    assert "transcript block collapsed" in saved
    assert "## Active" in saved


# -- combined scrub + prune -------------------------------------------------


def test_scrub_and_prune_combined() -> None:
    """Transcript scrub followed by per-ticket prune works in sequence."""
    text = (
        "## Active\n"
        "- ticket-T1: open\n"
        "[2026-06-25T21:42:39Z]\n"
        "Q: status of T1?\n"
        "A: T1 is open\n"
        "ticket-T1: needs review\n"
    )
    # Apply scrub first, then prune.
    scrubbed = _prune_transcripts(text)
    assert "Q: status of T1?" not in scrubbed
    assert "transcript block collapsed" in scrubbed
    result = _prune_ticket_lines(scrubbed, "ticket-T1")
    assert "closed" in result
    assert "## Active" in result
    assert "needs review" not in result  # ticket line pruned


# -- reference material -----------------------------------------------------


def test_reference_roundtrip(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    assert mem.load_reference() == ""
    mem.save_reference("## State Machine\nopen → in_progress → review → done")
    assert "## State Machine" in mem.load_reference()
    assert (tmp_path / "mem_reference.md").exists()


def test_reference_capped(tmp_path: Path) -> None:
    """save_reference truncates to MAX_REFERENCE_CHARS."""
    from robotsix_board_agent.memory import MAX_REFERENCE_CHARS

    mem = BoardManagerMemory(tmp_path / "mem.json")
    long_text = "x" * (MAX_REFERENCE_CHARS + 500)
    mem.save_reference(long_text)
    assert len(mem.load_reference()) == MAX_REFERENCE_CHARS


def test_search_reference_finds_matches(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.save_reference(
        "## State Machine\n"
        "open → in_progress → review → done\n\n"
        "## Repo Registry\n"
        "frontend: react-app\n"
        "backend: api-server\n\n"
        "## Approval Inventory\n"
        "Ticket T-1: pending approval\n"
        "Ticket T-2: approved"
    )
    result = mem.search_reference("state machine")
    assert "open → in_progress" in result
    assert "Repo Registry" not in result  # no keyword match
    assert "Approval Inventory" not in result


def test_search_reference_matches_multiple_sections(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.save_reference(
        "## Section A\n"
        "contains keyword alpha\n\n"
        "## Section B\n"
        "no match here\n\n"
        "## Section C\n"
        "also contains keyword alpha"
    )
    result = mem.search_reference("keyword alpha")
    assert "Section A" in result
    assert "Section B" not in result
    assert "Section C" in result


def test_search_reference_no_match(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.save_reference("## Data\nsome content here")
    result = mem.search_reference("nonexistent")
    assert "no reference material matches" in result


def test_search_reference_empty_store(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    result = mem.search_reference("anything")
    assert "no reference material available" in result


def test_search_reference_empty_query(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.save_reference("## Data\nsome content")
    result = mem.search_reference("")
    assert "no reference material available" in result


def test_search_reference_case_insensitive(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    mem.save_reference("## STATE MACHINE\nOpen → In_Progress → Review")
    result = mem.search_reference("state machine")
    assert "STATE MACHINE" in result


def test_search_reference_result_capped(tmp_path: Path) -> None:
    """search_reference caps output at ~2000 chars."""
    mem = BoardManagerMemory(tmp_path / "mem.json")
    # Build many paragraphs that all match to exceed the cap.
    paragraphs = [f"## Section {i}\nkeyword present here " + "x" * 200 for i in range(30)]
    mem.save_reference("\n\n".join(paragraphs))
    result = mem.search_reference("keyword")
    assert len(result) <= 2010  # ~2000 chars + ellipsis


# -- save_notes truncation status -------------------------------------------


def test_save_notes_returns_truncation_status(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json", max_notes_chars=10)
    status = mem.save_notes("x" * 50)
    assert "truncated" in status
    assert "10" in status


def test_save_notes_returns_ok_when_within_cap(tmp_path: Path) -> None:
    mem = BoardManagerMemory(tmp_path / "mem.json")
    status = mem.save_notes("short note")
    assert status == "maintained memory updated"
    assert "truncated" not in status
