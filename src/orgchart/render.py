"""Render the USMCC org chart to SVG (and PNG) from a steering file.

The chart is drawn as flat SVG: rounded group boxes, orthogonal connector
polylines, circular headshots and left- or below-aligned labels. Nothing is
painted behind the chart, so every output has a transparent background and
the same drawing is emitted once per theme.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

REPO = Path(__file__).resolve().parents[2]

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp"}

# (css family, weight, file in fonts/) embedded into every SVG.
FONT_FILES = [
    ("Lato", 400, "Lato-Regular.ttf"),
    ("Lato", 700, "Lato-Bold.ttf"),
    ("Source Sans Pro", 400, "SourceSansPro-Regular.ttf"),
    ("Source Sans Pro", 600, "SourceSansPro-SemiBold.ttf"),
]


# --------------------------------------------------------------------------
# config


@dataclass
class Person:
    id: str
    name: str
    role: str
    affiliation: str
    style: dict
    layout: str
    cx: float
    cy: float
    photo: Path | None

    @property
    def r(self) -> float:
        return self.style["r"]


def load_config(path: Path) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh)


def find_photo(person: dict, headshots: Path) -> Path | None:
    named = person.get("photo")
    if named:
        candidate = headshots / named
        return candidate if candidate.exists() else None
    for ext in PHOTO_EXTS:
        candidate = headshots / f"{person['id']}{ext}"
        if candidate.exists():
            return candidate
    return None


def build_people(cfg: dict, headshots: Path) -> dict[str, Person]:
    people = {}
    for entry in cfg["people"]:
        style = cfg["styles"][entry.get("style", "lg")]
        cx, cy = entry["at"]
        people[entry["id"]] = Person(
            id=entry["id"],
            name=entry["name"],
            role=entry.get("role", ""),
            affiliation=entry.get("affiliation", ""),
            style=style,
            layout=entry.get("layout", "left"),
            cx=cx,
            cy=cy,
            photo=find_photo(entry, headshots),
        )
    return people


def resolve(value, people: dict[str, Person]) -> float:
    """Resolve a coordinate that may be a number or an "<id>:<anchor>" ref."""
    if isinstance(value, (int, float)):
        return float(value)
    pid, _, anchor = str(value).partition(":")
    if pid not in people:
        raise KeyError(f"unknown person id in connector: {pid!r}")
    p = people[pid]
    try:
        return {
            "cx": p.cx, "cy": p.cy,
            "left": p.cx - p.r, "right": p.cx + p.r,
            "top": p.cy - p.r, "bottom": p.cy + p.r,
        }[anchor]
    except KeyError:
        raise KeyError(f"unknown anchor {anchor!r} on {pid!r}") from None


# --------------------------------------------------------------------------
# assets


def data_uri(path: Path) -> str:
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def font_face_css(fonts: Path) -> str:
    """Embed the TTFs so the SVG travels with its type."""
    faces = []
    for family, weight, filename in FONT_FILES:
        ttf = fonts / filename
        if not ttf.exists():
            continue
        blob = base64.b64encode(ttf.read_bytes()).decode()
        faces.append(
            f"@font-face{{font-family:'{family}';font-style:normal;"
            f"font-weight:{weight};"
            f"src:url(data:font/ttf;base64,{blob}) format('truetype');}}"
        )
    return "".join(faces)


def initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# --------------------------------------------------------------------------
# drawing


def stack(typo: dict, role: str) -> str:
    """CSS font stack for a typographic role ("display" or "secondary")."""
    return typo[role]["stack"]


def fmt(value: float) -> str:
    return f"{value:g}"


def text(x, y, content, *, size, weight, fill, anchor="start",
         stack=None) -> str:
    family = f' font-family="{escape(stack)}"' if stack else ""
    return (
        f'<text x="{fmt(x)}" y="{fmt(y)}"{family} font-size="{fmt(size)}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">'
        f"{escape(content)}</text>"
    )


def draw_headshot(p: Person, theme: dict, ring_w: float, typo: dict) -> str:
    clip = f"clip-{p.id}"
    out = [
        f'<clipPath id="{clip}"><circle cx="{fmt(p.cx)}" cy="{fmt(p.cy)}" '
        f'r="{fmt(p.r)}"/></clipPath>'
    ]
    if p.photo is not None:
        out.append(
            f'<image clip-path="url(#{clip})" x="{fmt(p.cx - p.r)}" '
            f'y="{fmt(p.cy - p.r)}" width="{fmt(2 * p.r)}" '
            f'height="{fmt(2 * p.r)}" preserveAspectRatio="xMidYMid slice" '
            f'href="{data_uri(p.photo)}"/>'
        )
    else:
        out.append(
            f'<circle cx="{fmt(p.cx)}" cy="{fmt(p.cy)}" r="{fmt(p.r)}" '
            f'fill="{theme["placeholder"]}" fill-opacity="0.10"/>'
        )
        out.append(
            text(p.cx, p.cy + p.r * 0.30, initials(p.name),
                 size=p.r * 0.78, weight=400, fill=theme["placeholder"],
                 anchor="middle", stack=stack(typo, "secondary"))
        )
    out.append(
        f'<circle cx="{fmt(p.cx)}" cy="{fmt(p.cy)}" r="{fmt(p.r)}" '
        f'fill="none" stroke="{theme["ring"]}" stroke-width="{fmt(ring_w)}"/>'
    )
    return "".join(out)


def draw_person(p: Person, theme: dict, ring_w: float, typo: dict) -> str:
    s = p.style
    dy = s["dy"]
    out = [f'<g id="node-{p.id}">', draw_headshot(p, theme, ring_w, typo)]
    if p.layout == "below":
        x, anchor = p.cx, "middle"
    else:
        x, anchor = p.cx + p.r + s["gap"], "start"
    out.append(text(x, p.cy + dy["name"], p.name,
                    size=s["name"]["size"], weight=s["name"]["weight"],
                    fill=theme["ink"], anchor=anchor,
                    stack=stack(typo, s["name"].get("font", "display"))))
    for key in ("role", "affiliation"):
        value = getattr(p, key)
        if value:
            out.append(text(x, p.cy + dy[key], value,
                            size=s["meta"]["size"], weight=s["meta"]["weight"],
                            fill=theme["muted"], anchor=anchor,
                            stack=stack(typo, s["meta"].get("font", "secondary"))))
    out.append("</g>")
    return "".join(out)


def draw_group(group: dict, theme: dict, strokes: dict, typo: dict) -> str:
    x, y, w, h = group["box"]
    out = [
        f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" '
        f'rx="{fmt(strokes["box_radius"])}" fill="none" '
        f'stroke="{theme["ink"]}" stroke-width="{fmt(strokes["box"])}"/>'
    ]
    label = group.get("label")
    if label:
        lx, ly = label["at"]
        step = label.get("line_height", label["size"] + 6)
        for i, line in enumerate(label["lines"]):
            out.append(text(lx, ly + i * step, line, size=label["size"],
                            weight=label.get("weight", 400), fill=theme["ink"],
                            anchor=label.get("align", "start"),
                            stack=stack(typo, label.get("font", "secondary"))))
    return "".join(out)


def draw_connector(points, people, theme, width) -> str:
    pts = " ".join(
        f"{fmt(resolve(x, people))},{fmt(resolve(y, people))}" for x, y in points
    )
    return (
        f'<polyline points="{pts}" fill="none" stroke="{theme["line"]}" '
        f'stroke-width="{fmt(width)}" stroke-linecap="square" '
        f'stroke-linejoin="miter"/>'
    )


def render(cfg: dict, theme_name: str, people: dict[str, Person],
           fonts: Path) -> str:
    theme = cfg["themes"][theme_name]
    strokes = cfg["strokes"]
    typo = cfg["typography"]
    w, h = cfg["canvas"]["width"], cfg["canvas"]["height"]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'font-family="{escape(typo["display"]["stack"])}">',
        f"<style>{font_face_css(fonts)}text{{font-kerning:normal}}</style>",
        f"<title>{escape(cfg['meta']['title'])} — {escape(str(cfg['meta']['date']))}</title>",
    ]

    tx, ty = typo["title"]["at"]
    parts.append(text(tx, ty, cfg["meta"]["title"], size=typo["title"]["size"],
                      weight=typo["title"]["weight"], fill=theme["ink"],
                      anchor="middle",
                      stack=stack(typo, typo["title"].get("font", "display"))))
    dx, dyy = typo["date"]["at"]
    parts.append(text(dx, dyy, str(cfg["meta"]["date"]),
                      size=typo["date"]["size"],
                      weight=typo["date"]["weight"], fill=theme["muted"],
                      anchor="middle",
                      stack=stack(typo, typo["date"].get("font", "secondary"))))

    for group in cfg.get("groups", []):
        parts.append(draw_group(group, theme, strokes, typo))
    for points in cfg.get("connectors", []):
        parts.append(draw_connector(points, people, theme, strokes["connector"]))
    for p in people.values():
        parts.append(draw_person(p, theme, strokes["ring"], typo))

    parts.append("</svg>")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# PNG


def fontconfig_env(fonts: Path) -> dict:
    """Point fontconfig at the repo font directory so PNGs use Lato too."""
    conf = Path(tempfile.mkdtemp(prefix="orgchart-fc-")) / "fonts.conf"
    conf.write_text(
        '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">'
        f"<fontconfig><dir>{fonts}</dir>"
        "<dir>/usr/share/fonts</dir><dir>~/.fonts</dir>"
        f"<cachedir>{conf.parent}</cachedir></fontconfig>"
    )
    env = dict(os.environ)
    env["FONTCONFIG_FILE"] = str(conf)
    return env


def write_png(svg_path: Path, png_path: Path, scale: float, fonts: Path) -> bool:
    if importlib.util.find_spec("cairosvg") is None:
        return False
    # cairo resolves fonts through fontconfig, which reads its configuration
    # when the library is first loaded, so the environment has to be set
    # before cairosvg is imported.
    os.environ.update(fontconfig_env(fonts))
    import cairosvg

    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), scale=scale,
                     background_color="transparent")
    return True


# --------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-c", "--config", type=Path,
                    default=REPO / "config" / "chart.yaml")
    ap.add_argument("-o", "--out", type=Path, default=REPO / "out")
    ap.add_argument("--headshots", type=Path, default=REPO / "headshots")
    ap.add_argument("--fonts", type=Path, default=REPO / "fonts")
    ap.add_argument("--themes", nargs="*", default=None,
                    help="themes to render (default: all in the config)")
    ap.add_argument("--scale", type=float, default=2.0,
                    help="PNG scale factor relative to the SVG canvas")
    ap.add_argument("--no-png", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    people = build_people(cfg, args.headshots)
    args.out.mkdir(parents=True, exist_ok=True)

    missing = [p.id for p in people.values() if p.photo is None]
    if missing:
        print(f"note: no headshot found for {', '.join(missing)} "
              f"(drawing initials placeholders); add files to "
              f"{args.headshots}/<id>.jpg", file=sys.stderr)
    if not all((args.fonts / f).exists() for _, _, f in FONT_FILES):
        print("note: fonts/ is incomplete — run scripts/fetch-fonts.sh to "
              "embed Lato and Source Sans Pro; falling back to system sans",
              file=sys.stderr)

    base = cfg["meta"].get("basename", "org-chart")
    for theme_name in (args.themes or list(cfg["themes"])):
        svg_path = args.out / f"{base}-{theme_name}.svg"
        svg_path.write_text(render(cfg, theme_name, people, args.fonts))
        print(f"wrote {svg_path.relative_to(REPO)}")
        if not args.no_png:
            png_path = svg_path.with_suffix(".png")
            if write_png(svg_path, png_path, args.scale, args.fonts):
                print(f"wrote {png_path.relative_to(REPO)}")
            else:
                print("note: cairosvg not installed — skipping PNG "
                      "(pip install cairosvg)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
