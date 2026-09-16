"""Command-line entry point for the local server."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import uuid

import uvicorn

from amnesia_agent_local_server.app import create_app


def is_loopback_host(host: str) -> bool:
    """Return True if *host* is a loopback bind target.

    Accepts ``localhost``, ``127.0.0.1``, ``::1``, bracketed IPv6 forms such as
    ``[::1]``, and any address in a loopback range (e.g. ``127.0.0.2``).
    Other hostnames and non-loopback IPs (including ``0.0.0.0`` / ``::``) are
    not treated as loopback.
    """
    normalized = host.strip().lower()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    # Drop IPv6 zone id if present (e.g. fe80::1%lo0).
    if "%" in normalized:
        normalized = normalized.split("%", 1)[0]
    if normalized in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the amnesia agent local server.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (loopback by default)")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--instance-id", default=None)
    args = parser.parse_args(argv)

    if not is_loopback_host(args.host):
        parser.error(
            f"Refusing to bind to non-loopback host {args.host!r}. "
            "Only loopback addresses (127.0.0.1, localhost, ::1, or a loopback "
            "range address) are supported."
        )

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
