#!/usr/bin/env bash
# Convert a pcap to the per-packet CSV that nebby/bif.py reads (TCP only).
# Same tshark fields as Nebby's analysis/pcap2csv.sh.
#   usage: nebby/pcap2csv.sh capture.pcap packets.csv
set -euo pipefail
if [ $# -ne 2 ]; then echo "usage: $0 <capture.pcap> <out.csv>" >&2; exit 1; fi

tshark -r "$1" -Y tcp -o tcp.relative_sequence_numbers:TRUE \
    -T fields -E header=y -E separator=, -E quote=d -E occurrence=f \
    -e frame.time_relative -e frame.number -e frame.len \
    -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport \
    -e tcp.len -e tcp.seq -e tcp.ack \
    >"$2" 2>/dev/null
