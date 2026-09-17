"""Global looping music service shared by the Ren'Py frontend pages."""

from __future__ import annotations

from typing import Any

try:
    import renpy  # type: ignore[import-not-found]
except ImportError:
    renpy = None  # type: ignore[assignment]

MUSIC_CHANNEL = "music"


class MusicPlayer:
    """Play looping music while suppressing replay of the current path."""

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend
        self._playing_path: str | None = None

    @property
    def playing_path(self) -> str | None:
        return self._playing_path

    def _resolved_backend(self) -> Any | None:
        if self._backend is not None:
            return self._backend
        if renpy is None:
            return None
        return getattr(renpy, "music", None)

    def play_looped(self, path: str) -> bool:
        """Play ``path`` on the shared music channel unless it is already playing."""
        if not isinstance(path, str) or not path:
            return False
        if path == self._playing_path:
            return False
        backend = self._resolved_backend()
        if backend is None:
            return False
        backend.play(path, channel=MUSIC_CHANNEL, loop=True)
        self._playing_path = path
        return True

    def stop(self) -> bool:
        """Stop the shared music channel and forget its current path."""
        backend = self._resolved_backend()
        was_playing = self._playing_path is not None
        if backend is not None:
            backend.stop(channel=MUSIC_CHANNEL)
        self._playing_path = None
        return was_playing


music = MusicPlayer()
