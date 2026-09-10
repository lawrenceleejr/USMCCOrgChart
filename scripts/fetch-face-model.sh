#!/usr/bin/env bash
# Download the YuNet face detector used by scripts/frame-headshots.py.
# Only needed when re-framing headshots; the result is committed to
# config/framing.yaml, so builds never need this.
set -euo pipefail

dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/models"
file="$dir/face_detection_yunet_2023mar.onnx"
sha="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
# the file is Git LFS in opencv_zoo, so fetch it from the media host
url="https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"

mkdir -p "$dir"
if [ -f "$file" ] && echo "$sha  $file" | sha256sum -c - >/dev/null 2>&1; then
  echo "models/$(basename "$file") already present"
  exit 0
fi
curl -sSf -L -o "$file" "$url"
echo "$sha  $file" | sha256sum -c -
