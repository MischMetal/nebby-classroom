# Measure a website's congestion window with Nebby

These scripts use [Nebby](https://github.com/NUS-SNL/Nebby) to download a web
page through an emulated slow link, record every packet, and plot how the
website's server grew and shrank its **congestion window (cwnd)** over time.

## 1. What you need

* **Linux** with `sudo` access. Ubuntu 22.04 or 24.04 works best, and a VM is fine.
  The emulator Nebby uses (mahimahi) needs Linux, so it does not run on macOS and
  usually fails under WSL.
  * On macOS or Windows, create an Ubuntu VM, for example with
    [Multipass](https://multipass.run/):
    ```bash
    multipass launch 24.04 -n nebby -c 2 -m 4G -d 15G
    multipass shell nebby
    ```
* A normal internet connection (no proxy).

## 2. Install (once, about 5 minutes)

```bash
git clone <this-repo-url> nebby-classroom
cd nebby-classroom
./setup.sh
```

Run it as your normal user, **not** with `sudo`. It asks for your password when
it needs it. When it finishes, it should print `plotting: OK` and `mahimahi: OK`.

## 3. Measure a website

```bash
./measure.sh <name> <url>
```

For example:

```bash
./measure.sh wikipedia https://en.wikipedia.org/wiki/Transmission_Control_Protocol
```

* `<name>` is any short label (letters, digits, `.`, `_`, `-`). It names the results folder.
* A measurement takes up to about a minute. Don't use the network heavily while it runs.
* The graph is drawn automatically when the measurement ends.

Results go to `results/<name>/`:

| file | what it is |
|---|---|
| `cwnd.png` | **the cwnd graph** |
| `bif.csv` | the data behind the graph (time, bytes in flight, smoothed packets in flight) |
| `packets.csv`, `capture.pcap` | the raw packet trace |
| `wget.log` | what the download did (check this if something looks wrong) |
| `meta.json` | the settings used |

Open the graph with `xdg-open results/wikipedia/cwnd.png`, or copy it out of your VM.

### Measure many websites at once

**Large pages from the top 5,000 websites.** `full_links.csv` (from the Nebby
study) lists one large page for each of the 5,000 most popular websites, as
`<rank> <domain> <url>`. These pages are big enough to produce meaningful
graphs. Measuring all of them takes days, so pick a range of ranks:

```bash
./measure_all.sh full_links.csv 1-20       # ranks 1 to 20
./measure_all.sh full_links.csv 250-270    # ranks 250 to 270
```

Each result is saved as `results/<rank>-<domain>/`, e.g. `results/5-wikipedia.org/cwnd.png`.
To find a particular site: `grep -i spotify full_links.csv`.

**Your own list.** You can also list sites in `sites.txt` (or any file), one
`<name> <url>` per line. A starter list is included:

```
wikipedia   https://en.wikipedia.org/wiki/Transmission_Control_Protocol
youtube     https://www.youtube.com/
```

```bash
./measure_all.sh              # measures every site in sites.txt
./measure_all.sh mysites.txt  # or your own list
```

Options for `measure.sh` (below) go after the list and range, e.g.
`./measure_all.sh full_links.csv 1-20 -b 500`. When you're done:

```bash
./gallery.sh                  # puts all the graphs on one page: results/index.html
```

Expect up to about a minute per site. Some links will fail (pages move, some
sites block scripted downloads); the summary at the end lists which.

### Choosing a good URL

Nebby downloads **only the page's HTML file**, without images or scripts. The
graph shows something interesting only if that file is big enough for the
server to hit a few losses: aim for **200 KB or more**. The pages in
`full_links.csv` were chosen to be large. Elsewhere, long articles, big home
pages (news, shopping, video sites) and large downloadable files work well.
If your graph only shows a short climb from zero, try a bigger page or file, or
a lower bandwidth (`-b 100`).

### Options

```bash
./measure.sh [options] <name> <url>
```

| option | meaning | default |
|---|---|---|
| `-b KBPS` | bandwidth of the emulated bottleneck | 200 kbps (use 500–1000 for large files / video sites) |
| `-d MS` | one-way delay between the bottleneck and you | 50 ms (round-trip = 2 × (pre + post)) |
| `-p MS` | one-way delay before the capture point | 0 ms |
| `-q BDP` | bottleneck buffer size, in bandwidth-delay products | 2 |
| `-t SEC` | stop the download after this many seconds | 60 |
| `-f` | overwrite `results/<name>` if it already exists | |

Example: `./measure.sh -b 500 -t 90 kernel https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.6.tar.xz`

## 4. Plot (again)

`measure.sh` already makes the graph. To redraw graphs with different options
without measuring again:

```bash
./plot.sh                                # redraw every graph in results/
./plot.sh results/wikipedia              # just one
./plot.sh results/wikipedia --smooth-rtts 2   # smooth over 2 RTTs instead of 1
./plot.sh results/wikipedia --raw        # no smoothing: the per-packet estimate only
./plot.sh results/wikipedia --xmax 20    # only show the first 20 seconds
./plot.sh results/wikipedia --all-flows  # one panel per TCP connection (e.g. after redirects)
```

## 5. Reading the graph

* **x axis:** seconds since the connection started.
* **y axis:** the server's bytes in flight divided by the packet size, which is
  roughly its **cwnd in packets**.
* **Dark blue line:** the cwnd, averaged over one round-trip time (the shortest
  RTT seen during the download) so the overall shape is easy to see.
* **Faint light-blue line:** the raw estimate after every packet and ACK. Its
  fast up-and-down fuzz within each RTT is normal.
* **Red ×:** a retransmission, so a packet was lost just before.
* **Dashed lines:** **BDP** (just enough data to fill the link) and **BDP + buffer**
  (the most the link can hold before the queue overflows and drops packets).
* The first ~0.5 s is the TCP and TLS handshake; after that the server starts sending.

## Troubleshooting

| problem | fix |
|---|---|
| `'mm-delay' not found` | run `./setup.sh` |
| "run as your normal user, not root" | run `./measure.sh`, not `sudo ./measure.sh` |
| `results/<name> already exists` | add `-f` to overwrite, or use another name |
| "no TCP flow carried more than 5 KB" | the site blocked the download, redirected to a tiny page, or is IPv6-only; read `results/<name>/wget.log` and try another URL |
| the graph only shows a short climb | the page is too small: use a bigger page/file or `-b 100` |
| "no packets captured" | read `results/<name>/emulator.log`; check `sysctl net.ipv4.ip_forward` is `1` (`sudo sysctl -w net.ipv4.ip_forward=1`) |

## Credit

Based on Nebby (MIT license, NUS-SNL):

> Ayush Mishra, Lakshay Rastogi, Raj Joshi, Ben Leong. *Keeping an Eye on
> Congestion Control in the Wild with Nebby.* ACM SIGCOMM 2024.
