# USMCC Org Chart

Renders the USMCC leadership org chart from a single steering file to
transparent SVG and PNG, in a light-background and a dark-background variant.

```
make            # fetch fonts, then render everything into out/
make chart      # re-render only
```

or directly:

```
PYTHONPATH=src python3 -m orgchart [--scale 2] [--themes light] [--no-png]
```

## What lives where

| Path | Purpose |
| --- | --- |
| `config/chart.yaml` | The steering file: date, people, positions, connectors, themes |
| `headshots/` | One photo per person, named `<id>.jpg` (or `.png`/`.webp`) |
| `fonts/` | Lato + Source Sans Pro, fetched by `scripts/fetch-fonts.sh` |
| `src/orgchart/render.py` | The renderer |
| `out/` | Rendered `usmcc-org-chart-{light,dark}.{svg,png}` |

## Editing the chart

Everything is in `config/chart.yaml`.

* **Date** — `meta.date`. It is never taken from the clock; set it by hand.
* **People** — an entry under `people` with an `id`, `name`, `role`,
  `affiliation`, a `style` (`lg`, `md`, `sm`), a `layout` (`left` puts the
  text beside the headshot, `below` centres it underneath) and `at: [x, y]`,
  the centre of the headshot in canvas units.
* **Connectors** — polylines under `connectors`. A coordinate may be a number
  or an anchor string `"<person-id>:<anchor>"` where anchor is one of `cx`,
  `cy`, `top`, `bottom`, `left`, `right`, so lines follow people when a
  headshot moves.
* **Boxes** — the rounded containers under `groups`, as `[x, y, w, h]`.
* **Type and weights** — `typography`, `styles`, `strokes`. Lato sets the
  title and names; Source Sans Pro sets roles, affiliations, labels and the
  date.
* **Themes** — `themes.light` and `themes.dark` only change ink colours. The
  background is always transparent, in both the SVG and the PNG.

## Headshots

Drop a file into `headshots/` named after the person's `id` in the config —
`headshots/holmes.jpg` for `id: holmes`. Images are cropped to a circle from
the centre (`xMidYMid slice`), so square-ish crops work best. Anyone without
a photo renders as a soft initials disc and is listed as a note at build
time, so the chart always builds.

Photos are embedded in the SVG as data URIs, which makes each SVG standalone
but also fairly large — that is the intended trade.

## Requirements

Python 3.10+, PyYAML, and cairosvg for the PNGs (`pip install cairosvg`).
Without cairosvg the SVGs still render and the PNG step is skipped.
