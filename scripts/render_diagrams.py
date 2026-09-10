#!/usr/bin/env python3
"""Render the editable Mermaid sources. Requires Mermaid CLI 11.17.0 and Chrome."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mmdc', default='mmdc', help='Path to Mermaid CLI executable')
    parser.add_argument('--chrome', help='Optional existing Chrome/Chromium executable')
    parser.add_argument('--output-dir', type=Path, help='Defaults to assets/diagrams')
    parser.add_argument('--png-dir', type=Path, help='Optional local visual-review previews')
    args = parser.parse_args()
    sources = Path(__file__).resolve().parents[1] / 'assets' / 'diagrams'
    destination = args.output_dir or sources
    destination.mkdir(parents=True, exist_ok=True)
    if args.png_dir:
        args.png_dir.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output([args.mmdc, '--version'], text=True).strip()
    if version != '11.17.0':
        parser.error(f'Use reviewed Mermaid CLI 11.17.0; found {version}')
    with tempfile.TemporaryDirectory(prefix='shared-memory-diagrams-') as temporary:
        tmp = Path(temporary)
        browser = tmp / 'browser.json'
        browser.write_text(json.dumps({'executablePath': args.chrome} if args.chrome else {}))
        for source in sorted(sources.glob('*.mmd')):
            config = tmp / 'mermaid.json'
            config.write_text(json.dumps({
                'theme': 'base', 'securityLevel': 'strict', 'htmlLabels': False,
                'deterministicIds': True, 'deterministicIDSeed': source.stem,
                'themeVariables': {
                    'fontFamily': 'Arial, Helvetica, sans-serif', 'fontSize': '18px',
                    'primaryColor': '#ffffff', 'primaryTextColor': '#0f172a',
                    'primaryBorderColor': '#64748b', 'lineColor': '#475569',
                    'clusterBkg': '#f8fafc', 'clusterBorder': '#cbd5e1',
                    'edgeLabelBackground': '#ffffff',
                },
                'flowchart': {'htmlLabels': False, 'curve': 'linear',
                              'padding': 18, 'nodeSpacing': 35, 'rankSpacing': 45},
            }))
            command = [args.mmdc, '-i', str(source), '-c', str(config),
                       '-p', str(browser), '-b', 'white', '-w', '1600']
            subprocess.run(command + ['-o', str(destination / (source.stem + '.svg'))], check=True)
            if args.png_dir:
                subprocess.run(command + ['-o', str(args.png_dir / (source.stem + '.png')),
                                           '-s', '1.5'], check=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
