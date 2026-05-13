#!/usr/bin/env python3
"""Download display fonts into the local fonts/ directory."""
import os
import sys
import urllib.request

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# Both are variable fonts that Pillow can load directly.
# PlayfairDisplay: wght axis (elegant serif, used for title)
# Inter: opsz + wght axes (clean sans-serif, used for body)
FONTS = {
    "PlayfairDisplay.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/playfairdisplay"
        "/PlayfairDisplay%5Bwght%5D.ttf"
    ),
    "Inter.ttf": (
        "https://github.com/google/fonts/raw/main/ofl/inter"
        "/Inter%5Bopsz%2Cwght%5D.ttf"
    ),
}

os.makedirs(FONTS_DIR, exist_ok=True)

for filename, url in FONTS.items():
    dest = os.path.join(FONTS_DIR, filename)
    if os.path.exists(dest):
        print(f"  already exists: {filename}")
        continue
    print(f"  downloading {filename}…")
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"  saved → {dest}")
    except (urllib.error.URLError, OSError) as exc:
        print(f"  FAILED {filename}: {exc}", file=sys.stderr)
        sys.exit(1)

print("Done.")
