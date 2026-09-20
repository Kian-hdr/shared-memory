#!/usr/bin/env python3
"""Prepare/install one user LaunchAgent, or run its bounded capture operation."""
import argparse
try:
    import fcntl
except ImportError:  # Windows may inspect/prepare configuration, but cannot run a LaunchAgent.
    fcntl = None
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time


def physical(value):
    path = Path(value).expanduser().absolute()
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or (candidate.exists() and getattr(candidate.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Symlink/reparse paths are not supported; supply a physical absolute path.')
    if path.resolve() != path:
        raise ValueError('Symlink paths are not supported; supply the physical absolute path.')
    return path


def private(path, project):
    path = physical(path)
    if path == project or project in path.parents or path in project.parents:
        raise ValueError('Private capture/state paths must be separate from the selected workspace.')
    lower = str(path).replace('\\', '/').casefold()
    if lower.startswith('//') or any(marker in lower for marker in ('/cloudstorage/', '/mobile documents/', '/nextcloud/', 'onedrive', 'googledrive', 'google drive', 'dropbox')):
        raise ValueError('Private capture/state paths must be outside synchronized or network storage.')
    for parent in (path, *path.parents):
        if (parent / '.shared-memory.json').exists() or parent.name.casefold() in ('cloudstorage', 'mobile documents', 'nextcloud', 'box'):
            raise ValueError('Private capture/state paths must be outside synchronized workspaces.')
    return path


def validate(config):
    project = physical(config['project'])
    state = private(config['state'], project)
    binding_path = state / ('folder/folder.json' if (state / 'connection.json').exists() else 'folder.json')
    manifest = json.loads(physical(project / '.shared-memory.json').read_text())
    binding = json.loads(physical(binding_path).read_text())
    if manifest.get('format_version') != 3 or manifest.get('workflow') != 'folder':
        raise ValueError('Automatic capture requires an existing format-3 folder workspace.')
    if binding.get('readonly') is not False:
        raise ValueError('Automatic capture refuses read-only or unknown access bindings.')
    if binding.get('root') != str(project) or binding.get('project_id') != manifest.get('project_id'):
        raise ValueError('Private binding does not match the selected workspace.')
    if config.get('project_id', manifest['project_id']) != manifest['project_id']:
        raise ValueError('Workspace identity changed; prepare a new installation.')
    for key in ('python', 'runtime'):
        path = physical(config[key]) if key == 'python' else private(config[key], project)
        if not path.is_file():
            raise ValueError(f'{key} must be an existing absolute file.')
    if not os.access(config['python'], os.X_OK):
        raise ValueError('Python interpreter is not executable.')
    if hashlib.sha256(Path(config['runtime']).read_bytes()).hexdigest() != config.get('sha256'):
        raise ValueError('Runtime SHA-256 does not match the explicitly verified expected digest.')
    private(config['capture'], project)
    return manifest['project_id']


def atomic(path, data):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing a symlink output.')
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def command(config):
    return [config['python'], config['runtime'], 'sync', config['project'], '--state-dir', config['state'], '--brief']



def fingerprint(project):
    """Cheap metadata hint; any incomplete scan disables the idle optimization.

    Open each directory relative to its held parent descriptor with O_NOFOLLOW.
    Include portable history and ignored paths conservatively; never follow links.
    This is an idle check, not a replacement for runtime content validation.
    """
    if not hasattr(os, 'O_NOFOLLOW') or os.scandir not in os.supports_fd:
        return None
    digest = hashlib.sha256(b'shared-memory-capture-stat-v1\0')
    entries = 0

    def record(relative, metadata):
        nonlocal entries
        entries += 1
        digest.update(json.dumps((relative, metadata.st_dev, metadata.st_ino,
                      metadata.st_mode, metadata.st_size, metadata.st_mtime_ns,
                      metadata.st_ctime_ns), ensure_ascii=True).encode())
        digest.update(b'\0')

    def scan(descriptor, relative):
        record(relative, os.fstat(descriptor))
        with os.scandir(descriptor) as iterator:
            children = sorted(iterator, key=lambda item: item.name)
        for child in children:
            path = relative + '/' + child.name
            metadata = child.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode) and not getattr(metadata, 'st_file_attributes', 0) & 0x400:
                nested = os.open(child.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    scan(nested, path)
                finally:
                    os.close(nested)
            else:
                record(path, metadata)

    try:
        root = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            scan(root, '')
        finally:
            os.close(root)
    except (OSError, RecursionError):
        return None
    return {'version': 1, 'sha256': digest.hexdigest(), 'entries': entries}


def cached_result(capture):
    try:
        path = physical(capture / 'last-result.json')
        if path.stat().st_size > 32768:
            return None
        result = json.loads(path.read_text())
        return result if isinstance(result, dict) else None
    except (OSError, ValueError):
        return None


def capture_signature(config):
    state = Path(config['state'])
    binding = state / ('folder/folder.json' if (state / 'connection.json').exists() else 'folder.json')
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    digest.update(physical(binding).read_bytes())
    # Updating the installed runner also forces a fresh full capture.
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def recent_full_capture(result):
    # Both clocks bound idle reuse. A reboot or either clock moving backwards
    # invalidates the cache rather than extending its lifetime.
    for key, now in (('synced_at', time.time()), ('full_sync_monotonic', time.monotonic())):
        stamp = result.get(key)
        if not isinstance(stamp, (int, float)) or not 0 <= now - stamp < 600:
            return False
    return True


def run_once(config):
    if fcntl is None:
        raise ValueError('Automatic capture requires POSIX file locking; use the ordinary sync command on this platform.')
    capture = private(config['capture'], physical(config['project']))
    # launchd serializes this job; this additional lock also covers manual runs.
    if (capture / 'run.lock').is_symlink():
        raise ValueError('Refusing a symlink capture lock.')
    with (capture / 'run.lock').open('a') as lock:
        os.chmod(capture / 'run.lock', 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75
        started = time.perf_counter()
        result = {'checked_at': time.time(), 'ok': False, 'mode': 'sync'}
        code = 1
        try:
            validate(config)
            signature = capture_signature(config)
            before = fingerprint(config['project'])
            previous = cached_result(capture)
            if (before is not None and previous and previous.get('ok') is True
                    and previous.get('readiness') == 'ready'
                    and previous.get('capture_signature') == signature
                    and previous.get('pre_sync_fingerprint') == before
                    and recent_full_capture(previous)):
                result = {**previous, 'checked_at': time.time(), 'unchanged': True,
                          'mode': 'unchanged', 'duration_seconds': round(time.perf_counter() - started, 6)}
                atomic(capture / 'last-result.json', json.dumps(result, indent=2).encode())
                return 0
            result['unchanged'] = False
            # Output can contain private paths. Keep only the final bounded result,
            # never append forever or emit it into launchd's system log.
            completed = subprocess.run(command(config), capture_output=True, timeout=300)
            code = completed.returncode
            result['exit_code'] = code
            try:
                payload = json.loads(completed.stdout)
                result['ok'] = code == 0 and payload.get('ok') is True
                data = payload.get('data', {})
                result['readiness'] = data.get('readiness')
                result['attention_required'] = result['readiness'] != 'ready'
                result['summary'] = {key: value for key, value in data.items() if key in ('counts', 'attention', 'changes', 'conflicts', 'pending', 'excluded_count', 'partial_count', 'events')}
                if len(json.dumps(result['summary'])) > 8192:
                    result['summary'] = {'truncated': True, 'message': 'Inspect folder-status --brief for details.'}
                if not result['ok']:
                    result['error'] = str({'code': payload.get('code'), 'message': payload.get('message', payload.get('error', 'Runtime returned failure'))})[-4096:]
            except (ValueError, AttributeError):
                result['ok'] = False
                result['error'] = 'Runtime did not return a valid JSON success response.'
            if not result['ok']:
                result['stderr'] = completed.stderr.decode(errors='replace')[-4096:]
                code = code or 1
        except Exception as error:
            result['ok'] = False
            code = code or 1
            result['error'] = str(error)[-4096:]
        if result['ok'] and result.get('readiness') == 'ready':
            result['synced_at'] = time.time()
            result['full_sync_monotonic'] = time.monotonic()
            result['capture_signature'] = signature
            # Only the PRE-sync snapshot is cached. A concurrent edit, or a new
            # history event written by sync itself, forces a subsequent full run.
            if before is not None:
                result['pre_sync_fingerprint'] = before
        if result['ok'] and result.get('attention_required'):
            code = 2
        result['duration_seconds'] = round(time.perf_counter() - started, 6)
        atomic(capture / 'last-result.json', json.dumps(result, indent=2).encode())
        return code


def plan(args):
    project = physical(args.project)
    identifier = hashlib.sha256(str(project).encode()).hexdigest()[:16]
    capture = Path.home() / 'Library/Application Support/Shared Memory/Capture' / identifier
    if getattr(args, 'status', False) or getattr(args, 'uninstall', False):
        config = json.loads(physical(capture / 'config.json').read_text())
        if config.get('project') != str(project) or config.get('capture') != str(capture):
            raise ValueError('Saved capture configuration does not match this workspace path.')
    else:
        if not all((args.state_dir, args.runtime, args.sha256)):
            raise ValueError('--state-dir, --runtime and independently verified --sha256 are required.')
        config = dict(project=str(project), state=str(physical(args.state_dir)),
                  python=str(physical(args.python)), runtime=str(physical(args.runtime)), capture=str(capture), sha256=args.sha256.lower(), interval=args.interval)
        config['project_id'] = validate(config)
    label = 'space.sharedmemory.capture.' + identifier
    plist = {'Label': label, 'ProgramArguments': [config['python'], str(capture / 'capture.py'),
             '--run-config', str(capture / 'config.json')], 'StartInterval': config.get('interval', args.interval),
             'RunAtLoad': True, 'ProcessType': 'Background', 'Umask': 0o077}
    return config, plist, Path.home() / 'Library/LaunchAgents' / (label + '.plist')


def launchctl(*args, check=True):
    if sys.platform != 'darwin':
        raise ValueError('LaunchAgent control requires macOS.')
    return subprocess.run(['/bin/launchctl', *args], check=check, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', nargs='?')
    parser.add_argument('--state-dir')
    parser.add_argument('--runtime')
    parser.add_argument('--sha256', help='Independently verified SHA-256 of the installed runtime')
    parser.add_argument('--python', default=str(Path(sys.executable).resolve()))
    parser.add_argument('--interval', type=int, default=60, choices=range(30, 3601))
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--run-config')
    args = parser.parse_args()
    try:
        if args.run_config:
            config_path = physical(args.run_config)
            config = json.loads(config_path.read_text())
            if config_path.parent != physical(config['capture']):
                raise ValueError('Configuration must live in its private capture directory.')
            return run_once(config)
        if not args.project:
            parser.error('project is required')
        if sum((args.install, args.uninstall, args.status)) > 1:
            parser.error('Choose only one of --install, --uninstall, --status')
        config, plist, destination = plan(args)
        capture = Path(config['capture'])
        if not args.install and not args.uninstall and not args.status:
            print(json.dumps({'config': config, 'plist': plist, 'destination': str(destination)}, indent=2))
            return 0
        if sys.platform != 'darwin':
            raise ValueError('LaunchAgent control requires macOS.')
        target = 'gui/' + str(os.getuid())
        service = target + '/' + plist['Label']
        if args.status:
            status = launchctl('print', service, check=False)
            last = json.loads(physical(capture / 'last-result.json').read_text()) if (capture / 'last-result.json').exists() else None
            stale = not last or time.time() - last.get('checked_at', 0) > max(600, config.get('interval', 60) * 2 + 300)
            healthy = bool(status.returncode == 0 and last and last.get('ok') and last.get('readiness') == 'ready' and not stale)
            print(json.dumps({'loaded': status.returncode == 0, 'healthy': healthy, 'stale': stale, 'plist': str(destination), 'last_result': last}))
            return 0 if healthy else 2
        private(capture, Path(config['project']))
        if args.install:
            probe = command(config)
            probe[2] = 'folder-status'
            checked = subprocess.run(probe, capture_output=True, text=True, timeout=60)
            if checked.returncode or json.loads(checked.stdout).get('ok') is not True:
                raise ValueError('Installed runtime/binding preflight failed; nothing installed.')
        capture.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(capture, 0o700)
        loaded = launchctl('print', service, check=False).returncode == 0
        if destination.is_symlink():
            raise ValueError('Refusing a symlink LaunchAgent plist.')
        if destination.exists():
            existing = plistlib.loads(destination.read_bytes())
            if existing.get('Label') != plist['Label'] or existing.get('ProgramArguments', [None, None])[1:2] != [str(capture / 'capture.py')]:
                raise ValueError('Existing plist is not owned by this capture installation.')
            if not args.uninstall and destination.read_bytes() != plistlib.dumps(plist):
                shutil.copy2(destination, capture / ('previous-' + str(time.time_ns()) + '.plist'))
        if loaded and not destination.exists():
            raise ValueError('Loaded label has no owned plist; refusing to modify it.')
        if loaded:
            launchctl('bootout', service)
        if args.uninstall:
            if destination.exists():
                destination.rename(capture / ('uninstalled-' + str(time.time_ns()) + '.plist'))
            print(json.dumps({'uninstalled': True, 'history_preserved': True, 'private_recovery': str(capture)}))
            return 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        for name, data in (('capture.py', Path(__file__).read_bytes()), ('config.json', json.dumps(config).encode())):
            path = capture / name
            if path.is_symlink():
                raise ValueError('Refusing a symlink capture file.')
            if path.exists() and path.read_bytes() != data:
                shutil.copy2(path, capture / ('previous-' + str(time.time_ns()) + '-' + name))
            atomic(path, data)
        atomic(destination, plistlib.dumps(plist))
        launchctl('bootstrap', target, str(destination))
        launchctl('print', service)
        print(json.dumps({'installed': True, 'label': plist['Label'], 'result': str(capture / 'last-result.json')}))
        return 0
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
