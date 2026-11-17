#!/usr/bin/env python3
"""
Plot Nebby's bytes-in-flight (≈ cwnd) graph for one or more measurements.

Examples
  python3 nebby/plot_bif.py results/wikipedia            # a measurement folder
  python3 nebby/plot_bif.py results/*                    # every measurement
  python3 nebby/plot_bif.py some-trace-tcp.csv           # a raw Nebby CSV
  python3 nebby/plot_bif.py results/x --all-flows        # one panel per TCP flow
  python3 nebby/plot_bif.py results/x --smooth-rtts 2    # smooth over 2 RTTs instead of 1
  python3 nebby/plot_bif.py results/x --raw              # per-packet estimate only, no smoothing

For a folder, the plot is written to <folder>/cwnd.png and the time series of the
main flow to <folder>/bif.csv. For a CSV file, the plot is written next to it.
"""

import argparse
import csv
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import bif  # noqa: E402

# Colors (light theme): one series, a reserved "critical" red for loss events,
# and recessive gray for reference lines, ink and grid.
C_SERIES = "#2a78d6"
C_RAW = "#b9d3f3"      # light step of the series hue, for the unsmoothed estimate
C_LOSS = "#d03b3b"
C_REF = "#52514e"
C_INK = "#0b0b0b"
C_MUTED = "#8a8984"
C_GRID = "#e6e5e1"
C_SURFACE = "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": C_SURFACE, "axes.facecolor": C_SURFACE,
    "axes.edgecolor": C_MUTED, "axes.labelcolor": C_INK,
    "xtick.color": C_REF, "ytick.color": C_REF,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": C_GRID, "grid.linewidth": 0.8,
    "font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
    "legend.frameon": False,
})

NEBBY_NAME = re.compile(r"^(?P<name>.+?)-(?P<pre>\d+)-(?P<post>\d+)-(?P<bw>\d+)-(?P<buf>\d+(?:\.\d+)?)-tcp\.csv(?:\.gz)?$")


def resolve(inp):
    """Map an input path to (csv_path, meta, png_path, bif_csv_path or None)."""
    if os.path.isdir(inp):
        csv_path = os.path.join(inp, "packets.csv")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"{inp}: no packets.csv (did the measurement finish?)")
        meta_path = os.path.join(inp, "meta.json")
        meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
        meta.setdefault("name", os.path.basename(os.path.normpath(inp)))
        return csv_path, meta, os.path.join(inp, "cwnd.png"), os.path.join(inp, "bif.csv")

    base = re.sub(r"\.csv(\.gz)?$", "", inp)
    meta = {}
    for cand in (base + ".json", base + ".meta.json"):
        if os.path.exists(cand):
            meta = json.load(open(cand))
            break
    m = NEBBY_NAME.match(os.path.basename(inp))
    if m and not meta:
        meta = {"name": m["name"], "predelay_ms": int(m["pre"]), "postdelay_ms": int(m["post"]),
                "bw_kbps": int(m["bw"]), "buffer_bdp": float(m["buf"])}
    meta.setdefault("name", os.path.basename(base))
    return inp, meta, base + ".png", None


def ref_lines(meta, mss):
    """BDP and BDP+buffer in packets, from the emulated-link settings (if known)."""
    try:
        rtt_ms = 2 * (meta["predelay_ms"] + meta["postdelay_ms"])
        bdp = meta["bw_kbps"] * rtt_ms / 8.0               # bytes
        buf = meta.get("buffer_bytes", meta["buffer_bdp"] * bdp)
    except (KeyError, TypeError):
        return []
    return [(bdp / mss, "BDP"), ((bdp + buf) / mss, "BDP + buffer")]


