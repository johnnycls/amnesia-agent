"""Terminal rendering for pairing QR codes."""

from __future__ import annotations


def render_terminal_qr(value: str) -> str:
    """Render *value* as a compact Unicode QR code.

    ``segno`` is a small pure-Python dependency of the server package.
    Import it lazily so local-mode tests and clients do not pay QR setup costs.
    """
    try:
        import segno
    except ImportError as error:  # pragma: no cover - packaging failure
        raise RuntimeError("QR output requires the segno package") from error

    qr = segno.make(value, micro=False)
    matrix = qr.matrix
    quiet = 2
    rows: list[str] = []
    blank = " " * ((len(matrix[0]) + quiet * 2) * 2)
    rows.extend([blank] * quiet)
    for row in matrix:
        padded = [False] * quiet + list(row) + [False] * quiet
        # ASCII keeps the QR readable in Windows and SSH terminals with
        # incompatible Unicode code pages. Two columns per module preserve
        # approximately square modules on normal terminal fonts.
        rows.append("".join("##" if cell else "  " for cell in padded))
    rows.extend([blank] * quiet)
    return "\n".join(rows)


def terminal_hyperlink(label: str, url: str) -> str:
    """Return an OSC-8 hyperlink with a plain label fallback."""
    return f"\x1b]8;;{url}\x1b\\{label}\x1b]8;;\x1b\\"
