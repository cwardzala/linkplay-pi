#!/usr/bin/env python3
"""
LinkPlay Now Playing — Raspberry Pi + Inky wHAT
Polls a LinkPlay device and renders current track info on the e-ink display.

Run with --preview to simulate the display locally (no hardware needed).
"""

import argparse
import os
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFont

# --- Config ---
# Override via --host CLI arg or LINKPLAY_HOST env var
DEVICE_URL      = f"http://{os.environ.get('LINKPLAY_HOST', '192.168.0.186')}"
POLL_INTERVAL   = 3   # seconds between polls
SETTLE_SECS     = 6   # render only after state is stable for this long
REQUEST_TIMEOUT = 5

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONTS = os.path.join(_HERE, "fonts")

PLAYBACK_MODES = {
    "0":  "Idle",
    "1":  "AirPlay",
    "2":  "DLNA",
    "10": "Network",
    "11": "USB",
    "20": "HTTP",
    "31": "Spotify",
    "40": "Line-In",
    "41": "Bluetooth",
    "43": "Optical",
    "47": "Line-In 2",
    "51": "USB DAC",
}

# Analog inputs — no track metadata available
ANALOG_MODES = {"40", "43", "47"}
# Subset of analog inputs that show the vinyl graphic; others show source name only
VINYL_MODES  = {"40", "47"}   # Line-In, Line-In 2

STATUS_LABELS = {
    "play":  "Playing",
    "pause": "Paused",
    "stop":  "Stopped",
    "load":  "Loading",
}

MARGIN = 20
HEADER_H = 42
FOOTER_H = 34

# Grayscale drawing values — render in "L" mode so PIL antialises TrueType
# edges, then dither to the display palette at the end.
BG = 255  # white
FG = 0    # black

# --- Helpers ---

def hex_to_str(hex_str):
    try:
        if not hex_str or hex_str in ("", "00"):
            return ""
        return bytes.fromhex(hex_str).decode("utf-8", errors="replace")
    except (ValueError, AttributeError):
        return str(hex_str)


def _truetype(path, size, weight=None):
    font = ImageFont.truetype(path, size)
    if weight is not None:
        try:
            font.set_variation_by_axes([weight])
        except (AttributeError, OSError):
            pass
    return font


def load_fonts():
    playfair = os.path.join(_FONTS, "PlayfairDisplay.ttf")
    inter = os.path.join(_FONTS, "Inter.ttf")
    dejavu_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    dejavu = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    # Preferred: downloaded Playfair Display (serif title) + Inter (body)
    # Fallback: system DejaVu, then PIL default
    if os.path.exists(playfair) and os.path.exists(inter):
        try:
            return {
                "title":  _truetype(playfair, 34, weight=700),
                "artist": _truetype(inter,    22, weight=500),
                "album":  _truetype(inter,    17, weight=400),
                "meta":   _truetype(inter,    15, weight=400),
            }
        except (OSError, TypeError):
            pass

    try:
        return {
            "title":  ImageFont.truetype(dejavu_bold, 34),
            "artist": ImageFont.truetype(dejavu,      22),
            "album":  ImageFont.truetype(dejavu,      17),
            "meta":   ImageFont.truetype(dejavu,      15),
        }
    except (OSError, TypeError):
        pass

    d = ImageFont.load_default()
    return {"title": d, "artist": d, "album": d, "meta": d}


def truncate(draw, text, font, max_px):
    if not text:
        return text
    if draw.textlength(text, font=font) <= max_px:
        return text
    while len(text) > 1 and draw.textlength(text[:-1] + "…", font=font) > max_px:
        text = text[:-1]
    return text[:-1] + "…"


def wrap_text(draw, text, font, max_width, max_lines=2):
    """Split text into lines that fit max_width, up to max_lines."""
    words = text.split()
    lines, current = [], []
    for word in words:
        candidate = " ".join(current + [word])
        if draw.textlength(candidate, font=font) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
        if len(lines) == max_lines:
            return lines
    if current:
        lines.append(truncate(draw, " ".join(current), font, max_width))
    return lines


def to_inky_palette(img_gray, inky):
    """
    Convert a grayscale ("L") image to Inky's palette format.
    Applies Floyd-Steinberg dithering so antialiased TrueType edges are
    preserved as a dither pattern rather than hard-thresholded to black/white.
    """
    img_bw = img_gray.convert("1", dither=Image.FLOYDSTEINBERG)
    img_l  = img_bw.convert("L")  # 0 = black pixel, 255 = white pixel
    # Map grayscale values → Inky palette indices (0=WHITE, 1=BLACK)
    lut    = [inky.BLACK] * 128 + [inky.WHITE] * 128
    img_indexed = img_l.point(lut)
    return Image.frombytes("P", img_gray.size, img_indexed.tobytes())