def subtitle(meta, fl):
    bits = [meta["setup"]] if meta.get("setup") else []
    if "bw_kbps" in meta and not meta.get("setup"):
        bits.append(f"{meta['bw_kbps']} kbps bottleneck")
    if "postdelay_ms" in meta:
        bits.append(f"{2 * (meta.get('predelay_ms', 0) + meta['postdelay_ms'])} ms base RTT")
    if "buffer_bdp" in meta:
        bits.append(f"{meta['buffer_bdp']:g} BDP buffer")
    if fl.min_rtt:
        bits.append(f"min RTT seen {fl.min_rtt * 1000:.0f} ms")
    bits.append(f"MSS {fl.mss} B")
    bits.append(f"{fl.data_bytes / 1000:.0f} KB sent")
    return "  ·  ".join(bits)


def rtt_window(fl, meta):
    """Smoothing window: the min RTT seen in the trace, else the emulated base RTT."""
    if fl.min_rtt:
        return fl.min_rtt
    try:
        return 2 * (meta.get("predelay_ms", 0) + meta["postdelay_ms"]) / 1000.0
    except (KeyError, TypeError):
        return None


def smooth(times, values, window, step=None):
    """
    Time-weighted moving average of a step function over a centered window.

    BiF holds its value until the next packet, so we average it over *time*
    (not over packets, which would over-weight bursts). Returns (grid, avg).
    """
    t = np.asarray(times, dtype=float)
    v = np.asarray(values, dtype=float)
    # cumulative integral of the step function at each sample time (exact, piecewise linear)
    integ = np.concatenate(([0.0], np.cumsum(v[:-1] * np.diff(t))))
    step = step or window / 10.0
    grid = np.arange(t[0], t[-1] + step / 2, step)
    lo = np.clip(grid - window / 2, t[0], t[-1])
    hi = np.clip(grid + window / 2, t[0], t[-1])
    span = np.maximum(hi - lo, 1e-9)
    avg = (np.interp(hi, t, integ) - np.interp(lo, t, integ)) / span
    return grid, avg


def draw_flow(ax, fl, meta, args, show_refs=True):
    pk = [b / fl.mss for b in fl.bif]
    win = None if args.raw else rtt_window(fl, meta)
    if win and len(fl.times) > 2:
        win *= args.smooth_rtts
        ax.plot(fl.times, pk, color=C_RAW, lw=0.6, zorder=1, label="per-packet estimate")
        grid, avg = smooth(fl.times, pk, win)
        ax.plot(grid, avg, color=C_SERIES, lw=1.8, zorder=2,
                label=f"cwnd (bytes in flight, averaged over {win * 1000:.0f} ms"
                      f" ≈ {args.smooth_rtts:g} RTT)")
        loss_y = np.interp(fl.retx_times, grid, avg) if fl.retx_times else []
    else:
        ax.plot(fl.times, pk, color=C_SERIES, lw=1.0, label="bytes in flight ≈ cwnd")
        loss_y = [b / fl.mss for b in fl.retx_bif]
    if fl.retx_times and not args.no_loss:
        ax.scatter(fl.retx_times, loss_y, s=22, marker="x",
                   color=C_LOSS, lw=1.4, zorder=3, label="retransmission (loss)")
    if show_refs:
        for y, name in ref_lines(meta, fl.mss):
            ax.axhline(y, color=C_REF, lw=1, ls=(0, (4, 3)), zorder=1)
            ax.text(0.995, y, name, transform=ax.get_yaxis_transform(), color=C_REF,
                    va="bottom", ha="right", fontsize=9,
                    bbox=dict(fc=C_SURFACE, ec="none", pad=1, alpha=0.85))
    ax.set_ylim(bottom=0)
    # stop shortly after the last data packet (idle tails until FIN are uninformative)
    ax.set_xlim(0, args.xmax or max(fl.last_data_t * 1.03, 0.5))


