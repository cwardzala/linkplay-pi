#!/usr/bin/env bash
# linkplay-pi installer
# Usage: curl -sSL https://raw.githubusercontent.com/YOUR_USERNAME/linkplay-pi/main/install.sh | bash
set -euo pipefail

REPO_URL="https://github.com/cwardzala/linkplay-pi"
INSTALL_DIR="$HOME/linkplay-pi"
SERVICE="nowplaying"
VENV="$INSTALL_DIR/venv"
PYTHON="$VENV/bin/python"

# ── Colour helpers ────────────────────────────────────────────────────────────
if [ -t 1 ] && tput colors &>/dev/null 2>&1 && [ "$(tput colors)" -ge 8 ]; then
    BOLD=$(tput bold); GREEN=$(tput setaf 2)
    YELLOW=$(tput setaf 3); RED=$(tput setaf 1); RESET=$(tput sgr0)
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

info()  { printf "%s▶%s %s\n"  "$GREEN"  "$RESET" "$*"; }
warn()  { printf "%s⚠%s  %s\n" "$YELLOW" "$RESET" "$*"; }
error() { printf "%s✗%s  %s\n" "$RED"    "$RESET" "$*" >&2; exit 1; }
step()  { printf "\n%s── %s%s\n" "$BOLD" "$*" "$RESET"; }
hr()    { printf "%s%s%s\n" "$BOLD" "─────────────────────────────────────────" "$RESET"; }

# ── Guards ────────────────────────────────────────────────────────────────────
require_sudo() {
    # Redirect sudo's password prompt to the TTY so it works through curl | bash.
    if ! sudo -v </dev/tty 2>/dev/tty; then
        error "sudo access is required. Run as a user with sudo privileges."
    fi
}

require_cmd() {
    command -v "$1" &>/dev/null || error "'$1' not found. Install it and re-run."
}

is_raspberry_pi() {
    grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null \
        || grep -qi "raspberry pi" /proc/cpuinfo 2>/dev/null
}

# ── Prompt (works even when stdin is the curl pipe) ───────────────────────────
ask() {
    local prompt="$1" default="$2" reply
    printf "  %s [%s]: " "$prompt" "$default"
    read -r reply </dev/tty
    echo "${reply:-$default}"
}

confirm() {
    local reply
    printf "  %s [y/N]: " "$1"
    read -r reply </dev/tty
    [[ "${reply,,}" == "y" ]]
}

# ── Steps ─────────────────────────────────────────────────────────────────────
install_system_deps() {
    step "System packages"
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv git
    # SPI/I2C support for Inky
    sudo apt-get install -y --no-install-recommends \
        python3-spidev python3-lgpio 2>/dev/null || true
    info "Done."
}

clone_or_update() {
    step "Repository"
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Existing installation found — pulling latest..."
        git -C "$INSTALL_DIR" pull --ff-only
    else
        info "Cloning into $INSTALL_DIR..."
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
}

setup_venv() {
    step "Python environment"
    # --system-site-packages lets the venv use apt-installed packages like
    # python3-spidev and python3-lgpio without rebuilding them from source.
    python3 -m venv --system-site-packages "$VENV"
    "$VENV/bin/pip" install --upgrade pip -q
    "$VENV/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
    info "Done."
}

download_fonts() {
    step "Fonts"
    "$PYTHON" "$INSTALL_DIR/src/download_fonts.py"
}

enable_hardware_interfaces() {
    step "Hardware interfaces"
    if command -v raspi-config &>/dev/null; then
        sudo raspi-config nonint do_i2c 0
        sudo raspi-config nonint do_spi 0
        info "I2C and SPI enabled."
    else
        warn "raspi-config not found — enable I2C and SPI manually:"
        warn "  sudo raspi-config  →  Interface Options"
    fi
}

install_service() {
    local ip="$1"
    local user; user="$(whoami)"
    local target="/etc/systemd/system/${SERVICE}.service"

    step "systemd service"
    sudo cp "$INSTALL_DIR/nowplaying.service" "$target"
    sudo sed -i \
        -e "s|LINKPLAY_HOST=.*|LINKPLAY_HOST=${ip}|" \
        -e "s|^User=.*|User=${user}|" \
        -e "s|WorkingDirectory=.*|WorkingDirectory=${INSTALL_DIR}|" \
        -e "s|ExecStart=.*|ExecStart=${PYTHON} ${INSTALL_DIR}/src/nowplaying.py|" \
        "$target"

    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE"
    info "Service enabled and started."
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo
    hr
    printf "%s  linkplay-pi installer%s\n" "$BOLD" "$RESET"
    hr
    echo

    if ! is_raspberry_pi; then
        warn "Raspberry Pi not detected — hardware setup will be skipped."
        PI=false
    else
        info "Raspberry Pi detected."
        PI=true
    fi

    require_sudo
    require_cmd python3
    require_cmd git

    echo
    local ip
    ip=$(ask "LinkPlay device IP" "192.168.0.186")

    install_system_deps
    clone_or_update
    setup_venv
    download_fonts

    if [ "$PI" = true ]; then
        enable_hardware_interfaces
    fi

    if confirm "Install and enable systemd service (starts on boot)?"; then
        install_service "$ip"
        SERVICE_INSTALLED=true
    else
        warn "Skipping service install. Run manually with:"
        warn "  $PYTHON $INSTALL_DIR/src/nowplaying.py --host $ip"
        SERVICE_INSTALLED=false
    fi

    echo
    hr
    info "Setup complete!"
    echo
    printf "  %-12s %s\n" "Device IP:"  "$ip"
    printf "  %-12s %s\n" "Installed:"  "$INSTALL_DIR"
    if [ "${SERVICE_INSTALLED:-false}" = true ]; then
        printf "  %-12s %s\n" "Service:"    "sudo systemctl status $SERVICE"
        printf "  %-12s %s\n" "Logs:"       "journalctl -u $SERVICE -f"
    fi
    echo
    hr
    echo
}

main "$@"
