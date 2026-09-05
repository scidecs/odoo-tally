#!/usr/bin/env bash
# Stage checks: Python compile + XML well-formedness + manifest sanity.
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

echo "== Publication hygiene =="
if grep -Rni --exclude-dir=.git --exclude='*.pyc' --exclude='*.png' 'Sen''dan' "$ROOT"; then
    echo "  FAIL found legacy customer reference"; fail=1
else
    echo "  no legacy customer references"
fi

[ "$fail" -eq 0 ] && echo "ALL STAGE CHECKS PASSED" || { echo "STAGE CHECKS FAILED"; exit 1; }
