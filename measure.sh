#!/usr/bin/env bash
# Measure one website with Nebby and plot its cwnd (bytes-in-flight) graph.
#
#   ./measure.sh [options] <name> <url>
#   ./measure.sh wikipedia https://en.wikipedia.org/wiki/Transmission_Control_Protocol
#
# Results go to results/<name>/:
#   cwnd.png      the graph            packets.csv  per-packet trace (tshark)
#   bif.csv       bytes in flight      capture.pcap raw capture
#   meta.json     link settings        wget.log     what the download did
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)

PRE=0          # one-way delay before the capture point, ms (Nebby: pre-delay)
POST=50        # one-way delay between the bottleneck and the client, ms
BW=200         # bottleneck bandwidth, kbps
BUF=2          # bottleneck buffer, in BDPs
TIMEOUT=60     # stop the download after this many seconds
OUT="$ROOT/results"
FORCE=0

usage() {
    cat <<EOF
Usage: $0 [options] <name> <url>

Options (defaults follow the Nebby paper's web-page setup):
  -b KBPS   bottleneck bandwidth in kbps       (default $BW; use 500-1000 for video sites)
  -d MS     one-way delay after the bottleneck  (default $POST ms, so base RTT = 2*(pre+post))
  -p MS     one-way delay before the capture    (default $PRE ms)
  -q BDP    buffer size in BDPs                 (default $BUF)
  -t SEC    max download time in seconds        (default $TIMEOUT)
  -o DIR    results folder                      (default results/)
  -f        overwrite results/<name> if it exists
EOF
    exit 1
}

while getopts "b:d:p:q:t:o:fh" opt; do
    case $opt in
        b) BW=$OPTARG ;; d) POST=$OPTARG ;; p) PRE=$OPTARG ;; q) BUF=$OPTARG ;;
        t) TIMEOUT=$OPTARG ;; o) OUT=$OPTARG ;; f) FORCE=1 ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))
[ $# -eq 2 ] || usage
NAME=$1 URL=$2

die() { echo "error: $*" >&2; exit 1; }
[[ $NAME =~ ^[A-Za-z0-9._-]+$ ]] || die "name may only contain letters, digits, '.', '_' and '-'"
[[ $URL =~ ^https?:// ]] || die "url must start with http:// or https://"
for pair in "-b:$BW" "-d:$POST" "-p:$PRE" "-t:$TIMEOUT"; do
    [[ ${pair#*:} =~ ^[0-9]+$ ]] || die "${pair%%:*} must be a whole number (got '${pair#*:}')"
done
[[ $BUF =~ ^[0-9]+(\.[0-9]+)?$ ]] || die "buffer must be a number"
[ "$BW" -ge 12 ] || die "bandwidth must be at least 12 kbps"
[ "$EUID" -ne 0 ] || die "run as your normal user, not root (mahimahi refuses root); the script calls sudo itself"
for c in mm-delay mm-link tcpdump tshark wget; do
    command -v "$c" >/dev/null || die "'$c' not found; run ./setup.sh first"
done

OUT=$(mkdir -p "$OUT" && cd "$OUT" && pwd)
DIR="$OUT/$NAME"
if [ -e "$DIR" ]; then
    [ "$FORCE" = 1 ] || die "$DIR already exists (use -f to overwrite, or pick another name)"
    rm -rf "$DIR"
fi
mkdir -p "$DIR"

# sudo is needed inside the emulator (tcpdump, MTU, sysctl). Ask once, keep it alive.
sudo -v
( while true; do sudo -n true 2>/dev/null; sleep 50; done ) &
KEEPALIVE=$!
cleanup() {
    kill "$KEEPALIVE" 2>/dev/null || true
    sudo pkill -INT -f -- "[-]w $DIR/capture.pcap" 2>/dev/null || true
}
trap cleanup EXIT
[ "$(sysctl -n net.ipv4.ip_forward)" = 1 ] || sudo sysctl -q -w net.ipv4.ip_forward=1

# --- emulated link (same construction as Nebby's simnet.sh) -------------------
# BDP in bytes = bw[kbps] * RTT[ms] / 8, with RTT = 2 * (pre + post)
BUF_BYTES=$(awk -v p="$PRE" -v q="$POST" -v b="$BW" -v k="$BUF" 'BEGIN { printf "%d", (p + q) * b * k / 4 }')
[ "$BUF_BYTES" -ge 1500 ] || BUF_BYTES=1500
# mahimahi trace: each line is one 1500-byte delivery opportunity (ms timestamp);
# bw/12 opportunities per 1000 ms = bw kbps.
NUM=$((BW / 12))
for ((c = 1; c <= NUM; c++)); do echo $((c * 1000 / NUM)); done >"$DIR/link.trace"

cat >"$DIR/meta.json" <<EOF
{
  "name": "$NAME",
  "url": "$URL",
  "predelay_ms": $PRE,
  "postdelay_ms": $POST,
  "bw_kbps": $BW,
  "buffer_bdp": $BUF,
  "buffer_bytes": $BUF_BYTES,
  "timeout_s": $TIMEOUT,
  "date": "$(date -Is)",
  "kernel": "$(uname -r)"
}
EOF

echo "== $NAME: $URL"
echo "   bottleneck ${BW} kbps, base RTT $((2 * (PRE + POST))) ms, buffer ${BUF} BDP (${BUF_BYTES} B), up to ${TIMEOUT}s"
mm-delay "$PRE" "$ROOT/nebby/emu/bottleneck.sh" "$DIR" "$POST" "$BUF_BYTES" "$URL" "$TIMEOUT" \
    >"$DIR/emulator.log" 2>&1 || echo "   (emulator exited with $?; see $DIR/emulator.log)"

[ -s "$DIR/capture.pcap" ] || die "no packets captured; see $DIR/emulator.log and $DIR/tcpdump.log"
"$ROOT/nebby/pcap2csv.sh" "$DIR/capture.pcap" "$DIR/packets.csv"
echo "   captured $(($(wc -l <"$DIR/packets.csv") - 1)) TCP packets"
tail -n 3 "$DIR/wget.log" 2>/dev/null | sed 's/^/   wget: /' || true

PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
"$PY" "$ROOT/nebby/plot_bif.py" "$DIR"
