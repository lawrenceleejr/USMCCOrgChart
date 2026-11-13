#!/usr/bin/env python3
"""Pull headshots from the USMCC website repo.

The website keeps a photo per person under content/all_people/<Name>/ (and
the council under content/leadership/<slug>/). This matches each person in
chart.yaml to their directory by name and copies the largest photo it finds
into headshots/, which is a far better source than cropping a rendered
chart.

    git clone https://github.com/lawrenceleejr/usmccwebsite /tmp/usmccwebsite
    scripts/fetch-headshots-from-site.py --site /tmp/usmccwebsite

People whose directory is named differently to their chart entry carry a
`photo_source:` key in chart.yaml naming the directory.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
CONTENT = ("content/all_people", "content/leadership")
# The site's own fallback store, named FirstLast.<ext>. Photos land here
# when the membership database has none, but the site only finds them by
# the database's form of the name, so some never reach a people page
# (Ben Rosser's is saved as BenRosser.jpg; the database calls him Benjamin).
SAVED = "scripts/saved_photos"
EXTS = (".jpg", ".jpeg", ".png", ".webp")


def normalise(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def title_of(directory: Path) -> str | None:
    index = directory / "index.md"
    if not index.exists():
        return None
    match = re.search(r"^title:\s*(.+)$", index.read_text(), re.M)
    return match.group(1).strip() if match else None


def index_site(site: Path) -> dict[str, list[Path]]:
    """Map normalised names to the directories that go by them."""
    found: dict[str, list[Path]] = {}
    for area in CONTENT:
        root = site / area
        if not root.is_dir():
            continue
        for directory in sorted(root.iterdir()):
            if not directory.is_dir():
                continue
            keys = {normalise(directory.name)}
            title = title_of(directory)
            if title:
                keys.add(normalise(title))
            for key in keys:
                found.setdefault(key, []).append(directory)
    return found


def digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def placeholders(site: Path, threshold: int) -> set[str]:
    """Digests of images the site reuses across people.

    Most of the site's entries share one default portrait. It is the
    largest file in several of those directories, so without this it would
    win on resolution and be copied in as somebody's face.
    """
    counts: Counter[str] = Counter()
    for area in CONTENT:
        for path in (site / area).glob("*/*"):
            if path.suffix.lower() in EXTS:
                counts[digest(path)] += 1
    return {d for d, n in counts.items() if n >= threshold}


def index_saved(site: Path) -> dict[str, list[Path]]:
    """Map normalised names to files in the site's saved_photos store."""
    found: dict[str, list[Path]] = {}
    root = site / SAVED
    if root.is_dir():
        for path in sorted(root.iterdir()):
            if path.suffix.lower() in EXTS:
                found.setdefault(normalise(path.stem), []).append(path)
    return found


def best_photo(candidates: list[Path], skip: set[str]) -> Path | None:
    """The largest real image among the candidates."""
    best, best_pixels = None, 0
    for path in candidates:
        if path.suffix.lower() not in EXTS or digest(path) in skip:
            continue
        try:
            with Image.open(path) as im:
                pixels = im.size[0] * im.size[1]
        except OSError:
            continue
        if pixels > best_pixels:
            best, best_pixels = path, pixels
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", type=Path, required=True,
                    help="path to a checkout of the usmccwebsite repo")
    ap.add_argument("--config", type=Path, default=REPO / "config" / "chart.yaml")
    ap.add_argument("--out", type=Path, default=REPO / "headshots")
    ap.add_argument("--only", nargs="*", help="fetch just these ids")
    ap.add_argument("--placeholder-threshold", type=int, default=3,
                    help="an image reused by this many people is treated as "
                         "the site's default portrait, not a face")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text())
    site = index_site(args.site)
    saved = index_saved(args.site)
    if not site:
        print(f"no {' or '.join(CONTENT)} under {args.site}", file=sys.stderr)
        return 1

    shared = placeholders(args.site, args.placeholder_threshold)
    if shared:
        print(f"ignoring {len(shared)} shared placeholder image(s)")

    args.out.mkdir(parents=True, exist_ok=True)
    missing = []
    for person in cfg["people"]:
        pid = person["id"]
        if args.only and pid not in args.only:
            continue
        if person.get("alias_of"):
            continue  # a second placing of someone already fetched
        # try both the site's name for them and the chart's, since the
        # saved store may use either
        keys = {normalise(person["name"])}
        if person.get("photo_source"):
            keys.add(normalise(person["photo_source"]))
        directories = [d for k in keys for d in site.get(k, [])]
        candidates = [f for d in directories for f in sorted(d.iterdir())]
        candidates += [f for k in keys for f in saved.get(k, [])]
        if not candidates:
            missing.append(f"{pid} ({person['name']})")
            continue
        source = best_photo(candidates, shared)
        if source is None:
            where = directories[0].name if directories else "saved photos"
            missing.append(f"{pid} (only a placeholder in {where})")
            continue
        with Image.open(source) as im:
            size = im.size
        dest = args.out / f"{pid}{source.suffix.lower()}"
        for stale in args.out.glob(f"{pid}.*"):
            if stale != dest and not args.dry_run:
                stale.unlink()
        print(f"{pid:<12} {size[0]:>5}x{size[1]:<5} "
              f"{source.relative_to(args.site)} -> {dest.name}")
        if not args.dry_run:
            shutil.copy2(source, dest)

    if missing:
        print("\nno photo on the site for: " + ", ".join(missing) +
              "\n(leaving whatever is already in headshots/)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
