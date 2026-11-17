#!/usr/bin/env bash
# Measure every site in a list (default: sites.txt), one after another.
#
#   ./measure_all.sh                          # all of sites.txt with default settings
#   ./measure_all.sh my_sites.txt             # your own list
#   ./measure_all.sh full_links.csv 1-20      # only ranks 1..20 of full_links.csv
#   ./measure_all.sh full_links.csv 100-120 -b 500   # extra options go to measure.sh
#
# Two list formats are accepted ('#' starts a comment):
#   <name> <url>            (sites.txt)
#   <rank> <domain> <url>   (full_links.csv; saved as results/<rank>-<domain>)
# The optional FROM-TO range selects lines by rank (or by line number for
# <name> <url> lists). Existing results/<name> folders are overwritten.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)

LIST="$ROOT/sites.txt"
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then LIST=$1; shift; fi
[ -f "$LIST" ] || { echo "error: no such list: $LIST" >&2; exit 1; }
FROM=1 TO=999999
if [ $# -gt 0 ] && [[ $1 =~ ^([0-9]+)-([0-9]+)$ ]]; then
    FROM=${BASH_REMATCH[1]} TO=${BASH_REMATCH[2]}; shift
fi

sudo -v || exit 1
ok=() failed=()
n=0
while read -r a b c _; do
    [ -z "${a:-}" ] && continue
    [ "${a:0:1}" = "#" ] && continue
    n=$((n + 1))
    if [[ $a =~ ^[0-9]+$ ]] && [ -n "${c:-}" ]; then
        rank=$a name="$a-$b" url=$c      # <rank> <domain> <url>
    else
        rank=$n name=$a url=$b           # <name> <url>
    fi
    [ "$rank" -lt "$FROM" ] && continue
    [ "$rank" -gt "$TO" ] && break
    if "$ROOT/measure.sh" -f "$@" "$name" "$url" </dev/null; then
        ok+=("$name")
    else
        failed+=("$name")
    fi
    sleep 1
done <"$LIST"

echo
echo "== done: ${#ok[@]} measured, ${#failed[@]} failed"
[ ${#failed[@]} -eq 0 ] || echo "   failed: ${failed[*]}"
echo "   graphs: results/<name>/cwnd.png   (./gallery.sh puts them all on one page)"
