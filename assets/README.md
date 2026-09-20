# Shared Memory artwork

Neutral silver and graphite pages connected by one continuous line. The complete
standard and dark icons are exported by Apple's Icon Composer for macOS. The
background, mask and edge treatment come from the native renderer, not a manually
drawn tile. The README selects the PNG matching the viewer's preferred color scheme.

| Asset | Standard / light background | Dark appearance / background |
|---|---|---|
| Native icon, 1024px | [PNG](shared-memory.png) | [PNG](shared-memory-dark.png) |
| macOS icon container | [ICNS](shared-memory.icns) | [ICNS](shared-memory-dark.icns) |
| Transparent symbol | [Dark ink](shared-memory-mark-dark.svg) | [Light ink](shared-memory-mark-light.svg) |
| Publication wordmark | [Dark ink](shared-memory-wordmark-dark.svg) | [Light ink](shared-memory-wordmark-light.svg) |

[Native Icon Composer source](SharedMemory.icon/icon.json) ·
[Appearance preview](light-dark-preview.png).
PNG exports include 16, 24, 32, 48, 64, 128, 256, 512 and 1024 pixels. Internal detail
softens at 16px. Wordmark lettering is outlined and needs no installed font.

`shared-memory.svg` and `shared-memory-dark.svg` are compatibility copies of the
unmasked foreground vector, identical across appearances. They do not reproduce
the native background. Use the PNG exports for the complete icon or open
`SharedMemory.icon` in Icon Composer for native editing and appearance previews.

The native source follows Apple's layered icon workflow. The checked-in exports
were rendered with Icon Composer 27.0 (129), design generation 27, macOS Default
and Dark. These are standalone artwork assets, not a shipped macOS application.
The ICNS files are explicit alternatives and do not switch Finder appearance
automatically. No app installation or runtime appearance-switching test is claimed.

## Regenerate native exports

On a Mac with Icon Composer 27 and Pillow in your development Python environment:

```sh
python scripts/render_icon.py --output /path/to/a/new/icon-output
```

The script uses Icon Composer bundled with Xcode. Set `--ictool` for another
installation; `xcrun ictool` may resolve to a different, incompatible executable.
It writes both appearances to a fresh directory. These are artwork development
requirements only, not Shared Memory runtime dependencies.

## Provenance

Original refinement of this repository's MIT shared-pages artwork. Previous color
versions remain in Git history. Wordmark lettering uses outlined Manrope SemiBold
from [Google Fonts](https://github.com/google/fonts/tree/main/ofl/manrope), licensed
under the [SIL Open Font License 1.1](Manrope-OFL.txt). No font binaries, Apple icon
artwork or SF fonts are redistributed. No trademark clearance is claimed.

References: [Apple app icons](https://developer.apple.com/design/human-interface-guidelines/app-icons)
and [Icon Composer workflow](https://developer.apple.com/documentation/xcode/creating-your-app-icon-using-icon-composer).
