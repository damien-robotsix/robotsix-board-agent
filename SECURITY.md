# Security Policy

## Supported Versions

This is a personal, solo-built project. No releases are published, no SLAs are
offered, and no security guarantees are provided. The project is made available
as-is under the MIT license.

Only the tip of `main` is ever "supported."

## Reporting a Vulnerability

**Do not** report security issues via public GitHub issues — use the private
[GitHub Security Advisories](https://github.com/damien-robotsix/robotsix-board-agent/security/advisories/new)
mechanism instead.

There is no promised timeline for a response or fix. I triage security reports
as time permits.

## Key Risk

This agent exposes the mill board's full ticket lifecycle over structured JSON
messages. Write operations — such as `create_ticket`, `transition`, `approve`,
`merge_now`, and `comment` — can modify board state. Users should:

- Run this agent only in a trusted environment with no sensitive data.
- Keep the board API token tightly scoped.
- Never expose the agent's communication channel beyond intended consumers.
