#!/usr/bin/env python3
"""Build the GitHub Pages site.

A deliberately plain page whose job is to hold stable URLs. Each render is
published under a fixed name — light.svg, dark.png and so on — so another
site can point an <img> at one and never have to change it when the chart
is redrawn or re-dated.
"""

from __future__ import annotations

import argparse
import shutil
from html import escape
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
FORMATS = ("webp", "png", "svg")

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0 auto; padding: 3rem 1.25rem 5rem; max-width: 54rem;
    font: 400 16px/1.55 system-ui, sans-serif;
    color: #16181c; background: #fff;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #ececec; background: #16181c; }}
    .frame.light {{ box-shadow: 0 0 0 1px #333; }}
  }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .2rem; }}
  p.sub {{ margin: 0 0 2.5rem; opacity: .65; }}
  h2 {{ font-size: 1rem; font-weight: 600; margin: 2.5rem 0 .75rem; }}
  .frame {{ padding: 1rem; border-radius: 3px; }}
  .frame.light {{ background: #fff; box-shadow: 0 0 0 1px #ddd; }}
  .frame.dark {{ background: #16181c; box-shadow: 0 0 0 1px #333; }}
  img {{ display: block; width: 100%; height: auto; }}
  ul {{ list-style: none; padding: 0; margin: .75rem 0 0; }}
  li {{ margin: .2rem 0; }}
  code, a code {{ font: 13px/1.5 ui-monospace, monospace; }}
  a {{ color: inherit; text-underline-offset: 3px; }}
  pre {{
    overflow-x: auto; padding: .8rem 1rem; border-radius: 3px;
    background: rgba(127,127,127,.12); font: 13px/1.5 ui-monospace, monospace;
  }}
</style>
<h1>{title}</h1>
<p class="sub">{date} · transparent background · these URLs are stable</p>
{sections}
<h2>Embedding</h2>
<pre>&lt;img src="{base}light.webp" alt="{title}"&gt;</pre>
<p class="sub" style="margin-top:.6rem">
  WebP is the one to embed — same picture as the PNG at roughly a quarter
  of the bytes. Swap <code>light</code> for <code>dark</code>; the SVG is
  there for print and editing, and is much larger because it carries the
  photographs inside it. Every rebuild replaces these files in place, so an
  embed picks up the new chart on its own.
</p>
</html>
"""

SECTION = """<h2>{label}</h2>
<div class="frame {theme}"><img src="{theme}.png" alt="{title}, {theme}"></div>
<ul>{links}</ul>"""

LABELS = {"light": "For light backgrounds", "dark": "For dark backgrounds"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=REPO / "config" / "chart.yaml")
    ap.add_argument("--out", type=Path, default=REPO / "out")
    ap.add_argument("--site", type=Path, default=REPO / "site")
    ap.add_argument("--base-url", default="",
                    help="published root, used only in the embed example")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text())
    base = cfg["meta"].get("basename", "org-chart")
    args.site.mkdir(parents=True, exist_ok=True)

    sections = []
    for theme in cfg["themes"]:
        published = []
        for ext in FORMATS:
            source = args.out / f"{base}-{theme}.{ext}"
            if not source.exists():
                continue
            # a fixed name, independent of the chart's title or date, so an
            # embed never has to be updated
            shutil.copy2(source, args.site / f"{theme}.{ext}")
            published.append((ext, source.stat().st_size))
        if not published:
            print(f"note: nothing rendered for {theme}")
            continue
        links = "".join(
            f'<li><a href="{theme}.{ext}"><code>{theme}.{ext}</code></a> '
            f'<span class="sub">{size / 1024:.0f} KB</span></li>'
            for ext, size in published)
        sections.append(SECTION.format(theme=theme, label=LABELS.get(theme, theme),
                                       title=escape(cfg["meta"]["title"]),
                                       links=links))
    if not sections:
        raise SystemExit(f"nothing to publish: {args.out} has no {base}-* files")

    root = args.base_url if args.base_url.endswith("/") else args.base_url + "/"
    (args.site / "index.html").write_text(PAGE.format(
        title=escape(cfg["meta"]["title"]),
        date=escape(str(cfg["meta"]["date"])),
        base=escape(root if args.base_url else ""),
        sections="\n".join(sections)))
    print(f"built {args.site}/index.html and "
          f"{len(list(args.site.glob('*.*'))) - 1} stable files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
