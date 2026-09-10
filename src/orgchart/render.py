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
from dataclasses import dataclass, field
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
    roles: list[str]
    affiliation: str
    style: dict
    layout: str
    cx: float
    cy: float
    photo: Path | None
    crop: dict
    # which of the lines under the name to draw, and in what order
    order: list[str] = field(default_factory=lambda: ["role", "affiliation"])

    @property
    def r(self) -> float:
        return self.style["r"]

    def meta(self) -> list[tuple[str, str]]:
        """The lines under the name, in the person's `order`.

        Roles come before the affiliation unless the entry says otherwise.

        A role given as an empty string keeps its line but draws nothing,
        which lines affiliations up across a row where only some people
        carry a title.
        """
        lines: list[tuple[str, str]] = []
        for key in self.order:
            if key == "role":
                lines += [(f"role{i}", r) for i, r in enumerate(self.roles)]
            elif self.affiliation:
                lines.append(("affiliation", self.affiliation))
        return lines

    def meta_dy(self, index: int) -> float:
        """Baseline offset of the index-th line under the name.

        Roles stack downwards on the configured role/affiliation spacing, so
        a single-role node lands exactly where it always did.
        """
        dy = self.style["dy"]
        step = dy["affiliation"] - dy["role"]
        return dy["role"] + index * step


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


DEFAULT_CROP = {"zoom": 1.0, "dx": 0.0, "dy": 0.0}


def nudge(crop: dict, tweak: dict | None) -> dict:
    """Apply a hand tweak on top of a computed crop.

    `dx`/`dy` shift the subject within the circle, in canvas units —
    negative dx moves them left, positive dy moves them down — and
    `scale` multiplies the framed zoom. They are relative, so re-running
    the framer does not throw the tweak away.
    """
    if not tweak:
        return crop
    return {**crop,
            "zoom": crop["zoom"] * float(tweak.get("scale", 1.0)),
            "dx": crop["dx"] + float(tweak.get("dx", 0.0)),
            "dy": crop["dy"] + float(tweak.get("dy", 0.0))}


def load_framing(path: Path | None) -> dict:
    """Generated per-person crop knobs, if they have been computed."""
    if path is None or not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def build_people(cfg: dict, headshots: Path,
                 framing: Path | None = None) -> dict[str, Person]:
    base_crop = {**DEFAULT_CROP, **(cfg.get("defaults", {}).get("crop") or {})}
    computed = load_framing(framing)
    entries = {e["id"]: e for e in cfg["people"]}
    people = {}
    for entry in cfg["people"]:
        style = cfg["styles"][entry.get("style", "lg")]
        cx, cy = entry["at"]
        # an absent role means no line at all; an empty one reserves it
        role = entry.get("role") if "role" in entry else None
        # someone who sits in two places on the chart is one person: the
        # second entry borrows the first's photo and framing
        source = entries.get(entry.get("alias_of"), entry)
        people[entry["id"]] = Person(
            id=entry["id"],
            name=entry["name"],
            roles=([] if role is None else
                   [role] if isinstance(role, str) else list(role)),
            affiliation=entry.get("affiliation", ""),
            style=style,
            layout=entry.get("layout", "left"),
            order=list(entry.get("order", ("role", "affiliation"))),
            cx=cx,
            cy=cy,
            photo=find_photo(source, headshots),
            # generated framing sits under anything set by hand, then any
            # nudge is applied relative to the result
            crop=nudge(
                {**base_crop, **(computed.get(source["id"]) or {}),
                 **(entry.get("crop") or {})},
                entry.get("nudge")),
        )
    return people


def text_extent(cfg: dict, role: str, size: float, weight: int, content: str,
                fonts: Path) -> tuple[float, float, float, float]:
    """Ink box of a text run relative to its (x, baseline) anchor point."""
    from . import metrics

    return metrics.extent(fonts, cfg["typography"][role]["family"], weight,
                          content, size)


def wrap(cfg: dict, spec: dict, content: str, fonts: Path) -> list[str]:
    """Break a sentence into lines that fit `spec["width"]` canvas units."""
    role = spec.get("font", "secondary")
    size, weight = spec["size"], spec.get("weight", 400)
    width = spec["width"]
    lines, current = [], ""
    for word in content.split():
        trial = f"{current} {word}".strip()
        x0, _, x1, _ = text_extent(cfg, role, size, weight, trial, fonts)
        if current and x1 - x0 > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def group_text_lines(group: dict, cfg: dict, fonts: Path) -> list[str]:
    spec = group.get("text")
    return wrap(cfg, spec, spec["content"], fonts) if spec else []


