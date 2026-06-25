# Changelog

All notable changes to robotsix-board-agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Added dedicated test file `tests/constants/test_constants.py` for the constants module
- Fixed stale documentation: `docs/architecture.md` corrected maintained memory note cap from 8,000 to 2,000 characters to match `MAX_NOTES_CHARS`
- Added complexity classifier (`_select_manager_model`) that routes simple
  read-only board-status queries to a cheaper Claude tier (Sonnet/Haiku),
  reducing Opus token spend. Requests classified as COMPLEX or any that fail
  classification fall back to the default Opus level-3 agent.
- Added transcript guard (`_prune_transcripts`) to `save_notes` so Q&A blocks
  cannot accumulate in the maintained-memory note
- Closing a ticket via `mark_done` now prunes its detailed memory entries to a
  single summary line (`prune_closed_ticket`)
- Shrunk board-manager input tokens: reduced `MAX_NOTES_CHARS` from 8000 to
  2000 and updated the recall system prompt to produce 2-3 factual outcome
  summaries instead of verbatim transcripts. The maintained-memory system
  prompt now emphasises keeping only bare current state. (mill: board-manager: shrink system prompt — trim maintained-memory block and summarise verbatim history (20260624T212717Z-board-manager-shrink-system-prompt-trim-fd7c))

- Removed unused destructured bindings (`_Registry`, `_Request`) from
  `agent.py:_resolve_agent_comm()` call.

### Changed

- Removed the "REPOSITORY STRUCTURE" section from `_MANAGER_SYSTEM` prompt in
  `board_manager.py` — the BoardManager agent has no file-reading tools, so the
  guidance was inapplicable and wasted context tokens.

- Pinned `dangoslen/changelog-enforcer` GitHub Action to a specific commit SHA
  in `.github/workflows/ci.yml` for supply-chain security.

- Extracted duplicated Langfuse tracing setup into a shared `_setup_langfuse_tracing()`
  helper in `_imports.py`, replacing the identical 8-line `try/except ImportError`
  block that was duplicated in `agent.py` and `board_manager.py`.

- Updated system prompt with a repository-structure policy: the board-manager now
  trusts the architecture documentation for high-level design and module layout,
  and only drills into individual source files when the doc is missing detail or
  appears out of date. Reduces duplicate context tokens (~3,000-6,000 per run).

- Updated system prompt to avoid `board_cards` fallback when a ticket ID is unknown
  or partial — prevents wasted full-board-state loads (~5,000-15,000 tokens per
  lookup). The LLM is now instructed to use `list_tickets` with state filters or
  ask the user for the full ID instead.
- Shortened the default report format in `BoardManager`'s system prompt: the LLM now uses
  descriptive paragraph summaries at the file/function level and omits exhaustive file:line
  references unless explicitly requested, reducing output tokens by ~30-40% on analysis
  replies.

- Updated `Agent` and `BrokeredAgent` test stubs to accept broker connection parameters
  (`broker_host`, `broker_port`, `broker_scheme`, `broker_token`) and added lifecycle
  test assertions for those parameters.

### Added

- Added `ruff-check` CI job to `.github/workflows/ci.yml` for authoritative ruff enforcement
  on every push and PR, independent of pre-commit.ci.

- Extracted `_truncate_list` helper from `_truncate_result` — a pure, non-mutating function
  that returns a truncated copy and the omission count, reducing nesting depth and
  eliminating the in-place list mutation side-effect.

- Initial release.
- AGENT.md with repo conventions and hard rules for agents.
- Architecture overview page in documentation navigation.

### Removed

- Removed three redundant entries (`_handle_request`, `BrokeredBoardResponder`, `BoardManager`) from `vulture_whitelist.py` — these symbols are referenced by name in tests and scripts, so Vulture no longer flags them.
- **Breaking:** Removed the unused `openrouter_key` parameter from `BoardManager.__init__`. This parameter was never read and auth is handled via `claude login`.
