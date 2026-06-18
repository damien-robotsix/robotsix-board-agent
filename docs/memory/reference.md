# Board Manager Memory

`BoardManagerMemory` provides bounded, two-track persistence for the board
manager's conversational context.

## Two-track storage

| Track               | Format   | Purpose                                                    |
|---------------------|----------|------------------------------------------------------------|
| Conversation trace  | JSON     | Timestamped Q→A pairs; used by the level-1 recall scanner  |
| Maintained memory   | Markdown | Free-form note curated by the level-3 agent itself         |

The conversation trace holds only the user's question and the manager's final
answer — internal tool steps and reasoning are **not** stored, keeping the file
compact and coherent.

## Initialisation

```python
from pathlib import Path
from robotsix_board_agent.memory import BoardManagerMemory

memory = BoardManagerMemory(
    Path("memory.json"),
    max_conversations=200,
    max_notes_chars=8000,
)
```

### Constructor parameters

| Parameter           | Type   | Default | Purpose                                      |
|---------------------|--------|---------|----------------------------------------------|
| `path`              | `Path` | (required) | JSON file for the conversation trace       |
| `max_conversations` | `int`  | `200`   | Hard cap on retained Q→A pairs               |
| `max_notes_chars`   | `int`  | `8000`  | Hard cap on the maintained memory note (chars) |

The maintained-memory note is stored alongside the trace file with a `_notes.md`
suffix. For `path=Path("memory.json")`, the notes file is `memory_notes.md`.

## Conversation trace

### `load() -> list[dict[str, str]]`

Returns stored conversations as a list of `{timestamp, question, answer}` dicts,
oldest first. Returns an empty list if the file does not exist or is corrupted.

### `append(question, answer, *, timestamp=None)`

Appends a Q→A turn with an ISO-8601 timestamp (UTC `now()` by default) and
writes the JSON file. If the number of entries exceeds `max_conversations`, the
oldest entries are pruned.

### `as_prompt() -> str`

Renders all stored entries as a compact text block for an LLM:

```
[2025-01-01T00:00:00Z]
Q: what is the status of the auth epic?
A: ...
```

Returns an empty string when there are no stored entries.

## Maintained memory

### `load_notes() -> str`

Returns the agent-curated memory note. Returns `""` when the file does not exist
or is unreadable.

### `save_notes(text)`

Replaces the maintained memory note. The text is truncated to `max_notes_chars`.

## Pruning behavior

- The conversation trace is pruned on every `append()`: when the list exceeds
  `max_conversations`, the oldest entries (at the front of the list) are dropped.
- The maintained memory note is not pruned automatically — the level-3 agent is
  prompted to rewrite (not append) the note via the `update_memory` tool, keeping
  it concise under the `MAX_NOTES_CHARS` cap.

## Persistence path

Both files are created in the parent directory of `path` (directories are
auto-created on write).

| File              | Example path         | Content                |
|-------------------|----------------------|------------------------|
| Trace file        | `./memory.json`      | `[{timestamp, question, answer}, ...]` |
| Notes file        | `./memory_notes.md`  | Free-form agent note   |
