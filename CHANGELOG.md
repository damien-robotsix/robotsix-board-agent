# Changelog

All notable changes to robotsix-board-agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Updated system prompt to avoid `board_cards` fallback when a ticket ID is unknown
  or partial — prevents wasted full-board-state loads (~5,000-15,000 tokens per
  lookup). The LLM is now instructed to use `list_tickets` with state filters or
  ask the user for the full ID instead.

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

- **Breaking:** Removed the unused `openrouter_key` parameter from `BoardManager.__init__`. This parameter was never read and auth is handled via `claude login`.
