## 0.0.0 (unreleased)

- Added "Documentation conventions" section to AGENT.md: new docs files
  under `docs/` must have a corresponding `mkdocs.yml` nav entry.
- Add `docs/configuration.md` to the `mkdocs.yml` nav so the configuration guide is discoverable from the documentation site sidebar.
- Added `get_multiple_ticket_descriptions` to the read-operations table in `docs/client/api.md` (the method already existed in code and other docs but was missing from this table).
# Changelog

All notable changes to robotsix-board-agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Added ``codespell`` and ``markdownlint-cli2`` pre-commit hooks for automated
  documentation quality checks

- Added unit tests for ``scripts/check_kind_literals.py`` covering
  ``_is_kind_context``, ``_read_default_ticket_kind``, ``_find_kind_literals``,
  and ``main``

- Added ``env_doc_sync`` periodic workflow and ``docs/configuration.md``
  documenting all environment variables

- Added ``continue-on-error`` to the ``dependency-submission`` CI job to
  prevent non-critical dependency-graph submission failures from blocking CI

- Added direct unit tests for `_TicketCache` (TTL-based ticket read cache) in
  `test_board_manager.py`

- Added CycloneDX SBOM generation to the release workflow (``sbom`` job) and
  dependency-graph submission to CI (``dependency-submission`` job) for
  supply-chain transparency

- Added ``actionlint`` job to CI pipeline for GitHub Actions workflow
  syntax/expression validation, complementing the existing ``zizmor``
  security audit job. Also added ``actionlint-docker`` pre-commit hook.
- Fixed stale op count in `docs/architecture.md`: changed "15 ops" to "16 ops"
  to match the actual `OP_TABLE` size (7 read + 9 write).

- Trimmed board-manager recall-prompt bloat: added ``max_recall_conversations``
  parameter (default 50) to cap the number of prior Q&A pairs sent to the recall
  LLM scan each turn, preventing accumulated conversation history from bloating
  every invocation.  The full trace is still kept on disk for traceability; only
  the recall prompt is capped.

- Documented ``max_output_chars`` field in ``docs/config/reference.md`` fields table and usage example.

- Changed complexity-classifier tiebreaker for MODERATE-vs-COMPLEX from COMPLEX to
  MODERATE so ambiguous requests default to the cheaper Sonnet tier instead of
  Opus, reducing per-trace cost.

- Fixed mypy strict type errors in test suite: added ``Generator`` return types for
  fixtures that ``yield``, annotated untyped function signatures with ``Any``, and
  added ``# type: ignore[method-assign]`` for MagicMock attribute assignments

- Promoted `constants` to a standalone module: added module entry in `docs/modules.yaml`,
  created `docs/constants/reference.md` documenting `DEFAULT_*` constants and
  `BoardErrorCode` enum, and removed constants paths from the `__init__` module.

- Added community health files: issue templates (bug report, feature request),
  PR template, and ``FUNDING.yml``

- Fixed stale tool counts in documentation: `docs/architecture.md` now says
  "16 board operations + update_memory + lookup_reference", and
  `docs/board_manager/api.md` now includes the missing
  `get_multiple_ticket_descriptions` row in the tool table.

- Added ``LOG_LEVEL`` environment variable support for controlling logging verbosity
  (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``) — the library
  (``agent.py``) defaults to ``INFO`` and the CLI (``manager_cli.py``) defaults to
  ``WARNING``; invalid values silently fall back to the respective default

- Restored public API re-exports in ``src/robotsix_board_agent/__init__.py``
  (deleted by a docs-stage commit; ``BoardAgent``, ``BoardClient``,
  ``BoardAgentSettings``, ``OP_TABLE``, ``WRITE_OPS``, ``BoardOp``,
  ``UnknownOpError``, ``dispatch``, ``BoardAPIError``)
- Removed orphaned ``.robotsix-mill/periodic/langfuse_cleanup.yaml`` periodic config
  (empty placeholder that was never wired into the mill scheduler)
- Documented ``get_multiple_ticket_descriptions`` read operation in `docs/ops/operations.md`

- Added ``max_output_chars`` row to the ``BoardAgentSettings`` field table in
  ``AGENT.md`` (was missing after the field was added in a prior ticket), and
  added a rule requiring table updates when new config fields are added
- Suppressed verbose LLM output in board-manager: added "SILENCE BETWEEN TOOLS"
  prompt rule to eliminate step-by-step narration between tool calls, tightened
  the REPORT FORMAT section to demand extremely terse ids+outcomes-only replies,
  and added a configurable ``max_output_chars`` guard (default 2,000) to truncate
  overlong answers — targets the ~99% output-token cost dominance observed in
  fleet cost analysis
