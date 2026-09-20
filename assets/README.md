# Shared Memory artwork

Shared folio: three overlapping pages connected by one continuous line. The standard
and dark appearances share the same geometry. The repository README selects the dark
variant when the viewer prefers a dark color scheme.

| Asset | Standard / light background | Dark appearance / background |
|---|---|---|
| Icon vector | [SVG](shared-memory.svg) | [SVG](shared-memory-dark.svg) |
| Icon, 1024px | [PNG](shared-memory.png) | [PNG](shared-memory-dark.png) |
| macOS icon container | [ICNS](shared-memory.icns) | [ICNS](shared-memory-dark.icns) |
| Transparent symbol | [Dark ink](shared-memory-mark-dark.svg) | [Light ink](shared-memory-mark-light.svg) |
| Publication wordmark | [Dark ink](shared-memory-wordmark-dark.svg) | [Light ink](shared-memory-wordmark-light.svg) |

[Appearance preview](light-dark-preview.png). PNG icon exports are available at
16, 24, 32, 48, 64, 128, 256, 512 and 1024 pixels. Use the full-colour icon at 32px
or larger when the connecting line matters; internal detail softens at 16px.
Wordmark lettering is outlined, so SVG use needs no font installation. Preserve
proportions and leave surrounding whitespace at least the height of the capital S.

These are macOS-style documentation and folder assets, with a rounded tile baked
into the artwork. Shared Memory does not include a native macOS application or
an Icon Composer project. The two ICNS files are explicit alternatives; they do
not automatically switch a Finder folder's icon when macOS changes appearance.

## Regenerate icon exports

Install CairoSVG and Pillow in an isolated development environment. CairoSVG also
requires the Cairo native library (on macOS, available through Homebrew). Then run:

```sh
python scripts/render_icon.py --output /path/to/a/new/icon-output
```

The renderer reads the checked-in SVG sources and writes both appearances only to
a new directory. Review its output before replacing assets. These dependencies are
for artwork development only; they are not Shared Memory runtime requirements.

## Provenance

Original vector refinement of this repository's shared-pages artwork, distributed
under the repository [MIT license](../LICENSE). The previous icon remains in Git
history, including the immutable [v0.4.0 assets](https://github.com/Kian-hdr/shared-memory/tree/v0.4.0/assets).

Wordmark lettering uses outlined Manrope SemiBold from
[Google Fonts](https://github.com/google/fonts/tree/main/ofl/manrope), licensed under
the [SIL Open Font License 1.1](Manrope-OFL.txt). No font binaries, Apple artwork,
SF fonts or stock icons are redistributed. No trademark clearance is claimed.