def plot_one(inp, args):
    csv_path, meta, png, bif_csv = resolve(inp)
    if args.out:
        if os.path.isdir(args.out) or len(args.inputs) > 1:
            fname = f"{meta['name']}.png" if os.path.isdir(inp) else os.path.basename(png)
            png = os.path.join(args.out, fname)
        else:
            png = args.out
    flows = bif.analyze(csv_path, min_data_bytes=args.min_kb * 1000)
    if not flows:
        print(f"[!] {inp}: no TCP flow carried more than {args.min_kb} KB of data. "
              "The page may be too small, blocked or served over QUIC; try another URL.")
        return False

    title = args.title or meta.get("name", "")

    if args.all_flows and len(flows) > 1:
        flows = flows[:12]
        cols = 2 if len(flows) > 1 else 1
        rows = math.ceil(len(flows) / cols)
        fig, axs = plt.subplots(rows, cols, figsize=(14, 3.6 * rows), squeeze=False)
        for i, fl in enumerate(flows):
            ax = axs[i // cols][i % cols]
            draw_flow(ax, fl, meta, args)
            ax.set_title(f"flow {i + 1}: {fl.label()}"
                         f"  ({fl.data_bytes / 1000:.0f} KB)", fontsize=10, loc="left")
            ax.set_ylabel("packets in flight")
            ax.set_xlabel("time (s)")
        for j in range(len(flows), rows * cols):
            axs[j // cols][j % cols].set_visible(False)
        fig.suptitle(title, fontweight="bold", x=0.01, ha="left")
        axs[0][0].legend(loc="upper right", fontsize=8)
    else:
        fl = flows[0]
        fig, ax = plt.subplots(figsize=(12, 5.5))
        draw_flow(ax, fl, meta, args)
        ax.set_title(title, loc="left", pad=22)
        ax.text(0, 1.02, subtitle(meta, fl), transform=ax.transAxes, color=C_REF, fontsize=9.5)
        ax.set_xlabel("time since connection start (s)")
        ax.set_ylabel("bytes in flight / MSS  (packets)")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=9)

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(png)), exist_ok=True)
    fig.savefig(png, dpi=args.dpi)
    plt.close(fig)

    main = flows[0]
    if bif_csv:
        with open(bif_csv, "w", newline="") as fh:
            w = csv.writer(fh)
            win = rtt_window(main, meta)
            if win and len(main.times) > 2:
                grid, avg = smooth(main.times, main.bif, win * args.smooth_rtts)
                sm = np.interp(main.times, grid, avg)
            else:
                sm = main.bif
            w.writerow(["time_s", "bytes_in_flight", "packets_in_flight", "packets_in_flight_smoothed"])
            for t, b, a in zip(main.times, main.bif, sm):
                w.writerow([f"{t:.6f}", b, f"{b / main.mss:.2f}", f"{a / main.mss:.2f}"])

    nflows = len(flows)
    print(f"[+] {inp}: {nflows} flow(s); main flow {main.data_bytes / 1000:.0f} KB over "
          f"{main.duration:.1f} s, {len(main.retx_times)} retransmissions -> {png}")
    if main.data_bytes < 100_000:
        print("    note: under 100 KB of data; the flow may end before its first loss. "
              "A larger page/file (or a lower bandwidth) gives a more telling graph.")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="measurement folders (results/<name>) or Nebby CSV files")
    ap.add_argument("--all-flows", action="store_true", help="one panel per TCP flow (largest 12)")
    ap.add_argument("--min-kb", type=float, default=5, help="ignore flows smaller than this (default 5 KB)")
    ap.add_argument("--smooth-rtts", type=float, default=1.0,
                    help="smoothing window in RTTs (default 1)")
    ap.add_argument("--raw", action="store_true", help="plot the per-packet estimate only, no smoothing")
    ap.add_argument("--no-loss", action="store_true", help="do not mark retransmissions")
    ap.add_argument("--xmax", type=float, help="cut the x axis at this many seconds")
    ap.add_argument("--out", help="output PNG (one input) or output folder (many inputs)")
    ap.add_argument("--title", help="custom plot title")
    ap.add_argument("--dpi", type=int, default=130)
    args = ap.parse_args()

    ok = 0
    for inp in args.inputs:
        try:
            ok += plot_one(inp, args)
        except Exception as e:  # keep going over the other measurements
            print(f"[!] {inp}: {e}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
