"""Clearance audit for the chart layout.

The chart is positioned by hand in the steering file, so nothing stops two
headshots, a label and a connector, or a box border and the circle it
contains from drifting into each other. This measures every pair that could
collide and reports anything closer than the clearances in `clearance:`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .render import Person, group_boxes, person_boxes, resolve

DEFAULTS = {
    "circle_to_circle": 24.0,
    "circle_to_text": 14.0,
    "text_to_text": 14.0,
    "line_to_circle": 16.0,
    "line_to_text": 12.0,
    "box_padding": 20.0,
    "canvas_margin": 20.0,
}


@dataclass(frozen=True)
class Violation:
    kind: str
    a: str
    b: str
    gap: float
    required: float

    def __str__(self) -> str:
        return (f"{self.kind:<17} {self.a} ↔ {self.b}: "
                f"{self.gap:.1f} < {self.required:.0f}")


# --------------------------------------------------------------------------
# geometry


def seg_point_distance(seg, px, py) -> float:
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return math.hypot(px - x0, py - y0)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def seg_box_distance(seg, box) -> float:
    """Distance between a segment and an axis-aligned box (0 if they meet)."""
    x0, y0, x1, y1 = box
    samples = 64
    (ax, ay), (bx, by) = seg
    best = math.inf
    for i in range(samples + 1):
        t = i / samples
        px, py = ax + (bx - ax) * t, ay + (by - ay) * t
        dx = max(x0 - px, 0, px - x1)
        dy = max(y0 - py, 0, py - y1)
        best = min(best, math.hypot(dx, dy))
        if best == 0:
            break
    return best


def box_distance(a, b) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0)
    dy = max(a[1] - b[3], b[1] - a[3], 0)
    return math.hypot(dx, dy)


def box_segments(box):
    x, y, w, h = box
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return [(corners[i], corners[(i + 1) % 4]) for i in range(4)]


# --------------------------------------------------------------------------


def collect(cfg: dict, people: dict[str, Person], fonts: Path):
    circles = [(p.id, p.cx, p.cy, p.r) for p in people.values()]

    texts = []
    for p in people.values():
        texts += person_boxes(p, cfg, fonts)

    from . import metrics
    typo = cfg["typography"]
    boxes = group_boxes(cfg, people, fonts)
    for spec, content in ((typo["title"], cfg["meta"]["title"]),
                          (typo["date"], str(cfg["meta"]["date"]))):
        role = spec.get("font", "display")
        x0, y0, x1, y1 = metrics.extent(fonts, typo[role]["family"],
                                        spec["weight"], content, spec["size"])
        ax, ay = spec["at"]
        w = x1 - x0
        texts.append((content, ax - w / 2, ay + y0, ax + w / 2, ay + y1))
    for g in cfg.get("groups", []):
        label = g.get("label")
        if not label:
            continue
        gx, gy, _, _ = boxes[g["id"]]
        role = label.get("font", "secondary")
        step = label.get("line_height", label["size"] + 6)
        for i, line in enumerate(label["lines"]):
            x0, y0, x1, y1 = metrics.extent(fonts, typo[role]["family"],
                                            label.get("weight", 400), line,
                                            label["size"])
            ax = gx + label["at"][0]
            ay = gy + label["at"][1] + i * step
            w = x1 - x0
            left = ax - w / 2 if label.get("align") == "middle" else ax
            texts.append((f"{g['id']}:{line}", left, ay + y0, left + w, ay + y1))

    lines = []
    for i, points in enumerate(cfg.get("connectors", [])):
        pts = [(resolve(x, people), resolve(y, people)) for x, y in points]
        for a, b in zip(pts, pts[1:]):
            lines.append((f"connector[{i}]", (a, b)))
    for gid, box in boxes.items():
        for j, seg in enumerate(box_segments(box)):
            lines.append((f"box:{gid}[{'trbl'[j]}]", seg))

    return circles, texts, lines, boxes


def audit(cfg: dict, people: dict[str, Person], fonts: Path) -> list[Violation]:
    limits = {**DEFAULTS, **(cfg.get("clearance") or {})}
    circles, texts, lines, boxes = collect(cfg, people, fonts)
    members = {pid for g in cfg.get("groups", []) for pid in g.get("members", [])}
    owner = {pid: g["id"] for g in cfg.get("groups", [])
             for pid in g.get("members", [])}
    out: list[Violation] = []

    def check(kind, a, b, gap, required):
        if gap < required - 1e-6:
            out.append(Violation(kind, a, b, gap, required))

    for i, (ida, ax, ay, ar) in enumerate(circles):
        for idb, bx, by, br in circles[i + 1:]:
            check("circle/circle", ida, idb,
                  math.hypot(ax - bx, ay - by) - ar - br,
                  limits["circle_to_circle"])

    for cid, cx, cy, r in circles:
        for tid, *box in texts:
            if tid.startswith(f"{cid}."):
                continue
            # distance from a box to a circle
            dx = max(box[0] - cx, 0, cx - box[2])
            dy = max(box[1] - cy, 0, cy - box[3])
            check("circle/text", cid, tid, math.hypot(dx, dy) - r,
                  limits["circle_to_text"])

    def source(tid: str) -> str:
        return re.split(r"[.:]", tid, maxsplit=1)[0]

    for i, (ida, *a) in enumerate(texts):
        for idb, *b in texts[i + 1:]:
            if source(ida) == source(idb):
                continue  # runs of one node, or lines of one label
            check("text/text", ida, idb, box_distance(a, b),
                  limits["text_to_text"])

    for lid, seg in lines:
        for cid, cx, cy, r in circles:
            gid = lid[4:].split("[")[0] if lid.startswith("box:") else None
            if gid and cid in members and owner[cid] == gid:
                required = limits["box_padding"]
            else:
                required = limits["line_to_circle"]
            check("line/circle", lid, cid, seg_point_distance(seg, cx, cy) - r,
                  required)
        for tid, *box in texts:
            if lid.startswith("box:") and tid.startswith(f"{lid[4:].split('[')[0]}:"):
                continue  # a box and its own label
            check("line/text", lid, tid, seg_box_distance(seg, tuple(box)),
                  limits["line_to_text"])

    margin = limits["canvas_margin"]
    w, h = cfg["canvas"]["width"], cfg["canvas"]["height"]
    for cid, cx, cy, r in circles:
        edge = min(cx - r, cy - r, w - (cx + r), h - (cy + r))
        check("canvas", cid, "edge", edge, margin)
    for tid, *box in texts:
        edge = min(box[0], box[1], w - box[2], h - box[3])
        check("canvas", tid, "edge", edge, margin)

    return sorted(out, key=lambda v: v.gap)
