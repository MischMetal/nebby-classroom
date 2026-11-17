#!/usr/bin/env bash
# Runs INSIDE the innermost mahimahi shell: this is the "client" whose traffic
# crosses the emulated bottleneck. Mirrors Nebby's client.sh.
set -u
out=$1 url=$2 timeout_s=$3

# A 100-byte MTU makes the client advertise a tiny MSS (~48-60 B). The server
# then needs many packets per RTT even at a few hundred kbps, which gives
# Nebby a fine-grained view of the cwnd from a cheap, slow bottleneck.
sudo ip link set dev ingress mtu 100
# Without SACK, every loss shows up as plain duplicate ACKs, which is what
# Nebby's bytes-in-flight estimator corrects for.
sudo sysctl -q -w net.ipv4.tcp_sack=0

echo "[client] fetching $url (max ${timeout_s}s)"
{
    echo "# $(date -Is) $url"
    timeout "$timeout_s" wget -4 -U Mozilla --tries=1 --timeout=30 -O /dev/null "$url"
    echo "# wget exit code: $? (124 = stopped by the time limit, which is fine)"
} >>"$out/wget.log" 2>&1
sleep 1
