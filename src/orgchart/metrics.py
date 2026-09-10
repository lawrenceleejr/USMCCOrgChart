"""Text measurement, so the layout audit can reason about real ink boxes."""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

# family -> weight -> file in fonts/
FILES = {
    "Lato": {400: "Lato-Regular.ttf", 700: "Lato-Bold.ttf"},
    "Source Sans Pro": {400: "SourceSansPro-Regular.ttf",
                        600: "SourceSansPro-SemiBold.ttf"},
}


def _file(fonts: Path, family: str, weight: int) -> Path | None:
    faces = FILES.get(family)
    if not faces:
        return None
    # nearest available weight
    weight = min(faces, key=lambda w: abs(w - int(weight)))
    path = fonts / faces[weight]
    return path if path.exists() else None


@lru_cache(maxsize=None)
def _font(path: str, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(path, size)


def extent(fonts: Path, family: str, weight: int, content: str,
           size: float) -> tuple[float, float, float, float]:
    """Ink box of `content` relative to its left-baseline origin, y down.

    Falls back to a rough estimate when Pillow or the font file is missing,
    which keeps the audit useful (if blunter) on a bare checkout.
    """
    path = _file(fonts, family, weight)
    if path is not None and importlib.util.find_spec("PIL") is not None:
        font = _font(str(path), int(round(size)))
        x0, y0, x1, y1 = font.getbbox(content, anchor="ls")
        return float(x0), float(y0), float(x1), float(y1)
    width = 0.52 * size * len(content)
    return 0.0, -0.74 * size, width, 0.21 * size
