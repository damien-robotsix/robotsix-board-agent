"""Tests for the board manager's bounded conversation memory."""

from __future__ import annotations

from pathlib import Path

from robotsix_board_agent.memory import BoardManagerMemory


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