def person_boxes(p: Person, cfg: dict, fonts: Path) -> list[tuple]:
    """Text ink boxes for a person, in absolute canvas coordinates."""
    st = p.style
    x = p.cx if p.layout == "below" else p.cx + p.r + st["gap"]
    runs = [("name", p.name, st["name"], st["dy"]["name"])]
    for i, (key, content) in enumerate(p.meta()):
        runs.append((key, content, st["meta"], p.meta_dy(i)))
    boxes = []
    for key, content, spec, offset in runs:
        if not content:
            continue
        role = spec.get("font", "display" if key == "name" else "secondary")
        x0, y0, x1, y1 = text_extent(cfg, role, spec["size"], spec["weight"],
                                     content, fonts)
        w = x1 - x0
        left = x + x0 - (w / 2 if p.layout == "below" else 0)
        top = p.cy + offset + y0
        boxes.append((f"{p.id}.{key}", left, top, left + w, top + (y1 - y0)))
    return boxes


def group_boxes(cfg: dict, people: dict[str, Person],
                fonts: Path) -> dict[str, tuple[float, float, float, float]]:
    """Resolve every group container to (x, y, w, h).

    A group with `members` is sized to enclose those people — headshots and
    labels alike — with `padding` of clear space on every side, so a box can
    never crop what it contains. `match_vertical` copies another group's top
    and height, which keeps side-by-side containers aligned.
    """
    pad_default = cfg.get("clearance", {}).get("box_padding", 20)
    resolved: dict[str, tuple] = {}
    pending = list(cfg.get("groups", []))
    for _ in range(len(pending) + 1):
        deferred = []
        for g in pending:
            if "box" in g:
                resolved[g["id"]] = tuple(g["box"])
                continue
            pad = g.get("padding", pad_default)
            # a scalar pads every side; a list is [top, right, bottom, left],
            # which lets a box reserve a band for its own label
            pt, pr, pb, pl = ((pad,) * 4 if isinstance(pad, (int, float))
                              else tuple(pad))
            if g.get("members"):
                xs, ys = [], []
                for pid in g["members"]:
                    person = people[pid]
                    xs += [person.cx - person.r, person.cx + person.r]
                    ys += [person.cy - person.r, person.cy + person.r]
                    for _n, x0, y0, x1, y1 in person_boxes(person, cfg, fonts):
                        xs += [x0, x1]
                        ys += [y0, y1]
                x, y = min(xs) - pl, min(ys) - pt
                w, h = max(xs) + pr - x, max(ys) + pb - y
            else:
                x, y, w, h = g.get("x", 0), 0, g.get("width", 0), 0
            # a prose block has to fit inside the box that carries it
            spec = g.get("text")
            if spec:
                lines = group_text_lines(g, cfg, fonts)
                step = spec.get("line_height", spec["size"] + 7)
                w = max(w, spec["at"][0] + spec["width"] + pr)
                h = max(h, spec["at"][1] + (len(lines) - 1) * step
                        + spec["size"] * 0.3 + pb)
            ref = g.get("match_vertical")
            if ref:
                if ref not in resolved:
                    deferred.append(g)
                    continue
                _, ry, _, rh = resolved[ref]
                y, h = ry, rh
            resolved[g["id"]] = (g.get("x", x), y, g.get("width", w), h)
        pending = deferred
        if not pending:
            break
    if pending:
        raise ValueError("unresolvable match_vertical chain in groups")
    return resolved


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


def font_face_css(fonts: Path, used: set[tuple[str, int]]) -> str:
    """Embed the TTFs actually drawn with, so the SVG travels with its type."""
    faces = []
    for family, weight, filename in FONT_FILES:
        ttf = fonts / filename
        if (family, weight) not in used or not ttf.exists():
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


# (family, weight) pairs used by the drawing in progress, so only those
# faces are embedded.
USED_FACES: set[tuple[str, int]] = set()


def font(typo: dict, role: str) -> dict:
    """The face for a typographic role ("display" or "secondary")."""
    return typo[role]


