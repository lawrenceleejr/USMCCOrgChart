#!/usr/bin/env python3
"""Lift the headshots out of a reference render of the chart.

A stop-gap until real headshot files exist: crops each face out of an
existing chart image using the coordinate map in config/source-layout.yaml
and writes headshots/<id>.png. The crops are square and centred on the
circle, which is what the renderer expects; anything sharper should replace
them with an original photo.

    scripts/extract-headshots.py path/to/usmcc-leadership.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="reference chart image")
    ap.add_argument("--layout", type=Path,
                    default=REPO / "config" / "source-layout.yaml")
    ap.add_argument("--out", type=Path, default=REPO / "headshots")
    ap.add_argument("--pad", type=float, default=0.0,
                    help="extra margin around the circle, as a fraction of "
                         "its radius; a little padding leaves the renderer "
                         "room to shift the crop later")
    ap.add_argument("--mask", action="store_true",
                    help="also alpha-mask the crop to the circle, dropping "
                         "the ring and whatever sits outside it")
    ap.add_argument("--only", nargs="*", help="extract just these ids")
    ap.add_argument("--force", action="store_true",
                    help="overwrite headshots that already exist")
    args = ap.parse_args(argv)

    layout = yaml.safe_load(args.layout.read_text())
    ref_w, ref_h = layout["canvas"]
    args.out.mkdir(parents=True, exist_ok=True)

    with Image.open(args.source) as src:
        image = src.convert("RGBA")
    k = image.width / ref_w
    if abs(image.height / ref_h - k) > 0.01:
        print(f"warning: {args.source.name} is {image.width}x{image.height}, "
              f"a different aspect ratio to the reference "
              f"{ref_w}x{ref_h} — crops will be off", file=sys.stderr)

    written = skipped = 0
    for pid, (cx, cy, r) in layout["faces"].items():
        if args.only and pid not in args.only:
            continue
        dest = args.out / f"{pid}.png"
        if dest.exists() and not args.force:
            skipped += 1
            continue
        rr = r * (1 + args.pad) * k
        box = (round(cx * k - rr), round(cy * k - rr),
               round(cx * k + rr), round(cy * k + rr))
        crop = image.crop(box)
        if args.mask:
            mask = Image.new("L", crop.size, 0)
            inset = crop.width * args.pad / (2 * (1 + args.pad))
            ImageDraw.Draw(mask).ellipse(
                (inset, inset, crop.width - inset, crop.height - inset),
                fill=255)
            crop.putalpha(mask)
        crop.save(dest)
        written += 1
        print(f"wrote {dest.relative_to(REPO)} ({crop.width}x{crop.height})")

    if skipped:
        print(f"{skipped} headshot(s) already present; --force to replace",
              file=sys.stderr)
    if not written:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
