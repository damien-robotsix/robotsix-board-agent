# Board Manager Memory

`BoardManagerMemory` provides bounded, three-track persistence for the board
manager's conversational context.

## Three-track storage

| Track               | Format   | Purpose                                                    |
|---------------------|----------|------------------------------------------------------------|
| Conversation trace  | JSON     | Timestamped Q→A pairs; used by the level-1 recall scanner  |
| Maintained memory   | Markdown | Free-form note curated by the level-3 agent itself         |
| Reference material  | Markdown | Canonical reference data (state-machine catalog, repo      |
|                     |          | registry, epic genealogy, approval inventories); fetched    |
|                     |          | on-demand via the ``lookup_reference`` tool, not injected   |
|                     |          | on every call.                                             |

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
    max_notes_chars=2000,
)
```

### Constructor parameters

| Parameter           | Type   | Default | Purpose                                      |
|---------------------|--------|---------|----------------------------------------------|
| `path`              | `Path` | (required) | JSON file for the conversation trace       |
| `max_conversations` | `int`  | `200`   | Hard cap on retained Q→A pairs               |
| `max_notes_chars`   | `int`  | `2000`  | Hard cap on the maintained memory note (chars) |

The maintained-memory note is stored alongside the trace file with a `_notes.md`
suffix, and the reference-material file with a `_reference.md` suffix. For
`path=Path("memory.json")`, the files are `memory_notes.md` and
`memory_reference.md`.

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

### `save_notes(text) -> str`

Replaces the maintained memory note. Verbose Q&A transcript blocks are stripped
before saving (safety net — the agent is already prompted to summarise). The
text is truncated to `max_notes_chars`.

Returns `"maintained memory updated"` on success, or a truncation notice when
the input exceeded the cap — the agent can use this signal to trim stale entries
and retry.

## Reference material

### `load_reference() -> str`

Returns the reference-material file content (`""` when the file does not exist
or is unreadable). Called internally by `search_reference`; not exposed as an
LLM tool.

### `save_reference(text)`

Replaces the reference-material file, truncated to `MAX_REFERENCE_CHARS` (20,000).
Intended for integration code/tests to pre-populate the store, not for the LLM
agent to call directly.

### `search_reference(query: str) -> str`

Searches the reference material for paragraphs matching *query*. The text is
split on blank lines into paragraphs; any paragraph containing one of the query
words (case-insensitive, single-char words ignored) is included. The result is
capped at ~2,000 characters to keep the tool response lean.

Returns a plain-text summary or a notice when nothing matches. This is the
method backing the LLM tool `lookup_reference`.

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
| Reference file    | `./memory_reference.md`| Canonical reference material (state-
|                   |                      | machine catalog, repo registry, etc.) |
