#!/usr/bin/env bash
# (Re)draw cwnd graphs without measuring again.
#
#   ./plot.sh                          # every folder in results/
#   ./plot.sh results/wikipedia        # one measurement
#   ./plot.sh results/youtube --all-flows --smooth
#   ./plot.sh -h                       # all options
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3

has_input=0
for a in "$@"; do [ "${a#-}" = "$a" ] && has_input=1; done
if [ "$has_input" = 0 ] && [ "${1:-}" != "-h" ] && [ "${1:-}" != "--help" ]; then
    shopt -s nullglob
    dirs=("$ROOT"/results/*/)
    [ ${#dirs[@]} -gt 0 ] || { echo "no measurements in results/ yet; run ./measure.sh first"; exit 1; }
    set -- "${dirs[@]}" "$@"
fi
exec "$PY" "$ROOT/nebby/plot_bif.py" "$@"
