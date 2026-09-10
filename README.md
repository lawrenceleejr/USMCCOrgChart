# USMCC Org Chart

Renders the USMCC leadership org chart from a single steering file to
transparent SVG and PNG, in a light-background and a dark-background variant.

```
make            # fetch fonts, then render everything into out/
make chart      # re-render only
make check      # layout clearance audit, writes nothing
```

or directly:

```
PYTHONPATH=src python3 -m orgchart [--scale 2] [--themes light]
                                   [--formats png webp] [--strict]
```

Every push builds the chart in CI and uploads the PNGs and WebPs (and the
SVGs, separately) as workflow artifacts.

## What lives where

| Path | Purpose |
| --- | --- |
| `config/chart.yaml` | The steering file: date, people, positions, connectors, themes |
| `headshots/` | One photo per person, named `<id>.jpg` (or `.png`/`.webp`) |
| `fonts/` | Lato + Source Sans Pro, fetched by `scripts/fetch-fonts.sh` |
| `src/orgchart/render.py` | The renderer |
| `out/` | Rendered `usmcc-org-chart-{light,dark}.{svg,png,webp}` |
| `config/source-layout.yaml` | Face coordinates in the original chart image, for extraction |
| `scripts/extract-headshots.py` | Lifts headshots out of a reference render |
| `src/orgchart/audit.py` | The layout clearance audit |

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
`headshots/holmes.jpg` for `id: holmes`. Anyone without a photo renders as a
soft initials disc and is listed as a note at build time, so the chart
always builds.

Photos need not be square. The short edge is scaled to the circle's
diameter and the rest is cropped, so nothing is ever squashed. Three knobs
per person adjust what the circle shows:

```yaml
  - id: holmes
    name: Tova Holmes
    crop: {zoom: 1.25, dx: 0, dy: 14}
```

* `zoom` — above 1 crops tighter around the subject; 1.0 fits the short edge.
* `dx` / `dy` — shift the photo inside the circle, in canvas units. Positive
  `dy` moves the photo down, showing more of the top of the frame.

A `defaults: {crop: {...}}` block sets the starting point for everyone.

Photos are embedded in the SVG as data URIs, which makes each SVG standalone
but also fairly large — that is the intended trade.

### Extracting from an existing chart image

To bootstrap from a rendered chart rather than original photos:

```
scripts/extract-headshots.py path/to/usmcc-leadership.png [--pad 0.1] [--mask]
```

It crops each face using `config/source-layout.yaml`, which records where
the faces sit *in that source image*. Those coordinates are deliberately
separate from `config/chart.yaml`, because the live layout has since moved.
Existing files are kept unless you pass `--force`. Crops are only as sharp
as the source — replace them with originals when you have them.

## Spacing

Positions are set by hand, so the build audits them. Every headshot, text
ink box (measured from the real font files), connector segment and box
border is checked against the minimum clear distances in the `clearance:`
block of the steering file. Violations print on every build; `--strict`
turns them into a failure, which is how CI runs.

Group boxes are not positioned by hand at all: a group listing `members` is
sized to enclose those people and their labels with `padding` of clear
space, so a border can never cut through a headshot.

## Requirements

Python 3.10+, PyYAML, Pillow, and cairosvg for the rasters
(`pip install -e .`). Without cairosvg the SVGs still render and the raster
step is skipped. `pip install -e ".[dev]"` adds pytest; run the suite with
`python -m pytest`.
