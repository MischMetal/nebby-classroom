#!/usr/bin/env bash
# Collect every graph in results/ into one page: results/index.html
#
#   ./gallery.sh
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
shopt -s nullglob
imgs=("$ROOT"/results/*/cwnd.png)
[ ${#imgs[@]} -gt 0 ] || { echo "no graphs in results/ yet; run ./measure.sh first"; exit 1; }
"$PY" "$ROOT/nebby/make_gallery.py" "$ROOT/results/index.html" "${imgs[@]}" "$@"
echo "open it with: xdg-open results/index.html"
