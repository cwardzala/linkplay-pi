# linkplay-pi

Displays currently playing track info from a [LinkPlay](https://developer.arylic.com/httpapi/) device on a Raspberry Pi with an [Inky wHAT](https://shop.pimoroni.com/products/inky-what) e-ink display.

Polls the device every 5 seconds and only refreshes the display when something changes (title, artist, album, source, or volume).

## Features

- Track title (Playfair Display, wraps to 2 lines), artist, and album
- Source label and volume in the footer (Spotify, AirPlay, Bluetooth, etc.)
- Vinyl record graphic for analog inputs (Line-In, Optical) — no metadata shown
- Dithered rendering for smooth text edges on e-ink

## Requirements

- Python 3.8+
- Raspberry Pi with Inky wHAT attached (for hardware use)
- A LinkPlay device on your local network

## Raspberry Pi setup (one-liner)

```bash
curl -sSL https://raw.githubusercontent.com/cwardzala/linkplay-pi/main/install.sh | bash
```

The installer will:
1. Install system packages (`python3-venv`, `git`, SPI/I2C support)
2. Clone this repo to `~/linkplay-pi`
3. Create a virtualenv and install Python dependencies
4. Download fonts (Playfair Display + Inter)
5. Enable I2C and SPI via `raspi-config`
6. Optionally install and enable a systemd service so it starts on boot

> **Note:** Update the `REPO_URL` at the top of `install.sh` to point to your fork before hosting it.

## Manual setup

**1. Clone and enter the project:**

```bash
git clone <repo-url> linkplay-pi
cd linkplay-pi
```

**2. Download fonts:**

```bash
python3 src/download_fonts.py
```

This fetches Playfair Display and Inter from Google Fonts into a local `fonts/` directory. No internet access needed after this step.

**3. Install dependencies:**

On the Raspberry Pi:

```bash
pip3 install -r requirements.txt
```

For local development (no Inky hardware):

```bash
pip3 install -r requirements-local.txt
```

## Running

**On the Pi:**

```bash
python3 src/nowplaying.py --host 192.168.0.186
```

**Local development** (opens an emulator window — no hardware needed):

```bash
INKY_DISPLAY=what:black python3 src/nowplaying.py --host 192.168.0.186
```

The `INKY_DISPLAY` value is `<type>:<colour>` — type is `phat`, `what`, or `impression`; colour is `black`, `red`, or `yellow`.

### Configuring the device IP

The device IP can be set three ways, in order of precedence:

| Method | Example |
|--------|---------|
| `--host` CLI flag | `python3 src/nowplaying.py --host 192.168.1.50` |
| `LINKPLAY_HOST` env var | `LINKPLAY_HOST=192.168.1.50 python3 src/nowplaying.py` |
| Default in source | Edit `DEVICE_URL` in `src/nowplaying.py` |

## Running on boot (systemd)

**1. Copy the project to your Pi:**

```bash
scp -r . pi@raspberrypi.local:/home/pi/linkplay-pi
```

**2. Edit the service file** to set your device IP:

```bash
nano nowplaying.service
# Update: Environment=LINKPLAY_HOST=192.168.x.x
```

**3. Install and enable the service:**

```bash
sudo cp nowplaying.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nowplaying
```

**Check status / logs:**

```bash
sudo systemctl status nowplaying
journalctl -u nowplaying -f
```

## Supported sources

| Mode | Label | Display |
|------|-------|---------|
| Spotify | Spotify | Track info |
| AirPlay | AirPlay | Track info |
| Bluetooth | Bluetooth | Track info |
| USB | USB | Track info |
| DLNA | DLNA | Track info |
| Network | Network | Track info |
| Line-In | Line-In | Vinyl graphic |
| Line-In 2 | Line-In 2 | Vinyl graphic |
| Optical | Optical | Centered source name |
