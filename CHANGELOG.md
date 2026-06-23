# Changelog

All notable changes to robotsix-board-agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial release.
- AGENT.md with repo conventions and hard rules for agents.
- Architecture overview page in documentation navigation.

### Removed

- **Breaking:** Removed the unused `openrouter_key` parameter from `BoardManager.__init__`. This parameter was never read and auth is handled via `claude login`.
