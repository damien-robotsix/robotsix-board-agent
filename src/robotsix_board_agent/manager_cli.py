"""Talk to the board manager over the broker in natural language.

Usage::

    robotsix-board-manager "close all stale draft tickets"
    robotsix-board-manager what is the status of the auth epic?

Environment:
    ROBOTSIX_BROKER_HOST    broker host (default: ai-broker.robotsix.net)
    ROBOTSIX_BROKER_PORT    broker port (default: 443)
    ROBOTSIX_BROKER_SCHEME  http/https  (default: https)
    BOARD_MANAGER_CLI_TOKEN this CLI's broker bearer token (required)
    BOARD_MANAGER_CLI_ID    this CLI's agent id (default: board-manager-cli)
    BOARD_MANAGER_TARGET    manager agent id (default: board-manager-robotsix-mill)
    LOG_LEVEL               logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL;
                            default: WARNING)
"""

from __future__ import annotations

import logging as _logging
import os
import sys

from robotsix_agent_comm.protocol import Error
from robotsix_agent_comm.sdk import BrokeredAgent


def main(argv: list[str] | None = None) -> int:
    """Send a natural-language instruction to the board manager via the broker.

    *argv* — optional argument list (defaults to ``sys.argv[1:]``).  The first
    argument (or the joined argument string) is sent as a message to the
    broker-registered board manager.  Returns 0 on success, 2 on usage or config
    errors.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    _log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
    _valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if _log_level not in _valid_levels:
        _log_level = "WARNING"
    _logging.basicConfig(
        level=getattr(_logging, _log_level, _logging.WARNING),
        format="%(levelname)s:%(name)s:%(message)s",
    )

    if not args:
        print(
            'usage: robotsix-board-manager "<natural-language instruction>"',
            file=sys.stderr,
        )
        return 2
    message = " ".join(args)

    token = os.environ.get("BOARD_MANAGER_CLI_TOKEN")
    if not token:
        print("BOARD_MANAGER_CLI_TOKEN is required", file=sys.stderr)
        return 2

    agent = BrokeredAgent(
        os.environ.get("BOARD_MANAGER_CLI_ID", "board-manager-cli"),
        broker_host=os.environ.get("ROBOTSIX_BROKER_HOST", "ai-broker.robotsix.net"),
        broker_port=int(os.environ.get("ROBOTSIX_BROKER_PORT", "443")),
        broker_scheme=os.environ.get("ROBOTSIX_BROKER_SCHEME", "https"),
        broker_token=token,
        timeout=180.0,
    )
    target = os.environ.get("BOARD_MANAGER_TARGET", "board-manager-robotsix-mill")
    with agent:
        reply = agent.send_request(target, {"message": message}, timeout=180.0)

    body = getattr(reply, "body", None)
    if isinstance(body, dict) and "reply" in body:
        print(body["reply"])
    else:
        print(body)
    return 1 if isinstance(reply, Error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
