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
python3 - "$MOD/__manifest__.py" <<'PY'
import ast, sys
src = open(sys.argv[1]).read()
d = ast.literal_eval(src[src.index("{"):])
assert d.get("name"), "missing name"
assert d.get("version"), "missing version"
for f in d.get("data", []):
    print("  lists:", f)
print("  manifest OK:", d["name"], d["version"])
PY

[ "$fail" -eq 0 ] && echo "ALL STAGE CHECKS PASSED" || { echo "STAGE CHECKS FAILED"; exit 1; }