def rel(path: Path) -> str:
    """Repo-relative path when possible, absolute otherwise."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def fmt(value: float) -> str:
    return f"{value:g}"


def text(x, y, content, *, size, weight, fill, anchor="start",
         font=None) -> str:
    family = ""
    if font:
        family = f' font-family="{escape(font["stack"])}"'
        USED_FACES.add((font["family"], int(weight)))
    return (
        f'<text x="{fmt(x)}" y="{fmt(y)}"{family} font-size="{fmt(size)}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">'
        f"{escape(content)}</text>"
    )


# crops the renderer had to pull back to keep a circle fully covered
CLAMPED: list[str] = []


def image_size(path: Path) -> tuple[int, int] | None:
    """Pixel size of a headshot, or None when Pillow is unavailable."""
    if importlib.util.find_spec("PIL") is None:
        return None
    from PIL import Image

    with Image.open(path) as im:
        return im.size


def placement(p: Person) -> str:
    """Fit a headshot into its circle.

    The short edge of the source is scaled to the circle's diameter, so a
    rectangular photo is cropped rather than squashed. `zoom` tightens the
    crop around the subject, `dx`/`dy` shift the source inside the circle in
    canvas units (positive dy moves the photo down, i.e. shows more of the
    top of the frame).
    """
    size = image_size(p.photo)
    if size is None:  # no Pillow: let the renderer centre-crop for us
        return (f'x="{fmt(p.cx - p.r)}" y="{fmt(p.cy - p.r)}" '
                f'width="{fmt(2 * p.r)}" height="{fmt(2 * p.r)}" '
                f'preserveAspectRatio="xMidYMid slice"')
    src_w, src_h = size
    scale = (2 * p.r) / min(src_w, src_h) * float(p.crop["zoom"])
    # never let a crop expose the circle: zoom below full coverage, or a
    # shift that runs off the edge, would leave a transparent bite
    floor = (2 * p.r) / min(src_w, src_h)
    if scale < floor:
        CLAMPED.append(f"{p.id} (zoom {p.crop['zoom']:.2f} below coverage)")
        scale = floor
    w, h = src_w * scale, src_h * scale
    x = p.cx - w / 2 + float(p.crop["dx"])
    y = p.cy - h / 2 + float(p.crop["dy"])
    bounded_x = min(max(x, p.cx + p.r - w), p.cx - p.r)
    bounded_y = min(max(y, p.cy + p.r - h), p.cy - p.r)
    # a sub-pixel correction is just the framer sitting on the boundary
    if max(abs(bounded_x - x), abs(bounded_y - y)) > 0.5:
        CLAMPED.append(f"{p.id} (shift runs past the edge of the photo)")
    return (f'x="{fmt(bounded_x)}" y="{fmt(bounded_y)}" width="{fmt(w)}" '
            f'height="{fmt(h)}" preserveAspectRatio="none"')


def draw_headshot(p: Person, theme: dict, ring_w: float, typo: dict) -> str:
    clip = f"clip-{p.id}"
    out = [
        f'<clipPath id="{clip}"><circle cx="{fmt(p.cx)}" cy="{fmt(p.cy)}" '
        f'r="{fmt(p.r)}"/></clipPath>'
    ]
    if p.photo is not None:
        out.append(
            f'<image clip-path="url(#{clip})" {placement(p)} '
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
                 anchor="middle", font=font(typo, "secondary"))
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
                    font=font(typo, s["name"].get("font", "display"))))
    for i, (_key, value) in enumerate(p.meta()):
        if not value:
            continue  # a reserved but empty line
        out.append(text(x, p.cy + p.meta_dy(i), value,
                        size=s["meta"]["size"], weight=s["meta"]["weight"],
                        fill=theme["muted"], anchor=anchor,
                        font=font(typo, s["meta"].get("font", "secondary"))))
    out.append("</g>")
    return "".join(out)


def grid_cells(group: dict, box: tuple) -> list[tuple[float, float]]:
    """Lattice of circle centres covering a group box.

    The lattice is centred on the box and extended a ring beyond every edge,
    so the border cuts through the outermost circles and the group reads as
    a window onto a larger crowd rather than a tidy set of portraits.
    """
    spec = group["grid"]
    r, gap = spec["r"], spec.get("gap", 10)
    x, y, w, h = box
    want = 2 * r + gap
    # `top` keeps a fraction of the box clear for the label; the lattice
    # starts a full circle below it rather than being cut there.
    first = y + h * spec.get("top", 0.0)
    if spec.get("top"):
        first += r
    depth = y + h - first
    # Anchor a column of centres on each side border and a row on the
    # bottom one, then even the spacing out: those circles are cut in half
    # and the crowd reads as continuing past the frame.
    cols = max(round(w / want), 1) + 1
    rows = max(round(depth / want), 1) + 1
    step_x = w / (cols - 1) if cols > 1 else 0
    step_y = depth / (rows - 1) if rows > 1 else 0
    return [(x + c * step_x, first + rw * step_y)
            for rw in range(rows) for c in range(cols)]


def draw_grid(group: dict, box: tuple, theme: dict, strokes: dict,
              typo: dict, headshots: Path) -> str:
    spec = group["grid"]
    r = spec["r"]
    x, y, w, h = box
    gid = group["id"]
    photos = [headshots / name for name in spec.get("photos", [])]
    out = [f'<clipPath id="grid-{gid}"><rect x="{fmt(x)}" y="{fmt(y)}" '
           f'width="{fmt(w)}" height="{fmt(h)}" '
           f'rx="{fmt(strokes["box_radius"])}"/></clipPath>',
           f'<g clip-path="url(#grid-{gid})">']
    for i, (cx, cy) in enumerate(grid_cells(group, box)):
        photo = photos[i] if i < len(photos) and photos[i].exists() else None
        if photo is not None:
            clip = f"grid-{gid}-{i}"
            out.append(f'<clipPath id="{clip}"><circle cx="{fmt(cx)}" '
                       f'cy="{fmt(cy)}" r="{fmt(r)}"/></clipPath>')
            out.append(f'<image clip-path="url(#{clip})" x="{fmt(cx - r)}" '
                       f'y="{fmt(cy - r)}" width="{fmt(2 * r)}" '
                       f'height="{fmt(2 * r)}" '
                       f'preserveAspectRatio="xMidYMid slice" '
                       f'href="{data_uri(photo)}"/>')
        else:
            out.append(f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(r)}" '
                       f'fill="{theme["placeholder"]}" '
                       f'fill-opacity="{spec.get("fill_opacity", 0.10)}"/>')
        out.append(f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(r)}" '
                   f'fill="none" stroke="{theme["ring"]}" '
                   f'stroke-width="{fmt(spec.get("ring", strokes["ring"] * 0.7))}"/>')
    out.append("</g>")
    return "".join(out)


def draw_group(group: dict, box: tuple, theme: dict, strokes: dict,
               typo: dict, lines: list[str] | None = None) -> str:
    x, y, w, h = box
    lines = lines or []
    out = [
        f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" '
        f'rx="{fmt(strokes["box_radius"])}" fill="none" '
        f'stroke="{theme["ink"]}" stroke-width="{fmt(strokes["box"])}"/>'
    ]
    spec = group.get("text")
    if spec:
        step = spec.get("line_height", spec["size"] + 7)
        for i, line in enumerate(lines):
            out.append(text(x + spec["at"][0], y + spec["at"][1] + i * step,
                            line, size=spec["size"],
                            weight=spec.get("weight", 400),
                            fill=theme.get("muted", theme["ink"]),
                            anchor=spec.get("align", "start"),
                            font=font(typo, spec.get("font", "secondary"))))

    label = group.get("label")
    if label:
        # label offsets are relative to the box corner, so a computed box
        # carries its label with it
        lx, ly = x + label["at"][0], y + label["at"][1]
        step = label.get("line_height", label["size"] + 6)
        for i, line in enumerate(label["lines"]):
            out.append(text(lx, ly + i * step, line, size=label["size"],
                            weight=label.get("weight", 400), fill=theme["ink"],
                            anchor=label.get("align", "start"),
                            font=font(typo, label.get("font", "secondary"))))
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
           fonts: Path, boxes: dict | None = None,
           headshots: Path | None = None) -> str:
    headshots = headshots or REPO / "headshots"
    theme = cfg["themes"][theme_name]
    strokes = cfg["strokes"]
    typo = cfg["typography"]
    w, h = cfg["canvas"]["width"], cfg["canvas"]["height"]

    USED_FACES.clear()
    CLAMPED.clear()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'font-family="{escape(typo["display"]["stack"])}">',
        None,  # placeholder, filled in below once the faces used are known
        f"<title>{escape(cfg['meta']['title'])} — {escape(str(cfg['meta']['date']))}</title>",
    ]

    tx, ty = typo["title"]["at"]
    parts.append(text(tx, ty, cfg["meta"]["title"], size=typo["title"]["size"],
                      weight=typo["title"]["weight"], fill=theme["ink"],
                      anchor="middle",
                      font=font(typo, typo["title"].get("font", "display"))))
    dx, dyy = typo["date"]["at"]
    parts.append(text(dx, dyy, str(cfg["meta"]["date"]),
                      size=typo["date"]["size"],
                      weight=typo["date"]["weight"], fill=theme["muted"],
                      anchor="middle",
                      font=font(typo, typo["date"].get("font", "secondary"))))

    boxes = boxes if boxes is not None else group_boxes(cfg, people, fonts)
    for group in cfg.get("groups", []):
        box = boxes[group["id"]]
        if group.get("grid"):
            parts.append(draw_grid(group, box, theme, strokes, typo,
                                   headshots))
        parts.append(draw_group(group, box, theme, strokes, typo,
                                group_text_lines(group, cfg, fonts)))
    for points in cfg.get("connectors", []):
        parts.append(draw_connector(points, people, theme, strokes["connector"]))
    for p in people.values():
        parts.append(draw_person(p, theme, strokes["ring"], typo))

    parts.append("</svg>")
    parts[1] = (f"<style>{font_face_css(fonts, USED_FACES)}"
                f"text{{font-kerning:normal}}</style>")
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


def write_raster(svg_path: Path, scale: float, fonts: Path,
                 formats: list[str], webp_quality: int,
                 webp_lossless: bool) -> list[Path]:
    """Rasterise one SVG into every requested format, alpha preserved."""
    if importlib.util.find_spec("cairosvg") is None:
        return []
    # cairo resolves fonts through fontconfig, which reads its configuration
    # when the library is first loaded, so the environment has to be set
    # before cairosvg is imported.
    os.environ.update(fontconfig_env(fonts))
    import cairosvg

    png_bytes = cairosvg.svg2png(url=str(svg_path), scale=scale,
                                 background_color="transparent")
    written = []
    if "png" in formats:
        out = svg_path.with_suffix(".png")
        out.write_bytes(png_bytes)
        written.append(out)
    if "webp" in formats:
        from io import BytesIO

        from PIL import Image

        out = svg_path.with_suffix(".webp")
        with Image.open(BytesIO(png_bytes)) as im:
            im.save(out, "WEBP", lossless=webp_lossless, quality=webp_quality,
                    method=6, exact=True)
        written.append(out)
    return written


# --------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-c", "--config", type=Path,
                    default=REPO / "config" / "chart.yaml")
    ap.add_argument("-o", "--out", type=Path, default=REPO / "out")
    ap.add_argument("--headshots", type=Path, default=REPO / "headshots")
    ap.add_argument("--fonts", type=Path, default=REPO / "fonts")
    ap.add_argument("--framing", type=Path,
                    default=REPO / "config" / "framing.yaml",
                    help="generated crop knobs from frame-headshots.py")
    ap.add_argument("--themes", nargs="*", default=None,
                    help="themes to render (default: all in the config)")
    ap.add_argument("--scale", type=float, default=2.0,
                    help="raster scale factor relative to the SVG canvas")
    ap.add_argument("--formats", nargs="*", default=["png", "webp"],
                    choices=["png", "webp"],
                    help="raster formats to write alongside the SVG")
    ap.add_argument("--webp-quality", type=int, default=92)
    ap.add_argument("--webp-lossless", action="store_true")
    ap.add_argument("--no-check", action="store_true",
                    help="skip the layout clearance audit")
    ap.add_argument("--check-only", action="store_true",
                    help="run the layout audit and write nothing")
    ap.add_argument("--strict", action="store_true",
                    help="fail the build when the audit finds a violation")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    people = build_people(cfg, args.headshots, args.framing)
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

    violations = []
    if not args.no_check:
        from .audit import audit

        violations = audit(cfg, people, args.fonts)
        for v in violations:
            print(f"clearance: {v}", file=sys.stderr)
        if violations and args.strict:
            print(f"{len(violations)} clearance violation(s); refusing to "
                  f"build with --strict", file=sys.stderr)
            return 1

    if args.check_only:
        print("layout clean" if not violations else
              f"{len(violations)} clearance violation(s)")
        return 1 if violations else 0

    boxes = group_boxes(cfg, people, args.fonts)
    base = cfg["meta"].get("basename", "org-chart")
    for theme_name in (args.themes or list(cfg["themes"])):
        svg_path = args.out / f"{base}-{theme_name}.svg"
        svg_path.write_text(render(cfg, theme_name, people, args.fonts, boxes,
                                   args.headshots))
        print(f"wrote {rel(svg_path)}")
        if args.formats:
            written = write_raster(svg_path, args.scale, args.fonts,
                                   args.formats, args.webp_quality,
                                   args.webp_lossless)
            if written:
                for out in written:
                    print(f"wrote {rel(out)}")
            else:
                print("note: cairosvg not installed — skipping rasters "
                      "(pip install cairosvg)", file=sys.stderr)
    if CLAMPED:
        print("note: crop clamped to keep the circle covered: "
              + ", ".join(dict.fromkeys(CLAMPED))
              + " — needs a roomier source photo", file=sys.stderr)
    if violations:
        print(f"note: {len(violations)} clearance violation(s) above",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
