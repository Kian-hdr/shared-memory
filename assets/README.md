# Shared Memory icon

Three overlapping pages share one continuous line: separate contributors, shared
knowledge. Original artwork distributed under this repository's MIT license.

- `shared-memory.svg`: editable vector source, suitable for documentation.
- `shared-memory.png`: transparent 1024 × 1024 raster.
- `shared-memory.icns`: standalone macOS icon with multiple resolutions.

This is artwork for the product and project folder. Shared Memory does not include
a native macOS application, menu bar companion or Obsidian plugin.

To regenerate the raster and ICNS using Python with Pillow installed:

```sh
python scripts/render_icon.py --output /path/to/a/new/icon-output
```

The renderer writes only to a new output directory. Review the output before
replacing the checked-in assets. Pillow is an artwork development dependency;
it is not needed to run Shared Memory.
