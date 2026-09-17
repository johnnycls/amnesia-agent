"""Validation for OS-delivered amnesia:// pairing links."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from api.client import ServerUrlError, normalize_server_url


class PairingLinkError(ValueError):
    """Raised when an incoming pairing link is not safe to process."""


@dataclass(frozen=True)
class PairingPayload:
    server_url: str
    code: str
    version: int = 1


def parse_pairing_link(value: str) -> PairingPayload:
    if not isinstance(value, str) or len(value) > 4096:
        raise PairingLinkError("Pairing link is invalid")
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "amnesia" or parsed.netloc.lower() != "pair":
        raise PairingLinkError("Pairing link must use amnesia://pair")
    if parsed.path or parsed.fragment:
        raise PairingLinkError("Pairing link has an invalid path or fragment")
    query = parse_qs(parsed.query, keep_blank_values=True)
    version = query.get("v", [""])[0]
    if version != "1":
        raise PairingLinkError("Unsupported pairing link version")
    code = query.get("code", [""])[0]
    if not code or len(code) > 256:
        raise PairingLinkError("Pairing link has no valid code")
    raw_server = query.get("server", [""])[0]
    try:
        server_url = normalize_server_url(raw_server)
    except ServerUrlError as error:
        raise PairingLinkError(str(error)) from error
    if server_url.startswith("http://"):
        host = urlsplit(server_url).hostname
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise PairingLinkError("Remote pairing links must use HTTPS")
    return PairingPayload(server_url=server_url, code=code)
