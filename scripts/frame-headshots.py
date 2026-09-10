#!/usr/bin/env python3
"""Frame every headshot the same way: nose at the centre, whole head shown.

Detects the face in each headshot with YuNet (which returns the nose tip as
a landmark, not an estimate), then solves for the crop knobs that put the
nose at the circle's centre and make the head as large as it can be while
staying entirely inside the circle. Where the source is too tightly cropped
to allow both, coverage wins — the circle is never left with a transparent
gap — and the shortfall is reported.

Writes config/framing.yaml, which the renderer merges under any `crop:`
written by hand in chart.yaml, so a manual override always wins.

    scripts/fetch-face-model.sh
    scripts/frame-headshots.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from orgchart.render import build_people  # noqa: E402

# The head is derived from the eye landmarks rather than the detection box,
# which is tight and inconsistent between photos. Interocular distance is a
# stable ruler: on an adult head, vertex-to-eyeline is about 1.6 of it,
# eyeline-to-chin about 2.0, and half the head breadth about 1.3.
HEAD_ABOVE = 1.75   # a little over anthropometric, to allow for hair
HEAD_BELOW = 2.05
HEAD_HALF_WIDTH = 1.35

# YuNet is trained on small inputs and drifts badly on large ones, so
# detection runs on a downscaled copy and the landmarks are scaled back.
DETECT_LONG_EDGE = 640


def detect(path: Path, model: Path, score: float):
    """The most prominent face: its eye landmarks and its nose tip."""
    import cv2
    import numpy as np
    from PIL import Image

    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        full = (rgb.width, rgb.height)
        k = min(1.0, DETECT_LONG_EDGE / max(rgb.size))
        small = rgb.resize((max(1, round(rgb.width * k)),
                            max(1, round(rgb.height * k)))) if k < 1 else rgb
        image = np.array(small)[:, :, ::-1].copy()

    h, w = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(model), "", (w, h), score, 0.3, 5000)
    detector.setInputSize((w, h))
    _, faces = detector.detect(image)
    if faces is None or not len(faces):
        return full, None
    # the largest face, so a bystander in the background never wins
    face = max(faces, key=lambda f: f[2] * f[3])
    back = 1 / k if k < 1 else 1.0
    point = lambda i: (float(face[i]) * back, float(face[i + 1]) * back)
    return full, {
        "right_eye": point(4),
        "left_eye": point(6),
        "nose": point(8),
        "score": float(face[-1]),
    }


def head_box(face: dict) -> tuple[float, float, float, float]:
    """Estimated extent of the whole head, in source pixels."""
    (rx, ry), (lx, ly) = face["right_eye"], face["left_eye"]
    iod = max(((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5, 1e-6)
    eye_x, eye_y = (rx + lx) / 2, (ry + ly) / 2
    return (eye_x - HEAD_HALF_WIDTH * iod, eye_y - HEAD_ABOVE * iod,
            eye_x + HEAD_HALF_WIDTH * iod, eye_y + HEAD_BELOW * iod)


def solve(size, face: dict, radius: float, fill: float):
    """Crop knobs placing the nose at the centre with the head inside.

    Returns (zoom, dx, dy, head_fits).
    """
    w, h = size
    nx, ny = face["nose"]
    left, top, right, bottom = head_box(face)
    # how far the head reaches from the nose, in source pixels
    reach = max(nx - left, right - nx, ny - top, bottom - ny)

    # scale that makes the head exactly fill `fill` of the circle
    head_scale = radius * fill / reach
    # the image must still cover the circle once shifted to centre the nose
    cover_x = radius / max(w / 2 - abs(nx - w / 2), 1e-6)
    cover_y = radius / max(h / 2 - abs(ny - h / 2), 1e-6)
    cover_scale = max(cover_x, cover_y, 2 * radius / min(w, h))

    scale = max(head_scale, cover_scale)
    zoom = scale * min(w, h) / (2 * radius)
    dx = -(nx - w / 2) * scale
    dy = -(ny - h / 2) * scale
    return zoom, dx, dy, head_scale >= cover_scale


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO / "config" / "chart.yaml")
    ap.add_argument("--headshots", type=Path, default=REPO / "headshots")
    ap.add_argument("--out", type=Path, default=REPO / "config" / "framing.yaml")
    ap.add_argument("--model", type=Path,
                    default=REPO / "models" / "face_detection_yunet_2023mar.onnx")
    ap.add_argument("--fill", type=float, default=0.94,
                    help="fraction of the circle the head may occupy; lower "
                         "leaves more air around every face")
    ap.add_argument("--score", type=float, default=0.5,
                    help="detector confidence threshold")
    ap.add_argument("--min-score", type=float, default=0.7,
                    help="below this confidence the photo is left alone "
                         "rather than framed on a guess")
    ap.add_argument("--min-source", type=int, default=160,
                    help="short edge below which a photo is left alone; the "
                         "reference-chart crops are already circle-tight and "
                         "have no detail to zoom into")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.model.exists():
        print(f"missing {args.model.name} — run scripts/fetch-face-model.sh",
              file=sys.stderr)
        return 1

    cfg = yaml.safe_load(args.config.read_text())
    people = build_people(cfg, args.headshots)

    # with --only, keep everyone else's framing rather than dropping it
    framing = {}
    if args.only and args.out.exists():
        framing = {k: v for k, v in (yaml.safe_load(args.out.read_text()) or {}).items()}
    undetected, cramped, skipped = [], [], []
    for pid, person in people.items():
        if args.only and pid not in args.only:
            continue
        if person.photo is None:
            continue
        size, face = detect(person.photo, args.model, args.score)
        if face is None:
            undetected.append(pid)
            continue
        score = face["score"]
        if min(size) < args.min_source:
            skipped.append(f"{pid} (source only {min(size)}px)")
            continue
        if score < args.min_score:
            skipped.append(f"{pid} (confidence {score:.2f})")
            continue
        zoom, dx, dy, fits = solve(size, face, person.r, args.fill)
        framing[pid] = {"zoom": round(zoom, 3), "dx": round(dx, 1),
                        "dy": round(dy, 1)}
        if not fits:
            cramped.append(pid)
        print(f"{pid:<12} {size[0]:>4}x{size[1]:<4} conf={score:.2f} "
              f"zoom={zoom:5.2f} dx={dx:+7.1f} dy={dy:+7.1f}"
              f"{'' if fits else '   head cropped: source too tight'}")

    header = ("# Generated by scripts/frame-headshots.py — do not edit.\n"
              "#\n"
              "# Crop knobs placing each nose at the centre of its circle,\n"
              "# with the head as large as it can be while staying inside.\n"
              "# The renderer merges these under any `crop:` set by hand in\n"
              "# chart.yaml, so a manual override still wins.\n")
    body = yaml.safe_dump(framing, sort_keys=True, default_flow_style=None)
    if args.dry_run:
        print("\n" + header + body)
    else:
        args.out.write_text(header + body)
        print(f"\nwrote {args.out.relative_to(REPO)} for {len(framing)} people")

    if skipped:
        print("left unframed: " + ", ".join(skipped), file=sys.stderr)
    if undetected:
        print("no face detected for: " + ", ".join(undetected) +
              " (left unframed)", file=sys.stderr)
    if cramped:
        print("head does not fit for: " + ", ".join(cramped) +
              " — needs a less tightly cropped source", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
