#!/usr/bin/env bash
# Runs INSIDE the outer `mm-delay <predelay>` shell (see measure.sh).
#
#   Internet --[mm-delay predelay]--(tcpdump here, "ingress")--[mm-link bottleneck + droptail
#            queue]--[mm-delay postdelay]-- client (wget)
#
# tcpdump sits just before the bottleneck, so it sees every data packet the
# server sends and every ACK the client returns. This mirrors Nebby's btl.sh.
set -u
out=$1 postdelay=$2 buf_bytes=$3 url=$4 timeout_s=$5
here=$(cd "$(dirname "$0")" && pwd)

sudo tcpdump -i ingress -n -s 128 -U -Z "$(id -un)" -w "$out/capture.pcap" \
    >"$out/tcpdump.log" 2>&1 &
tcpdump_pid=$!
sleep 1   # let tcpdump attach before traffic starts

mm-link "$out/link.trace" "$out/link.trace" \
    --uplink-queue=droptail --downlink-queue=droptail \
    --uplink-queue-args="bytes=$buf_bytes" --downlink-queue-args="bytes=$buf_bytes" \
    mm-delay "$postdelay" "$here/client.sh" "$out" "$url" "$timeout_s"

sleep 2   # catch the last ACKs / FINs
# "[-]w" matches tcpdump's "-w" but not this pkill's own command line
sudo pkill -INT -f -- "[-]w $out/capture.pcap" || true
wait "$tcpdump_pid" 2>/dev/null || true
