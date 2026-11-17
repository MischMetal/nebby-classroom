"""
Bytes-in-flight (BiF) estimation from a packet trace, following Nebby.

Nebby measures a remote sender from the receiver side. The receiver sits behind
an emulated bottleneck (mahimahi) and tcpdump records every data packet and ACK
at the bottleneck's ingress. From that trace we estimate, for every packet, how
many bytes the server currently has in flight:

    BiF ~= highest sequence number sent - highest ACK received + 1 MSS

Duplicate ACKs mean a packet left the network without advancing the
cumulative ACK, so on each duplicate ACK the estimate is reduced by one MSS
(this is the loss correction from Nebby's `bif_lakshay.py`).

Because the bottleneck is the only queue on the path and the client never
limits the window, BiF tracks the sender's congestion window closely, which is
why we can call the plot a "cwnd evolution graph".

The input is the CSV produced by `nebby/pcap2csv.sh` (tshark fields). Columns are
looked up by name, so the older Nebby CSV layouts (with or without
`_ws.col.Time`, with or without `ip.src`) also work. Files may be gzip'd.
"""

import csv
import gzip
import io
from collections import Counter, defaultdict

# tshark field names we need (all others are ignored)
F_TIME = "frame.time_relative"
F_SPORT = "tcp.srcport"
F_DPORT = "tcp.dstport"
F_LEN = "tcp.len"
F_SEQ = "tcp.seq"
F_ACK = "tcp.ack"
F_SRC = "ip.src"
F_DST = "ip.dst"


class Flow:
    """One TCP connection, with its BiF time series."""

    def __init__(self, key):
        self.key = key
        self.packets = []          # (t, sport, dport, len, seq, ack, src, dst)
        self.sender_port = None    # port of the side that sends the bulk data
        self.server = None         # (ip, port) of the data sender, if known
        self.mss = None
        self.data_bytes = 0
        # results
        self.times = []            # seconds since the flow's first packet
        self.bif = []              # bytes in flight after each packet
        self.retx_times = []       # times of retransmitted data packets
        self.retx_bif = []
        self.dupack_times = []
        self.min_rtt = None        # seconds, measured at the capture point
        self.last_data_t = 0.0     # time of the last data packet

    @property
    def client_port(self):
        a, b = self.key
        return b if a == self.sender_port else a

    @property
    def duration(self):
        return self.times[-1] - self.times[0] if self.times else 0.0

    def label(self):
        if self.server and self.server[0]:
            return f"{self.server[0]}:{self.server[1]} -> client port {self.client_port}"
        return f"server port {self.sender_port} -> client port {self.client_port}"


def _open(path):
    if str(path).endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), newline="")
    return open(path, newline="")


def _int(x):
    return int(x) if x not in (None, "") else None


def read_flows(path):
    """Group the packets of a tshark CSV into TCP flows."""
    flows = {}
    with _open(path) as fh:
        reader = csv.DictReader(fh)
        missing = {F_TIME, F_SPORT, F_DPORT, F_LEN, F_SEQ, F_ACK} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}; "
                             "was it produced by nebby/pcap2csv.sh?")
        for row in reader:
            sport, dport = _int(row.get(F_SPORT)), _int(row.get(F_DPORT))
            if sport is None or dport is None or row.get(F_SEQ) in (None, ""):
                continue  # not TCP (DNS, ARP, ...)
            key = tuple(sorted((sport, dport)))
            fl = flows.get(key)
            if fl is None:
                fl = flows[key] = Flow(key)
            fl.packets.append((float(row[F_TIME]), sport, dport,
                               _int(row.get(F_LEN)) or 0, _int(row[F_SEQ]),
                               _int(row.get(F_ACK)) or 0,
                               row.get(F_SRC, ""), row.get(F_DST, "")))
    return flows


def estimate_bif(fl):
    """Run Nebby's BiF estimator over one flow (fills fl.times / fl.bif ...)."""
    sent = defaultdict(int)
    for p in fl.packets:
        sent[p[1]] += p[3]
    if not sent or max(sent.values()) == 0:
        return fl
    fl.sender_port = max(sent, key=sent.get)
    fl.data_bytes = sent[fl.sender_port]

    lens = Counter(p[3] for p in fl.packets if p[1] == fl.sender_port and p[3] > 0)
    fl.mss = lens.most_common(1)[0][0]
    mss = fl.mss

    t0 = fl.packets[0][0]
    max_seq = max_ack = None
    back_ack = None
    send_time = {}  # seq_end -> first send time (for RTT samples)
    retx_ends = set()
    rtts = []

    for (t, sport, _dport, length, seq, ack, src, dst) in fl.packets:
        if sport == fl.sender_port:
            # ---- data packet (server -> client)
            if fl.server is None:
                fl.server = (src, sport)
            is_retx = False
            if max_seq is None:
                max_seq, max_ack = seq, (max_ack or 0)
            elif seq < max_seq and length > 0:
                is_retx = True
                retx_ends.add(seq + length)
            max_seq = max(max_seq, seq)
            if length > 0:
                fl.last_data_t = t - t0
                send_time.setdefault(seq + length, t)
            bif = max_seq - max_ack + mss
            if is_retx:
                fl.retx_times.append(t - t0)
                fl.retx_bif.append(max(bif, 0))
        else:
            # ---- ACK (client -> server)
            dup = False
            if max_ack is None:
                max_ack, max_seq = ack, (max_seq or 0)
            else:
                if ack <= max_ack:
                    dup = (ack == back_ack)
                    back_ack = ack
                if ack > max_ack and ack in send_time and ack not in retx_ends:
                    rtts.append(t - send_time[ack])
                max_ack = max(max_ack, ack)
            bif = max_seq - max_ack + mss
            if dup and len(fl.bif) > 10:
                fl.dupack_times.append(t - t0)
                loss_est = fl.bif[-1] - mss
                max_ack += mss  # the cumulative ACK will catch up later
                bif = min(bif, loss_est)
        fl.times.append(t - t0)
        fl.bif.append(max(bif, 0))

    fl.min_rtt = min(rtts) if rtts else None
    return fl


def analyze(path, min_data_bytes=0):
    """Return the flows of a trace, largest (by bytes sent) first."""
    flows = [estimate_bif(f) for f in read_flows(path).values()]
    flows = [f for f in flows if f.sender_port is not None and f.data_bytes >= min_data_bytes]
    flows.sort(key=lambda f: f.data_bytes, reverse=True)
    return flows
