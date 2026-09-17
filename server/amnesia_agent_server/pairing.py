"""Remote pairing codes and per-device bearer tokens."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from amnesia_agent_server.config import _atomic_write_json

PAIRING_TTL_SECONDS = 10 * 60
PAIRING_VERSION = 1


class PairingError(ValueError):
    """Raised when a pairing payload or code is invalid."""


@dataclass(frozen=True)
class PairingPayload:
    """One validated custom-scheme pairing payload."""

    server_url: str
    code: str
    version: int = PAIRING_VERSION


@dataclass(frozen=True)
class ActivePairing:
    code: str
    expires_at: float


class DeviceTokenStore:
    """Persist hashes of device tokens and authenticate bearer tokens."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def issue(self, label: str) -> tuple[str, str]:
        """Create one raw device token and persist only its hash."""
        token = secrets.token_urlsafe(32)
        device_id = uuid.uuid4().hex
        record = {
            "id": device_id,
            "label": label.strip()[:120] or "unnamed-device",
            "token_hash": _token_hash(token),
            "created_at": time.time(),
        }
        with self._lock:
            raw = self._read()
            devices = raw.setdefault("devices", [])
            devices.append(record)
            _atomic_write_json(self.path, raw)
        return device_id, token

    def authenticate(self, token: str) -> bool:
        if not token:
            return False
        candidate = _token_hash(token)
        with self._lock:
            return any(
                isinstance(device, dict)
                and secrets.compare_digest(str(device.get("token_hash", "")), candidate)
                for device in self._read().get("devices", [])
            )

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"devices": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"devices": []}
        if not isinstance(raw, dict) or not isinstance(raw.get("devices", []), list):
            return {"devices": []}
        return raw


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PairingManager:
    """Own the single rotating pairing code used by remote onboarding."""

    def __init__(
        self,
        public_url: str,
        device_tokens: DeviceTokenStore,
        *,
        ttl_seconds: int = PAIRING_TTL_SECONDS,
        on_rotate: Callable[[str], None] | None = None,
    ) -> None:
        self.public_url = _validate_public_url(public_url)
        self.device_tokens = device_tokens
        self.ttl_seconds = ttl_seconds
        self.on_rotate = on_rotate
        self._lock = threading.RLock()
        self._active: ActivePairing | None = None

    def current_payload(self, now: float | None = None) -> PairingPayload:
        now = time.time() if now is None else now
        with self._lock:
            if self._active is None or self._active.expires_at <= now:
                self._rotate_locked(now)
            assert self._active is not None
            return PairingPayload(self.public_url, self._active.code)

    def consume(self, code: str, label: str = "device") -> tuple[PairingPayload, str]:
        """Consume the active code and issue a new device token."""
        now = time.time()
        with self._lock:
            active = self._active
            if active is None or active.expires_at <= now:
                self._rotate_locked(now)
                raise PairingError("Pairing code has expired")
            if not secrets.compare_digest(code, active.code):
                raise PairingError("Pairing code is invalid or expired")
            consumed = PairingPayload(self.public_url, active.code)
            self._rotate_locked(now)
            _device_id, token = self.device_tokens.issue(label)
            return consumed, token

    def force_rotate(self) -> PairingPayload:
        with self._lock:
            self._rotate_locked(time.time())
            assert self._active is not None
            return PairingPayload(self.public_url, self._active.code)

    def expiry(self) -> float:
        """Return the active code expiry, creating a code if necessary."""
        self.current_payload()
        with self._lock:
            assert self._active is not None
            return self._active.expires_at

    def print_payload(self, payload: PairingPayload | None = None) -> None:
        """Print the QR and clickable/plain pairing link."""
        from amnesia_agent_server.qr import render_terminal_qr, terminal_hyperlink

        payload = payload or self.current_payload()
        link = self.pairing_link(payload)
        print(f"\nRemote pairing code active for {self.ttl_seconds // 60} minutes.", flush=True)
        print("Pairing link:", flush=True)
        print(terminal_hyperlink(link, link), flush=True)
        print("\nScan this QR code with the target device:", flush=True)
        try:
            print(render_terminal_qr(link), flush=True)
        except RuntimeError as error:
            print(f"[QR unavailable: {error}]", flush=True)
        expires = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(self.expiry()))
        print(f"Pairing link expires at {expires}.", flush=True)

    def pairing_link(self, payload: PairingPayload | None = None) -> str:
        payload = payload or self.current_payload()
        return "amnesia://pair?" + urlencode(
            {
                "v": payload.version,
                "server": payload.server_url,
                "code": payload.code,
            },
            quote_via=quote,
        )

    def _rotate_locked(self, now: float) -> None:
        self._active = ActivePairing(
            code=secrets.token_urlsafe(32),
            expires_at=now + self.ttl_seconds,
        )
        if self.on_rotate is not None:
            self.on_rotate(self.pairing_link(PairingPayload(self.public_url, self._active.code)))


def parse_pairing_link(value: str) -> PairingPayload:
    """Parse and validate an ``amnesia://pair`` link."""
    if not isinstance(value, str) or len(value) > 4096:
        raise PairingError("Pairing link is invalid")
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "amnesia" or parsed.netloc.lower() != "pair":
        raise PairingError("Pairing link must use amnesia://pair")
    if parsed.path or parsed.fragment:
        raise PairingError("Pairing link has an invalid path or fragment")
    values = dict(parse_qsl(parsed.query))
    if values.get("v") != str(PAIRING_VERSION):
        raise PairingError("Unsupported pairing link version")
    code = values.get("code", "")
    if not code or len(code) > 256:
        raise PairingError("Pairing link has no valid code")
    server_url = _validate_public_url(values.get("server", ""))
    return PairingPayload(server_url=server_url, code=code)


def _validate_public_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in ("http", "https")
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise PairingError("Pairing server URL must be an HTTP(S) origin")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise PairingError("Remote pairing server URL must use HTTPS")
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))
