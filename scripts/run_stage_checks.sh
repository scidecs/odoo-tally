#!/usr/bin/env bash
# Stage checks: code, XML, manifest, store assets and publication hygiene.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOD="$ROOT/tally_integration"
fail=0

echo "== Python compile =="
if command -v python3 >/dev/null 2>&1; then
    python3 -m compileall -q "$MOD" || fail=1
else
    echo "python3 not found — skipping"; 
fi

echo "== XML well-formedness =="
if command -v python3 >/dev/null 2>&1; then
    while IFS= read -r f; do
        python3 -c "import sys,xml.dom.minidom as m; m.parse(sys.argv[1])" "$f" \
            && echo "  ok  $f" || { echo "  FAIL $f"; fail=1; }
    done < <(find "$MOD" -name '*.xml' | sort)
fi

echo "== Manifest =="
python3 - "$MOD/__manifest__.py" "$MOD" <<'PY' || fail=1
import ast, sys
src = open(sys.argv[1]).read()
d = ast.literal_eval(src[src.index("{"):])
assert d.get("name"), "missing name"
assert len(d["name"]) <= 25, "Odoo Apps name exceeds 25 characters"
assert d.get("version"), "missing version"
assert d.get("license") == "LGPL-3", "unexpected release license"
assert d.get("support"), "missing support email"
for f in d.get("data", []):
    path = __import__("pathlib").Path(sys.argv[2]) / f
    assert path.is_file(), f"manifest data file missing: {f}"
    print("  lists:", f)
for f in d.get("images", []):
    path = __import__("pathlib").Path(sys.argv[2]) / f
    assert path.is_file(), f"manifest image missing: {f}"
assert (__import__("pathlib").Path(sys.argv[2]) / "static/description/index.html").is_file()
print("  manifest OK:", d["name"], d["version"])
PY

echo "== Store description =="
python3 - "$MOD/static/description/index.html" <<'PY' || fail=1
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import urlparse

index = Path(sys.argv[1])

class StoreParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.scripts = 0
        self.external_assets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script":
            self.scripts += 1
        if tag == "img":
            self.images.append(values)
            src = values.get("src", "")
            if urlparse(src).scheme or src.startswith("//"):
                self.external_assets.append(src)

parser = StoreParser()
parser.feed(index.read_text(encoding="utf-8"))
assert not parser.scripts, "store description must not contain JavaScript"
assert not parser.external_assets, f"external image assets are not allowed: {parser.external_assets}"
assert parser.images, "store description has no images"
for image in parser.images:
    src = image.get("src")
    assert src, "image is missing src"
    assert image.get("alt", "").strip(), f"image is missing useful alt text: {src}"
    assert (index.parent / src).is_file(), f"store image is missing: {src}"
print(f"  {len(parser.images)} local images, all present with alt text; no scripts")
PY

echo "== Publication hygiene =="
if grep -Rni --exclude-dir=.git --exclude='*.pyc' --exclude='*.png' --exclude='*.jpg' 'Sen''dan' "$ROOT"; then
    echo "  FAIL found legacy customer reference"; fail=1
else
    echo "  no legacy customer references"
fi
if grep -RniE --exclude='*.png' --exclude='*.jpg' '(Sh''ory|/Users/[^/[:space:]]+)' \
    "$MOD/static/description" "$ROOT/Docs" "$ROOT/README.md"; then
    echo "  FAIL found private path or legacy project reference in public content"; fail=1
else
    echo "  no private paths or legacy project references in public content"
fi

[ "$fail" -eq 0 ] && echo "ALL STAGE CHECKS PASSED" || { echo "STAGE CHECKS FAILED"; exit 1; }
