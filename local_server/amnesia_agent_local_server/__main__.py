"""Command-line entry point for the local server."""

from __future__ import annotations

import argparse
import asyncio
import uuid

import uvicorn

from amnesia_agent_local_server.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the amnesia agent local server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (loopback by default)")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--instance-id", default=None)
    args = parser.parse_args()

    application = create_app(instance_id=args.instance_id or uuid.uuid4().hex)
    config = uvicorn.Config(
        application,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )
    server = uvicorn.Server(config)
    application.state.uvicorn_server = server
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
