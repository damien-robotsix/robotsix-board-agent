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
"""

from __future__ import annotations

import os
import sys

from robotsix_agent_comm.protocol import Error
from robotsix_agent_comm.sdk.agent import Agent
from robotsix_agent_comm.transport.brokered import create_transport_pair


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
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

    registry, transport = create_transport_pair(
        "brokered",
        broker_host=os.environ.get("ROBOTSIX_BROKER_HOST", "ai-broker.robotsix.net"),
        broker_port=int(os.environ.get("ROBOTSIX_BROKER_PORT", "443")),
        broker_scheme=os.environ.get("ROBOTSIX_BROKER_SCHEME", "https"),
        broker_token=token,
    )
    agent = Agent(
        os.environ.get("BOARD_MANAGER_CLI_ID", "board-manager-cli"),
        registry,
        transport=transport,
        pull=True,
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
