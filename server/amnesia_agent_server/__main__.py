"""Command-line entry point for the server."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import uuid

import uvicorn

from amnesia_agent_server.app import create_app
from amnesia_agent_server.config import ConfigStore
from amnesia_agent_server.pairing import DeviceTokenStore, PairingManager


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
    parser = argparse.ArgumentParser(description="Run the amnesia agent server.")
    parser.add_argument("--host", default=None, help="Bind host (loopback by default)")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--instance-id", default=None)
    parser.add_argument("--remote", action="store_true", help="Enable authenticated remote mode")
    parser.add_argument(
        "--public-url",
        default=os.environ.get("AMNESIA_PUBLIC_URL"),
        help="Public HTTP(S) origin used in pairing links",
    )
    parser.add_argument("--tls-cert", default=None)
    parser.add_argument("--tls-key", default=None)
    parser.add_argument("--workspace-root", default=None)
    args = parser.parse_args(argv)

    host = args.host or "127.0.0.1"
    if not args.remote and not is_loopback_host(host):
        parser.error(
            f"Refusing to bind to non-loopback host {host!r}. Use --remote for "
            "authenticated remote mode."
        )
    if args.remote and not args.public_url:
        parser.error("--remote requires --public-url or AMNESIA_PUBLIC_URL")
    if args.remote and not is_loopback_host(host) and not (args.tls_cert and args.tls_key):
        parser.error(
            "A non-loopback remote bind requires --tls-cert and --tls-key; "
            "use --host 127.0.0.1 behind an HTTPS reverse proxy instead."
        )
    if (args.tls_cert is None) != (args.tls_key is None):
        parser.error("--tls-cert and --tls-key must be supplied together")

    config_store = ConfigStore()
    pairing_manager = None
    if args.remote:
        device_tokens = DeviceTokenStore(config_store.root / "device-tokens.json")
        pairing_manager = PairingManager(
            args.public_url,
            device_tokens,
            on_rotate=lambda _link: None,
        )

    application = create_app(
        config_store=config_store,
        instance_id=args.instance_id or uuid.uuid4().hex,
        remote=args.remote,
        public_url=args.public_url,
        pairing_manager=pairing_manager,
        workspace_root=args.workspace_root,
    )
    if pairing_manager is not None:
        pairing_manager.on_rotate = lambda _link: pairing_manager.print_payload()
    config = uvicorn.Config(
        application,
        host=host,
        port=args.port,
        log_level=args.log_level,
        ssl_certfile=args.tls_cert,
        ssl_keyfile=args.tls_key,
    )
    server = uvicorn.Server(config)
    application.state.uvicorn_server = server
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
