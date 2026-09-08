#!/usr/bin/env python3
"""Render the Shared Memory mark as PNG and macOS ICNS (requires Pillow).

The icon is standalone artwork. This does not build or install an application.
SVG geometry is mirrored here to keep raster generation independent of browsers.
"""
from pathlib import Path
import argparse

from PIL import Image, ImageDraw


def render(size: int) -> Image.Image:
    scale = 4
    image = Image.new("RGBA", (1024 * scale, 1024 * scale))
    draw = ImageDraw.Draw(image)

    def rounded(bounds, radius, color):
        draw.rounded_rectangle(tuple(x * scale for x in bounds), radius=radius * scale, fill=color)

    def line(points, width, color):
        points = [(x * scale, y * scale) for x, y in points]
        draw.line(points, fill=color, width=width * scale, joint="curve")
        radius = width * scale / 2
        for x, y in points:
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)

    rounded((64, 64, 960, 960), 200, "#102F38")
    rounded((216, 224, 592, 672), 72, "#398EA2")
    rounded((324, 288, 700, 736), 72, "#70CECE")
    rounded((432, 352, 808, 800), 72, "#F2F8F3")
    # Quadratic Bezier segments matching the vector artwork.
    points = [(300, 456), (510, 456)]
    for n in range(1, 31):
        t = n / 30
        points.append(((1-t)**2*510 + 2*(1-t)*t*540 + t*t*540,
                       (1-t)**2*456 + 2*(1-t)*t*456 + t*t*486))
    points.append((540, 534))
    for n in range(1, 31):
        t = n / 30
        points.append(((1-t)**2*540 + 2*(1-t)*t*540 + t*t*570,
                       (1-t)**2*534 + 2*(1-t)*t*564 + t*t*564))
    points.append((724, 564))
    line(points, 36, "#102F38")
    line([(528, 660), (712, 660)], 32, "#70CECE")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Fresh output directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    icon = render(1024)
    icon.save(args.output / "shared-memory.png")
    icon.save(args.output / "shared-memory.icns", format="ICNS")
    for size in (16, 32, 64, 128, 256):
        render(size).save(args.output / f"preview-{size}.png")
    print(args.output)


if __name__ == "__main__":
    main()
