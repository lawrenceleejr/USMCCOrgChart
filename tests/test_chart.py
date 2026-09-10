"""Tests for the chart layout, headshot placement and extraction."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from orgchart import render  # noqa: E402
from orgchart.audit import audit  # noqa: E402

CONFIG = REPO / "config" / "chart.yaml"
FONTS = REPO / "fonts"


@pytest.fixture(scope="module")
def cfg():
    return render.load_config(CONFIG)


@pytest.fixture(scope="module")
def people(cfg):
    return render.build_people(cfg, REPO / "headshots")


def test_layout_has_no_clearance_violations(cfg, people):
    violations = audit(cfg, people, FONTS)
    assert not violations, "\n".join(str(v) for v in violations)


def test_group_boxes_enclose_their_members(cfg, people):
    boxes = render.group_boxes(cfg, people, FONTS)
    for group in cfg["groups"]:
        if not group.get("members"):
            continue
        x, y, w, h = boxes[group["id"]]
        for pid in group["members"]:
            p = people[pid]
            assert x < p.cx - p.r and p.cx + p.r < x + w
            assert y < p.cy - p.r and p.cy + p.r < y + h


def test_multiple_roles_stack_under_the_name(cfg, people):
    one = render.Person(id="a", name="A", roles=["Chair"], affiliation="FNAL",
                        style=cfg["styles"]["sm"], layout="below", cx=0.0,
                        cy=0.0, photo=None, crop=dict(render.DEFAULT_CROP))
    two = render.Person(id="b", name="B", roles=["Chair", "Speakers"],
                        affiliation="FNAL", style=cfg["styles"]["sm"],
                        layout="below", cx=0.0, cy=0.0, photo=None,
                        crop=dict(render.DEFAULT_CROP))
    assert [k for k, _ in one.meta()] == ["role0", "affiliation"]
    assert [k for k, _ in two.meta()] == ["role0", "role1", "affiliation"]
    step = cfg["styles"]["sm"]["dy"]["affiliation"] - cfg["styles"]["sm"]["dy"]["role"]
    # a single-role node is unmoved; the extra role pushes the affiliation down
    assert one.meta_dy(0) == cfg["styles"]["sm"]["dy"]["role"]
    assert one.meta_dy(1) == cfg["styles"]["sm"]["dy"]["affiliation"]
    assert two.meta_dy(2) == cfg["styles"]["sm"]["dy"]["affiliation"] + step


def test_alias_shares_one_photo_and_framing(cfg, people):
    aliases = [e for e in cfg["people"] if e.get("alias_of")]
    bare = render.build_people({**cfg, "people": [
        {k: v for k, v in e.items() if k != "nudge"} for e in cfg["people"]]},
        REPO / "headshots", REPO / "config" / "framing.yaml")
    for entry in aliases:
        alias, original = people[entry["id"]], people[entry["alias_of"]]
        assert alias.photo == original.photo
        # the alias inherits the original's framing; each placing may still
        # carry its own nudge on top
        assert bare[entry["id"]].crop == bare[entry["alias_of"]].crop
        # same person, shown twice, in different roles and places
        assert alias.name == original.name
        assert (alias.cx, alias.cy) != (original.cx, original.cy)
        assert alias.roles != original.roles


def test_group_prose_wraps_to_its_width(cfg):
    spec = {"font": "secondary", "size": 17, "weight": 400, "width": 150}
    words = "the muon collider community steering the design of a facility"
    lines = render.wrap(cfg, spec, words, FONTS)
    assert len(lines) > 1
    assert " ".join(lines).split() == words.split()
    for line in lines:
        x0, _, x1, _ = render.text_extent(cfg, "secondary", 17, 400, line, FONTS)
        assert x1 - x0 <= spec["width"] or " " not in line


def test_renders_both_themes(cfg, people):
    for theme in cfg["themes"]:
        svg = render.render(cfg, theme, people, FONTS)
        assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
        # transparent by construction: nothing paints the full canvas
        w, h = cfg["canvas"]["width"], cfg["canvas"]["height"]
        assert f'width="{w}" height="{h}"' in svg
        assert "<rect" not in svg.split("<style>")[0]
        for person in people.values():
            assert f'id="node-{person.id}"' in svg


def rect(image_path: Path, r: float, **crop):
    p = render.Person(id="t", name="T", roles=[], affiliation="",
                      style={"r": r, "gap": 0,
                             "name": {"size": 10, "weight": 700},
                             "meta": {"size": 8, "weight": 400},
                             "dy": {"name": 0, "role": 0, "affiliation": 0}},
                      layout="left", cx=100.0, cy=100.0, photo=image_path,
                      crop={**render.DEFAULT_CROP, **crop})
    attrs = render.placement(p)
    return {k: float(v) for k, v in re.findall(r'(x|y|width|height)="([-\d.]+)"',
                                               attrs)}


def test_rectangular_headshot_fills_the_circle_without_squashing(tmp_path):
    src = tmp_path / "wide.png"
    Image.new("RGB", (400, 200), "grey").save(src)
    box = rect(src, r=50)
    # short edge scaled to the diameter, aspect ratio kept, centred
    assert box["height"] == pytest.approx(100)
    assert box["width"] == pytest.approx(200)
    assert box["x"] + box["width"] / 2 == pytest.approx(100)
    assert box["y"] + box["height"] / 2 == pytest.approx(100)


def test_crop_knobs_zoom_and_shift(tmp_path):
    src = tmp_path / "tall.png"
    Image.new("RGB", (200, 400), "grey").save(src)
    base = rect(src, r=50)
    zoomed = rect(src, r=50, zoom=2.0)
    assert zoomed["width"] == pytest.approx(base["width"] * 2)
    assert zoomed["x"] + zoomed["width"] / 2 == pytest.approx(100)

    # a shift needs spare pixels to move into, so zoom in first
    room = rect(src, r=50, zoom=2.0)
    shifted = rect(src, r=50, zoom=2.0, dx=10, dy=-5)
    assert shifted["x"] == pytest.approx(room["x"] + 10)
    assert shifted["y"] == pytest.approx(room["y"] - 5)


def test_crop_never_exposes_the_circle(tmp_path):
    src = tmp_path / "tight.png"
    Image.new("RGB", (200, 200), "grey").save(src)
    # a zoom below coverage and a shift with nowhere to go are both pulled
    # back rather than leaving a transparent bite out of the circle
    for crop in ({"zoom": 0.5}, {"dx": 60}, {"dy": -60}, {"zoom": 0.8, "dx": 40}):
        box = rect(src, r=50, **crop)
        assert box["x"] <= 100 - 50 and box["x"] + box["width"] >= 100 + 50
        assert box["y"] <= 100 - 50 and box["y"] + box["height"] >= 100 + 50


def test_extract_headshots_crops_on_the_reference_coordinates(tmp_path):
    layout = yaml.safe_load((REPO / "config" / "source-layout.yaml").read_text())
    w, h = layout["canvas"]
    scale = 2  # a 2x export of the reference image
    source = Image.new("RGB", (w * scale, h * scale), "white")
    draw = ImageDraw.Draw(source)
    marks = {}
    for i, (pid, (cx, cy, r)) in enumerate(layout["faces"].items()):
        colour = (10 + i * 15, 60, 200 - i * 10)
        marks[pid] = colour
        draw.ellipse([(cx - r) * scale, (cy - r) * scale,
                      (cx + r) * scale, (cy + r) * scale], fill=colour)
    src_path = tmp_path / "reference.png"
    source.save(src_path)

    out = tmp_path / "headshots"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "extract-headshots.py"),
         str(src_path), "--out", str(out)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    for pid, (_cx, _cy, r) in layout["faces"].items():
        crop = Image.open(out / f"{pid}.png").convert("RGB")
        assert crop.size == (round(2 * r * scale),) * 2
        # the centre of each crop is that person's face, not a neighbour's
        assert crop.getpixel((crop.width // 2, crop.height // 2)) == marks[pid]
