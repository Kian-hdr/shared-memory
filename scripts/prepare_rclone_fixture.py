#!/usr/bin/env python3
"""Stage an exact official rclone binary for disposable local-backend CI tests.

No account configuration, provider access or machine-wide installation. Hashes
were checked against https://downloads.rclone.org/v1.75.0/SHA256SUMS on 2026-09-08.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import stat
import urllib.request
import zipfile

VERSION = '1.75.0'
HASHES = {
    'linux-amd64': 'aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa',
    'linux-arm64': 'd0ad88ba4c8e285b7c9efa591e0ab643280a91741e13c27f3a9c0957ccfa5203',
    'osx-amd64': '19edbb8e5e73096eb66e92a42abbc5c34bfa8981ea3986a53872c7eef85a22f4',
    'osx-arm64': '35e8f2a666ce789b29111db0dd843ddabc0d59c6b609d07bcaae5d1a07cba6f8',
    'windows-amd64': '203581f0a7baeae873f2347483a798c79e2eaf5c384a4e9d866aa374f1c89ac0',
}
LIMIT = 128 * 1024 * 1024


def prepare(output):
    system = {'Darwin': 'osx', 'Linux': 'linux', 'Windows': 'windows'}[platform.system()]
    machine = {'x86_64': 'amd64', 'amd64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}[platform.machine().lower()]
    target = system + '-' + machine
    expected = HASHES[target]
    name = 'rclone-v' + VERSION + '-' + target
    url = 'https://downloads.rclone.org/v' + VERSION + '/' + name + '.zip'
    output = Path(output).absolute()
    if output.exists() or not output.parent.is_dir() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('Choose a fresh output below an existing physical directory.')
    with urllib.request.urlopen(url, timeout=30) as response:
        archive = response.read(LIMIT + 1)
    if len(archive) > LIMIT or hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError('Official archive did not match the reviewed byte/hash bounds.')
    binary = 'rclone.exe' if system == 'windows' else 'rclone'
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or len(names) > 100:
            raise ValueError('Unexpected archive inventory.')
        info = z.getinfo(name + '/' + binary)
        if info.file_size > LIMIT or stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('Unexpected executable archive entry.')
        data = z.read(info)
    output.mkdir(mode=0o700)
    executable = output / binary
    with executable.open('xb') as stream:
        stream.write(data)
    executable.chmod(0o700)
    return {'version': VERSION, 'target': target, 'archive_sha256': expected,
            'executable_sha256': hashlib.sha256(data).hexdigest(), 'directory': str(output),
            'evidence_scope': 'disposable local-backend test dependency; no provider access'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--github-path', action='store_true')
    args = parser.parse_args()
    result = prepare(args.output)
    if args.github_path:
        if os.environ.get('GITHUB_ACTIONS') != 'true':
            raise ValueError('GITHUB_PATH is only updated inside the configured CI job.')
        with open(os.environ['GITHUB_PATH'], 'a', encoding='utf-8') as stream:
            stream.write(result['directory'] + '\n')
    print(json.dumps(result))
