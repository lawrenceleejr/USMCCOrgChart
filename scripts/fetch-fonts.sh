#!/usr/bin/env bash
# Download the faces the chart is set in into fonts/: Lato for display type
# (title, names) and Source Sans Pro for secondary type (roles, affiliations,
# labels, date). The renderer embeds these in the SVG, so a chart carries its
# own type wherever it is opened.
set -euo pipefail

dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/fonts"
mkdir -p "$dir"

fetch() {  # family-query, weight, filename
  local css url
  css=$(curl -sSf -A "Mozilla/5.0" "https://fonts.googleapis.com/css2?family=$1:wght@$2")
  url=$(printf '%s' "$css" | tr '}' '\n' | grep -o 'https://[^)]*\.ttf' | head -1)
  [ -n "$url" ] || { echo "could not resolve $1 $2 from Google Fonts" >&2; exit 1; }
  curl -sSf -o "$dir/$3" "$url"
  echo "fetched fonts/$3"
}

fetch "Lato" 400 Lato-Regular.ttf
fetch "Lato" 700 Lato-Bold.ttf
fetch "Source+Sans+Pro" 400 SourceSansPro-Regular.ttf
fetch "Source+Sans+Pro" 600 SourceSansPro-SemiBold.ttf
