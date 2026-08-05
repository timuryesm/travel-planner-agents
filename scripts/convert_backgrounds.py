"""
One-off: convert the skyline backgrounds from PNG to WebP.

The images are photographs, which is the case PNG is worst at — it is
lossless, so every pixel of sky gradient costs real bytes. WebP at q=85 is
visually indistinguishable here and roughly an order of magnitude smaller.

Kept in the repo rather than run and forgotten so the assets are
reproducible: if the source PNGs are ever re-exported, this is how they
become the files the app actually ships.
"""
from pathlib import Path
from PIL import Image

ASSETS = Path("frontend/src/assets")
QUALITY = 85          # photographic; 85 avoids banding in the night sky
METHOD = 6            # slowest/best encoder effort — this runs once

for name in ("toronto-day", "toronto-night"):
    src = ASSETS / f"{name}.png"
    dst = ASSETS / f"{name}.webp"
    img = Image.open(src).convert("RGB")   # drop alpha: backgrounds are opaque
    img.save(dst, "WEBP", quality=QUALITY, method=METHOD)
    before = src.stat().st_size
    after = dst.stat().st_size
    print(f"{name}: {before/1e6:.2f} MB → {after/1e6:.2f} MB "
          f"({100 * after / before:.0f}%)")