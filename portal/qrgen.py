"""Server-side QR code generation using `segno` (no PIL dependency).

Returns SVG by default — text format, scales perfectly, embeds inline in
the control-room wizard without an extra HTTP fetch.
"""
from __future__ import annotations

import io


def make_qr_svg(data: str, scale: int = 6, border: int = 2) -> str:
    """Encode `data` into a QR code as an SVG document string."""
    import segno
    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=scale, border=border, dark="#1f3a63", light="#ffffff", xmldecl=False, svgns=True)
    return buf.getvalue().decode("utf-8")


def make_qr_png_bytes(data: str, scale: int = 8, border: int = 2) -> bytes:
    """Encode `data` into a QR code as PNG bytes."""
    import segno
    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=border, dark="#1f3a63", light="#ffffff")
    return buf.getvalue()
