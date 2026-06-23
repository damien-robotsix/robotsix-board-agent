# Changelog

All notable changes to robotsix-board-agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Extracted `_truncate_list` helper from `_truncate_result` — a pure, non-mutating function
  that returns a truncated copy and the omission count, reducing nesting depth and
  eliminating the in-place list mutation side-effect.

- Initial release.
- AGENT.md with repo conventions and hard rules for agents.
- Architecture overview page in documentation navigation.