- Right-sized board-manager model routing: trivial read-only/status/listing turns
  now default to Haiku (was Sonnet), straightforward CRUD/dedup/organisation
  turns route to Sonnet via a new `moderate_model` parameter, and only genuinely
  ambiguous multi-step planning runs on Opus. The three-tier classifier
  (`SIMPLE_READ`/`MODERATE`/`COMPLEX`) stays within the Claude subscription SKU
  — no pay-per-token path introduced.
- Tightened `bump-git-pin.yml` workflow: `new-rev` input now requires a full
  40-character commit SHA (used directly without `git ls-remote` resolution);
  short SHAs (< 40 chars) are rejected, and only `latest-main` is resolved
- Added `get_multiple_ticket_descriptions` — a batch read tool that fetches
  descriptions for an arbitrary list of ticket ids in a single round-trip,
  replacing N sequential `get_ticket`/`ticket_description` calls.  The
  `BoardClient` method issues concurrent `GET /tickets/{id}/description`
  requests; individual failures are captured as per-ticket error entries so
  partial results are always returned.  The board-manager system prompt now
  instructs the agent to batch-fetch all needed descriptions in one pass.
- Added reusable `bump-git-pin.yml` workflow and `scripts/bump_git_pin.py` for
  automated single-package git-pin bumps — resolves target commits, updates
  `pyproject.toml` `[tool.uv.sources]`, refreshes the lockfile, and opens a PR
- Updated `deps-bump.yml` to support both periodic batch `uv lock --upgrade`
  refreshes (via robotsix-mill) and single-package pin bumps (via the new
  reusable workflow), gated by `workflow_dispatch` inputs
- Bumped `robotsix-llmio` pin from `28b23a848003` to `3da3c4317f4a` to unblock
  fleet-wide `sqlite_utils` adoption (includes `core/sqlite_utils.py`)
- **BoardManager**: Read-only ticket-status queries are now served directly from
  the board API without spawning an LLM call, avoiding unnecessary Claude-SDK
  subscription spend on status polls.  A short-TTL cache (default 5 min) avoids
  repeated board-API calls for the same ticket id.
- Added tests for `_fast_read_ticket`, cache hit/expiry, write-intent gating,
  and API-error fallback in `TestFastReadTicket`.
- Added test coverage for `_truncate_result`: a new unit test verifies that
  non-list results (e.g. plain strings) are returned unchanged, bypassing
  truncation even when they exceed `_RESULT_CAP`
- Added docstrings to all 15 private `_*` handler functions in `ops.py`
  (`_list_tickets`, `_get_ticket`, `_board_cards`, `_history`, `_merge_status`,
  `_description`, `_create_ticket`, `_add_comment`, `_transition`, `_approve`,
  `_mark_done`, `_merge_now`, `_resume_blocked`, `_migrate`, `_set_priority`)
- Fixed zizmor alerts (artipacked, ref-version-mismatch, dependabot-cooldown) in CI workflows
- Fixed CodeQL alerts (py/empty-except, py/import-and-import-from) in `_imports.py`, `test__imports.py`, and `completeness_check.py`
- Pinned `astral-sh/setup-uv` to correct v5 commit SHA and added
  `persist-credentials: false` to all `actions/checkout` steps in CI workflow
- Removed the `dependency-review` CI job — the repository does not have
  Dependency graph enabled, so the action cannot run
- Removed the empty `tracing` optional-dependency group from `pyproject.toml`
- Migrated zizmor pre-commit hook from local `language: system` to official
  `zizmorcore/zizmor-pre-commit` managed repo (v1.23.1) with `--offline` arg,
  ensuring the hook works without manual global zizmor installation
- Refactored `_prune_transcripts`: extracted `_find_and_collapse_block` helper to
  reduce nesting from depth-5 to depth-2 and simplify index tracking
- Fixed `_CLASSIFY_SYSTEM` prompt parenthetical to use actual tool names
  (`merge_now`, `resume_blocked`) instead of the mismatched shorthands
  (`merge`, `resume`)
- Fixed `_MANAGER_SYSTEM` prompt parenthetical to use actual tool names
  (`merge_now`, `resume_blocked`) instead of the mismatched shorthands
  (`merge`, `resume`)
- Added direct unit tests for the `_truncate_list` helper in `test_board_manager.py`
- Added `zizmor` CI job to `.github/workflows/ci.yml` for GitHub Actions workflow
  security auditing (SARIF output for Code Scanning), and a local pre-commit hook
- Added reference-material store (`_reference.md` sibling file) separate from
  the maintained-memory note, with ``lookup_reference`` tool for on-demand
  keyword search — reference material (state-machine catalog, repo registry,
  etc.) is no longer injected into every LLM call, only fetched when needed
- ``update_memory`` now returns an explicit truncation notice when the
  maintained-memory note exceeds the character cap, so the agent can trim
  stale entries
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
