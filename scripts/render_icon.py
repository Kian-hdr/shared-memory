#!/usr/bin/env python3
"""Render both checked-in SVG icon appearances (requires CairoSVG and Pillow).

Standalone documentation/folder artwork, not an application or Icon Composer build.
The SVG is the source of truth; no separately maintained duplicate geometry.
"""
from pathlib import Path
import argparse
import io

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Fresh output directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for stem in ("shared-memory", "shared-memory-dark"):
        source = ROOT / "assets" / (stem + ".svg")
        png = cairosvg.svg2png(url=str(source), output_width=1024, output_height=1024)
        icon = Image.open(io.BytesIO(png)).convert("RGBA")
        icon.save(args.output / (stem + ".png"))
        icon.save(args.output / (stem + ".icns"), format="ICNS")
        for size in SIZES:
            icon.resize((size, size), Image.Resampling.LANCZOS).save(
                args.output / (stem + "-" + str(size) + ".png"))
    print(args.output)


if __name__ == "__main__":
    main()
