#!/usr/bin/env python3
"""Generate/check Markdown diagrams; SVG rendering needs Mermaid CLI 11.17.0."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def generated_markdown(document, sources, *, native_theme=False):
    """Replace only named generated regions; preserve captions and fallbacks."""
    names = [source.name for source in sources]
    if not names:
        raise ValueError('No Mermaid sources found')
    for kind in ('BEGIN', 'END'):
        found = re.findall(r'<!-- ' + kind + r' GENERATED MERMAID: ([^\n]+) -->', document)
        if sorted(found) != sorted(names):
            raise ValueError(f'Expected exactly one {kind} marker for each Mermaid source')
    replacements = []
    for source in sources:
        text = source.read_bytes().decode('utf-8')
        if native_theme:
            # Keep the shared graph, but let GitHub choose light/dark presentation.
            text = ''.join(line for line in text.splitlines(keepends=True)
                           if not re.match(r'^\s*class(?:Def)?\s', line))
        if not text.endswith('\n') or '```' in text:
            raise ValueError(f'{source.name}: use newline-terminated Mermaid without Markdown fences')
        begin = f'<!-- BEGIN GENERATED MERMAID: {source.name} -->'
        end = f'<!-- END GENERATED MERMAID: {source.name} -->'
        start, stop = document.index(begin), document.index(end) + len(end)
        if stop <= start:
            raise ValueError(f'{source.name}: reversed generated markers')
        replacements.append((start, stop, f'{begin}\n```mermaid\n{text}```\n{end}'))
    ranges = sorted(replacements)
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError('Generated Mermaid regions overlap')
    for start, stop, block in reversed(ranges):
        document = document[:start] + block + document[stop:]
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mmdc', default='mmdc', help='Path to Mermaid CLI executable')
    parser.add_argument('--chrome', help='Optional existing Chrome/Chromium executable')
    parser.add_argument('--output-dir', type=Path, help='Defaults to assets/diagrams')
    parser.add_argument('--png-dir', type=Path, help='Optional local visual-review previews')
    markdown = parser.add_mutually_exclusive_group()
    markdown.add_argument('--check-markdown', action='store_true',
                          help='Check generated blocks against .mmd sources; no Node/browser or writes')
    markdown.add_argument('--update-markdown', action='store_true',
                          help='Regenerate Markdown blocks only; no Node/browser needed')
    args = parser.parse_args()
    sources = Path(__file__).resolve().parents[1] / 'assets' / 'diagrams'
    source_files = sorted(sources.glob('*.mmd'))
    guide = sources.parents[1] / 'docs' / 'DIAGRAMS.md'
    readme = sources.parents[1] / 'README.md'
    original = guide.read_bytes().decode('utf-8')
    original_readme = readme.read_bytes().decode('utf-8')
    try:
        updated = generated_markdown(original, source_files)
        updated_readme = generated_markdown(original_readme, source_files, native_theme=True)
    except ValueError as exc:
        parser.error(str(exc))
    if args.check_markdown:
        if original != updated or original_readme != updated_readme:
            parser.error('Generated Mermaid blocks differ; run --update-markdown')
        print(f'Checked {len(source_files) * 2} generated Mermaid blocks in README and guide; no files changed')
        return 0
    if args.update_markdown:
        if original != updated:
            guide.write_bytes(updated.encode('utf-8'))
        if original_readme != updated_readme:
            readme.write_bytes(updated_readme.encode('utf-8'))
        print(f'Updated {len(source_files) * 2} generated Mermaid blocks in README and guide')
        return 0
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
        for source in source_files:
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
    if original != updated:
        guide.write_bytes(updated.encode('utf-8'))
    if original_readme != updated_readme:
        readme.write_bytes(updated_readme.encode('utf-8'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