def draw_vinyl(draw, cx, cy, radius):
    """Draw a vinyl record icon centered at (cx, cy)."""
    r = radius
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=FG)
    for ring_r in [int(r * 0.93), int(r * 0.82), int(r * 0.71)]:
        draw.ellipse([cx-ring_r, cy-ring_r, cx+ring_r, cy+ring_r], outline=BG, width=1)
    lr = int(r * 0.42)
    draw.ellipse([cx-lr, cy-lr, cx+lr, cy+lr], fill=BG)
    ir = int(r * 0.27)
    draw.ellipse([cx-ir, cy-ir, cx+ir, cy+ir], outline=FG, width=1)
    hr = max(4, int(r * 0.07))
    draw.ellipse([cx-hr, cy-hr, cx+hr, cy+hr], fill=FG)


# --- API ---

def get_player_status():
    try:
        resp = requests.get(
            f"{DEVICE_URL}/httpapi.asp?command=getPlayerStatus",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[warn] API error: {exc}", file=sys.stderr)
        return None


def needs_update(prev, curr):
    if (prev is None) != (curr is None):
        return True
    if prev is None:
        return False
    return any(
        prev.get(k) != curr.get(k)
        for k in ("status", "Title", "Artist", "Album", "mode", "vol")
    )


# --- Rendering ---

def render(inky, fonts, status):
    W, H = inky.width, inky.height

    # Render to grayscale so PIL antialiases TrueType edges naturally.
    # to_inky_palette() dithers this down to the display's 2-color palette.
    img  = Image.new("L", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Header bar
    draw.rectangle([0, 0, W, HEADER_H], fill=FG)
    header = "NOW PLAYING"
    hw = draw.textlength(header, font=fonts["meta"])
    draw.text(
        ((W - hw) / 2, (HEADER_H - fonts["meta"].size) / 2), header, font=fonts["meta"], fill=BG
    )

    # Idle / no device
    is_idle = (
        status is None
        or (status.get("status") in ("stop", "") and not hex_to_str(status.get("Title", "")))
    )
    if is_idle:
        msg = "Nothing Playing" if status else "No Device"
        mw = draw.textlength(msg, font=fonts["artist"])
        draw.text(
            ((W - mw) / 2, (H - fonts["artist"].size) / 2), msg, font=fonts["artist"], fill=FG
        )
        inky.set_image(to_inky_palette(img, inky))
        inky.show()
        return

    pb_status = status.get("status", "")
    title  = hex_to_str(status.get("Title", "")) or "Unknown Track"
    artist = hex_to_str(status.get("Artist", ""))
    album  = hex_to_str(status.get("Album", ""))
    raw_mode = str(status.get("mode", ""))
    mode     = PLAYBACK_MODES.get(raw_mode, "")
    vol      = status.get("vol", "")

    content_top    = HEADER_H + 8
    content_bottom = H - FOOTER_H

    if raw_mode in VINYL_MODES:
        # Line-In — centered vinyl graphic, no track metadata
        vinyl_r  = 44
        vinyl_cx = W // 2
        vinyl_cy = (content_top + content_bottom) // 2
        draw_vinyl(draw, vinyl_cx, vinyl_cy, vinyl_r)
    elif raw_mode in ANALOG_MODES:
        # Other analog input (e.g. Optical) — centered source name, no metadata
        label = mode or "Input"
        lw = draw.textlength(label, font=fonts["title"])
        ly = (content_top + content_bottom - fonts["title"].size) // 2
        draw.text(((W - lw) / 2, ly), label, font=fonts["title"], fill=FG)
    else:
        # Measure text block for vertical centering
        title_lines  = wrap_text(draw, title, fonts["title"], W - MARGIN * 2, max_lines=2)
        line_h       = fonts["title"].size + 5
        title_block  = len(title_lines) * line_h
        artist_block = (fonts["artist"].size + 8) if artist else 0
        album_block  = fonts["album"].size if album else 0
        # +10 for the gap between title and artist drawn below
        block_h      = title_block + 10 + artist_block + album_block

        available = content_bottom - content_top
        y = content_top + max(0, (available - block_h) // 2)

        for line in title_lines:
            lw = draw.textlength(line, font=fonts["title"])
            draw.text(((W - lw) / 2, y), line, font=fonts["title"], fill=FG)
            y += line_h
        y += 10

        if artist:
            a  = truncate(draw, artist, fonts["artist"], W - MARGIN * 2)
            aw = draw.textlength(a, font=fonts["artist"])
            draw.text(((W - aw) / 2, y), a, font=fonts["artist"], fill=FG)
            y += fonts["artist"].size + 8

        if album:
            al  = truncate(draw, album, fonts["album"], W - MARGIN * 2)
            alw = draw.textlength(al, font=fonts["album"])
            draw.text(((W - alw) / 2, y), al, font=fonts["album"], fill=FG)

    # Footer separator
    draw.line([MARGIN, H - FOOTER_H, W - MARGIN, H - FOOTER_H], fill=FG, width=1)

    footer_y = H - FOOTER_H + 7
    if mode:
        draw.text((MARGIN, footer_y), mode, font=fonts["meta"], fill=FG)

    status_label = STATUS_LABELS.get(pb_status, "")
    right_parts  = [p for p in [status_label, f"Vol {vol}" if vol else ""] if p]
    right_text   = "  •  ".join(right_parts)
    if right_text:
        rw = draw.textlength(right_text, font=fonts["meta"])
        draw.text((W - MARGIN - rw, footer_y), right_text, font=fonts["meta"], fill=FG)

    inky.set_image(to_inky_palette(img, inky))
    inky.show()


# --- Debouncer ---

class Debouncer:
    """Coalesces rapid state changes; renders only after state has settled.

    The settle timer starts on the *first* change in a burst and does not
    reset when subsequent changes arrive. This prevents incremental metadata
    updates (status → title → artist → album arriving one poll apart) from
    continuously deferring the render.
    """

    def __init__(self, settle_secs):
        self.settle_secs = settle_secs
        self._queued     = None
        self._first_seen = None  # time of the first change in this burst

    @property
    def pending(self):
        return self._queued is not None

    @property
    def latest(self):
        return self._queued

    def see(self, value, now):
        """Record the latest value. Only starts the timer on the first call."""
        if self._first_seen is None:
            self._first_seen = now
        self._queued = value

    def flush(self, now):
        """Return and clear the queued value if settled, else None."""
        if not self.pending or (now - self._first_seen) < self.settle_secs:
            return None
        value            = self._queued
        self._queued     = None
        self._first_seen = None
        return value

    def take(self):
        """Return and clear the queued value immediately, bypassing settle."""
        value            = self._queued
        self._queued     = None
        self._first_seen = None
        return value


# --- Mock display (local preview without hardware) ---

class MockInky:
    WHITE  = 0
    BLACK  = 1
    RED    = 2
    YELLOW = 2
    width  = 400
    height = 300

    def set_border(self, *_):
        pass

    def set_image(self, img):
        # Apply a display-accurate palette: index 0=white, 1=black, 2=red
        palette = [255, 255, 255,  0, 0, 0,  255, 0, 0] + [0] * (256 * 3 - 9)
        img.putpalette(palette)
        self._img = img.convert("RGB")

    def show(self):
        self._img.save("preview.png")
        self._img.show()
        print("[preview] Saved preview.png")


# --- Main loop ---

def main():
    parser = argparse.ArgumentParser(description="LinkPlay Now Playing for Inky wHAT")
    parser.add_argument(
        "--preview", action="store_true", help="Simulate display locally (no hardware)"
    )
    parser.add_argument(
        "--host", metavar="IP", help="LinkPlay device IP (overrides LINKPLAY_HOST env var)"
    )
    args = parser.parse_args()

    global DEVICE_URL
    if args.host:
        DEVICE_URL = f"http://{args.host}"

    if args.preview:
        inky = MockInky()
        print("Preview mode — no hardware required")
    else:
        try:
            from inky.auto import auto
            inky = auto(ask_user=True, verbose=True)
        except Exception as exc:
            sys.exit(f"Failed to initialize display: {exc}")

    inky.set_border(inky.WHITE)
    fonts = load_fonts()

    print(f"Polling {DEVICE_URL} every {POLL_INTERVAL}s (settle delay: {SETTLE_SECS}s)")
    debouncer   = Debouncer(SETTLE_SECS)
    prev_status = None
    first_run   = True

    while True:
        now    = time.monotonic()
        status = get_player_status()

        compare = debouncer.latest if debouncer.pending else prev_status
        if first_run or needs_update(compare, status):
            debouncer.see(status, now)

        # On first run render immediately; afterwards wait for settle.
        s = debouncer.take() if first_run else debouncer.flush(now)

        if s is not None:
            title  = hex_to_str(s.get("Title", ""))  if s else ""
            artist = hex_to_str(s.get("Artist", "")) if s else ""
            print(f"[render] {s.get('status', '?') if s else 'no device'}"
                  f"  {title!r}  {artist!r}")
            render(inky, fonts, s)
            prev_status = s
            first_run   = False

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
