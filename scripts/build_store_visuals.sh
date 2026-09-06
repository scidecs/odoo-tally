#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
asset_dir="$repo_dir/tally_integration/static/description/assets"

command -v magick >/dev/null || { printf 'ImageMagick is required\n' >&2; exit 1; }
cd "$asset_dir"
for name in store_hero_v3 video_poster_v3 architecture_v3; do
    magick -background none "$name.svg" -density 144 -resize 1680x "$name.png"
    identify "$name.png"
done
