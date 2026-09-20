#!/usr/bin/env python3
"""Install a stable, checksum-bound command for an already verified runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time


def launcher(python, runtime, digest):
    return (f'#!{python}\n' + '''import hashlib, json, os, sys
from pathlib import Path
''' + f'RUNTIME = {str(runtime)!r}\nEXPECTED = {digest!r}\nPYTHON = {str(python)!r}\n' + '''try:
    if hashlib.sha256(Path(RUNTIME).read_bytes()).hexdigest() != EXPECTED:
        raise ValueError('Installed runtime checksum changed; restore or reinstall the verified package.')
    args = sys.argv[1:]
    if args and args[0] in ('sync', 'folder-status') and '--full' not in args and '--brief' not in args:
        args.append('--brief')
    args = [arg for arg in args if arg != '--full']
    os.execv(PYTHON, [PYTHON, RUNTIME, *args])
except (OSError, ValueError) as error:
    print(json.dumps({'ok': False, 'code': 'launcher_error', 'message': str(error)}))
    sys.exit(5)
''')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--destination', type=Path, default=Path.home()/'.local/bin/shared-memory')
    a = p.parse_args()
    if os.name == "nt":
        p.error("The command launcher supports macOS/Linux; on Windows use Python with the verified .pyz directly.")
    runtime = a.runtime.expanduser().absolute()
    target = a.destination.expanduser().absolute()
    if runtime.resolve() != runtime or not runtime.is_file():
        p.error('Runtime must be a physical installed file.')
    if hashlib.sha256(runtime.read_bytes()).hexdigest() != a.sha256:
        p.error('Runtime checksum mismatch.')
    python = Path(sys.executable).resolve()
    if any(c in str(python) for c in (' ', '\n')):
        p.error('Interpreter shebang requires a path without spaces; choose a compatible interpreter.')
    if target.is_symlink() or target.parent.resolve() != target.parent:
        p.error('Command destination must not traverse symlinks.')
    data = launcher(python, runtime, a.sha256).encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    recovery = None
    if target.exists() and target.read_bytes() != data:
        recovery = target.with_name(target.name + '.previous-' + str(time.time_ns()))
        shutil.copy2(target, recovery)
    temporary = target.with_name(target.name + '.new-' + str(time.time_ns()))
    with temporary.open('xb') as f:
        f.write(data)
    temporary.chmod(0o755)
    os.replace(temporary, target)
    print(json.dumps({'command': str(target), 'runtime': str(runtime), 'recovery': str(recovery) if recovery else None}))


if __name__ == '__main__':
    main()
