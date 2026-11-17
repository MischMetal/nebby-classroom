#!/usr/bin/env bash
# One-time setup for Nebby-classroom on Ubuntu / Debian (22.04 or 24.04 recommended).
#
#   ./setup.sh
#
# Installs: mahimahi (built from source), tcpdump, tshark, wget, curl, and a
# Python virtualenv (.venv) with matplotlib + numpy. Safe to run twice.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || die "Nebby needs Linux (mahimahi uses Linux network namespaces). Use an Ubuntu VM; see README."
command -v apt-get >/dev/null || die "this script supports Debian/Ubuntu (apt). Install the packages listed in it by hand."
[ "$EUID" -ne 0 ] || die "run as your normal user; the script uses sudo where needed"
if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "warning: WSL detected. mahimahi often fails under WSL; a real Ubuntu VM is recommended."
fi
sudo -v

# ---------------------------------------------------------------- packages
say "Installing system packages"
echo "wireshark-common wireshark-common/install-setuid boolean false" | sudo debconf-set-selections
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git build-essential autotools-dev dh-autoreconf pkg-config \
    protobuf-compiler libprotobuf-dev libssl-dev ssl-cert \
    libxcb-present-dev libcairo2-dev libpango1.0-dev \
    iptables iproute2 dnsmasq-base apache2-bin debhelper \
    tcpdump tshark wget curl kmod \
    python3 python3-venv python3-pip

# ---------------------------------------------------------------- mahimahi
if command -v mm-delay >/dev/null && command -v mm-link >/dev/null; then
    say "mahimahi already installed ($(command -v mm-delay))"
else
    say "Building mahimahi from source (takes a few minutes)"
    SRC="${XDG_CACHE_HOME:-$HOME/.cache}/nebby-classroom/mahimahi"
    if [ ! -d "$SRC/.git" ]; then
        mkdir -p "$(dirname "$SRC")"
        git clone --depth 1 https://github.com/ravinet/mahimahi "$SRC"
    fi
    (
        cd "$SRC"
        # Newer compilers add warnings; mahimahi builds with -Werror. Drop it.
        sed -i 's/ -Werror//' configure.ac
        ./autogen.sh
        ./configure
        make -j"$(nproc)"
        sudo make install
    )
    command -v mm-delay >/dev/null || die "mahimahi build failed; see output above"
fi

# mahimahi needs IP forwarding; make it survive reboots.
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/90-nebby-classroom.conf >/dev/null
sudo sysctl -q -w net.ipv4.ip_forward=1

# ---------------------------------------------------------------- python
say "Creating Python environment in .venv"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"

chmod +x "$ROOT"/*.sh "$ROOT"/nebby/*.sh "$ROOT"/nebby/emu/*.sh "$ROOT"/nebby/*.py

# ---------------------------------------------------------------- self-test
say "Self-test"
"$ROOT/.venv/bin/python" -c "import matplotlib" && echo "plotting: OK"
if mm-delay 1 true 2>/dev/null; then echo "mahimahi: OK"; else
    echo "mahimahi: FAILED to start a shell. Check 'sysctl net.ipv4.ip_forward' (must be 1) and that you are not root."
fi

cat <<EOF

All set. Try:
  ./measure.sh wikipedia https://en.wikipedia.org/wiki/Transmission_Control_Protocol
  xdg-open results/wikipedia/cwnd.png
EOF
