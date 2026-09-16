"""Ren'Py displayable adapters for validated media assets."""

from __future__ import annotations

from typing import Any

from characters.loader import MediaAsset


def make_displayable(asset: MediaAsset) -> Any:
    """Build a Ren'Py image or PNG-sequence displayable for an asset."""
    if len(asset.frames) == 1:
        return asset.frames[0]

    try:
        from renpy.display.anim import Animation  # type: ignore[import-not-found]
    except ImportError:
        return asset.path

    delay = 1.0 / asset.fps
    args: list[Any] = []
    for frame in asset.frames[:-1]:
        args.extend((frame, delay))
    if asset.loop:
        args.extend((asset.frames[-1], delay))
    else:
        # Animation holds the final displayable for its remaining lifetime.
        args.append(asset.frames[-1])
    return Animation(*args)
