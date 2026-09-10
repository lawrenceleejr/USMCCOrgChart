#!/usr/bin/env python3
"""Build the GitHub Pages site: both chart variants, on their own grounds.

The charts are transparent, so the page shows each one over the background
it is meant for, and offers every format for download.
"""

from __future__ import annotations

import argparse
import shutil
from html import escape
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700&\
family=Source+Sans+Pro:wght@400&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: #111;
    --muted: #5a5a5a;
    --rule: #d8d8d8;
    --page: #fdfdfc;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink: #ececec; --muted: #a6a6a6; --rule: #333; --page: #16181c; }}
  }}
  html {{ background: var(--page); }}
  body {{
    margin: 0 auto;
    padding: 4rem 1.5rem 6rem;
    max-width: 60rem;
    color: var(--ink);
    font: 400 17px/1.6 "Source Sans Pro", system-ui, sans-serif;
  }}
  h1 {{
    font: 700 2.6rem/1.1 Lato, system-ui, sans-serif;
    margin: 0;
    letter-spacing: -0.01em;
  }}
  .date {{ color: var(--muted); margin: 0.35rem 0 3.5rem; }}
  figure {{ margin: 0 0 4rem; }}
  .frame {{ padding: 1.5rem; border-radius: 3px; }}
  .frame.light {{ background: #ffffff; box-shadow: 0 0 0 1px var(--rule); }}
  .frame.dark {{ background: #16181c; box-shadow: 0 0 0 1px #2c2f36; }}
  img {{ display: block; width: 100%; height: auto; }}
  figcaption {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.25rem;
    align-items: baseline;
    margin-top: 0.9rem;
    color: var(--muted);
    font-size: 0.95rem;
  }}
  figcaption b {{ color: var(--ink); font-weight: 400; }}
  a {{ color: inherit; text-underline-offset: 3px; }}
  footer {{
    margin-top: 5rem;
    padding-top: 1.25rem;
    border-top: 1px solid var(--rule);
    color: var(--muted);
    font-size: 0.9rem;
  }}
</style>
<h1>{title}</h1>
<p class="date">{date}</p>
{figures}
<footer>
  Every image has a transparent background. Rendered from
  <a href="https://github.com/{repo}">{repo}</a>; the date and the people
  are set in <code>config/chart.yaml</code>.
</footer>
</html>
"""

FIGURE = """<figure>
  <div class="frame {theme}"><img src="{png}" alt="{title}, {theme} variant"></div>
  <figcaption>
    <b>{label}</b>
    <span>download
      <a href="{svg}">SVG</a> ·
      <a href="{png}">PNG</a> ·
      <a href="{webp}">WebP</a>
    </span>
  </figcaption>
</figure>"""

LABELS = {"light": "For light backgrounds", "dark": "For dark backgrounds"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=REPO / "config" / "chart.yaml")
    ap.add_argument("--out", type=Path, default=REPO / "out")
    ap.add_argument("--site", type=Path, default=REPO / "site")
    ap.add_argument("--repo", default="lawrenceleejr/USMCCOrgChart")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text())
    base = cfg["meta"].get("basename", "org-chart")

    args.site.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in sorted(args.out.glob(f"{base}-*")):
        shutil.copy2(path, args.site / path.name)
        copied.append(path.name)
    if not copied:
        raise SystemExit(f"nothing to publish: {args.out} has no {base}-* files")

    figures = []
    for theme in cfg["themes"]:
        names = {ext: f"{base}-{theme}.{ext}" for ext in ("svg", "png", "webp")}
        missing = [n for n in names.values() if n not in copied]
        if missing:
            print(f"note: skipping {theme} — missing {', '.join(missing)}")
            continue
        figures.append(FIGURE.format(theme=theme,
                                     label=LABELS.get(theme, theme),
                                     title=escape(cfg["meta"]["title"]),
                                     **names))

    (args.site / "index.html").write_text(PAGE.format(
        title=escape(cfg["meta"]["title"]),
        date=escape(str(cfg["meta"]["date"])),
        repo=escape(args.repo),
        figures="\n".join(figures),
    ))
    print(f"built {args.site}/index.html with {len(figures)} figure(s) "
          f"and {len(copied)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
